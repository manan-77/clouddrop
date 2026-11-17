import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import httpx2 as httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.modules.sharing.models import Permission
from app.modules.sharing.repository import PermissionRepository
from app.modules.storage.models import File
from tests.conftest import BUCKET

if TYPE_CHECKING:
    from mypy_boto3_s3.client import S3Client


@dataclass
class Person:
    email: str
    headers: dict[str, str]


def _person(client: TestClient, label: str) -> Person:
    email = f"{label}-{uuid.uuid4().hex[:8]}@example.com"
    password = "a-long-test-password"
    body = {"email": email, "password": password, "display_name": label.title()}
    assert client.post("/api/v1/auth/register", json=body).status_code == 201
    login = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    return Person(email, {"Authorization": f"Bearer {login.json()['access_token']}"})


@pytest.fixture
def people(client: TestClient) -> dict[str, Person]:
    return {name: _person(client, name) for name in ("owner", "editor", "viewer", "stranger")}


def _folder(client: TestClient, who: Person, name: str, parent: str | None = None) -> str:
    response = client.post(
        "/api/v1/folders", json={"name": name, "parent_id": parent}, headers=who.headers
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def _file(
    client: TestClient,
    who: Person,
    s3_client: "S3Client",
    session: Session,
    folder: str | None,
    name: str = "a.txt",
    ready: bool = True,
) -> str:
    body = b"hello"
    init = client.post(
        "/api/v1/files/uploads",
        json={
            "name": name,
            "content_type": "text/plain",
            "size_bytes": len(body),
            "folder_id": folder,
        },
        headers=who.headers,
    )
    assert init.status_code == 201, init.text
    file_id = str(init.json()["file"]["id"])
    s3_client.put_object(Bucket=BUCKET, Key=init.json()["upload"]["fields"]["key"], Body=body)
    assert (
        client.post(f"/api/v1/files/{file_id}/uploads/complete", headers=who.headers).status_code
        == 200
    )
    if ready:
        session.execute(update(File).where(File.id == uuid.UUID(file_id)).values(status="ready"))
        session.commit()
    return file_id


def _grant(
    client: TestClient, owner: Person, kind: str, rid: str, who: Person, role: str
) -> httpx.Response:
    return client.post(
        f"/api/v1/{kind}/{rid}/permissions",
        json={"email": who.email, "role": role},
        headers=owner.headers,
    )


class TestGrantApi:
    def test_grantRevokeAndList_workForTheOwnerAndAreIdempotent(self, client, people) -> None:
        owner, editor = people["owner"], people["editor"]
        folder = _folder(client, owner, "Shared")
        first = _grant(client, owner, "folders", folder, editor, "viewer")
        assert first.status_code == 201 and first.headers["Location"].endswith(first.json()["id"])
        again = _grant(client, owner, "folders", folder, editor, "editor")
        assert again.status_code == 200 and again.json()["id"] == first.json()["id"]
        assert again.json()["role"] == "editor"
        listing = client.get(f"/api/v1/folders/{folder}/permissions", headers=owner.headers).json()
        assert listing["total"] == 1 and listing["items"][0]["email"] == editor.email
        changed = client.patch(
            f"/api/v1/folders/{folder}/permissions/{first.json()['id']}",
            json={"role": "viewer"},
            headers=owner.headers,
        )
        assert changed.json()["role"] == "viewer"
        url = f"/api/v1/folders/{folder}/permissions/{first.json()['id']}"
        assert client.delete(url, headers=owner.headers).status_code == 204
        assert client.delete(url, headers=owner.headers).status_code == 404

    def test_unknownEmailSelfAndInvalidRole_areRefused(self, client, people) -> None:
        owner = people["owner"]
        folder = _folder(client, owner, "F")
        path = f"/api/v1/folders/{folder}/permissions"
        unknown = client.post(
            path, json={"email": "nobody@example.com", "role": "viewer"}, headers=owner.headers
        )
        assert unknown.status_code == 404 and unknown.json()["error"]["code"] == "user_not_found"
        own = _grant(client, owner, "folders", folder, owner, "viewer")
        assert own.status_code == 422 and own.json()["error"]["code"] == "cannot_share_with_self"
        bad = client.post(
            path, json={"email": people["editor"].email, "role": "owner"}, headers=owner.headers
        )
        assert bad.status_code == 422

    def test_onlyReadyFilesCanBeShared(self, client, people, s3_client, session: Session) -> None:
        owner, viewer = people["owner"], people["viewer"]
        pending = _file(client, owner, s3_client, session, None, "p.txt", ready=False)
        refused = _grant(client, owner, "files", pending, viewer, "viewer")
        assert refused.status_code == 409 and refused.json()["error"]["code"] == "file_not_ready"
        ready = _file(client, owner, s3_client, session, None, "r.txt")
        assert _grant(client, owner, "files", ready, viewer, "viewer").status_code == 201

    @pytest.mark.parametrize("who", ["editor", "viewer", "stranger"])
    def test_nonOwners_cannotManageSharingAndGet404(self, client, people, who: str) -> None:
        owner = people["owner"]
        folder = _folder(client, owner, "F")
        _grant(client, owner, "folders", folder, people["editor"], "editor")
        _grant(client, owner, "folders", folder, people["viewer"], "viewer")
        actor = people[who]
        base = f"/api/v1/folders/{folder}/permissions"
        assert client.get(base, headers=actor.headers).status_code == 404
        assert (
            _grant(client, actor, "folders", folder, people["stranger"], "viewer").status_code
            == 404
        )
        listing = client.get(base, headers=owner.headers).json()["items"][0]["id"]
        assert (
            client.patch(
                f"{base}/{listing}", json={"role": "editor"}, headers=actor.headers
            ).status_code
            == 404
        )
        assert client.delete(f"{base}/{listing}", headers=actor.headers).status_code == 404

    def test_grantEndpoint_isRateLimitedPerUser(self, client, people) -> None:
        owner, viewer = people["owner"], people["viewer"]
        limit = get_settings().rate_limit_grant_per_user
        folder = _folder(client, owner, "F")
        statuses = [
            _grant(client, owner, "folders", folder, viewer, "viewer").status_code
            for _ in range(limit + 1)
        ]
        assert statuses[-1] == 429 and 429 not in statuses[:limit]
        # The budget is per user: someone else can still share.
        other = _folder(client, people["editor"], "Mine")
        assert (
            _grant(client, people["editor"], "folders", other, viewer, "viewer").status_code == 201
        )

    def test_aStrangerCannotTellAMissingResourceFromAForbiddenOne(self, client, people) -> None:
        owner, stranger = people["owner"], people["stranger"]
        folder = _folder(client, owner, "F")
        forbidden = client.get(f"/api/v1/folders/{folder}", headers=stranger.headers)
        missing = client.get(f"/api/v1/folders/{uuid.uuid4()}", headers=stranger.headers)
        assert forbidden.status_code == missing.status_code == 404
        assert forbidden.json()["error"]["code"] == missing.json()["error"]["code"]
        assert forbidden.json()["error"]["message"] == missing.json()["error"]["message"]


class TestRoleMatrix:
    """viewer reads, editor reads and writes, only the owner deletes and shares."""

    @pytest.fixture
    def tree(self, client, people, s3_client, session: Session) -> dict[str, str]:
        owner = people["owner"]
        top = _folder(client, owner, "Top")
        child = _folder(client, owner, "Child", top)
        file_id = _file(client, owner, s3_client, session, child, "deep.txt")
        _grant(client, owner, "folders", top, people["editor"], "editor")
        _grant(client, owner, "folders", top, people["viewer"], "viewer")
        return {"top": top, "child": child, "file": file_id}

    @pytest.mark.parametrize(
        ("who", "status"), [("editor", 200), ("viewer", 200), ("stranger", 404)]
    )
    def test_read_everythingUnderAGrantedFolder(
        self, client, people, tree, who: str, status: int
    ) -> None:
        h = people[who].headers
        assert client.get(f"/api/v1/folders/{tree['top']}", headers=h).status_code == status
        assert client.get(f"/api/v1/folders/{tree['child']}", headers=h).status_code == status
        assert client.get(f"/api/v1/files/{tree['file']}", headers=h).status_code == status
        listing = client.get(f"/api/v1/files?folder_id={tree['child']}", headers=h)
        assert listing.status_code == status
        if status == 200:
            assert [i["name"] for i in listing.json()["items"]] == ["deep.txt"]
        sub = client.get(f"/api/v1/folders?parent_id={tree['top']}", headers=h)
        assert sub.status_code == status

    @pytest.mark.parametrize(
        ("who", "status"), [("editor", 201), ("viewer", 404), ("stranger", 404)]
    )
    def test_write_createFolderAndUploadIntoTheSharedTree(
        self, client, people, tree, who: str, status: int
    ) -> None:
        h = people[who].headers
        made = client.post(
            "/api/v1/folders", json={"name": "New", "parent_id": tree["child"]}, headers=h
        )
        assert made.status_code == status
        upload = client.post(
            "/api/v1/files/uploads",
            json={
                "name": "u.txt",
                "content_type": "text/plain",
                "size_bytes": 3,
                "folder_id": tree["child"],
            },
            headers=h,
        )
        assert upload.status_code == status

    @pytest.mark.parametrize(
        ("who", "status"), [("editor", 200), ("viewer", 404), ("stranger", 404)]
    )
    def test_write_renameFolderAndFile(self, client, people, tree, who: str, status: int) -> None:
        h = people[who].headers
        assert (
            client.patch(
                f"/api/v1/folders/{tree['child']}", json={"name": "Renamed"}, headers=h
            ).status_code
            == status
        )
        assert (
            client.patch(
                f"/api/v1/files/{tree['file']}", json={"name": "r.txt"}, headers=h
            ).status_code
            == status
        )

    @pytest.mark.parametrize("who", ["editor", "viewer", "stranger"])
    def test_delete_isOwnerOnly(self, client, people, tree, who: str) -> None:
        h = people[who].headers
        assert client.delete(f"/api/v1/files/{tree['file']}", headers=h).status_code == 404
        assert client.delete(f"/api/v1/folders/{tree['child']}", headers=h).status_code == 404
        assert (
            client.delete(
                f"/api/v1/files/{tree['file']}", headers=people["owner"].headers
            ).status_code
            == 204
        )

    def test_editorUploadsLandInTheOwnersWorkspaceNotTheEditors(
        self, client, people, tree, s3_client, session: Session
    ) -> None:
        editor, owner = people["editor"], people["owner"]
        uploaded = _file(client, editor, s3_client, session, tree["child"], "by-editor.txt")
        names = [
            i["name"]
            for i in client.get(
                f"/api/v1/files?folder_id={tree['child']}", headers=owner.headers
            ).json()["items"]
        ]
        assert "by-editor.txt" in names
        # The editor's own root stays empty.
        assert client.get("/api/v1/files", headers=editor.headers).json()["total"] == 0
        row = session.execute(
            text(
                "select u.email, f.created_by from files f "
                "join workspaces w on w.id = f.workspace_id join users u on u.id = w.owner_id "
                "where f.id = :i"
            ),
            {"i": uploaded},
        ).one()
        assert row.email == owner.email  # the owner's workspace (and quota) holds it
        editor_id = session.scalar(
            text("select id from users where email = :e"), {"e": editor.email}
        )
        assert row.created_by == editor_id  # while the uploader is remembered

    def test_download_nonOwnersSeeAndGetOnlyReadyFiles(
        self, client, people, tree, s3_client, session: Session
    ) -> None:
        viewer, owner = people["viewer"], people["owner"]
        url = f"/api/v1/files/{tree['file']}/download"
        assert client.get(url, headers=viewer.headers).status_code == 200
        for status, owner_status in (("processing", 200), ("infected", 403)):
            session.execute(
                update(File).where(File.id == uuid.UUID(tree["file"])).values(status=status)
            )
            session.commit()
            # A grantee cannot even tell the file exists until it is ready.
            assert client.get(url, headers=viewer.headers).status_code == 404
            assert client.get(url, headers=owner.headers).status_code == owner_status


class TestInheritance:
    def test_folderGrantCoversFuturelyCreatedDescendants(
        self, client, people, s3_client, session
    ) -> None:
        owner, viewer = people["owner"], people["viewer"]
        top = _folder(client, owner, "Top")
        _grant(client, owner, "folders", top, viewer, "viewer")
        later = _folder(client, owner, "Later", top)
        file_id = _file(client, owner, s3_client, session, later)
        assert client.get(f"/api/v1/folders/{later}", headers=viewer.headers).status_code == 200
        assert client.get(f"/api/v1/files/{file_id}", headers=viewer.headers).status_code == 200

    def test_aGrantDoesNotReachSiblingsOrParents(self, client, people, s3_client, session) -> None:
        owner, viewer = people["owner"], people["viewer"]
        parent = _folder(client, owner, "Parent")
        granted = _folder(client, owner, "Granted", parent)
        sibling = _folder(client, owner, "Sibling", parent)
        _grant(client, owner, "folders", granted, viewer, "viewer")
        assert client.get(f"/api/v1/folders/{granted}", headers=viewer.headers).status_code == 200
        assert client.get(f"/api/v1/folders/{sibling}", headers=viewer.headers).status_code == 404
        assert client.get(f"/api/v1/folders/{parent}", headers=viewer.headers).status_code == 404
        root_file = _file(client, owner, s3_client, session, None, "root.txt")
        assert client.get(f"/api/v1/files/{root_file}", headers=viewer.headers).status_code == 404

    def test_aFileGrantCoversThatFileOnly(self, client, people, s3_client, session) -> None:
        owner, viewer = people["owner"], people["viewer"]
        folder = _folder(client, owner, "F")
        shared = _file(client, owner, s3_client, session, folder, "shared.txt")
        other = _file(client, owner, s3_client, session, folder, "other.txt")
        _grant(client, owner, "files", shared, viewer, "viewer")
        assert client.get(f"/api/v1/files/{shared}", headers=viewer.headers).status_code == 200
        assert client.get(f"/api/v1/files/{other}", headers=viewer.headers).status_code == 404
        assert client.get(f"/api/v1/folders/{folder}", headers=viewer.headers).status_code == 404

    def test_theHighestRoleAlongThePathWins(self, client, people) -> None:
        owner, person = people["owner"], people["editor"]
        top = _folder(client, owner, "Top")
        inner = _folder(client, owner, "Inner", top)
        other = _folder(client, owner, "Other", top)
        _grant(client, owner, "folders", top, person, "viewer")
        _grant(client, owner, "folders", inner, person, "editor")
        h = person.headers
        assert (
            client.post(
                "/api/v1/folders", json={"name": "x", "parent_id": inner}, headers=h
            ).status_code
            == 201
        )
        assert (
            client.post(
                "/api/v1/folders", json={"name": "y", "parent_id": other}, headers=h
            ).status_code
            == 404
        )
        # Revoking the lower grant leaves the inherited viewer role in place.
        grant_id = client.get(f"/api/v1/folders/{inner}/permissions", headers=owner.headers).json()[
            "items"
        ][0]["id"]
        client.delete(f"/api/v1/folders/{inner}/permissions/{grant_id}", headers=owner.headers)
        assert client.get(f"/api/v1/folders/{inner}", headers=h).status_code == 200
        assert (
            client.post(
                "/api/v1/folders", json={"name": "z", "parent_id": inner}, headers=h
            ).status_code
            == 404
        )

    def test_revokeTakesEffectImmediately(self, client, people) -> None:
        owner, viewer = people["owner"], people["viewer"]
        folder = _folder(client, owner, "F")
        grant = _grant(client, owner, "folders", folder, viewer, "viewer").json()["id"]
        assert client.get(f"/api/v1/folders/{folder}", headers=viewer.headers).status_code == 200
        client.delete(f"/api/v1/folders/{folder}/permissions/{grant}", headers=owner.headers)
        assert client.get(f"/api/v1/folders/{folder}", headers=viewer.headers).status_code == 404

    def test_aDeletedFolderDisappearsForGrantees(self, client, people) -> None:
        owner, viewer = people["owner"], people["viewer"]
        top = _folder(client, owner, "Top")
        _grant(client, owner, "folders", top, viewer, "viewer")
        inner = _folder(client, owner, "Inner", top)
        assert client.delete(f"/api/v1/folders/{inner}", headers=owner.headers).status_code == 204
        assert client.get(f"/api/v1/folders/{inner}", headers=viewer.headers).status_code == 404

    def test_movingAFileOutOfTheSharedTreeRemovesAccessAndMovingInGrantsIt(
        self, client, people, s3_client, session
    ) -> None:
        owner, viewer = people["owner"], people["viewer"]
        shared = _folder(client, owner, "Shared")
        private = _folder(client, owner, "Private")
        _grant(client, owner, "folders", shared, viewer, "viewer")
        file_id = _file(client, owner, s3_client, session, shared)
        assert client.get(f"/api/v1/files/{file_id}", headers=viewer.headers).status_code == 200
        client.patch(f"/api/v1/files/{file_id}", json={"folder_id": private}, headers=owner.headers)
        assert client.get(f"/api/v1/files/{file_id}", headers=viewer.headers).status_code == 404
        client.patch(f"/api/v1/files/{file_id}", json={"folder_id": shared}, headers=owner.headers)
        assert client.get(f"/api/v1/files/{file_id}", headers=viewer.headers).status_code == 200

    def test_aFileGrantFollowsTheFileWhenItMoves(self, client, people, s3_client, session) -> None:
        owner, viewer = people["owner"], people["viewer"]
        a, b = _folder(client, owner, "A"), _folder(client, owner, "B")
        file_id = _file(client, owner, s3_client, session, a)
        _grant(client, owner, "files", file_id, viewer, "viewer")
        client.patch(f"/api/v1/files/{file_id}", json={"folder_id": b}, headers=owner.headers)
        assert client.get(f"/api/v1/files/{file_id}", headers=viewer.headers).status_code == 200

    def test_editorMoves_stayInsideTheSharedWorkspaceAndNeverToTheRoot(
        self, client, people, s3_client, session
    ) -> None:
        owner, editor = people["owner"], people["editor"]
        shared = _folder(client, owner, "Shared")
        inner = _folder(client, owner, "Inner", shared)
        outside = _folder(client, owner, "Outside")
        mine = _folder(client, editor, "Mine")
        _grant(client, owner, "folders", shared, editor, "editor")
        file_id = _file(client, owner, s3_client, session, shared)
        url, h = f"/api/v1/files/{file_id}", editor.headers
        assert client.patch(url, json={"folder_id": inner}, headers=h).status_code == 200
        assert client.patch(url, json={"folder_id": None}, headers=h).status_code == 404
        assert client.patch(url, json={"folder_id": outside}, headers=h).status_code == 404
        assert client.patch(url, json={"folder_id": mine}, headers=h).status_code == 404

    def test_breadcrumbsStopAtTheGrantedFolder(self, client, people) -> None:
        owner, viewer = people["owner"], people["viewer"]
        a = _folder(client, owner, "A")
        b = _folder(client, owner, "B", a)
        c = _folder(client, owner, "C", b)
        _grant(client, owner, "folders", b, viewer, "viewer")
        path = client.get(f"/api/v1/folders/{c}/path", headers=viewer.headers).json()
        assert [f["name"] for f in path] == ["B", "C"]
        full = client.get(f"/api/v1/folders/{c}/path", headers=owner.headers).json()
        assert [f["name"] for f in full] == ["A", "B", "C"]


class TestSharedWithMe:
    def test_listsDirectGrantsOnlyAndDropsRevokedOnes(
        self, client, people, s3_client, session
    ) -> None:
        owner, viewer = people["owner"], people["viewer"]
        top = _folder(client, owner, "Top")
        _folder(client, owner, "Inner", top)
        file_id = _file(client, owner, s3_client, session, None, "solo.txt")
        _grant(client, owner, "folders", top, viewer, "editor")
        grant = _grant(client, owner, "files", file_id, viewer, "viewer").json()["id"]
        page = client.get("/api/v1/shared-with-me", headers=viewer.headers).json()
        assert page["total"] == 2
        by_name = {i["name"]: i for i in page["items"]}
        assert by_name["Top"]["resource_type"] == "folder" and by_name["Top"]["role"] == "editor"
        assert (
            by_name["solo.txt"]["resource_type"] == "file"
            and by_name["solo.txt"]["size_bytes"] == 5
        )
        assert by_name["Top"]["owner_name"] == "Owner"
        client.delete(f"/api/v1/files/{file_id}/permissions/{grant}", headers=owner.headers)
        assert client.get("/api/v1/shared-with-me", headers=viewer.headers).json()["total"] == 1

    def test_isPaginatedInTheDatabaseWithAConstantQueryCount(
        self, client, people, session: Session
    ) -> None:
        owner, viewer = people["owner"], people["viewer"]
        for i in range(6):
            _grant(client, owner, "folders", _folder(client, owner, f"F{i}"), viewer, "viewer")
        counts: list[int] = []
        for size in (2, 6):
            statements: list[str] = []

            def record(conn, cursor, statement, *args, bucket=statements):  # type: ignore[no-untyped-def]
                bucket.append(statement)

            engine = session.get_bind()
            event.listen(engine, "before_cursor_execute", record)
            try:
                page = client.get(
                    f"/api/v1/shared-with-me?page_size={size}", headers=viewer.headers
                ).json()
            finally:
                event.remove(engine, "before_cursor_execute", record)
            assert len(page["items"]) == size and page["total"] == 6
            counts.append(len(statements))
        assert counts[0] == counts[1]

    def test_otherUsersNeverSeeSomeoneElsesGrants(self, client, people) -> None:
        owner = people["owner"]
        _grant(client, owner, "folders", _folder(client, owner, "F"), people["viewer"], "viewer")
        assert (
            client.get("/api/v1/shared-with-me", headers=people["stranger"].headers).json()["total"]
            == 0
        )


class TestConstraints:
    def test_aGrantNeedsExactlyOneResourceAndAValidRole(
        self, session: Session, client, people
    ) -> None:
        owner, viewer = people["owner"], people["viewer"]
        folder = _folder(client, owner, "F")
        user_id = session.scalar(text("select id from users where email = :e"), {"e": viewer.email})
        for kwargs in (
            {"role": "viewer"},  # no resource
            {"role": "viewer", "folder_id": uuid.UUID(folder), "file_id": uuid.uuid4()},
            {"role": "owner", "folder_id": uuid.UUID(folder)},
        ):
            with pytest.raises(IntegrityError), session.begin_nested():
                session.add(Permission(grantee_id=user_id, **kwargs))
                session.flush()


def _start_multipart(client: TestClient, who: Person, folder: str) -> httpx.Response:
    return client.post(
        "/api/v1/files/uploads/multipart",
        json={
            "name": "big.txt",
            "content_type": "text/plain",
            "size_bytes": 20_000_000,
            "folder_id": folder,
        },
        headers=who.headers,
    )


def _parts(client: TestClient, who: Person, file_id: str) -> httpx.Response:
    return client.post(
        f"/api/v1/files/{file_id}/uploads/parts", json={"part_numbers": [1]}, headers=who.headers
    )


class TestUploadsInSharedFolders:
    @pytest.fixture
    def shared(self, client, people) -> str:
        folder = _folder(client, people["owner"], "Shared")
        _grant(client, people["owner"], "folders", folder, people["editor"], "editor")
        _grant(client, people["owner"], "folders", folder, people["viewer"], "viewer")
        return folder

    @pytest.mark.parametrize(
        ("who", "status"), [("editor", 201), ("viewer", 404), ("stranger", 404)]
    )
    def test_multipartInit_followsTheWriteRule(
        self, client, people, shared, who: str, status: int
    ) -> None:
        assert _start_multipart(client, people[who], shared).status_code == status

    def test_onlyTheUploaderOrTheOwnerMayDriveAnUploadInProgress(
        self, client, people, shared
    ) -> None:
        owner = people["owner"]
        file_id = _start_multipart(client, owner, shared).json()["file"]["id"]
        for name in ("editor", "viewer", "stranger"):
            who = people[name]
            assert _parts(client, who, file_id).status_code == 404
            done = client.post(f"/api/v1/files/{file_id}/uploads/complete", headers=who.headers)
            assert done.status_code == 404
            assert (
                client.delete(f"/api/v1/files/{file_id}/uploads", headers=who.headers).status_code
                == 404
            )
        assert _parts(client, owner, file_id).status_code == 200

    def test_theOwnerCanAbortAnEditorsUploadEvenAfterTheGrantIsRevoked(
        self, client, people, shared
    ) -> None:
        owner, editor = people["owner"], people["editor"]
        file_id = _start_multipart(client, editor, shared).json()["file"]["id"]
        assert _parts(client, editor, file_id).status_code == 200
        grants = client.get(f"/api/v1/folders/{shared}/permissions", headers=owner.headers)
        grant = next(g for g in grants.json()["items"] if g["email"] == editor.email)["id"]
        client.delete(f"/api/v1/folders/{shared}/permissions/{grant}", headers=owner.headers)
        assert (
            client.delete(f"/api/v1/files/{file_id}/uploads", headers=editor.headers).status_code
            == 404
        )
        assert _start_multipart(client, editor, shared).status_code == 404
        assert (
            client.delete(f"/api/v1/files/{file_id}/uploads", headers=owner.headers).status_code
            == 204
        )

    def test_uploadInit_isRateLimitedPerUser(self, client, people, shared) -> None:
        limit = get_settings().rate_limit_upload_init_per_user
        body = {"name": "x.txt", "content_type": "text/plain", "size_bytes": 1, "folder_id": shared}
        codes = [
            client.post(
                "/api/v1/files/uploads", json=body, headers=people["editor"].headers
            ).status_code
            for _ in range(limit + 1)
        ]
        assert codes[-1] == 429 and 429 not in codes[:limit]

    def test_uploadIntoADeletedSharedFolder_is404(self, client, people) -> None:
        owner, editor = people["owner"], people["editor"]
        top = _folder(client, owner, "Top")
        inner = _folder(client, owner, "Inner", top)
        _grant(client, owner, "folders", top, editor, "editor")
        client.delete(f"/api/v1/folders/{inner}", headers=owner.headers)
        assert _start_multipart(client, editor, inner).status_code == 404


class TestNonReadyFilesStayHidden:
    def test_aGranteeSeesOnlyReadyFilesAndTheirOwnUploads(
        self, client, people, s3_client, session: Session
    ) -> None:
        owner, editor, viewer = people["owner"], people["editor"], people["viewer"]
        folder = _folder(client, owner, "F")
        _grant(client, owner, "folders", folder, editor, "editor")
        _grant(client, owner, "folders", folder, viewer, "viewer")
        ready = _file(client, owner, s3_client, session, folder, "ready.txt")
        flagged = _file(client, owner, s3_client, session, folder, "flagged.txt", ready=False)
        mine = _file(client, editor, s3_client, session, folder, "mine.txt", ready=False)
        session.execute(update(File).where(File.id == uuid.UUID(flagged)).values(status="infected"))
        session.commit()

        def names(who: Person) -> set[str]:
            url = f"/api/v1/files?folder_id={folder}"
            return {i["name"] for i in client.get(url, headers=who.headers).json()["items"]}

        assert names(owner) == {"ready.txt", "flagged.txt", "mine.txt"}
        assert names(viewer) == {"ready.txt"}
        assert names(editor) == {"ready.txt", "mine.txt"}
        assert client.get(f"/api/v1/files/{flagged}", headers=viewer.headers).status_code == 404
        assert client.get(f"/api/v1/files/{flagged}", headers=editor.headers).status_code == 404
        assert client.get(f"/api/v1/files/{mine}", headers=editor.headers).status_code == 200
        assert client.get(f"/api/v1/files/{ready}", headers=viewer.headers).status_code == 200

    def test_aFileThatLaterTurnsInfectedLeavesSharedWithMe(
        self, client, people, s3_client, session: Session
    ) -> None:
        owner, viewer = people["owner"], people["viewer"]
        file_id = _file(client, owner, s3_client, session, None)
        _grant(client, owner, "files", file_id, viewer, "viewer")
        assert client.get("/api/v1/shared-with-me", headers=viewer.headers).json()["total"] == 1
        session.execute(update(File).where(File.id == uuid.UUID(file_id)).values(status="infected"))
        session.commit()
        assert client.get("/api/v1/shared-with-me", headers=viewer.headers).json()["total"] == 0


class TestHiddenAncestors:
    def test_theTopOfASharedTreeDoesNotRevealItsParent(self, client, people) -> None:
        owner, viewer = people["owner"], people["viewer"]
        a = _folder(client, owner, "A")
        b = _folder(client, owner, "B", a)
        c = _folder(client, owner, "C", b)
        _grant(client, owner, "folders", b, viewer, "viewer")
        assert (
            client.get(f"/api/v1/folders/{b}", headers=viewer.headers).json()["parent_id"] is None
        )
        assert client.get(f"/api/v1/folders/{c}", headers=viewer.headers).json()["parent_id"] == b
        assert client.get(f"/api/v1/folders/{b}", headers=owner.headers).json()["parent_id"] == a
        path = client.get(f"/api/v1/folders/{c}/path", headers=viewer.headers).json()
        assert [f["parent_id"] for f in path] == [None, b]
        children = client.get(f"/api/v1/folders?parent_id={b}", headers=viewer.headers).json()
        assert children["items"][0]["parent_id"] == b

    def test_aFileOnlyGranteeIsNotToldTheFolder(
        self, client, people, s3_client, session: Session
    ) -> None:
        owner, viewer = people["owner"], people["viewer"]
        folder = _folder(client, owner, "F")
        file_id = _file(client, owner, s3_client, session, folder)
        _grant(client, owner, "files", file_id, viewer, "viewer")
        assert (
            client.get(f"/api/v1/files/{file_id}", headers=viewer.headers).json()["folder_id"]
            is None
        )
        assert (
            client.get(f"/api/v1/files/{file_id}", headers=owner.headers).json()["folder_id"]
            == folder
        )

    def test_pathStartsAtTheHighestGrantWhenSeveralNestedGrantsExist(self, client, people) -> None:
        owner, person = people["owner"], people["editor"]
        top = _folder(client, owner, "Top")
        a = _folder(client, owner, "A", top)
        b = _folder(client, owner, "B", a)
        c = _folder(client, owner, "C", b)
        _grant(client, owner, "folders", a, person, "viewer")
        _grant(client, owner, "folders", c, person, "editor")
        path = client.get(f"/api/v1/folders/{c}/path", headers=person.headers).json()
        assert [f["name"] for f in path] == ["A", "B", "C"]


class TestMovesAndGrantEdgeCases:
    def test_anEditorCannotMoveIntoAFolderWhereTheyAreOnlyAViewer(
        self, client, people, s3_client, session: Session
    ) -> None:
        owner, person = people["owner"], people["editor"]
        rw, ro = _folder(client, owner, "RW"), _folder(client, owner, "RO")
        _grant(client, owner, "folders", rw, person, "editor")
        _grant(client, owner, "folders", ro, person, "viewer")
        file_id = _file(client, owner, s3_client, session, rw)
        moved = client.patch(
            f"/api/v1/files/{file_id}", json={"folder_id": ro}, headers=person.headers
        )
        assert moved.status_code == 404

    def test_aPermissionIdIsOnlyValidUnderItsOwnResource(
        self, client, people, s3_client, session: Session
    ) -> None:
        owner, viewer = people["owner"], people["viewer"]
        one, two = _folder(client, owner, "One"), _folder(client, owner, "Two")
        grant = _grant(client, owner, "folders", one, viewer, "viewer").json()["id"]
        file_id = _file(client, owner, s3_client, session, None)
        for url in (
            f"/api/v1/folders/{two}/permissions/{grant}",
            f"/api/v1/files/{file_id}/permissions/{grant}",
        ):
            assert client.get(url, headers=owner.headers).status_code == 404
            assert (
                client.patch(url, json={"role": "editor"}, headers=owner.headers).status_code == 404
            )
            assert client.delete(url, headers=owner.headers).status_code == 404
        assert (
            client.get(
                f"/api/v1/folders/{one}/permissions/{grant}", headers=owner.headers
            ).status_code
            == 200
        )

    def test_aDeactivatedAccountCannotBeGrantedAccess(
        self, client, people, session: Session
    ) -> None:
        owner, viewer = people["owner"], people["viewer"]
        folder = _folder(client, owner, "F")
        session.execute(
            text("update users set is_active = false where email = :e"), {"e": viewer.email}
        )
        session.commit()
        refused = _grant(client, owner, "folders", folder, viewer, "viewer")
        assert refused.status_code == 404 and refused.json()["error"]["code"] == "user_not_found"

    def test_grantsListIsPagedAndOrdered(self, client, people) -> None:
        owner = people["owner"]
        folder = _folder(client, owner, "F")
        for name in ("editor", "viewer", "stranger"):
            _grant(client, owner, "folders", folder, people[name], "viewer")
        base = f"/api/v1/folders/{folder}/permissions"
        first = client.get(f"{base}?page_size=2", headers=owner.headers).json()
        second = client.get(f"{base}?page_size=2&page=2", headers=owner.headers).json()
        emails = [i["email"] for i in first["items"] + second["items"]]
        assert first["total"] == 3 and len(first["items"]) == 2 and len(second["items"]) == 1
        assert emails == sorted(emails)
        assert client.get(f"{base}?page_size=101", headers=owner.headers).status_code == 422
        assert client.get(f"{base}?page=9", headers=owner.headers).json()["items"] == []

    def test_twoGrantsRacingOnTheUniqueIndex_endAsOneIdempotentGrant(
        self, client, people, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        owner, viewer = people["owner"], people["viewer"]
        folder = _folder(client, owner, "F")
        first = _grant(client, owner, "folders", folder, viewer, "viewer")
        real = PermissionRepository.find
        calls = {"n": 0}

        def blind_first_time(
            self: PermissionRepository, *args: Any, **kwargs: Any
        ) -> Permission | None:
            calls["n"] += 1
            return None if calls["n"] == 1 else real(self, *args, **kwargs)

        monkeypatch.setattr(PermissionRepository, "find", blind_first_time)
        again = _grant(client, owner, "folders", folder, viewer, "editor")
        assert again.status_code == 200 and again.json()["id"] == first.json()["id"]
        assert again.json()["role"] == "editor"


class TestRoundTwoRules:
    def test_anEditorCannotRenameTheTopOfTheSharedTree_butCanRenameInsideIt(
        self, client, people
    ) -> None:
        owner, editor = people["owner"], people["editor"]
        _folder(client, owner, "TopSecretSibling")
        top = _folder(client, owner, "Shared")
        inner = _folder(client, owner, "Inner", top)
        _grant(client, owner, "folders", top, editor, "editor")
        for name in ("topsecretsibling", "anything"):
            denied = client.patch(
                f"/api/v1/folders/{top}", json={"name": name}, headers=editor.headers
            )
            assert (
                denied.status_code == 403 and denied.json()["error"]["code"] == "shared_root_locked"
            )
        ok = client.patch(
            f"/api/v1/folders/{inner}", json={"name": "Renamed"}, headers=editor.headers
        )
        assert ok.status_code == 200
        assert (
            client.patch(
                f"/api/v1/folders/{top}", json={"name": "Mine"}, headers=owner.headers
            ).status_code
            == 200
        )

    def test_anOwnerFillingTheirOwnSpaceIsNotRateLimited(self, client, people) -> None:
        owner = people["owner"]
        limit = get_settings().rate_limit_upload_init_per_user
        body = {"name": "x.txt", "content_type": "text/plain", "size_bytes": 1}
        codes = {
            client.post("/api/v1/files/uploads", json=body, headers=owner.headers).status_code
            for _ in range(limit + 5)
        }
        assert codes == {201}

    def test_aSecondEditorCannotCompleteOrAbortAnotherEditorsFile(
        self, client, people, s3_client, session: Session
    ) -> None:
        owner, first, second = people["owner"], people["editor"], _person(client, "editor2")
        folder = _folder(client, owner, "Shared")
        for who in (first, second):
            _grant(client, owner, "folders", folder, who, "editor")
        file_id = _file(client, first, s3_client, session, folder)  # ready, visible to both
        assert client.get(f"/api/v1/files/{file_id}", headers=second.headers).status_code == 200
        done = client.post(f"/api/v1/files/{file_id}/uploads/complete", headers=second.headers)
        assert done.status_code == 404
        assert (
            client.delete(f"/api/v1/files/{file_id}/uploads", headers=second.headers).status_code
            == 404
        )
        assert (
            client.post(
                f"/api/v1/files/{file_id}/uploads/complete", headers=first.headers
            ).status_code
            == 200
        )

    @pytest.mark.parametrize("listing", ["files", "folders"])
    def test_granteeListingsUseAConstantNumberOfQueries(
        self, client, people, s3_client, session: Session, listing: str
    ) -> None:
        owner, viewer = people["owner"], people["viewer"]
        top = _folder(client, owner, "Top")
        _grant(client, owner, "folders", top, viewer, "viewer")
        url = f"/api/v1/{listing}?{'folder_id' if listing == 'files' else 'parent_id'}={top}"
        counts = []
        for batch in (2, 6):
            for i in range(batch):
                if listing == "files":
                    _file(client, owner, s3_client, session, top, f"f{batch}-{i}.txt")
                else:
                    _folder(client, owner, f"d{batch}-{i}", top)
            statements: list[str] = []

            def record(conn, cursor, statement, *args, bucket=statements):  # type: ignore[no-untyped-def]  # SQLAlchemy event hook signature
                bucket.append(statement)

            engine = session.get_bind()
            event.listen(engine, "before_cursor_execute", record)
            try:
                response = client.get(url, headers=viewer.headers)
            finally:
                event.remove(engine, "before_cursor_execute", record)
            assert response.status_code == 200
            counts.append(len(statements))
        assert counts[0] == counts[1]
