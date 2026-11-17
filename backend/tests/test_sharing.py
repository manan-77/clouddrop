import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.modules.sharing.models import Permission
from app.modules.storage.models import File
from tests.conftest import BUCKET, FakeRateLimiter

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


def _grant(client: TestClient, owner: Person, kind: str, rid: str, who: Person, role: str):  # type: ignore[no-untyped-def]
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

    def test_grantEndpoint_isRateLimited(
        self, client, people, rate_limiter: FakeRateLimiter
    ) -> None:
        owner = people["owner"]
        folder = _folder(client, owner, "F")
        statuses = [
            _grant(client, owner, "folders", folder, people["viewer"], "viewer").status_code
            for _ in range(61)
        ]
        assert statuses[-1] == 429 and 429 not in statuses[:60]

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
        owner_ws = session.scalar(
            text("select workspace_id from files where id = :i"), {"i": uploaded}
        )
        owners = session.scalar(
            text("select owner_id from workspaces where id = :w"), {"w": owner_ws}
        )
        assert (
            str(owners) != ""
            and session.scalar(
                text("select count(*) from users where id = :o and email = :e"),
                {"o": owners, "e": owner.email},
            )
            == 1
        )

    def test_download_nonOwnersGetOnlyReadyFiles(
        self, client, people, tree, s3_client, session: Session
    ) -> None:
        viewer, owner = people["viewer"], people["owner"]
        assert (
            client.get(f"/api/v1/files/{tree['file']}/download", headers=viewer.headers).status_code
            == 200
        )
        session.execute(
            update(File).where(File.id == uuid.UUID(tree["file"])).values(status="processing")
        )
        session.commit()
        assert (
            client.get(f"/api/v1/files/{tree['file']}/download", headers=viewer.headers).status_code
            == 409
        )
        assert (
            client.get(f"/api/v1/files/{tree['file']}/download", headers=owner.headers).status_code
            == 200
        )
        session.execute(
            update(File).where(File.id == uuid.UUID(tree["file"])).values(status="infected")
        )
        session.commit()
        assert (
            client.get(f"/api/v1/files/{tree['file']}/download", headers=viewer.headers).status_code
            == 409
        )
        assert (
            client.get(f"/api/v1/files/{tree['file']}/download", headers=owner.headers).status_code
            == 403
        )


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
        names = [f["name"] for f in (path if isinstance(path, list) else path["items"])]
        assert names == ["B", "C"]
        full = client.get(f"/api/v1/folders/{c}/path", headers=owner.headers).json()
        assert [f["name"] for f in (full if isinstance(full, list) else full["items"])] == [
            "A",
            "B",
            "C",
        ]


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
