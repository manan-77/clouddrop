import uuid
from datetime import timedelta
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select, text, update
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.modules.storage.file_service import FileService
from app.modules.storage.models import File, FileVersion
from app.modules.storage.purge import purge_expired
from app.modules.storage.s3 import S3Storage
from tests.conftest import BUCKET, FakeDispatcher

if TYPE_CHECKING:
    from mypy_boto3_s3.client import S3Client

Headers = dict[str, str]
PART = get_settings().multipart_part_size_bytes
SIZE = PART + 10  # two parts: one full, one of 10 bytes
TYPE = "text/plain"


def _init(client: TestClient, headers: Headers, size: int = SIZE):  # type: ignore[no-untyped-def]
    return client.post(
        "/api/v1/files/uploads/multipart",
        json={"name": "big.txt", "content_type": TYPE, "size_bytes": size},
        headers=headers,
    )


def _version(session: Session, file_id: str) -> FileVersion:
    session.expire_all()
    version = session.scalar(select(FileVersion).where(FileVersion.file_id == uuid.UUID(file_id)))
    assert version is not None
    return version


def _put(s3_client: "S3Client", session: Session, file_id: str, number: int, size: int) -> None:
    version = _version(session, file_id)
    s3_client.upload_part(
        Bucket=BUCKET,
        Key=version.s3_key,
        UploadId=str(version.multipart_upload_id),
        PartNumber=number,
        Body=b"x" * size,
    )


def _open_uploads(s3_client: "S3Client") -> int:
    return len(s3_client.list_multipart_uploads(Bucket=BUCKET).get("Uploads", []))


class TestMultipart:
    def test_happyPath_assemblesVerifiesAndEnqueuesOnce(
        self, client, make_user, s3_client, session: Session, dispatcher: FakeDispatcher
    ) -> None:
        headers = make_user()
        init = _init(client, headers)
        assert init.status_code == 201 and init.headers["Location"].startswith("/api/v1/files/")
        body = init.json()
        assert body["multipart"]["part_count"] == 2 and body["multipart"]["part_size_bytes"] == PART
        assert "upload_id" not in init.text and "UploadId" not in init.text
        file_id = body["file"]["id"]
        urls = client.post(
            f"/api/v1/files/{file_id}/uploads/parts",
            json={"part_numbers": [2, 1, 1]},
            headers=headers,
        )
        assert [p["part_number"] for p in urls.json()["parts"]] == [1, 2]
        assert all("partNumber=" in p["url"] for p in urls.json()["parts"])
        _put(s3_client, session, file_id, 1, PART)
        _put(s3_client, session, file_id, 2, 10)
        done = client.post(f"/api/v1/files/{file_id}/uploads/complete", headers=headers)
        assert done.status_code == 200 and done.json()["status"] == "uploaded"
        version = _version(session, file_id)
        assert version.etag and version.multipart_upload_id is None
        assert s3_client.head_object(Bucket=BUCKET, Key=version.s3_key)["ContentLength"] == SIZE
        again = client.post(f"/api/v1/files/{file_id}/uploads/complete", headers=headers)
        assert again.status_code == 200 and len(dispatcher.calls) == 1

    def test_missingPart_isReportedAsIncompleteAndCanBeResumed(
        self, client, make_user, s3_client, session: Session
    ) -> None:
        headers = make_user()
        file_id = _init(client, headers).json()["file"]["id"]
        _put(s3_client, session, file_id, 1, PART)
        response = client.post(f"/api/v1/files/{file_id}/uploads/complete", headers=headers)
        assert (
            response.status_code == 409 and response.json()["error"]["code"] == "upload_incomplete"
        )
        _put(s3_client, session, file_id, 2, 10)
        assert (
            client.post(f"/api/v1/files/{file_id}/uploads/complete", headers=headers).status_code
            == 200
        )

    def test_partsOfTheWrongSize_failTheFileAndAbortTheUpload(
        self, client, make_user, s3_client, session: Session
    ) -> None:
        headers = make_user()
        file_id = _init(client, headers).json()["file"]["id"]
        _put(s3_client, session, file_id, 1, 6 * 1024 * 1024)  # not the part size the server chose
        _put(s3_client, session, file_id, 2, PART + 10 - 6 * 1024 * 1024)
        response = client.post(f"/api/v1/files/{file_id}/uploads/complete", headers=headers)
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "upload_size_mismatch"
        assert client.get(f"/api/v1/files/{file_id}", headers=headers).json()["status"] == "failed"
        assert _open_uploads(s3_client) == 0

    def test_alreadyAssembledObject_isAcceptedAfterALostResponse(
        self, client, make_user, s3_client, session: Session
    ) -> None:
        headers = make_user()
        file_id = _init(client, headers).json()["file"]["id"]
        _put(s3_client, session, file_id, 1, PART)
        _put(s3_client, session, file_id, 2, 10)
        version = _version(session, file_id)
        listed = s3_client.list_parts(
            Bucket=BUCKET, Key=version.s3_key, UploadId=str(version.multipart_upload_id)
        )["Parts"]
        s3_client.complete_multipart_upload(
            Bucket=BUCKET,
            Key=version.s3_key,
            UploadId=str(version.multipart_upload_id),
            MultipartUpload={
                "Parts": [{"PartNumber": p["PartNumber"], "ETag": p["ETag"]} for p in listed]
            },
        )
        done = client.post(f"/api/v1/files/{file_id}/uploads/complete", headers=headers)
        assert done.status_code == 200 and done.json()["status"] == "uploaded"

    def test_abort_removesTheUploadAndTheFile(
        self, client, make_user, s3_client, session: Session
    ) -> None:
        headers = make_user()
        file_id = _init(client, headers).json()["file"]["id"]
        _put(s3_client, session, file_id, 1, PART)
        assert _open_uploads(s3_client) == 1
        assert client.delete(f"/api/v1/files/{file_id}/uploads", headers=headers).status_code == 204
        assert _open_uploads(s3_client) == 0
        assert client.get(f"/api/v1/files/{file_id}", headers=headers).status_code == 404
        assert client.delete(f"/api/v1/files/{file_id}/uploads", headers=headers).status_code == 404

    def test_strangerGets404OnEveryEndpoint(self, client, make_user, s3_client) -> None:
        owner, stranger = make_user(), make_user()
        file_id = _init(client, owner).json()["file"]["id"]
        for method, path, kwargs in [
            ("post", f"/api/v1/files/{file_id}/uploads/parts", {"json": {"part_numbers": [1]}}),
            ("post", f"/api/v1/files/{file_id}/uploads/complete", {}),
            ("delete", f"/api/v1/files/{file_id}/uploads", {}),
        ]:
            assert getattr(client, method)(path, headers=stranger, **kwargs).status_code == 404

    @pytest.mark.parametrize("numbers", [[0], [3], [1, 99]])
    def test_invalidPartNumbers_areRejected(self, client, make_user, numbers: list[int]) -> None:
        headers = make_user()
        file_id = _init(client, headers).json()["file"]["id"]
        response = client.post(
            f"/api/v1/files/{file_id}/uploads/parts",
            json={"part_numbers": numbers},
            headers=headers,
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "invalid_part_number"

    def test_partUrlsForASingleRequestUpload_areRefused(self, client, make_user) -> None:
        headers = make_user()
        init = client.post(
            "/api/v1/files/uploads",
            json={"name": "a.txt", "content_type": TYPE, "size_bytes": 5},
            headers=headers,
        ).json()
        response = client.post(
            f"/api/v1/files/{init['file']['id']}/uploads/parts",
            json={"part_numbers": [1]},
            headers=headers,
        )
        assert response.status_code == 409

    def test_limits_sizeTypeAndQuotaApplyLikeTheSingleUpload(self, client, make_user) -> None:
        headers = make_user()
        too_big = _init(client, headers, get_settings().multipart_max_upload_bytes + 1)
        assert too_big.status_code == 422 and too_big.json()["error"]["code"] == "file_too_large"
        bad_type = client.post(
            "/api/v1/files/uploads/multipart",
            json={"name": "a.exe", "content_type": "application/x-msdownload", "size_bytes": SIZE},
            headers=headers,
        )
        assert bad_type.json()["error"]["code"] == "unsupported_file_type"


class TestLayoutAndConfig:
    def test_hugeFiles_growThePartSizeToStayWithinTenThousandParts(
        self, session: Session, dispatcher: FakeDispatcher
    ) -> None:
        service = FileService(session, get_settings(), dispatcher)  # type: ignore[arg-type]
        part_size, count = service.part_layout(200 * 1024**3)
        assert count <= 10_000 and part_size * count >= 200 * 1024**3
        assert service.part_layout(1) == (PART, 1)

    def test_multipartMaxAboveTheScannerLimit_isRejectedAtStartup(self) -> None:
        with pytest.raises(ValidationError):
            Settings(  # type: ignore[call-arg]
                _env_file=None,
                scanner_mode="clamav",
                multipart_max_upload_bytes=2 * 1024**3,
                scanner_max_stream_bytes=1024**3,
            )

    def test_partSizeBelowTheS3Minimum_isRejected(self) -> None:
        with pytest.raises(ValidationError):
            Settings(_env_file=None, multipart_part_size_bytes=1024)  # type: ignore[call-arg]


def test_purge_abortsAbandonedMultipartUploads(
    client, make_user, s3_client, session: Session, storage: S3Storage
) -> None:
    headers = make_user()
    file_id = _init(client, headers).json()["file"]["id"]
    _put(s3_client, session, file_id, 1, PART)
    session.execute(update(File).values(created_at=text("now() - interval '2 hours'")))
    session.commit()
    result = purge_expired(
        session,
        storage,
        retention=timedelta(days=30),
        pending_upload_ttl=timedelta(minutes=30),
        limit=10,
    )
    assert result.stale_uploads == 1 and _open_uploads(s3_client) == 0
