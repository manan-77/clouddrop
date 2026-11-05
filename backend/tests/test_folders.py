import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, event, func, update
from sqlalchemy.orm import Session

from app.modules.storage.models import Folder
from app.modules.storage.repository import FolderRepository

Headers = dict[str, str]


def _create(
    client: TestClient, headers: Headers, name: str, parent_id: str | None = None
) -> httpx.Response:
    return client.post(
        "/api/v1/folders", json={"name": name, "parent_id": parent_id}, headers=headers
    )


def test_createFolder_root_returns201LocationAndBody(
    client: TestClient, make_user: Callable[[], Headers]
) -> None:
    response = _create(client, make_user(), "Reports")
    assert response.status_code == 201
    body = response.json()
    assert response.headers["location"] == f"/api/v1/folders/{body['id']}"
    assert body["name"] == "Reports" and body["parent_id"] is None


def test_createFolder_siblingSameNameDifferentCase_returns409(
    client: TestClient, make_user: Callable[[], Headers]
) -> None:
    headers = make_user()
    assert _create(client, headers, "Reports").status_code == 201
    response = _create(client, headers, "REPORTS")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "folder_name_taken"


def test_createFolder_sameNameUnderDifferentParent_returns201(
    client: TestClient, make_user: Callable[[], Headers]
) -> None:
    headers = make_user()
    parent = _create(client, headers, "A").json()["id"]
    assert _create(client, headers, "Reports").status_code == 201
    assert _create(client, headers, "Reports", parent).status_code == 201


def test_createFolder_pathSeparatorsInName_areSanitized(
    client: TestClient, make_user: Callable[[], Headers]
) -> None:
    response = _create(client, make_user(), "../../etc")
    assert response.status_code == 201
    assert "/" not in response.json()["name"]


def test_createFolder_dotNameOrBlank_returns422(
    client: TestClient, make_user: Callable[[], Headers]
) -> None:
    headers = make_user()
    assert _create(client, headers, "..").status_code == 422
    assert _create(client, headers, "   ").status_code == 422


def test_folders_noToken_returns401(client: TestClient) -> None:
    assert client.get("/api/v1/folders").status_code == 401


def test_folders_otherUsersFolder_returns404ForEveryAction(
    client: TestClient, make_user: Callable[[], Headers]
) -> None:
    owner, stranger = make_user(), make_user()
    folder_id = _create(client, owner, "Private").json()["id"]
    url = f"/api/v1/folders/{folder_id}"
    assert client.get(url, headers=stranger).status_code == 404
    assert client.patch(url, json={"name": "x"}, headers=stranger).status_code == 404
    assert client.delete(url, headers=stranger).status_code == 404
    assert _create(client, stranger, "Child", folder_id).status_code == 404
    assert client.get(url, headers=owner).status_code == 200


def test_listFolders_rootAndChildren_areScopedAndPaginated(
    client: TestClient, make_user: Callable[[], Headers]
) -> None:
    headers = make_user()
    parent = _create(client, headers, "Parent").json()["id"]
    for name in ("b", "a", "c"):
        _create(client, headers, name, parent)
    _create(client, make_user(), "not-mine")

    root = client.get("/api/v1/folders", headers=headers).json()
    assert [f["name"] for f in root["items"]] == ["Parent"] and root["total"] == 1

    page = client.get(
        "/api/v1/folders", params={"parent_id": parent, "page": 2, "page_size": 2}, headers=headers
    ).json()
    assert [f["name"] for f in page["items"]] == ["c"]
    assert page["total"] == 3 and page["page"] == 2


def test_listFolders_pageSizeTooLarge_returns422(
    client: TestClient, make_user: Callable[[], Headers]
) -> None:
    response = client.get("/api/v1/folders", params={"page_size": 101}, headers=make_user())
    assert response.status_code == 422


def test_renameFolder_conflictAndSuccess(
    client: TestClient, make_user: Callable[[], Headers]
) -> None:
    headers = make_user()
    _create(client, headers, "A")
    folder_id = _create(client, headers, "B").json()["id"]
    url = f"/api/v1/folders/{folder_id}"
    assert client.patch(url, json={"name": "a"}, headers=headers).status_code == 409
    renamed = client.patch(url, json={"name": "C"}, headers=headers)
    assert renamed.status_code == 200 and renamed.json()["name"] == "C"


def test_deleteFolder_empty_returns204ThenGoneAndNameIsFree(
    client: TestClient, make_user: Callable[[], Headers]
) -> None:
    headers = make_user()
    folder_id = _create(client, headers, "Temp").json()["id"]
    url = f"/api/v1/folders/{folder_id}"
    assert client.delete(url, headers=headers).status_code == 204
    assert client.get(url, headers=headers).status_code == 404
    assert _create(client, headers, "Temp").status_code == 201


def test_deleteFolder_withChild_returns409(
    client: TestClient, make_user: Callable[[], Headers]
) -> None:
    headers = make_user()
    parent = _create(client, headers, "Parent").json()["id"]
    _create(client, headers, "Child", parent)
    response = client.delete(f"/api/v1/folders/{parent}", headers=headers)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "folder_not_empty"


def _chain(client: TestClient, headers: Headers, depth: int) -> list[str]:
    ids: list[str] = []
    parent: str | None = None
    for level in range(depth):
        parent = _create(client, headers, f"level-{level}", parent).json()["id"]
        ids.append(parent)
    return ids


def test_folderPath_rootFolder_returnsOnlyItself(
    client: TestClient, make_user: Callable[[], Headers]
) -> None:
    headers = make_user()
    folder_id = _create(client, headers, "Root").json()["id"]
    response = client.get(f"/api/v1/folders/{folder_id}/path", headers=headers)
    assert response.status_code == 200
    assert [f["id"] for f in response.json()] == [folder_id]


def test_folderPath_deepChain_returnsRootFirstToLeaf(
    client: TestClient, make_user: Callable[[], Headers]
) -> None:
    headers = make_user()
    ids = _chain(client, headers, 5)
    response = client.get(f"/api/v1/folders/{ids[-1]}/path", headers=headers)
    assert response.status_code == 200
    assert [f["id"] for f in response.json()] == ids


def test_folderPath_otherUsersOrDeletedOrUnknownFolder_returns404(
    client: TestClient, make_user: Callable[[], Headers]
) -> None:
    owner, stranger = make_user(), make_user()
    folder_id = _create(client, owner, "Private").json()["id"]
    assert client.get(f"/api/v1/folders/{folder_id}/path", headers=stranger).status_code == 404
    client.delete(f"/api/v1/folders/{folder_id}", headers=owner)
    assert client.get(f"/api/v1/folders/{folder_id}/path", headers=owner).status_code == 404
    missing = "00000000-0000-0000-0000-000000000000"
    assert client.get(f"/api/v1/folders/{missing}/path", headers=owner).status_code == 404


def test_folderPath_noToken_returns401(client: TestClient) -> None:
    missing = "00000000-0000-0000-0000-000000000000"
    assert client.get(f"/api/v1/folders/{missing}/path").status_code == 401


def test_folderPath_depthCap_stopsClimbingAtTheLimit(
    client: TestClient, make_user: Callable[[], Headers], session: Session
) -> None:
    headers = make_user()
    ids = _chain(client, headers, 6)
    leaf = session.get(Folder, uuid.UUID(ids[-1]))
    assert leaf is not None
    path = FolderRepository(session).get_path(leaf.workspace_id, leaf.id, max_depth=3)
    assert [str(f.id) for f in path] == ids[-3:]


def test_folderPath_queryCountDoesNotGrowWithDepth(
    client: TestClient, make_user: Callable[[], Headers], engine: Engine
) -> None:
    headers = make_user()
    shallow = _chain(client, headers, 1)[-1]
    with _sql_count(engine) as few:
        client.get(f"/api/v1/folders/{shallow}/path", headers=headers)
    other = make_user()
    deep = _chain(client, other, 8)[-1]
    with _sql_count(engine) as many:
        client.get(f"/api/v1/folders/{deep}/path", headers=other)
    assert len(many) == len(few)


@contextmanager
def _sql_count(engine: Engine) -> Iterator[list[str]]:
    statements: list[str] = []

    def _record(*args: object) -> None:
        statements.append(str(args[2]))

    event.listen(engine, "before_cursor_execute", _record)
    try:
        yield statements
    finally:
        event.remove(engine, "before_cursor_execute", _record)


def test_createFolder_beyondMaxDepth_returns422(
    client: TestClient, make_user: Callable[[], Headers], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.modules.storage.folder_service.MAX_FOLDER_DEPTH", 3)
    headers = make_user()
    ids = _chain(client, headers, 3)
    response = _create(client, headers, "too-deep", ids[-1])
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "folder_too_deep"
    assert _create(client, headers, "sibling-of-leaf", ids[-2]).status_code == 201


def test_folderPath_softDeletedMiddleAncestor_pathStopsBelowIt(
    client: TestClient, make_user: Callable[[], Headers], session: Session
) -> None:
    headers = make_user()
    ids = _chain(client, headers, 5)
    session.execute(
        update(Folder).where(Folder.id == uuid.UUID(ids[1])).values(deleted_at=func.now())
    )
    response = client.get(f"/api/v1/folders/{ids[-1]}/path", headers=headers)
    assert response.status_code == 200
    assert [f["id"] for f in response.json()] == ids[2:]
