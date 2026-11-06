import uuid
from collections.abc import Callable, Iterator
from typing import TYPE_CHECKING

import boto3
import pytest
from alembic.config import Config
from fastapi.testclient import TestClient
from moto import mock_aws
from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from alembic import command
from app.core.config import get_settings
from app.db.session import get_session
from app.main import create_app
from app.modules.processing.dispatcher import get_dispatcher
from app.modules.storage.deps import get_storage
from app.modules.storage.s3 import S3Storage

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


BUCKET = "test-bucket"


class FakeDispatcher:
    "Records what would be sent to the worker; tests never touch a broker."

    def __init__(self) -> None:
        self.calls: list[uuid.UUID] = []

    def enqueue(self, file_version_id: uuid.UUID) -> None:
        self.calls.append(file_version_id)


@pytest.fixture
def dispatcher() -> FakeDispatcher:
    return FakeDispatcher()


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


@pytest.fixture
def client(
    session: Session, storage: S3Storage, dispatcher: FakeDispatcher
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
    with TestClient(app) as test_client:
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
