import uuid
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, NotFoundError
from app.core.pagination import PageParams
from app.modules.sharing.service import AccessService, Action
from app.modules.storage.models import Folder
from app.modules.storage.naming import sanitize_name
from app.modules.storage.repository import FileRepository, FolderRepository
from app.modules.workspaces.service import WorkspaceService


class FolderService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.folders = FolderRepository(session)
        self.files = FileRepository(session)
        self.workspaces = WorkspaceService(session)
        self.access = AccessService(session)

    def list_folders(
        self, user_id: uuid.UUID, parent_id: uuid.UUID | None, params: PageParams
    ) -> tuple[list[Folder], int]:
        workspace_id = self._scope(user_id, Action.READ)
        if parent_id is not None:
            self._get(workspace_id, parent_id)
        return self.folders.list_children(workspace_id, parent_id, params.page_size, params.offset)

    def get_folder(self, user_id: uuid.UUID, folder_id: uuid.UUID) -> Folder:
        return self._get(self._scope(user_id, Action.READ), folder_id)

    def create_folder(self, user_id: uuid.UUID, name: str, parent_id: uuid.UUID | None) -> Folder:
        workspace_id = self._scope(user_id, Action.WRITE)
        if parent_id is not None:
            self._get(workspace_id, parent_id, lock="share")
        folder = Folder(workspace_id=workspace_id, parent_id=parent_id, name=sanitize_name(name))
        try:
            # The unique index is the arbiter, not a prior existence check.
            with self.session.begin_nested():
                self.folders.add(folder)
        except IntegrityError as exc:
            raise self._name_taken() from exc
        self.session.commit()
        return folder

    def rename_folder(self, user_id: uuid.UUID, folder_id: uuid.UUID, name: str) -> Folder:
        folder = self._get(self._scope(user_id, Action.WRITE), folder_id)
        try:
            with self.session.begin_nested():
                folder.name = sanitize_name(name)
                self.session.flush()
        except IntegrityError as exc:
            raise self._name_taken() from exc
        self.session.commit()
        return folder

    def delete_folder(self, user_id: uuid.UUID, folder_id: uuid.UUID) -> None:
        workspace_id = self._scope(user_id, Action.DELETE)
        folder = self._get(workspace_id, folder_id, lock="update")
        if self.folders.has_subfolders(workspace_id, folder_id) or self.files.has_files_in(
            workspace_id, folder_id
        ):
            raise ConflictError("Folder is not empty", code="folder_not_empty")
        folder.deleted_at = datetime.now(UTC)
        self.session.commit()

    def _scope(self, user_id: uuid.UUID, action: Action) -> uuid.UUID:
        workspace = self.workspaces.get_for_user(user_id)
        self.access.require(user_id, workspace.id, action)
        return workspace.id

    def _get(
        self,
        workspace_id: uuid.UUID,
        folder_id: uuid.UUID,
        lock: Literal["update", "share"] | None = None,
    ) -> Folder:
        folder = self.folders.get(workspace_id, folder_id, lock=lock)
        if folder is None:
            raise NotFoundError("Folder not found", code="folder_not_found")
        return folder

    @staticmethod
    def _name_taken() -> ConflictError:
        return ConflictError(
            "A folder with this name already exists here", code="folder_name_taken"
        )
