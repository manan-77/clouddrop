import hashlib
import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.modules.sharing.models import ShareLink
from app.modules.storage.models import File
from tests.test_sharing import Person, _file, _folder, _grant, _person

if TYPE_CHECKING:
    from mypy_boto3_s3.client import S3Client


@pytest.fixture
def people(client: TestClient) -> dict[str, Person]:
    return {name: _person(client, name) for name in ("owner", "editor", "viewer", "stranger")}


def _create(client: TestClient, who: Person, file_id: str, days: int = 7):  # type: ignore[no-untyped-def]
    return client.post(
        f"/api/v1/files/{file_id}/share-links", json={"expires_in_days": days}, headers=who.headers
    )


def _resolve(client: TestClient, token: str):  # type: ignore[no-untyped-def]
    return client.post("/api/v1/public/share-links/resolve", json={"token": token})


def _download(client: TestClient, token: str):  # type: ignore[no-untyped-def]
    return client.post("/api/v1/public/share-links/download", json={"token": token})


@pytest.fixture
def ready_file(client, people, s3_client: "S3Client", session: Session) -> str:
    return _file(client, people["owner"], s3_client, session, None, "report.txt")


class TestOwnerSide:
    def test_createReturnsTheTokenOnceAndStoresOnlyItsHash(
        self, client, people, ready_file, session: Session
    ) -> None:
        created = _create(client, people["owner"], ready_file)
        assert created.status_code == 201 and created.headers["Location"].endswith(
            created.json()["id"]
        )
        token = created.json()["token"]
        assert len(token) >= 40
        stored = session.scalar(text("select token_hash from share_links"))
        assert stored == hashlib.sha256(token.encode()).hexdigest() and token not in str(stored)
        listing = client.get(
            f"/api/v1/files/{ready_file}/share-links", headers=people["owner"].headers
        )
        assert listing.json()["total"] == 1
        assert "token" not in listing.text

    def test_expiryIsRequiredAndBounded(self, client, people, ready_file) -> None:
        owner = people["owner"]
        too_long = _create(client, owner, ready_file, get_settings().share_link_max_days + 1)
        assert too_long.status_code == 422 and too_long.json()["error"]["code"] == "link_too_long"
        for bad in (0, -1, 400):
            assert _create(client, owner, ready_file, bad).status_code == 422
        no_body = client.post(
            f"/api/v1/files/{ready_file}/share-links", json={}, headers=owner.headers
        )
        created = no_body.json()
        remaining = datetime.fromisoformat(created["expires_at"]) - datetime.now(UTC)
        assert no_body.status_code == 201 and timedelta(days=6) < remaining <= timedelta(days=7)

    @pytest.mark.parametrize("who", ["editor", "viewer", "stranger"])
    def test_onlyTheOwnerManagesLinks(self, client, people, ready_file, who: str) -> None:
        owner = people["owner"]
        _grant(client, owner, "files", ready_file, people["editor"], "editor")
        _grant(client, owner, "files", ready_file, people["viewer"], "viewer")
        link = _create(client, owner, ready_file).json()["id"]
        actor = people[who]
        assert _create(client, actor, ready_file).status_code == 404
        assert (
            client.get(f"/api/v1/files/{ready_file}/share-links", headers=actor.headers).status_code
            == 404
        )
        assert (
            client.delete(
                f"/api/v1/files/{ready_file}/share-links/{link}", headers=actor.headers
            ).status_code
            == 404
        )

    def test_onlyReadyFilesCanBeLinked(self, client, people, s3_client, session: Session) -> None:
        pending = _file(client, people["owner"], s3_client, session, None, "p.txt", ready=False)
        refused = _create(client, people["owner"], pending)
        assert refused.status_code == 409 and refused.json()["error"]["code"] == "file_not_ready"

    def test_aFileHasABoundedNumberOfActiveLinks(self, client, people, ready_file) -> None:
        cap = get_settings().share_link_max_active_per_file
        codes = [_create(client, people["owner"], ready_file).status_code for _ in range(cap + 1)]
        assert codes[-1] == 422 and set(codes[:cap]) == {201}

    def test_revokeIsIdempotentAndWritesOneEvent(self, client, people, ready_file) -> None:
        owner = people["owner"]
        link = _create(client, owner, ready_file).json()["id"]
        url = f"/api/v1/files/{ready_file}/share-links/{link}"
        assert client.delete(url, headers=owner.headers).status_code == 204
        assert client.delete(url, headers=owner.headers).status_code == 204
        events = client.get(
            f"/api/v1/audit-events?resource_id={ready_file}", headers=owner.headers
        ).json()["items"]
        assert [e["action"] for e in events].count("share_link.revoked") == 1
        assert (
            client.delete(
                f"/api/v1/files/{ready_file}/share-links/{uuid.uuid4()}", headers=owner.headers
            ).status_code
            == 404
        )


class TestPublicSide:
    def test_resolveAndDownloadWorkWithoutSigningIn(self, client, people, ready_file) -> None:
        token = _create(client, people["owner"], ready_file).json()["token"]
        resolved = _resolve(client, token)
        assert resolved.status_code == 200
        body = resolved.json()
        assert (
            body["file_name"] == "report.txt" and body["size_bytes"] == 5 and "expires_at" in body
        )
        assert "id" not in body and "workspace" not in resolved.text
        downloaded = _download(client, token)
        assert downloaded.status_code == 200 and downloaded.json()["url"].startswith("http")

    def test_everyUnusableLinkIsTheSameNotFound(
        self, client, people, ready_file, s3_client: "S3Client", session: Session
    ) -> None:
        owner = people["owner"]
        revoked = _create(client, owner, ready_file).json()
        client.delete(
            f"/api/v1/files/{ready_file}/share-links/{revoked['id']}", headers=owner.headers
        )
        expired = _create(client, owner, ready_file).json()
        session.execute(
            update(ShareLink)
            .where(ShareLink.id == uuid.UUID(expired["id"]))
            .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
        deleted_file = _file(client, owner, s3_client, session, None, "gone.txt")
        deleted = _create(client, owner, deleted_file).json()
        client.delete(f"/api/v1/files/{deleted_file}", headers=owner.headers)
        unready_file = _file(client, owner, s3_client, session, None, "later.txt")
        unready = _create(client, owner, unready_file).json()
        session.execute(
            update(File).where(File.id == uuid.UUID(unready_file)).values(status="processing")
        )
        session.commit()
        answers = []
        for token in (
            revoked["token"],
            expired["token"],
            deleted["token"],
            unready["token"],
            "x" * 43,
        ):
            for call in (_resolve, _download):
                response = call(client, token)
                assert response.status_code == 404
                error = response.json()["error"]
                answers.append((error["code"], error["message"], tuple(error["details"])))
        assert len(set(answers)) == 1 and answers[0][0] == "link_not_found"

    def test_aRevokedLinkStopsWorkingImmediately(self, client, people, ready_file) -> None:
        owner = people["owner"]
        link = _create(client, owner, ready_file).json()
        assert _download(client, link["token"]).status_code == 200
        client.delete(f"/api/v1/files/{ready_file}/share-links/{link['id']}", headers=owner.headers)
        assert _download(client, link["token"]).status_code == 404

    def test_theTokenMustComeInTheBodyNotTheUrl(self, client, people, ready_file) -> None:
        token = _create(client, people["owner"], ready_file).json()["token"]
        assert client.post(f"/api/v1/public/share-links/resolve?token={token}").status_code == 422
        assert client.get(f"/api/v1/public/share-links/resolve/{token}").status_code in (404, 405)
        assert _resolve(client, "short").status_code == 422

    def test_theTokenNeverReachesTheLogs(
        self, client, people, ready_file, caplog: pytest.LogCaptureFixture
    ) -> None:
        token = _create(client, people["owner"], ready_file).json()["token"]
        with caplog.at_level(logging.DEBUG):
            _resolve(client, token)
            _download(client, token)
            _download(client, "z" * 43)
        assert token not in caplog.text

    def test_publicEndpointsAreRateLimitedPerAddress(self, client, people, ready_file) -> None:
        token = _create(client, people["owner"], ready_file).json()["token"]
        limit = get_settings().rate_limit_public_link_per_ip
        codes = [_resolve(client, token).status_code for _ in range(limit + 1)]
        assert codes[-1] == 429 and 429 not in codes[:limit]

    def test_downloadsLandInTheOwnersTrailAsAnonymous(self, client, people, ready_file) -> None:
        owner = people["owner"]
        link = _create(client, owner, ready_file).json()
        _download(client, link["token"])
        events = client.get(
            f"/api/v1/audit-events?resource_id={ready_file}", headers=owner.headers
        ).json()["items"]
        assert [e["action"] for e in events][:2] == ["share_link.downloaded", "share_link.created"]
        assert events[0]["actor_name"] is None and events[0]["detail"] == link["id"]
        assert link["token"] not in str(events)

    def test_aLinkIsViewOnly_itCannotReachAnythingElse(self, client, people, ready_file) -> None:
        folder = _folder(client, people["owner"], "Other")
        token = _create(client, people["owner"], ready_file).json()["token"]
        # The token grants no API access: there is no way to present it as credentials.
        assert (
            client.get(
                f"/api/v1/folders/{folder}", headers={"Authorization": f"Bearer {token}"}
            ).status_code
            == 401
        )
        assert client.get(f"/api/v1/files/{ready_file}").status_code == 401
