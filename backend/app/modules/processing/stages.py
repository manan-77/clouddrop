import logging
from collections.abc import Callable
from typing import Protocol

from app.core.errors import ServiceUnavailableError
from app.modules.processing.constants import JobStage
from app.modules.processing.filetype import matches_declared_type
from app.modules.storage.constants import FileStatus
from app.modules.storage.models import File, FileVersion
from app.modules.storage.s3 import S3Storage

logger = logging.getLogger(__name__)

HEAD_BYTES = 4096


class PermanentStageError(Exception):
    """The file can never pass this stage. `code` is a short machine value, safe to store."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


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


class DetectTypeStage:
    """The first bytes must match the declared type; extension and client are not trusted."""

    name = JobStage.DETECT_TYPE
    file_status = FileStatus.PROCESSING

    def run(self, file: File, version: FileVersion, storage: S3Storage) -> None:
        head: bytes | None = _call(lambda: storage.read_head(version.s3_key, HEAD_BYTES))
        if head is None:
            raise PermanentStageError("object_missing")
        if not matches_declared_type(head, file.content_type):
            raise PermanentStageError("type_mismatch")


def _call[T](operation: Callable[[], T]) -> T:
    try:
        return operation()
    except ServiceUnavailableError as exc:
        raise TransientStageError("storage unavailable") from exc
