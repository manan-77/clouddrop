from __future__ import annotations

import logging
from collections.abc import Iterator
from dataclasses import dataclass
from typing import TYPE_CHECKING
from urllib.parse import quote

from botocore.exceptions import BotoCoreError, ClientError

from app.core.errors import ServiceUnavailableError

if TYPE_CHECKING:
    from botocore.response import StreamingBody
    from mypy_boto3_s3.client import S3Client

logger = logging.getLogger(__name__)

_NOT_FOUND_CODES = {"404", "NoSuchKey", "NotFound"}


@dataclass(frozen=True)
class PresignedUpload:
    url: str
    fields: dict[str, str]
    expires_in: int


@dataclass(frozen=True)
class ObjectInfo:
    size_bytes: int
    etag: str


class ObjectStream:
    """Chunked reader over an S3 body. Call `close()` on every path: a generator that never
    started would never release the connection."""

    def __init__(self, body: StreamingBody, chunk_size: int) -> None:
        self._body = body
        self._chunks = body.iter_chunks(chunk_size)

    def __iter__(self) -> Iterator[bytes]:
        return self

    def __next__(self) -> bytes:
        try:
            return next(self._chunks)
        except StopIteration:
            self.close()
            raise
        except (BotoCoreError, ClientError) as exc:
            self.close()
            raise S3Storage._unavailable("read object", exc) from exc

    def close(self) -> None:
        self._body.close()


class ObjectChangedError(Exception):
    """The object no longer has the ETag the caller expected."""


class S3Storage:
    "The only code that talks to S3. Blocking: call from `def` endpoints or workers only."

    def __init__(
        self,
        client: S3Client,
        bucket: str,
        upload_ttl_seconds: int,
        download_ttl_seconds: int,
    ) -> None:
        self.client = client
        self.bucket = bucket
        self.upload_ttl_seconds = upload_ttl_seconds
        self.download_ttl_seconds = download_ttl_seconds

    def create_upload(self, key: str, content_type: str, size_bytes: int) -> PresignedUpload:
        # S3 itself rejects any body whose size or type differs from what we approved.
        try:
            post = self.client.generate_presigned_post(
                Bucket=self.bucket,
                Key=key,
                Fields={"Content-Type": content_type},
                Conditions=[
                    {"Content-Type": content_type},
                    ["content-length-range", size_bytes, size_bytes],
                ],
                ExpiresIn=self.upload_ttl_seconds,
            )
        except (BotoCoreError, ClientError) as exc:
            raise self._unavailable("presign upload", exc) from exc
        return PresignedUpload(post["url"], dict(post["fields"]), self.upload_ttl_seconds)

    def head(self, key: str) -> ObjectInfo | None:
        try:
            response = self.client.head_object(Bucket=self.bucket, Key=key)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in _NOT_FOUND_CODES:
                return None
            raise self._unavailable("head object", exc) from exc
        except BotoCoreError as exc:
            raise self._unavailable("head object", exc) from exc
        return ObjectInfo(response["ContentLength"], response["ETag"].strip('"'))

    def read_head(self, key: str, length: int, *, if_match: str | None = None) -> bytes | None:
        """The first `length` bytes of an object, or None when it does not exist.

        With `if_match` the read only succeeds while the object still has that ETag, so bytes
        can never come from a different upload than the one that was verified.
        """
        byte_range = f"bytes=0-{length - 1}"
        try:
            if if_match:
                response = self.client.get_object(
                    Bucket=self.bucket, Key=key, Range=byte_range, IfMatch=f'"{if_match}"'
                )
            else:
                response = self.client.get_object(Bucket=self.bucket, Key=key, Range=byte_range)
            body = response["Body"]
            try:
                return bytes(body.read(length))
            finally:
                body.close()
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code")
            if code in _NOT_FOUND_CODES:
                return None
            if code in {"PreconditionFailed", "412"}:
                raise ObjectChangedError from exc
            if code == "InvalidRange":  # an empty object has no first byte
                return b""
            raise self._unavailable("read object", exc) from exc
        except BotoCoreError as exc:
            raise self._unavailable("read object", exc) from exc

    def iter_object(
        self, key: str, chunk_size: int, *, if_match: str | None = None
    ) -> ObjectStream | None:
        """Streams an object in chunks, never whole into memory. None when it does not exist.

        With `if_match` the stream fails with `ObjectChangedError` if the object is replaced.
        """
        try:
            if if_match:
                response = self.client.get_object(
                    Bucket=self.bucket, Key=key, IfMatch=f'"{if_match}"'
                )
            else:
                response = self.client.get_object(Bucket=self.bucket, Key=key)
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code")
            if code in _NOT_FOUND_CODES:
                return None
            if code in {"PreconditionFailed", "412"}:
                raise ObjectChangedError from exc
            raise self._unavailable("read object", exc) from exc
        except BotoCoreError as exc:
            raise self._unavailable("read object", exc) from exc
        return ObjectStream(response["Body"], chunk_size)

    def delete(self, key: str) -> None:
        try:
            self.client.delete_object(Bucket=self.bucket, Key=key)
        except (BotoCoreError, ClientError) as exc:
            raise self._unavailable("delete object", exc) from exc

    def create_download_url(self, key: str, filename: str) -> str:
        # `attachment` stops the browser rendering an uploaded HTML/SVG file inline.
        ascii_name = filename.encode("ascii", "ignore").decode()
        ascii_name = ascii_name.replace('"', "").replace("\\", "") or "download"
        disposition = f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"
        try:
            return self.client.generate_presigned_url(
                "get_object",
                Params={
                    "Bucket": self.bucket,
                    "Key": key,
                    "ResponseContentDisposition": disposition,
                },
                ExpiresIn=self.download_ttl_seconds,
            )
        except (BotoCoreError, ClientError) as exc:
            raise self._unavailable("presign download", exc) from exc

    @staticmethod
    def _unavailable(operation: str, exc: Exception) -> ServiceUnavailableError:
        logger.error("S3 %s failed: %s", operation, type(exc).__name__)
        return ServiceUnavailableError(
            "File storage is temporarily unavailable", code="storage_unavailable"
        )
