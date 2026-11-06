import uuid
from datetime import UTC, datetime

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
from app.modules.storage.s3 import PresignedUpload, S3Storage
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

    def init_upload(
        self,
        user_id: uuid.UUID,
        name: str,
        content_type: str,
        size_bytes: int,
        folder_id: uuid.UUID | None,
        storage: S3Storage,
    ) -> tuple[File, PresignedUpload]:
        workspace_id = self._scope(user_id, Action.WRITE)
        normalized_type = content_type.split(";")[0].strip().lower()
        if size_bytes > self.settings.max_upload_bytes:
            raise UnprocessableError("File is too large", code="file_too_large")
        if normalized_type not in self.settings.allowed_content_types:
            raise UnprocessableError(
                "This file type is not supported", code="unsupported_file_type"
            )
        # Soft limit: two simultaneous inits may overshoot by one file.
        if self.files.sum_size(workspace_id) + size_bytes > self.settings.user_quota_bytes:
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
        key = f"workspaces/{workspace_id}/files/{file.id}/v1"
        self.versions.add(
            FileVersion(
                file_id=file.id,
                version=1,
                s3_key=key,
                size_bytes=size_bytes,
                content_type=normalized_type,
            )
        )
        # Presign before committing so a storage failure leaves no orphan rows.
        upload = storage.create_upload(key, normalized_type, size_bytes)
        self.session.commit()
        return file, upload

    def complete_upload(self, user_id: uuid.UUID, file_id: uuid.UUID, storage: S3Storage) -> File:
        workspace_id = self._scope(user_id, Action.WRITE)
        # Row lock: two concurrent completes must not both flip the status.
        file = self._get(workspace_id, file_id, for_update=True)
        if file.status != FileStatus.PENDING_UPLOAD:
            return file
        version = self.versions.get_current(file.id)
        if version is None:
            raise NotFoundError("File not found", code="file_not_found")

        info = storage.head(version.s3_key)
        if info is None:
            raise ConflictError("The file has not been uploaded yet", code="upload_incomplete")
        if info.size_bytes != file.size_bytes:
            # Never trust the client's claim: discard whatever was actually uploaded.
            storage.delete(version.s3_key)
            file.status = FileStatus.FAILED
            self.session.commit()
            raise UnprocessableError(
                "Uploaded file size does not match", code="upload_size_mismatch"
            )

        version.etag = info.etag
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
