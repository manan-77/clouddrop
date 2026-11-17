import uuid
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, NotFoundError, UnprocessableError
from app.core.pagination import PageParams
from app.modules.sharing.repository import PermissionRepository
from app.modules.sharing.service import (
    AccessService,
    Action,
)
from app.modules.storage.constants import MAX_FOLDER_DEPTH
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
        self.permissions = PermissionRepository(session)

    def list_folders(
        self, user_id: uuid.UUID, parent_id: uuid.UUID | None, params: PageParams
    ) -> tuple[list[Folder], int]:
        if parent_id is None:
            workspace_id = self._own_workspace(user_id)
        else:
            parent = self._folder(user_id, parent_id, Action.READ)
            workspace_id = parent.workspace_id
        return self.folders.list_children(workspace_id, parent_id, params.page_size, params.offset)

    def get_folder(self, user_id: uuid.UUID, folder_id: uuid.UUID) -> Folder:
        return self._folder(user_id, folder_id, Action.READ)

    def get_folder_path(self, user_id: uuid.UUID, folder_id: uuid.UUID) -> list[Folder]:
        folder = self._folder(user_id, folder_id, Action.READ)
        path = self.folders.get_path(folder.workspace_id, folder.id, MAX_FOLDER_DEPTH)
        if self.workspaces.is_owner(user_id, folder.workspace_id):
            return path
        # A grantee never learns what lies above the folder they were given.
        granted = self.permissions.folder_grants_among(user_id, [item.id for item in path])
        start = next((i for i, item in enumerate(path) if item.id in granted), 0)
        return path[start:]

    def parent_visible(self, user_id: uuid.UUID, folder: Folder) -> bool:
        """Whether the caller may be told the parent id (not for the top of a shared tree)."""
        if folder.parent_id is None or self.workspaces.is_owner(user_id, folder.workspace_id):
            return True
        parent = self.folders.get_any(folder.parent_id)
        return parent is not None and self.access.folder_role(user_id, parent) is not None

    def create_folder(self, user_id: uuid.UUID, name: str, parent_id: uuid.UUID | None) -> Folder:
        if parent_id is None:
            workspace_id = self._own_workspace(user_id)
        else:
            parent = self._folder(user_id, parent_id, Action.WRITE, lock="share")
            workspace_id = parent.workspace_id
            # Enforced at write time so the breadcrumb cap can never silently truncate a path.
            if (
                len(self.folders.get_path(workspace_id, parent_id, MAX_FOLDER_DEPTH))
                >= MAX_FOLDER_DEPTH
            ):
                raise UnprocessableError(
                    f"Folders cannot be nested more than {MAX_FOLDER_DEPTH} levels deep",
                    code="folder_too_deep",
                )
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
        folder = self._folder(user_id, folder_id, Action.WRITE)
        try:
            with self.session.begin_nested():
                folder.name = sanitize_name(name)
                self.session.flush()
        except IntegrityError as exc:
            raise self._name_taken() from exc
        self.session.commit()
        return folder

    def delete_folder(self, user_id: uuid.UUID, folder_id: uuid.UUID) -> None:
        folder = self._folder(user_id, folder_id, Action.DELETE, lock="update")
        workspace_id = folder.workspace_id
        if self.folders.has_subfolders(workspace_id, folder_id) or self.files.has_files_in(
            workspace_id, folder_id
        ):
            raise ConflictError("Folder is not empty", code="folder_not_empty")
        folder.deleted_at = datetime.now(UTC)
        self.session.commit()

    def _own_workspace(self, user_id: uuid.UUID) -> uuid.UUID:
        workspace = self.workspaces.get_for_user(user_id)
        self.access.require(user_id, workspace.id, Action.WRITE)
        return workspace.id

    def _folder(
        self,
        user_id: uuid.UUID,
        folder_id: uuid.UUID,
        action: Action,
        lock: Literal["update", "share"] | None = None,
    ) -> Folder:
        """The folder if the caller may do `action` on it, else the 404 a missing one gives."""
        folder = self.folders.get_any(folder_id, lock=lock)
        if folder is None or not self.access.can_on_folder(user_id, folder, action):
            raise NotFoundError("Folder not found", code="folder_not_found")
        return folder

    @staticmethod
    def _name_taken() -> ConflictError:
        return ConflictError(
            "A folder with this name already exists here", code="folder_name_taken"
        )
