import hashlib
import uuid
from collections.abc import Callable, Iterable, Iterator, Sequence
from typing import TYPE_CHECKING

import boto3
import pytest
from alembic.config import Config
from fastapi.testclient import TestClient
from moto import mock_aws
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher
from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from alembic import command
from app.ai import chat as chat_module
from app.ai import embeddings as embeddings_module
from app.ai.chat import ChatMessage, ChatUsage
from app.ai.embeddings import EMBEDDING_DIM, EMBEDDING_MODEL
from app.core import security
from app.core.config import get_settings
from app.core.ratelimit import RateLimitResult, get_rate_limiter
from app.db.session import get_session
from app.main import create_app
from app.modules.processing import scanner as scanner_module
from app.modules.processing.dispatcher import get_dispatcher
from app.modules.processing.scanner import ScanResult
from app.modules.storage.deps import get_storage
from app.modules.storage.s3 import S3Storage
from app.modules.summaries.dispatcher import get_summary_dispatcher

if TYPE_CHECKING:
    from mypy_boto3_s3.client import S3Client

# Tests only ever touch this database; the dev database is never downgraded.
TEST_DATABASE = "clouddrop_test"


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    url = make_url(get_settings().database_url).set(database=TEST_DATABASE)
    assert url.database == TEST_DATABASE
    rendered = url.render_as_string(hide_password=False)
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", rendered.replace("%", "%%"))
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    test_engine = create_engine(url)
    yield test_engine
    test_engine.dispose()


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    connection = engine.connect()
    outer = connection.begin()
    test_session = Session(
        bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False
    )
    try:
        yield test_session
    finally:
        test_session.close()
        outer.rollback()
        connection.close()


@pytest.fixture(scope="session", autouse=True)
def _cheap_password_hashing() -> Iterator[None]:
    "Argon2 at production cost made every test user; tests need a valid hash, not a slow one."
    original = (security._hasher, security._DUMMY_HASH)
    security._hasher = PasswordHash((Argon2Hasher(time_cost=1, memory_cost=8, parallelism=1),))
    security._DUMMY_HASH = security._hasher.hash("timing-equaliser-not-a-real-password")
    yield
    security._hasher, security._DUMMY_HASH = original


BUCKET = "test-bucket"


class FakeDispatcher:
    "Records what would be sent to the worker; tests never touch a broker."

    def __init__(self) -> None:
        self.calls: list[uuid.UUID] = []
        self.on_enqueue: Callable[[uuid.UUID], None] | None = None

    def enqueue(self, file_version_id: uuid.UUID) -> None:
        if self.on_enqueue:
            self.on_enqueue(file_version_id)
        self.calls.append(file_version_id)


@pytest.fixture
def dispatcher() -> FakeDispatcher:
    return FakeDispatcher()


class FakeScanner:
    "Stands in for clamd: tests set `result` or `error` and read what was streamed to it."

    def __init__(self) -> None:
        self.enabled = True
        self.result = ScanResult(infected=False)
        self.error: Exception | None = None
        self.scanned: list[bytes] = []

    def scan(self, chunks: Iterable[bytes]) -> ScanResult:
        self.scanned.append(b"".join(chunks))
        if self.error:
            raise self.error
        return self.result


@pytest.fixture(autouse=True)
def fake_scanner(monkeypatch: pytest.MonkeyPatch) -> FakeScanner:
    scanner = FakeScanner()
    monkeypatch.setattr(scanner_module, "get_scanner", lambda: scanner)
    return scanner


class FakeEmbedder:
    """Stands in for the local model. Texts that share words get similar vectors (a hashed
    bag of words, normalised), so search tests can rank without the real model."""

    model = EMBEDDING_MODEL
    dim = EMBEDDING_DIM

    def __init__(self) -> None:
        self.document_batches: list[list[str]] = []
        self.queries: list[str] = []
        self.error: Exception | None = None
        # Tests set this to return vectors of the wrong size.
        self.vector_size = EMBEDDING_DIM

    def _vector(self, text: str) -> list[float]:
        vector = [0.0] * self.vector_size
        for word in text.lower().split():
            digest = hashlib.sha256(word.encode()).digest()
            vector[int.from_bytes(digest[:4], "big") % self.vector_size] += 1.0
        norm = sum(value * value for value in vector) ** 0.5 or 1.0
        return [value / norm for value in vector]

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        if self.error:
            raise self.error
        self.document_batches.append(list(texts))
        return [self._vector(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        if self.error:
            raise self.error
        self.queries.append(text)
        return self._vector(text)


@pytest.fixture(autouse=True)
def fake_embedder(monkeypatch: pytest.MonkeyPatch) -> FakeEmbedder:
    embedder = FakeEmbedder()
    monkeypatch.setattr(embeddings_module, "get_embedder", lambda: embedder)
    return embedder


class FakeSummaryDispatcher:
    "Records which versions would be sent to the worker for a summary."

    def __init__(self) -> None:
        self.calls: list[uuid.UUID] = []

    def enqueue(self, file_version_id: uuid.UUID) -> None:
        self.calls.append(file_version_id)


@pytest.fixture
def summary_dispatcher() -> FakeSummaryDispatcher:
    return FakeSummaryDispatcher()


class FakeChatStream:
    def __init__(self, pieces: list[str], error: Exception | None) -> None:
        self.usage = ChatUsage()
        self.closed = False
        self._pieces = pieces
        self._error = error

    def __iter__(self) -> Iterator[str]:
        yield from self._pieces
        if self._error:
            raise self._error

    def close(self) -> None:
        self.closed = True


class FakeChat:
    "Stands in for Ollama: tests set `reply` or `error` and read the messages that were sent."

    def __init__(self) -> None:
        self.reply = "ok"
        # Replies handed out one per call before `reply` is used (for a scripted conversation).
        self.replies: list[str] = []
        self.json_outputs: list[bool] = []
        self.output_caps: list[int | None] = []
        self.error: Exception | None = None  # raised when the stream is opened
        self.error_while_streaming: Exception | None = None
        self.calls: list[list[ChatMessage]] = []
        self.streams: list[FakeChatStream] = []
        # Runs when a stream is opened, so a test can look at the world at that moment.
        self.on_stream: Callable[[], None] | None = None

    def stream(
        self,
        messages: Sequence[ChatMessage],
        *,
        json_output: bool = False,
        max_output_tokens: int | None = None,
    ) -> FakeChatStream:
        self.calls.append(list(messages))
        self.json_outputs.append(json_output)
        self.output_caps.append(max_output_tokens)
        if self.on_stream:
            self.on_stream()
        if self.error:
            raise self.error
        words = (self.replies.pop(0) if self.replies else self.reply).split(" ")
        pieces = [word if index == 0 else " " + word for index, word in enumerate(words)]
        stream = FakeChatStream(pieces, self.error_while_streaming)
        self.streams.append(stream)
        return stream


@pytest.fixture(autouse=True)
def fake_chat(monkeypatch: pytest.MonkeyPatch) -> FakeChat:
    chat = FakeChat()
    monkeypatch.setattr(chat_module, "get_chat_client", lambda: chat)
    return chat


@pytest.fixture
def s3_client(monkeypatch: pytest.MonkeyPatch) -> Iterator["S3Client"]:
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    with mock_aws():
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket=BUCKET)
        yield s3


@pytest.fixture
def storage(s3_client: "S3Client") -> S3Storage:
    return S3Storage(s3_client, BUCKET, upload_ttl_seconds=900, download_ttl_seconds=300)


class FakeRateLimiter:
    """Counts in memory so tests never touch Redis and never leak counts between tests."""

    def __init__(self) -> None:
        self.counts: dict[str, int] = {}

    def hit(self, key: str, limit: int, window_seconds: int) -> RateLimitResult:
        self.counts[key] = self.counts.get(key, 0) + 1
        return RateLimitResult(self.counts[key] <= limit, window_seconds)


@pytest.fixture
def rate_limiter() -> FakeRateLimiter:
    return FakeRateLimiter()


@pytest.fixture
def client(
    session: Session,
    storage: S3Storage,
    dispatcher: FakeDispatcher,
    rate_limiter: FakeRateLimiter,
    summary_dispatcher: FakeSummaryDispatcher,
) -> Iterator[TestClient]:
    app = create_app()

    def _request_session() -> Iterator[Session]:
        try:
            yield session
        finally:
            # Like the real get_session, drop anything the request did not commit.
            session.rollback()

    app.dependency_overrides[get_session] = _request_session
    app.dependency_overrides[get_storage] = lambda: storage
    app.dependency_overrides[get_dispatcher] = lambda: dispatcher
    app.dependency_overrides[get_rate_limiter] = lambda: rate_limiter
    app.dependency_overrides[get_summary_dispatcher] = lambda: summary_dispatcher
    with TestClient(app, headers={"X-Requested-With": "XMLHttpRequest"}) as test_client:
        yield test_client


@pytest.fixture
def make_user(client: TestClient) -> Callable[[], dict[str, str]]:
    "Registers and logs in a fresh user; returns its Authorization header."

    def _make() -> dict[str, str]:
        email = f"user-{uuid.uuid4().hex[:8]}@example.com"
        password = "a-long-test-password"
        body = {"email": email, "password": password, "display_name": "Test User"}
        assert client.post("/api/v1/auth/register", json=body).status_code == 201
        login = client.post("/api/v1/auth/login", json={"email": email, "password": password})
        return {"Authorization": f"Bearer {login.json()['access_token']}"}

    return _make
