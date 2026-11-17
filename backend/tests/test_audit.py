from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.modules.audit.models import AuditEvent
from app.modules.audit.service import AuditService
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
        assert all(e["result"] == "success" and e["resource_type"] == "file" for e in events)

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

    def test_loginSuccessAndFailureAreRecordedForTheAccountOnly(self, client, people) -> None:
        owner = people["owner"]
        email = owner.email
        client.post("/api/v1/auth/login", json={"email": email, "password": "wrong-password-1"})
        client.post(
            "/api/v1/auth/login", json={"email": "nobody@example.com", "password": "x" * 12}
        )
        login = client.post(
            "/api/v1/auth/login", json={"email": email, "password": "a-long-test-password"}
        )
        assert login.status_code == 200
        user_events = _events(client, owner, "&resource_type=user")
        assert [(e["action"], e["result"]) for e in user_events] == [
            ("auth.login", "success"),
            ("auth.login_failed", "failure"),
            ("auth.login", "success"),  # the fixture's own sign-in
        ]


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


class TestFailureHandling:
    def test_aFailedAuditWriteForALoginFailureDoesNotHideTheOriginalError(
        self, client, people, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def broken(self: AuditService, **kwargs: object) -> None:
            raise SQLAlchemyError("audit table unavailable")

        monkeypatch.setattr(AuditService, "record", broken)
        response = client.post(
            "/api/v1/auth/login",
            json={"email": people["owner"].email, "password": "wrong-password-1"},
        )
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "invalid_credentials"

    def test_anActionThatCannotBeAuditedDoesNotHappen(
        self,
        client,
        people,
        monkeypatch: pytest.MonkeyPatch,
        s3_client: "S3Client",
        session: Session,
    ) -> None:
        owner = people["owner"]
        folder = _folder(client, owner, "F")

        def broken(self: AuditService, **kwargs: object) -> None:
            raise SQLAlchemyError("audit table unavailable")

        monkeypatch.setattr(AuditService, "record", broken)
        with pytest.raises(SQLAlchemyError):
            client.delete(f"/api/v1/folders/{folder}", headers=owner.headers)
        session.rollback()
        monkeypatch.undo()
        assert client.get(f"/api/v1/folders/{folder}", headers=owner.headers).status_code == 200


class TestConstraints:
    def test_unknownActionResultOrTypeIsRejectedByTheDatabase(
        self, client, people, session: Session
    ) -> None:
        workspace = session.scalar(text("select id from workspaces limit 1"))
        for column, value in (
            ("action", "file.exploded"),
            ("result", "maybe"),
            ("resource_type", "robot"),
        ):
            fields = {
                "action": "file.deleted",
                "result": "success",
                "resource_type": "file",
                column: value,
            }
            with pytest.raises(Exception), session.begin_nested():  # noqa: B017  (a CHECK violation)
                session.add(AuditEvent(workspace_id=workspace, **fields))
                session.flush()
