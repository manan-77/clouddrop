from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.modules.audit.constants import AuditAction, ResourceType
from app.modules.audit.models import AuditEvent
from app.modules.audit.repository import AuditRepository
from tests.conftest import BUCKET
from tests.test_sharing import Person, _file, _folder, _grant, _person

if TYPE_CHECKING:
    from mypy_boto3_s3.client import S3Client


@pytest.fixture
def people(client: TestClient) -> dict[str, Person]:
    return {name: _person(client, name) for name in ("owner", "editor", "viewer", "stranger")}


def _events(client: TestClient, who: Person, query: str = "") -> list[dict]:  # type: ignore[type-arg]
    response = client.get(f"/api/v1/audit-events?page_size=100{query}", headers=who.headers)
    assert response.status_code == 200, response.text
    return list(response.json()["items"])


def _actions(client: TestClient, who: Person, query: str = "") -> list[str]:
    return [e["action"] for e in _events(client, who, query)]


def _count(session: Session) -> int:
    session.expire_all()
    return int(session.scalar(select(func.count()).select_from(AuditEvent)) or 0)


class TestEventsAreWrittenOncePerAction:
    def test_uploadDownloadAndDelete(
        self, client, people, s3_client: "S3Client", session: Session
    ) -> None:
        owner = people["owner"]
        file_id = _file(client, owner, s3_client, session, None)
        before = _count(session)
        assert (
            client.get(f"/api/v1/files/{file_id}/download", headers=owner.headers).status_code
            == 200
        )
        assert _count(session) == before + 1
        client.delete(f"/api/v1/files/{file_id}", headers=owner.headers)
        events = _events(client, owner, f"&resource_id={file_id}")
        assert [e["action"] for e in events] == ["file.deleted", "file.downloaded", "file.uploaded"]
        assert all(e["resource_type"] == "file" and "result" not in e for e in events)

    def test_aRepeatedCompleteDoesNotDuplicateTheUploadEvent(
        self, client, people, s3_client: "S3Client", session: Session
    ) -> None:
        owner = people["owner"]
        file_id = _file(client, owner, s3_client, session, None)
        client.post(f"/api/v1/files/{file_id}/uploads/complete", headers=owner.headers)
        client.post(f"/api/v1/files/{file_id}/uploads/complete", headers=owner.headers)
        assert _actions(client, owner, f"&resource_id={file_id}").count("file.uploaded") == 1

    def test_folderDelete(self, client, people) -> None:
        owner = people["owner"]
        folder = _folder(client, owner, "F")
        client.delete(f"/api/v1/folders/{folder}", headers=owner.headers)
        events = _events(client, owner, f"&resource_id={folder}")
        assert [(e["action"], e["resource_type"]) for e in events] == [("folder.deleted", "folder")]

    def test_grantChangeAndRevoke_recordTheTargetAndRoleButNoEmail(self, client, people) -> None:
        owner, viewer = people["owner"], people["viewer"]
        folder = _folder(client, owner, "F")
        grant = _grant(client, owner, "folders", folder, viewer, "viewer").json()["id"]
        _grant(client, owner, "folders", folder, viewer, "editor")  # same person again: a change
        client.patch(
            f"/api/v1/folders/{folder}/permissions/{grant}",
            json={"role": "viewer"},
            headers=owner.headers,
        )
        client.delete(f"/api/v1/folders/{folder}/permissions/{grant}", headers=owner.headers)
        events = _events(client, owner, f"&resource_id={folder}")
        assert [e["action"] for e in events] == [
            "permission.revoked",
            "permission.changed",
            "permission.changed",
            "permission.granted",
        ]
        assert [e["detail"] for e in events] == ["viewer", "viewer", "editor", "viewer"]
        assert all(e["actor_name"] == "Owner" and e["target_user_id"] for e in events)
        assert viewer.email not in str(events)

    def test_actionsByAnEditorAreRecordedInTheOwnersTrail(
        self, client, people, s3_client: "S3Client", session: Session
    ) -> None:
        owner, editor = people["owner"], people["editor"]
        folder = _folder(client, owner, "F")
        _grant(client, owner, "folders", folder, editor, "editor")
        file_id = _file(client, editor, s3_client, session, folder)
        events = _events(client, owner, f"&resource_id={file_id}")
        assert events[0]["action"] == "file.uploaded" and events[0]["actor_name"] == "Editor"

    def test_loginIsRecordedButFailedLoginsAreNot(self, client, people) -> None:
        owner = people["owner"]
        before = [e["action"] for e in _events(client, owner, "&resource_type=user")]
        assert before == ["auth.login"]  # the fixture's own sign-in
        client.post(
            "/api/v1/auth/login", json={"email": owner.email, "password": "wrong-password-1"}
        )
        client.post(
            "/api/v1/auth/login", json={"email": "nobody@example.com", "password": "x" * 12}
        )
        assert _actions(client, owner, "&resource_type=user") == before
        ok = client.post(
            "/api/v1/auth/login", json={"email": owner.email, "password": "a-long-test-password"}
        )
        assert ok.status_code == 200
        assert _actions(client, owner, "&resource_type=user") == ["auth.login", "auth.login"]

    def test_aNoOpRoleChangeIsNotRecorded(self, client, people) -> None:
        owner, viewer = people["owner"], people["viewer"]
        folder = _folder(client, owner, "F")
        grant = _grant(client, owner, "folders", folder, viewer, "viewer").json()["id"]
        _grant(client, owner, "folders", folder, viewer, "viewer")  # same role again
        client.patch(
            f"/api/v1/folders/{folder}/permissions/{grant}",
            json={"role": "viewer"},
            headers=owner.headers,
        )
        assert _actions(client, owner, f"&resource_id={folder}") == ["permission.granted"]

    def test_grantsOnAFileAndAGranteesDownloadLandInTheOwnersTrail(
        self, client, people, s3_client: "S3Client", session: Session
    ) -> None:
        owner, viewer = people["owner"], people["viewer"]
        file_id = _file(client, owner, s3_client, session, None)
        _grant(client, owner, "files", file_id, viewer, "viewer")
        assert (
            client.get(f"/api/v1/files/{file_id}/download", headers=viewer.headers).status_code
            == 200
        )
        events = _events(client, owner, f"&resource_id={file_id}")
        assert [e["action"] for e in events] == [
            "file.downloaded",
            "permission.granted",
            "file.uploaded",
        ]
        assert events[0]["actor_name"] == "Viewer" and events[1]["resource_type"] == "file"
        # The grantee's own trail (their workspace) does not contain it.
        assert _actions(client, viewer, f"&resource_id={file_id}") == []

    def test_aMultipartCompleteRecordsOneUploadEvent(
        self, client, people, s3_client: "S3Client", session: Session
    ) -> None:
        owner = people["owner"]
        init = client.post(
            "/api/v1/files/uploads/multipart",
            json={"name": "big.txt", "content_type": "text/plain", "size_bytes": 20_000_000},
            headers=owner.headers,
        ).json()
        file_id = init["file"]["id"]
        row = session.execute(
            text("select s3_key, multipart_upload_id from file_versions where file_id = :f"),
            {"f": file_id},
        ).one()
        for number, size in ((1, 16 * 1024 * 1024), (2, 20_000_000 - 16 * 1024 * 1024)):
            s3_client.upload_part(
                Bucket=BUCKET,
                Key=row.s3_key,
                UploadId=row.multipart_upload_id,
                PartNumber=number,
                Body=b"x" * size,
            )
        done = client.post(f"/api/v1/files/{file_id}/uploads/complete", headers=owner.headers)
        assert done.status_code == 200
        assert _actions(client, owner, f"&resource_id={file_id}") == ["file.uploaded"]


class TestReading:
    def test_onlyTheOwnersOwnWorkspaceIsVisible(self, client, people) -> None:
        owner, editor, stranger = people["owner"], people["editor"], people["stranger"]
        folder = _folder(client, owner, "F")
        _grant(client, owner, "folders", folder, editor, "editor")
        assert "permission.granted" in _actions(client, owner)
        assert "permission.granted" not in _actions(client, editor)
        assert "permission.granted" not in _actions(client, stranger)
        # Someone else's resource id gives an empty page, not a 404 or a hint.
        other = client.get(f"/api/v1/audit-events?resource_id={folder}", headers=stranger.headers)
        assert other.status_code == 200 and other.json()["items"] == []

    def test_requiresAuthentication(self, client) -> None:
        assert client.get("/api/v1/audit-events").status_code == 401

    def test_isPagedNewestFirst(self, client, people) -> None:
        owner = people["owner"]
        for i in range(5):
            client.delete(
                f"/api/v1/folders/{_folder(client, owner, f'F{i}')}", headers=owner.headers
            )
        first = client.get("/api/v1/audit-events?page_size=2", headers=owner.headers).json()
        second = client.get("/api/v1/audit-events?page_size=2&page=2", headers=owner.headers).json()
        stamps = [e["created_at"] for e in first["items"] + second["items"]]
        assert first["total"] >= 6 and stamps == sorted(stamps, reverse=True)
        assert (
            client.get("/api/v1/audit-events?page_size=101", headers=owner.headers).status_code
            == 422
        )

    def test_theListUsesAConstantNumberOfQueries(self, client, people, session: Session) -> None:
        owner = people["owner"]
        counts = []
        for batch in (3, 9):
            for i in range(batch):
                client.delete(
                    f"/api/v1/folders/{_folder(client, owner, f'q{batch}{i}')}",
                    headers=owner.headers,
                )
            statements: list[str] = []

            def record(conn, cursor, statement, *args, bucket=statements):  # type: ignore[no-untyped-def]  # SQLAlchemy event hook signature
                bucket.append(statement)

            engine = session.get_bind()
            event.listen(engine, "before_cursor_execute", record)
            try:
                assert (
                    client.get(
                        "/api/v1/audit-events?page_size=100", headers=owner.headers
                    ).status_code
                    == 200
                )
            finally:
                event.remove(engine, "before_cursor_execute", record)
            counts.append(len(statements))
        assert counts[0] == counts[1]


class TestNoSensitiveData:
    def test_noNamesEmailsTokensOrUrlsAreStored(
        self, client, people, s3_client: "S3Client", session: Session
    ) -> None:
        owner, viewer = people["owner"], people["viewer"]
        folder = _folder(client, owner, "Secret Folder Name")
        file_id = _file(client, owner, s3_client, session, folder, "secret-report.txt")
        _grant(client, owner, "folders", folder, viewer, "viewer")
        client.get(f"/api/v1/files/{file_id}/download", headers=owner.headers)
        rows = session.execute(text("select * from audit_events")).all()
        blob = " ".join(str(value) for row in rows for value in row).lower()
        for secret in (
            "secret folder name",
            "secret-report",
            viewer.email,
            owner.email,
            "x-amz",
            "bearer",
            "http",
        ):
            assert secret not in blob


class TestFailClosed:
    """If the audit row cannot be written, the action does not happen (a real CHECK violation)."""

    @staticmethod
    def _poison(monkeypatch: pytest.MonkeyPatch) -> None:
        def bad_add(self: AuditRepository, event: AuditEvent) -> None:
            event.action = "file.exploded"
            self.session.add(event)

        monkeypatch.setattr(AuditRepository, "add", bad_add)

    def test_folderDelete(
        self, client, people, monkeypatch: pytest.MonkeyPatch, session: Session
    ) -> None:
        owner = people["owner"]
        folder = _folder(client, owner, "F")
        self._poison(monkeypatch)
        with pytest.raises(DBAPIError):
            client.delete(f"/api/v1/folders/{folder}", headers=owner.headers)
        session.rollback()
        monkeypatch.undo()
        assert client.get(f"/api/v1/folders/{folder}", headers=owner.headers).status_code == 200

    def test_fileDeleteAndDownload(
        self,
        client,
        people,
        monkeypatch: pytest.MonkeyPatch,
        s3_client: "S3Client",
        session: Session,
    ) -> None:
        owner = people["owner"]
        file_id = _file(client, owner, s3_client, session, None)
        self._poison(monkeypatch)
        for call in (
            lambda: client.delete(f"/api/v1/files/{file_id}", headers=owner.headers),
            lambda: client.get(f"/api/v1/files/{file_id}/download", headers=owner.headers),
        ):
            with pytest.raises(DBAPIError):
                call()
            session.rollback()
        monkeypatch.undo()
        assert client.get(f"/api/v1/files/{file_id}", headers=owner.headers).status_code == 200
        assert _actions(client, owner, f"&resource_id={file_id}") == ["file.uploaded"]

    def test_grant(self, client, people, monkeypatch: pytest.MonkeyPatch, session: Session) -> None:
        owner, viewer = people["owner"], people["viewer"]
        folder = _folder(client, owner, "F")
        self._poison(monkeypatch)
        with pytest.raises(DBAPIError):
            _grant(client, owner, "folders", folder, viewer, "viewer")
        session.rollback()
        monkeypatch.undo()
        assert client.get(f"/api/v1/folders/{folder}", headers=viewer.headers).status_code == 404


class TestConstraints:
    def test_everyEnumMemberIsAcceptedAndUnknownValuesAreRejected(
        self, client, people, session: Session
    ) -> None:
        """The CHECK literals live in the migration; the drift test cannot see them."""
        workspace = session.scalar(text("select id from workspaces limit 1"))
        base = {"action": "file.deleted", "resource_type": "file"}
        for column, enum in (
            ("action", AuditAction),
            ("resource_type", ResourceType),
        ):
            for member in enum:
                with session.begin_nested():
                    session.add(
                        AuditEvent(workspace_id=workspace, **{**base, column: member.value})
                    )
                    session.flush()
        for column, value in (
            ("action", "file.exploded"),
            ("resource_type", "robot"),
        ):
            with pytest.raises(IntegrityError), session.begin_nested():
                session.add(AuditEvent(workspace_id=workspace, **{**base, column: value}))
                session.flush()


class TestReadingMore:
    def test_pagingPastTheEndAndDisjointPages(self, client, people) -> None:
        owner = people["owner"]
        for i in range(5):
            client.delete(
                f"/api/v1/folders/{_folder(client, owner, f'F{i}')}", headers=owner.headers
            )
        pages = [
            client.get(f"/api/v1/audit-events?page_size=4&page={n}", headers=owner.headers).json()
            for n in (1, 2, 3, 99)
        ]
        ids = [e["id"] for p in pages[:3] for e in p["items"]]
        assert len(ids) == len(set(ids)) and pages[3]["items"] == []
        assert len({p["total"] for p in pages}) == 1

    def test_filtersCombineAndInvalidValuesAre422(self, client, people) -> None:
        owner = people["owner"]
        folder = _folder(client, owner, "F")
        client.delete(f"/api/v1/folders/{folder}", headers=owner.headers)
        both = _events(client, owner, f"&resource_type=folder&resource_id={folder}")
        assert [e["action"] for e in both] == ["folder.deleted"]
        assert _events(client, owner, f"&resource_type=file&resource_id={folder}") == []
        assert (
            client.get(
                "/api/v1/audit-events?resource_type=robot", headers=owner.headers
            ).status_code
            == 422
        )
        assert (
            client.get("/api/v1/audit-events?resource_id=nope", headers=owner.headers).status_code
            == 422
        )

    def test_anEditorAndARevokedEditorNeverSeeTheOwnersTrail(
        self, client, people, s3_client: "S3Client", session: Session
    ) -> None:
        owner, editor = people["owner"], people["editor"]
        folder = _folder(client, owner, "F")
        grant = _grant(client, owner, "folders", folder, editor, "editor").json()["id"]
        file_id = _file(client, editor, s3_client, session, folder)
        assert not any(e["resource_id"] in (file_id, folder) for e in _events(client, editor))
        client.delete(f"/api/v1/folders/{folder}/permissions/{grant}", headers=owner.headers)
        assert not any(e["resource_id"] in (file_id, folder) for e in _events(client, editor))


class TestDownloadRateLimit:
    def test_downloadLinkRequestsAreRateLimitedPerUser(
        self, client, people, s3_client: "S3Client", session: Session
    ) -> None:
        from app.core.config import get_settings

        owner, viewer = people["owner"], people["viewer"]
        file_id = _file(client, owner, s3_client, session, None)
        _grant(client, owner, "files", file_id, viewer, "viewer")
        limit = get_settings().rate_limit_download_per_user
        codes = [
            client.get(f"/api/v1/files/{file_id}/download", headers=viewer.headers).status_code
            for _ in range(limit + 1)
        ]
        assert codes[-1] == 429 and 429 not in codes[:limit]
        # The owner is not limited: their rows go into their own trail.
        own = {
            client.get(f"/api/v1/files/{file_id}/download", headers=owner.headers).status_code
            for _ in range(limit + 2)
        }
        assert own == {200}
        total = client.get(
            f"/api/v1/audit-events?page_size=1&resource_id={file_id}", headers=owner.headers
        ).json()["total"]
        # upload, grant, the viewer's allowed downloads, then all of the owner's
        assert total == 2 + limit + (limit + 2)
