import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, NotFoundError, UnprocessableError
from app.core.pagination import PageParams
from app.modules.audit.constants import AuditAction, ResourceType
from app.modules.audit.service import AuditService
from app.modules.auth.models import User
from app.modules.auth.repository import UserRepository
from app.modules.sharing.models import Permission
from app.modules.sharing.repository import Kind, PermissionRepository
from app.modules.sharing.service import AccessService, Action
from app.modules.storage.constants import FileStatus
from app.modules.storage.models import File, Folder
from app.modules.storage.repository import FileRepository, FolderRepository


class SharingService:
    """Grant, change, revoke and list access. Only the owner of a resource may do any of it."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.access = AccessService(session)
        self.audit = AuditService(session)
        self.permissions = PermissionRepository(session)
        self.users = UserRepository(session)
        self.files = FileRepository(session)
        self.folders = FolderRepository(session)

    def _resource(self, user_id: uuid.UUID, kind: Kind, resource_id: uuid.UUID) -> File | Folder:
        """The resource, or 404 for anyone who is not its owner (they must not learn it exists)."""
        if kind == "files":
            file = self.files.get_any(resource_id)
            if file is None or not self.access.can_on_file(user_id, file, Action.SHARE):
                raise NotFoundError("File not found", code="file_not_found")
            return file
        folder = self.folders.get_any(resource_id)
        if folder is None or not self.access.can_on_folder(user_id, folder, Action.SHARE):
            raise NotFoundError("Folder not found", code="folder_not_found")
        return folder

    def grant(
        self, user_id: uuid.UUID, kind: Kind, resource_id: uuid.UUID, email: str, role: str
    ) -> tuple[Permission, User, bool]:
        resource = self._resource(user_id, kind, resource_id)
        if isinstance(resource, File) and resource.status != FileStatus.READY:
            raise ConflictError("The file is not available yet", code="file_not_ready")
        grantee = self.users.get_by_email(email.strip().lower())
        if grantee is None or not grantee.is_active:
            raise NotFoundError("No account with that email", code="user_not_found")
        if grantee.id == user_id:
            raise UnprocessableError("You already own this", code="cannot_share_with_self")
        existing = self.permissions.find(kind, resource_id, grantee.id, lock=True)
        if existing is not None:
            existing.role = role
            self._audit(user_id, resource, AuditAction.PERMISSION_CHANGED, grantee.id, role)
            self.session.commit()
            return existing, grantee, False
        permission = Permission(
            file_id=resource_id if kind == "files" else None,
            folder_id=resource_id if kind == "folders" else None,
            grantee_id=grantee.id,
            granted_by=user_id,
            role=role,
        )
        try:
            # The unique index is the arbiter when two grants race.
            with self.session.begin_nested():
                self.permissions.add(permission)
        except IntegrityError:
            winner = self.permissions.find(kind, resource_id, grantee.id, lock=True)
            if winner is None:
                raise  # not a lost race (for example the grantee vanished): surface the real error
            winner.role = role
            self._audit(user_id, resource, AuditAction.PERMISSION_CHANGED, grantee.id, role)
            self.session.commit()
            return winner, grantee, False
        self._audit(user_id, resource, AuditAction.PERMISSION_GRANTED, grantee.id, role)
        self.session.commit()
        return permission, grantee, True

    def list_grants(
        self, user_id: uuid.UUID, kind: Kind, resource_id: uuid.UUID, params: PageParams
    ) -> tuple[list[tuple[Permission, User]], int]:
        self._resource(user_id, kind, resource_id)
        return self.permissions.list_for(kind, resource_id, params.page_size, params.offset)

    def get_grant(
        self, user_id: uuid.UUID, kind: Kind, resource_id: uuid.UUID, permission_id: uuid.UUID
    ) -> tuple[Permission, User]:
        _, permission, grantee = self._load_grant(user_id, kind, resource_id, permission_id)
        return permission, grantee

    def _load_grant(
        self,
        user_id: uuid.UUID,
        kind: Kind,
        resource_id: uuid.UUID,
        permission_id: uuid.UUID,
        *,
        lock: bool = False,
    ) -> tuple[File | Folder, Permission, User]:
        resource = self._resource(user_id, kind, resource_id)
        # Mutating callers lock the row so a concurrent revoke cannot turn their write into a 500.
        permission = self.permissions.get(kind, resource_id, permission_id, lock=lock)
        if permission is None:
            raise NotFoundError("Permission not found", code="permission_not_found")
        return resource, permission, self.permissions.grantee(permission)

    def change_role(
        self,
        user_id: uuid.UUID,
        kind: Kind,
        resource_id: uuid.UUID,
        permission_id: uuid.UUID,
        role: str,
    ) -> tuple[Permission, User]:
        resource, permission, grantee = self._load_grant(
            user_id, kind, resource_id, permission_id, lock=True
        )
        permission.role = role
        self._audit(user_id, resource, AuditAction.PERMISSION_CHANGED, grantee.id, role)
        self.session.commit()
        return permission, grantee

    def revoke(
        self, user_id: uuid.UUID, kind: Kind, resource_id: uuid.UUID, permission_id: uuid.UUID
    ) -> None:
        resource, permission, grantee = self._load_grant(
            user_id, kind, resource_id, permission_id, lock=True
        )
        self.permissions.delete(permission)
        self._audit(user_id, resource, AuditAction.PERMISSION_REVOKED, grantee.id, permission.role)
        self.session.commit()

    def _audit(
        self,
        user_id: uuid.UUID,
        resource: File | Folder,
        action: AuditAction,
        grantee_id: uuid.UUID,
        role: str,
    ) -> None:
        self.audit.record(
            workspace_id=resource.workspace_id,
            actor_id=user_id,
            action=action,
            resource_type=ResourceType.FILE if isinstance(resource, File) else ResourceType.FOLDER,
            resource_id=resource.id,
            target_user_id=grantee_id,
            detail=role,
        )

    def shared_with_me(
        self, user_id: uuid.UUID, params: PageParams
    ) -> tuple[list[dict[str, object]], int]:
        return self.permissions.shared_with(user_id, params.page_size, params.offset)
