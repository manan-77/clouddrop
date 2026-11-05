from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, event, text
from sqlalchemy.orm import Session

from tests.conftest import BUCKET

if TYPE_CHECKING:
    from mypy_boto3_s3.client import S3Client

Headers = dict[str, str]
PDF = "application/pdf"


def _init(client: TestClient, headers: Headers, **overrides: object) -> httpx.Response:
    body = {"name": "report.pdf", "content_type": PDF, "size_bytes": 10, **overrides}
    return client.post("/api/v1/files/uploads", json=body, headers=headers)


def _upload_object(
    s3_client: "S3Client", init_body: dict[str, Any], size: int | None = None
) -> None:
    key = init_body["upload"]["fields"]["key"]
    body = b"x" * (size or init_body["file"]["size_bytes"])
    s3_client.put_object(Bucket=BUCKET, Key=key, Body=body)


def _ready_file(
    client: TestClient, s3_client: "S3Client", headers: Headers, **overrides: object
) -> dict[str, Any]:
    init = _init(client, headers, **overrides).json()
    _upload_object(s3_client, init)
    done = client.post(f"/api/v1/files/{init['file']['id']}/uploads/complete", headers=headers)
    assert done.status_code == 200, done.text
    result: dict[str, Any] = done.json()
    return result


def test_initUpload_validRequest_returns201WithPendingFileAndPresignedPost(
    client: TestClient, make_user: Callable[[], Headers]
) -> None:
    response = _init(client, make_user())
    assert response.status_code == 201
    body = response.json()
    assert response.headers["location"] == f"/api/v1/files/{body['file']['id']}"
    assert body["file"]["status"] == "pending_upload"
    assert body["upload"]["url"].startswith("http")
    assert body["upload"]["fields"]["Content-Type"] == PDF


def test_initUpload_filenameNeverAppearsInS3KeyAndResponseHidesKey(
    client: TestClient, make_user: Callable[[], Headers]
) -> None:
    body = _init(client, make_user(), name="../../secret.pdf").json()
    key = body["upload"]["fields"]["key"]
    assert "secret" not in key and ".." not in key
    assert key.endswith("/v1") and key.startswith("workspaces/")
    assert "s3_key" not in body["file"] and "key" not in body["file"]
    assert "/" not in body["file"]["name"]


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"size_bytes": 10**12}, "file_too_large"),
        ({"content_type": "application/x-msdownload"}, "unsupported_file_type"),
        ({"content_type": "text/html"}, "unsupported_file_type"),
    ],
)
def test_initUpload_invalidFile_returns422(
    client: TestClient,
    make_user: Callable[[], Headers],
    overrides: dict[str, object],
    code: str,
) -> None:
    response = _init(client, make_user(), **overrides)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == code


def test_initUpload_zeroSize_returns422(
    client: TestClient, make_user: Callable[[], Headers]
) -> None:
    assert _init(client, make_user(), size_bytes=0).status_code == 422


def test_initUpload_otherUsersFolder_returns404(
    client: TestClient, make_user: Callable[[], Headers]
) -> None:
    owner, stranger = make_user(), make_user()
    folder = client.post("/api/v1/folders", json={"name": "F"}, headers=owner).json()["id"]
    assert _init(client, stranger, folder_id=folder).status_code == 404


def test_completeUpload_objectMissing_returns409(
    client: TestClient, make_user: Callable[[], Headers]
) -> None:
    headers = make_user()
    file_id = _init(client, headers).json()["file"]["id"]
    response = client.post(f"/api/v1/files/{file_id}/uploads/complete", headers=headers)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "upload_incomplete"


def test_completeUpload_objectPresent_marksUploadedAndIsIdempotent(
    client: TestClient, make_user: Callable[[], Headers], s3_client: "S3Client"
) -> None:
    headers = make_user()
    init = _init(client, headers).json()
    _upload_object(s3_client, init)
    url = f"/api/v1/files/{init['file']['id']}/uploads/complete"
    first = client.post(url, headers=headers)
    second = client.post(url, headers=headers)
    assert first.status_code == second.status_code == 200
    assert first.json()["status"] == second.json()["status"] == "uploaded"


def test_completeUpload_sizeMismatch_returns422FailsFileAndDeletesObject(
    client: TestClient, make_user: Callable[[], Headers], s3_client: "S3Client"
) -> None:
    headers = make_user()
    init = _init(client, headers, size_bytes=10).json()
    _upload_object(s3_client, init, size=999)
    file_id = init["file"]["id"]
    response = client.post(f"/api/v1/files/{file_id}/uploads/complete", headers=headers)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "upload_size_mismatch"
    assert client.get(f"/api/v1/files/{file_id}", headers=headers).json()["status"] == "failed"
    assert s3_client.list_objects_v2(Bucket=BUCKET).get("KeyCount", 0) == 0


def test_files_otherUsersFile_returns404ForEveryAction(
    client: TestClient, make_user: Callable[[], Headers], s3_client: "S3Client"
) -> None:
    owner, stranger = make_user(), make_user()
    file_id = _ready_file(client, s3_client, owner)["id"]
    url = f"/api/v1/files/{file_id}"
    assert client.get(url, headers=stranger).status_code == 404
    assert client.get(f"{url}/download", headers=stranger).status_code == 404
    assert client.post(f"{url}/uploads/complete", headers=stranger).status_code == 404
    assert client.patch(url, json={"name": "x.pdf"}, headers=stranger).status_code == 404
    assert client.delete(url, headers=stranger).status_code == 404
    assert client.get(url, headers=owner).status_code == 200


def test_download_uploadedFile_returnsShortLivedPresignedUrl(
    client: TestClient, make_user: Callable[[], Headers], s3_client: "S3Client"
) -> None:
    headers = make_user()
    file_id = _ready_file(client, s3_client, headers, name="Q3 report.pdf")["id"]
    response = client.get(f"/api/v1/files/{file_id}/download", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["expires_in"] == 300
    assert "response-content-disposition" in body["url"].lower()
    assert "attachment" in body["url"].lower()


def test_download_pendingFile_returns409(
    client: TestClient, make_user: Callable[[], Headers]
) -> None:
    headers = make_user()
    file_id = _init(client, headers).json()["file"]["id"]
    response = client.get(f"/api/v1/files/{file_id}/download", headers=headers)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "file_not_ready"


def test_download_infectedFile_returns403(
    client: TestClient,
    make_user: Callable[[], Headers],
    s3_client: "S3Client",
    session: Session,
) -> None:
    headers = make_user()
    file_id = _ready_file(client, s3_client, headers)["id"]
    session.execute(text("UPDATE files SET status = 'infected' WHERE id = :id"), {"id": file_id})
    response = client.get(f"/api/v1/files/{file_id}/download", headers=headers)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "file_infected"


def test_updateFile_renameMoveAndExplicitNullMovesToRoot(
    client: TestClient, make_user: Callable[[], Headers], s3_client: "S3Client"
) -> None:
    headers = make_user()
    folder = client.post("/api/v1/folders", json={"name": "F"}, headers=headers).json()["id"]
    file_id = _ready_file(client, s3_client, headers)["id"]
    url = f"/api/v1/files/{file_id}"

    moved = client.patch(url, json={"name": "new.pdf", "folder_id": folder}, headers=headers).json()
    assert moved["name"] == "new.pdf" and moved["folder_id"] == folder

    renamed_only = client.patch(url, json={"name": "again.pdf"}, headers=headers).json()
    assert renamed_only["folder_id"] == folder

    to_root = client.patch(url, json={"folder_id": None}, headers=headers).json()
    assert to_root["folder_id"] is None

    assert client.patch(url, json={}, headers=headers).status_code == 422


def test_deleteFile_softDeletes_hidesFromGetAndListButKeepsObject(
    client: TestClient, make_user: Callable[[], Headers], s3_client: "S3Client"
) -> None:
    headers = make_user()
    file_id = _ready_file(client, s3_client, headers)["id"]
    assert client.delete(f"/api/v1/files/{file_id}", headers=headers).status_code == 204
    assert client.get(f"/api/v1/files/{file_id}", headers=headers).status_code == 404
    assert client.get("/api/v1/files", headers=headers).json()["total"] == 0
    assert s3_client.list_objects_v2(Bucket=BUCKET)["KeyCount"] == 1


def test_deleteFolder_withFile_returns409(
    client: TestClient, make_user: Callable[[], Headers], s3_client: "S3Client"
) -> None:
    headers = make_user()
    folder = client.post("/api/v1/folders", json={"name": "F"}, headers=headers).json()["id"]
    _ready_file(client, s3_client, headers, folder_id=folder)
    assert client.delete(f"/api/v1/folders/{folder}", headers=headers).status_code == 409


def test_listFiles_filtersByFolderAndStatusAndPaginates(
    client: TestClient, make_user: Callable[[], Headers], s3_client: "S3Client"
) -> None:
    headers = make_user()
    folder = client.post("/api/v1/folders", json={"name": "F"}, headers=headers).json()["id"]
    for name in ("b.pdf", "a.pdf", "c.pdf"):
        _ready_file(client, s3_client, headers, name=name, folder_id=folder)
    _init(client, headers, folder_id=folder, name="pending.pdf")

    params: dict[str, str | int] = {"folder_id": folder, "status": "uploaded", "page_size": 2}
    uploaded = client.get("/api/v1/files", params=params, headers=headers).json()
    assert [f["name"] for f in uploaded["items"]] == ["a.pdf", "b.pdf"]
    assert uploaded["total"] == 3
    assert (
        client.get("/api/v1/files", params={"status": "bogus"}, headers=headers).status_code == 422
    )
    assert client.get("/api/v1/files", headers=headers).json()["total"] == 0


@contextmanager
def _count_queries(engine: Engine) -> Iterator[list[str]]:
    statements: list[str] = []

    def _record(*args: object) -> None:
        statements.append(str(args[2]))

    event.listen(engine, "before_cursor_execute", _record)
    try:
        yield statements
    finally:
        event.remove(engine, "before_cursor_execute", _record)


def test_listFiles_queryCountDoesNotGrowWithRows(
    client: TestClient,
    make_user: Callable[[], Headers],
    s3_client: "S3Client",
    engine: Engine,
) -> None:
    headers = make_user()
    _ready_file(client, s3_client, headers, name="one.pdf")
    with _count_queries(engine) as few:
        client.get("/api/v1/files", headers=headers)
    for index in range(8):
        _ready_file(client, s3_client, headers, name=f"f{index}.pdf")
    with _count_queries(engine) as many:
        client.get("/api/v1/files", headers=headers)
    assert len(many) == len(few)
