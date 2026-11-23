import logging
import uuid
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.modules.processing.models import ChunkEmbedding, DocumentChunk
from app.modules.search import repository
from app.modules.storage.models import File, FileVersion, Folder
from tests.conftest import FakeEmbedder
from tests.test_sharing import Person, _file, _folder, _grant, _person

if TYPE_CHECKING:
    from mypy_boto3_s3.client import S3Client

INVOICE = "the invoice is due on five march and must be paid by bank transfer"
HOLIDAY = "office closed winter holiday until january"


@pytest.fixture(autouse=True)
def low_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    # The fake embedder is a bag of words, so related texts score far lower than the real model.
    monkeypatch.setattr(get_settings(), "search_min_score", 0.35)


@pytest.fixture
def people(client: TestClient) -> dict[str, Person]:
    return {name: _person(client, name) for name in ("owner", "viewer", "stranger")}


def _index(session: Session, embedder: FakeEmbedder, file_id: str, *texts: str) -> None:
    "Gives a file chunks and vectors the way the pipeline would, without running it."
    version = session.scalars(
        select(FileVersion).where(FileVersion.file_id == uuid.UUID(file_id))
    ).one()
    for index, content in enumerate(texts):
        chunk = DocumentChunk(
            file_version_id=version.id,
            chunk_index=index,
            page=index + 1,
            content=content,
            content_hash=f"{file_id}-{index}",
        )
        session.add(chunk)
        session.flush()
        session.add(
            ChunkEmbedding(
                chunk_id=chunk.id,
                model=embedder.model,
                dim=embedder.dim,
                embedding=embedder.embed_documents([content])[0],
            )
        )
    session.commit()


def _search(
    client: TestClient, who: Person, query: str, **params: int
) -> tuple[int, dict[str, object]]:
    response = client.post(
        "/api/v1/search", json={"query": query}, headers=who.headers, params=params
    )
    return response.status_code, response.json()


def _names(body: dict[str, object]) -> list[str]:
    return [hit["file_name"] for hit in body["items"]]  # type: ignore[index, union-attr]


class TestOwnSearch:
    def test_findsTheMeaningAndReturnsOnlySafeFields(
        self, client, people, s3_client: "S3Client", session: Session, fake_embedder: FakeEmbedder
    ) -> None:
        owner = people["owner"]
        bill = _file(client, owner, s3_client, session, None, "bill.txt")
        holiday = _file(client, owner, s3_client, session, None, "holiday.txt")
        _index(session, fake_embedder, bill, INVOICE)
        _index(session, fake_embedder, holiday, HOLIDAY)
        status, body = _search(client, owner, "when is the invoice due")
        assert status == 200
        assert _names(body) == ["bill.txt"]
        hit = body["items"][0]  # type: ignore[index]
        assert set(hit) == {"file_id", "file_name", "chunk_id", "page", "snippet", "score"}
        assert hit["file_id"] == bill and hit["page"] == 1 and hit["snippet"] == INVOICE
        assert 0.35 < hit["score"] <= 1
        assert (body["total"], body["page"], body["page_size"]) == (1, 1, 50)
        assert fake_embedder.queries == ["when is the invoice due"]

    def test_aFileAppearsOnceWithItsBestChunk_andBetterMatchesComeFirst(
        self, client, people, s3_client: "S3Client", session: Session, fake_embedder: FakeEmbedder
    ) -> None:
        owner = people["owner"]
        mixed = _file(client, owner, s3_client, session, None, "mixed.txt")
        other = _file(client, owner, s3_client, session, None, "other.txt")
        _index(session, fake_embedder, mixed, HOLIDAY, INVOICE)
        _index(session, fake_embedder, other, "invoice due soon please pay")
        _, body = _search(client, owner, "invoice due five march")
        assert _names(body) == ["mixed.txt", "other.txt"]
        assert body["items"][0]["page"] == 2  # type: ignore[index]

    def test_nothingCloseEnough_returnsAnEmptyPage(
        self, client, people, s3_client: "S3Client", session: Session, fake_embedder: FakeEmbedder
    ) -> None:
        owner = people["owner"]
        _index(session, fake_embedder, _file(client, owner, s3_client, session, None), INVOICE)
        status, body = _search(client, owner, "zebra giraffe savannah")
        assert (status, body["items"], body["total"]) == (200, [], 0)

    def test_pagesOverTheMatchingFiles(
        self, client, people, s3_client: "S3Client", session: Session, fake_embedder: FakeEmbedder
    ) -> None:
        owner = people["owner"]
        for index in range(3):
            file_id = _file(client, owner, s3_client, session, None, f"f{index}.txt")
            _index(session, fake_embedder, file_id, INVOICE + " " * index + f" extra{index}")
        _, first = _search(client, owner, "invoice due march", page=1, page_size=2)
        _, second = _search(client, owner, "invoice due march", page=2, page_size=2)
        assert (len(first["items"]), len(second["items"]), first["total"]) == (2, 1, 3)  # type: ignore[arg-type]
        assert not set(_names(first)) & set(_names(second))

    def test_onlyReadyFilesThatAreNotDeleted(
        self, client, people, s3_client: "S3Client", session: Session, fake_embedder: FakeEmbedder
    ) -> None:
        owner = people["owner"]
        processing = _file(client, owner, s3_client, session, None, "p.txt", ready=False)
        deleted = _file(client, owner, s3_client, session, None, "d.txt")
        kept = _file(client, owner, s3_client, session, None, "k.txt")
        for file_id in (processing, deleted, kept):
            _index(session, fake_embedder, file_id, INVOICE)
        session.execute(
            update(File).where(File.id == uuid.UUID(deleted)).values(deleted_at=text("now()"))
        )
        session.commit()
        _, body = _search(client, owner, "invoice due")
        assert _names(body) == ["k.txt"]


class TestAccess:
    def test_aStrangerNeverSeesSomeoneElsesFiles_evenWhenTheyMatchBetter(
        self, client, people, s3_client: "S3Client", session: Session, fake_embedder: FakeEmbedder
    ) -> None:
        owner, stranger = people["owner"], people["stranger"]
        _index(session, fake_embedder, _file(client, owner, s3_client, session, None), INVOICE)
        mine = _file(client, stranger, s3_client, session, None, "mine.txt")
        _index(session, fake_embedder, mine, "invoice due five march paid")
        _, body = _search(client, stranger, INVOICE)
        assert _names(body) == ["mine.txt"]

    def test_aFolderGrantCoversEverythingBelow_andRevokingEndsItAtOnce(
        self, client, people, s3_client: "S3Client", session: Session, fake_embedder: FakeEmbedder
    ) -> None:
        owner, viewer = people["owner"], people["viewer"]
        top = _folder(client, owner, "Top")
        deep = _folder(client, owner, "Deep", top)
        for folder, name in ((top, "top.txt"), (deep, "deep.txt")):
            _index(
                session,
                fake_embedder,
                _file(client, owner, s3_client, session, folder, name),
                INVOICE,
            )
        outside = _file(client, owner, s3_client, session, None, "outside.txt")
        _index(session, fake_embedder, outside, INVOICE)
        assert _names(_search(client, viewer, "invoice due")[1]) == []
        granted = _grant(client, owner, "folders", top, viewer, "viewer")
        assert sorted(_names(_search(client, viewer, "invoice due")[1])) == ["deep.txt", "top.txt"]
        revoke = client.delete(
            f"/api/v1/folders/{top}/permissions/{granted.json()['id']}", headers=owner.headers
        )
        assert revoke.status_code == 204
        assert _names(_search(client, viewer, "invoice due")[1]) == []

    def test_aFileGrantCoversThatFileOnly(
        self, client, people, s3_client: "S3Client", session: Session, fake_embedder: FakeEmbedder
    ) -> None:
        owner, viewer = people["owner"], people["viewer"]
        shared = _file(client, owner, s3_client, session, None, "shared.txt")
        private = _file(client, owner, s3_client, session, None, "private.txt")
        for file_id in (shared, private):
            _index(session, fake_embedder, file_id, INVOICE)
        assert _grant(client, owner, "files", shared, viewer, "viewer").status_code == 201
        assert _names(_search(client, viewer, "invoice due")[1]) == ["shared.txt"]

    def test_aDeletedFolderHidesWhatIsBelowItFromGrantees_butNotFromTheOwner(
        self, client, people, s3_client: "S3Client", session: Session, fake_embedder: FakeEmbedder
    ) -> None:
        owner, viewer = people["owner"], people["viewer"]
        top = _folder(client, owner, "Top")
        gone = _folder(client, owner, "Gone", top)
        _index(
            session, fake_embedder, _file(client, owner, s3_client, session, top, "a.txt"), INVOICE
        )
        below = _file(client, owner, s3_client, session, gone, "below.txt")
        _index(session, fake_embedder, below, INVOICE)
        direct = _file(client, owner, s3_client, session, gone, "direct.txt")
        _index(session, fake_embedder, direct, INVOICE)
        assert _grant(client, owner, "folders", top, viewer, "viewer").status_code == 201
        assert _grant(client, owner, "files", direct, viewer, "viewer").status_code == 201
        assert sorted(_names(_search(client, viewer, "invoice due")[1])) == [
            "a.txt",
            "below.txt",
            "direct.txt",
        ]
        session.execute(
            update(Folder).where(Folder.id == uuid.UUID(gone)).values(deleted_at=text("now()"))
        )
        session.commit()
        assert _names(_search(client, viewer, "invoice due")[1]) == ["a.txt"]
        assert len(_search(client, owner, "invoice due")[1]["items"]) == 3  # type: ignore[arg-type]

    def test_aUserWhoCanSeeOneFileStillFindsItAmongManyCloserOnesTheyCannotSee(
        self, client, people, s3_client: "S3Client", session: Session, fake_embedder: FakeEmbedder
    ) -> None:
        owner, viewer = people["owner"], people["viewer"]
        for index in range(25):
            file_id = _file(client, owner, s3_client, session, None, f"secret{index}.txt")
            _index(session, fake_embedder, file_id, "invoice due five march")
        visible = _file(client, owner, s3_client, session, None, "visible.txt")
        _index(session, fake_embedder, visible, "invoice due on march the office")
        assert _grant(client, owner, "files", visible, viewer, "viewer").status_code == 201
        _, body = _search(client, viewer, "invoice due five march")
        assert _names(body) == ["visible.txt"]


class TestOlderPgvector:
    def test_withoutIterativeScans_aWiderCandidateListIsUsedAndSearchStillWorks(
        self,
        client,
        people,
        s3_client: "S3Client",
        session: Session,
        fake_embedder: FakeEmbedder,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        owner = people["owner"]
        _index(session, fake_embedder, _file(client, owner, s3_client, session, None), INVOICE)
        monkeypatch.setattr(repository, "ITERATIVE_SCAN_SQL", "SET LOCAL hnsw.no_such_setting = 1")
        assert len(_search(client, owner, "invoice due")[1]["items"]) == 1  # type: ignore[arg-type]
        session.rollback()


class TestContract:
    def test_requiresSignIn(self, client) -> None:
        assert client.post("/api/v1/search", json={"query": "x"}).status_code == 401

    def test_termsTravelInTheBody_notTheUrl(self, client, people) -> None:
        assert (
            client.get("/api/v1/search?query=x", headers=people["owner"].headers).status_code == 405
        )

    @pytest.mark.parametrize("query", ["", "   ", "x" * 1001])
    def test_aMissingOrOversizedQuery_isRefused(self, client, people, query: str) -> None:
        status, body = _search(client, people["owner"], query)
        assert status == 422 and body["error"]["code"]  # type: ignore[index]

    def test_isRateLimitedPerUser(self, client, people) -> None:
        limit = get_settings().rate_limit_search_per_user
        statuses = [_search(client, people["owner"], "x")[0] for _ in range(limit + 1)]
        assert statuses[-1] == 429 and 429 not in statuses[:limit]
        assert _search(client, people["viewer"], "x")[0] == 200

    def test_whenTheEmbedderFails_itIs503_andTheQueryIsNotLogged(
        self, client, people, fake_embedder: FakeEmbedder, caplog: pytest.LogCaptureFixture
    ) -> None:
        fake_embedder.error = RuntimeError("model gone: secret-search-words")
        with caplog.at_level(logging.DEBUG):
            status, body = _search(client, people["owner"], "secret-search-words")
        assert status == 503 and body["error"]["code"] == "search_unavailable"  # type: ignore[index]
        assert "secret-search-words" not in caplog.text
