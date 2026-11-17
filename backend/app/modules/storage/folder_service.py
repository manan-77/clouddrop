import uuid
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, ForbiddenError, NotFoundError, UnprocessableError
from app.core.pagination import PageParams
from app.modules.audit.constants import AuditAction, ResourceType
from app.modules.audit.service import AuditService
from app.modules.sharing.repository import PermissionRepository
from app.modules.sharing.service import AccessService, Action, Role
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
        self.audit = AuditService(session)

    def list_folders(
        self, user_id: uuid.UUID, parent_id: uuid.UUID | None, params: PageParams
    ) -> tuple[list[Folder], int]:
        if parent_id is None:
            workspace_id = self._own_workspace(user_id, Action.READ)
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

    def role_in(self, user_id: uuid.UUID, folder_id: uuid.UUID | None) -> str:
        """The caller's role on a folder they were already allowed to read (owner at the root)."""
        if folder_id is None:
            return Role.OWNER.value
        folder = self.folders.get_any(folder_id)
        role = self.access.folder_role(user_id, folder) if folder else None
        return (role or Role.VIEWER).value

    def role_of(self, user_id: uuid.UUID, folder: Folder) -> str:
        return (self.access.folder_role(user_id, folder) or Role.VIEWER).value

    def path_roles(self, user_id: uuid.UUID, path: list[Folder]) -> list[str]:
        """The caller's role at each step of a path in one query (it never shrinks going down)."""
        if not path or self.workspaces.is_owner(user_id, path[0].workspace_id):
            return [Role.OWNER.value] * len(path)
        direct = self.permissions.folder_roles_among(user_id, [item.id for item in path])
        best = Role.VIEWER
        roles: list[str] = []
        for item in path:
            if item.id in direct and Role(direct[item.id]) == Role.EDITOR:
                best = Role.EDITOR
            roles.append(best.value)
        return roles

    def parent_visible(self, user_id: uuid.UUID, folder: Folder) -> bool:
        """Whether the caller may be told the parent id (not for the top of a shared tree)."""
        if folder.parent_id is None or self.workspaces.is_owner(user_id, folder.workspace_id):
            return True
        parent = self.folders.get_any(folder.parent_id)
        return parent is not None and self.access.folder_role(user_id, parent) is not None

    def _siblings_visible(self, user_id: uuid.UUID, folder: Folder) -> bool:
        """Whether every folder sharing this folder's name space is one the caller may see."""
        if self.workspaces.is_owner(user_id, folder.workspace_id):
            return True
        if folder.parent_id is None:
            return False  # a root folder's siblings are the owner's other top-level folders
        parent = self.folders.get_any(folder.parent_id)
        return parent is not None and self.access.folder_role(user_id, parent) is not None

    def create_folder(self, user_id: uuid.UUID, name: str, parent_id: uuid.UUID | None) -> Folder:
        if parent_id is None:
            workspace_id = self._own_workspace(user_id, Action.WRITE)
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
        if not self._siblings_visible(user_id, folder):
            # The top of a shared tree has siblings the editor cannot see, and a name clash with
            # one would reveal it. Only the owner renames it.
            raise ForbiddenError(
                "Only the owner can rename the top of a shared folder", code="shared_root_locked"
            )
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
        self.audit.record(
            workspace_id=workspace_id,
            actor_id=user_id,
            action=AuditAction.FOLDER_DELETED,
            resource_type=ResourceType.FOLDER,
            resource_id=folder.id,
        )
        self.session.commit()

    def _own_workspace(self, user_id: uuid.UUID, action: Action) -> uuid.UUID:
        workspace = self.workspaces.get_for_user(user_id)
        self.access.require(user_id, workspace.id, action)
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
