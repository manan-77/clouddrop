import contextlib
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import ConflictError, ForbiddenError, NotFoundError, UnprocessableError
from app.core.pagination import PageParams
from app.modules.processing.dispatcher import ProcessingDispatcher
from app.modules.sharing.service import AccessService, Action
from app.modules.storage.constants import DOWNLOADABLE_STATUSES, FileStatus
from app.modules.storage.models import File, FileVersion
from app.modules.storage.naming import sanitize_name
from app.modules.storage.repository import FileRepository, FileVersionRepository, FolderRepository
from app.modules.storage.s3 import MultipartGoneError, PresignedUpload, S3Storage
from app.modules.workspaces.service import WorkspaceService


class FileService:
    def __init__(
        self, session: Session, settings: Settings, dispatcher: ProcessingDispatcher
    ) -> None:
        self.dispatcher = dispatcher
        self.session = session
        self.settings = settings
        self.files = FileRepository(session)
        self.versions = FileVersionRepository(session)
        self.folders = FolderRepository(session)
        self.workspaces = WorkspaceService(session)
        self.access = AccessService(session)

    def _pending_cutoff(self) -> datetime:
        # An upload still pending after twice its presign lifetime is abandoned (the purge job
        # removes it); it must not keep counting against the quota meanwhile.
        return datetime.now(UTC) - timedelta(seconds=self.settings.presigned_upload_ttl_seconds * 2)

    def _create_pending(
        self,
        user_id: uuid.UUID,
        name: str,
        content_type: str,
        size_bytes: int,
        folder_id: uuid.UUID | None,
        max_bytes: int,
    ) -> tuple[File, FileVersion]:
        """Validates the request and adds the pending rows; the caller presigns and commits."""
        workspace_id = self._scope(user_id, Action.WRITE)
        normalized_type = content_type.split(";")[0].strip().lower()
        if size_bytes > max_bytes:
            raise UnprocessableError("File is too large", code="file_too_large")
        if normalized_type not in self.settings.allowed_content_types:
            raise UnprocessableError(
                "This file type is not supported", code="unsupported_file_type"
            )
        # Soft limit: two simultaneous inits may overshoot by one file.
        if (
            self.files.sum_size(workspace_id, self._pending_cutoff()) + size_bytes
            > self.settings.user_quota_bytes
        ):
            raise UnprocessableError("Storage quota exceeded", code="quota_exceeded")
        if (
            folder_id is not None
            and self.folders.get(workspace_id, folder_id, lock="share") is None
        ):
            raise NotFoundError("Folder not found", code="folder_not_found")

        file = File(
            workspace_id=workspace_id,
            folder_id=folder_id,
            name=sanitize_name(name),
            content_type=normalized_type,
            size_bytes=size_bytes,
        )
        self.files.add(file)
        # The key is server-generated; the user's filename never appears in it.
        version = FileVersion(
            file_id=file.id,
            version=1,
            s3_key=f"workspaces/{workspace_id}/files/{file.id}/v1",
            size_bytes=size_bytes,
            content_type=normalized_type,
        )
        self.versions.add(version)
        return file, version

    def init_upload(
        self,
        user_id: uuid.UUID,
        name: str,
        content_type: str,
        size_bytes: int,
        folder_id: uuid.UUID | None,
        storage: S3Storage,
    ) -> tuple[File, PresignedUpload]:
        file, version = self._create_pending(
            user_id, name, content_type, size_bytes, folder_id, self.settings.max_upload_bytes
        )
        # Presign before committing so a storage failure leaves no orphan rows.
        upload = storage.create_upload(version.s3_key, file.content_type, size_bytes)
        self.session.commit()
        return file, upload

    def part_layout(self, size_bytes: int) -> tuple[int, int]:
        """(part size, part count): the size grows only if S3's 10,000-part limit demands it."""
        part_size = max(self.settings.multipart_part_size_bytes, -(-size_bytes // 10_000))
        return part_size, -(-size_bytes // part_size)

    def init_multipart_upload(
        self,
        user_id: uuid.UUID,
        name: str,
        content_type: str,
        size_bytes: int,
        folder_id: uuid.UUID | None,
        storage: S3Storage,
    ) -> tuple[File, int, int]:
        file, version = self._create_pending(
            user_id,
            name,
            content_type,
            size_bytes,
            folder_id,
            self.settings.multipart_max_upload_bytes,
        )
        part_size, part_count = self.part_layout(size_bytes)
        version.part_size_bytes = part_size
        version.multipart_upload_id = storage.create_multipart(version.s3_key, file.content_type)
        try:
            self.session.commit()
        except Exception:
            # Do not leave an orphan upload accruing storage if the rows could not be saved.
            self.session.rollback()
            storage.abort_multipart(version.s3_key, str(version.multipart_upload_id))
            raise
        return file, part_size, part_count

    def _multipart_file(
        self, user_id: uuid.UUID, file_id: uuid.UUID, *, for_update: bool = False
    ) -> tuple[File, FileVersion]:
        file = self._get(self._scope(user_id, Action.WRITE), file_id, for_update=for_update)
        version = self.versions.get_current(file.id)
        if (
            file.status != FileStatus.PENDING_UPLOAD
            or version is None
            or not version.multipart_upload_id
        ):
            raise ConflictError("This is not an upload in progress", code="not_multipart_upload")
        return file, version

    def create_part_urls(
        self,
        user_id: uuid.UUID,
        file_id: uuid.UUID,
        part_numbers: list[int],
        storage: S3Storage,
    ) -> list[tuple[int, str]]:
        file, version = self._multipart_file(user_id, file_id)
        assert version.multipart_upload_id and version.part_size_bytes
        part_count = -(-file.size_bytes // version.part_size_bytes)
        numbers = sorted(set(part_numbers))
        if numbers[0] < 1 or numbers[-1] > part_count:
            raise UnprocessableError("Invalid part number", code="invalid_part_number")
        urls = []
        for number in numbers:
            last = number == part_count
            size = (
                file.size_bytes - version.part_size_bytes * (part_count - 1)
                if last
                else version.part_size_bytes
            )
            urls.append(
                (
                    number,
                    storage.presign_part(version.s3_key, version.multipart_upload_id, number, size),
                )
            )
        return urls

    def abort_upload(self, user_id: uuid.UUID, file_id: uuid.UUID, storage: S3Storage) -> None:
        workspace_id = self._scope(user_id, Action.WRITE)
        file = self._get(workspace_id, file_id, for_update=True)
        if file.status != FileStatus.PENDING_UPLOAD:
            raise ConflictError("This is not an upload in progress", code="upload_not_pending")
        version = self.versions.get_current(file.id)
        if version is not None:
            if version.multipart_upload_id:
                storage.abort_multipart(version.s3_key, version.multipart_upload_id)
                version.multipart_upload_id = None
            storage.delete(version.s3_key)  # a single-request upload may already have landed
        file.deleted_at = datetime.now(UTC)
        self.session.commit()

    def _assemble_multipart(self, file: File, version: FileVersion, storage: S3Storage) -> None:
        """Verifies the uploaded parts against the layout the server chose, then assembles them.

        The part list comes from S3, never from the client.
        """
        assert version.multipart_upload_id and version.part_size_bytes
        part_size = version.part_size_bytes
        part_count = -(-file.size_bytes // part_size)
        try:
            parts = storage.list_parts(version.s3_key, version.multipart_upload_id)
        except MultipartGoneError:
            return  # already assembled by an earlier attempt; the HEAD below verifies it
        numbers = [p.part_number for p in parts]
        if not set(range(1, part_count + 1)) <= set(numbers):
            raise ConflictError(
                "The file has not been fully uploaded yet", code="upload_incomplete"
            )
        expected_last = file.size_bytes - part_size * (part_count - 1)
        wrong = numbers != list(range(1, part_count + 1)) or any(
            p.size_bytes != (expected_last if p.part_number == part_count else part_size)
            for p in parts
        )
        if wrong:
            storage.abort_multipart(version.s3_key, version.multipart_upload_id)
            version.multipart_upload_id = None
            file.status = FileStatus.FAILED
            self.session.commit()
            raise UnprocessableError(
                "Uploaded file size does not match", code="upload_size_mismatch"
            )
        with contextlib.suppress(MultipartGoneError):  # completed by an earlier attempt
            storage.complete_multipart(version.s3_key, version.multipart_upload_id, parts)

    def complete_upload(self, user_id: uuid.UUID, file_id: uuid.UUID, storage: S3Storage) -> File:
        workspace_id = self._scope(user_id, Action.WRITE)
        # Row lock: two concurrent completes must not both flip the status.
        file = self._get(workspace_id, file_id, for_update=True)
        if file.status != FileStatus.PENDING_UPLOAD:
            return file
        version = self.versions.get_current(file.id)
        if version is None:
            raise NotFoundError("File not found", code="file_not_found")

        if version.multipart_upload_id:
            self._assemble_multipart(file, version, storage)
        info = storage.head(version.s3_key)
        if info is None:
            raise ConflictError("The file has not been uploaded yet", code="upload_incomplete")
        if info.size_bytes != file.size_bytes:
            # Never trust the client's claim: discard whatever was actually uploaded.
            storage.delete(version.s3_key)
            version.multipart_upload_id = None
            file.status = FileStatus.FAILED
            self.session.commit()
            raise UnprocessableError(
                "Uploaded file size does not match", code="upload_size_mismatch"
            )

        version.etag = info.etag
        version.multipart_upload_id = None
        version.enqueued_at = datetime.now(UTC)
        file.status = FileStatus.UPLOADED
        self.session.commit()
        # After the commit, never before: the worker must see the row. If the broker is down the
        # sweeper picks the file up later, so a failed enqueue never fails the upload.
        self.dispatcher.enqueue(version.id)
        return file

    def list_files(
        self,
        user_id: uuid.UUID,
        folder_id: uuid.UUID | None,
        status: FileStatus | None,
        params: PageParams,
    ) -> tuple[list[File], int]:
        workspace_id = self._scope(user_id, Action.READ)
        if folder_id is not None and self.folders.get(workspace_id, folder_id) is None:
            raise NotFoundError("Folder not found", code="folder_not_found")
        return self.files.list_files(
            workspace_id,
            folder_id,
            status.value if status else None,
            params.page_size,
            params.offset,
        )

    def get_file(self, user_id: uuid.UUID, file_id: uuid.UUID) -> File:
        return self._get(self._scope(user_id, Action.READ), file_id)

    def update_file(
        self,
        user_id: uuid.UUID,
        file_id: uuid.UUID,
        *,
        name: str | None,
        folder_id: uuid.UUID | None,
        move: bool,
    ) -> File:
        workspace_id = self._scope(user_id, Action.WRITE)
        file = self._get(workspace_id, file_id)
        if name is None and not move:
            raise UnprocessableError("Nothing to update", code="empty_update")
        if (
            move
            and folder_id is not None
            and self.folders.get(workspace_id, folder_id, lock="share") is None
        ):
            raise NotFoundError("Folder not found", code="folder_not_found")
        if name is not None:
            file.name = sanitize_name(name)
        if move:
            file.folder_id = folder_id
        self.session.commit()
        return file

    def delete_file(self, user_id: uuid.UUID, file_id: uuid.UUID) -> None:
        file = self._get(self._scope(user_id, Action.DELETE), file_id)
        # Soft delete only; a purge task removes the S3 objects later.
        file.deleted_at = datetime.now(UTC)
        self.session.commit()

    def create_download_url(
        self, user_id: uuid.UUID, file_id: uuid.UUID, storage: S3Storage
    ) -> tuple[str, int]:
        file = self._get(self._scope(user_id, Action.READ), file_id)
        if file.status == FileStatus.INFECTED:
            raise ForbiddenError(
                "This file was blocked because it may be unsafe", code="file_infected"
            )
        if file.status not in DOWNLOADABLE_STATUSES:
            raise ConflictError("The file is not available yet", code="file_not_ready")
        version = self.versions.get_current(file.id)
        if version is None:
            raise NotFoundError("File not found", code="file_not_found")
        return (
            storage.create_download_url(version.s3_key, file.name),
            self.settings.presigned_download_ttl_seconds,
        )

    def _scope(self, user_id: uuid.UUID, action: Action) -> uuid.UUID:
        workspace = self.workspaces.get_for_user(user_id)
        self.access.require(user_id, workspace.id, action)
        return workspace.id

    def _get(
        self, workspace_id: uuid.UUID, file_id: uuid.UUID, *, for_update: bool = False
    ) -> File:
        file = self.files.get(workspace_id, file_id, for_update=for_update)
        if file is None:
            raise NotFoundError("File not found", code="file_not_found")
        return file
