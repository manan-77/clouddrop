from collections.abc import Callable
from typing import Protocol

from app.core.config import get_settings
from app.core.errors import ServiceUnavailableError
from app.modules.processing import scanner as scanner_module
from app.modules.processing.constants import JobStage
from app.modules.processing.filetype import matches_declared_type
from app.modules.processing.scanner import ScannerUnavailableError, ScanTooLargeError
from app.modules.storage.constants import FileStatus
from app.modules.storage.models import File, FileVersion
from app.modules.storage.s3 import ObjectChangedError, ObjectStream, S3Storage

HEAD_BYTES = 4096


class PermanentStageError(Exception):
    """The file can never pass this stage. `code` is a short machine value, safe to store."""

    def __init__(self, code: str, file_status: FileStatus = FileStatus.FAILED) -> None:
        super().__init__(code)
        self.code = code
        # The status the file ends in; a malware hit ends in `infected`, not `failed`.
        self.file_status = file_status


class TransientStageError(Exception):
    """A dependency was unavailable; the task is retried with back-off."""


class Stage(Protocol):
    name: JobStage
    # The file's status while this stage runs.
    file_status: FileStatus

    def run(self, file: File, version: FileVersion, storage: S3Storage) -> None: ...


class VerifyObjectStage:
    """The object must still be exactly what the upload completion approved.

    The presigned upload stays valid for its lifetime, so a client could overwrite the object after
    completion; comparing size and ETag with what was recorded closes that gap.
    """

    name = JobStage.VERIFY_OBJECT
    file_status = FileStatus.SCANNING

    def run(self, file: File, version: FileVersion, storage: S3Storage) -> None:
        info = _call(lambda: storage.head(version.s3_key))
        if info is None:
            raise PermanentStageError("object_missing")
        if info.size_bytes != file.size_bytes:
            raise PermanentStageError("object_size_changed")
        if version.etag is None or info.etag != version.etag:
            raise PermanentStageError("object_changed")


class ScanStage:
    """Streams the object through the malware scanner. Never skipped silently."""

    name = JobStage.SCAN
    file_status = FileStatus.SCANNING
    # If the scanner stays unreachable until the attempts cap, say so instead of a generic code.
    exhausted_code = "scan_unavailable"

    def run(self, file: File, version: FileVersion, storage: S3Storage) -> None:
        # Looked up at call time so tests can replace it.
        scanner = scanner_module.get_scanner()
        if not scanner.enabled:
            return
        chunk_bytes = get_settings().scanner_chunk_bytes
        chunks: ObjectStream | None = None
        try:
            chunks = _call(
                lambda: storage.iter_object(version.s3_key, chunk_bytes, if_match=version.etag)
            )
            if chunks is None:
                raise PermanentStageError("object_missing")
            stream = chunks
            result = _call(lambda: scanner.scan(stream))
        except ObjectChangedError as exc:
            raise PermanentStageError("object_changed") from exc
        except ScanTooLargeError as exc:
            raise PermanentStageError("too_large_to_scan") from exc
        except ScannerUnavailableError as exc:
            raise TransientStageError("scanner unavailable") from exc
        finally:
            if chunks is not None:
                chunks.close()  # releases the S3 connection even when scanning stopped early
        if result.infected:
            raise PermanentStageError("infected", FileStatus.INFECTED)


class DetectTypeStage:
    """The first bytes must match the declared type; extension and client are not trusted."""

    name = JobStage.DETECT_TYPE
    file_status = FileStatus.PROCESSING

    def run(self, file: File, version: FileVersion, storage: S3Storage) -> None:
        try:
            # IfMatch: the bytes must come from the very object that verify_object approved.
            head: bytes | None = _call(
                lambda: storage.read_head(version.s3_key, HEAD_BYTES, if_match=version.etag)
            )
        except ObjectChangedError as exc:
            raise PermanentStageError("object_changed") from exc
        if head is None:
            raise PermanentStageError("object_missing")
        if not matches_declared_type(head, file.content_type):
            raise PermanentStageError("type_mismatch")


def _call[T](operation: Callable[[], T]) -> T:
    try:
        return operation()
    except ServiceUnavailableError as exc:
        raise TransientStageError("storage unavailable") from exc
