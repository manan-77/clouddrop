import uuid
from typing import Literal

from sqlalchemy import Select, func, literal, select
from sqlalchemy.orm import Session

from app.db.soft_delete import only_active
from app.modules.auth.models import User
from app.modules.sharing.models import Permission
from app.modules.storage.constants import FileStatus
from app.modules.storage.models import File, Folder
from app.modules.workspaces.models import Workspace

Kind = Literal["files", "folders"]


def _column(kind: Kind):  # type: ignore[no-untyped-def]
    return Permission.file_id if kind == "files" else Permission.folder_id


class PermissionRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, permission: Permission) -> None:
        self.session.add(permission)
        self.session.flush()

    def find(
        self, kind: Kind, resource_id: uuid.UUID, grantee_id: uuid.UUID, *, lock: bool = False
    ) -> Permission | None:
        query = select(Permission).where(
            _column(kind) == resource_id, Permission.grantee_id == grantee_id
        )
        return self.session.scalar(query.with_for_update() if lock else query)

    def get(
        self,
        kind: Kind,
        resource_id: uuid.UUID,
        permission_id: uuid.UUID,
        *,
        lock: bool = False,
    ) -> Permission | None:
        query = select(Permission).where(
            Permission.id == permission_id, _column(kind) == resource_id
        )
        return self.session.scalar(query.with_for_update() if lock else query)

    def list_for(
        self, kind: Kind, resource_id: uuid.UUID, limit: int, offset: int
    ) -> tuple[list[tuple[Permission, User]], int]:
        where = [_column(kind) == resource_id]
        total = self.session.scalar(select(func.count()).select_from(Permission).where(*where))
        rows = self.session.execute(
            select(Permission, User)
            .join(User, User.id == Permission.grantee_id)
            .where(*where)
            .order_by(User.email, Permission.id)
            .limit(limit)
            .offset(offset)
        )
        return [(p, u) for p, u in rows], int(total or 0)

    def grantee(self, permission: Permission) -> User:
        user = self.session.get(User, permission.grantee_id)
        assert user is not None  # the foreign key guarantees it
        return user

    def delete(self, permission: Permission) -> None:
        self.session.delete(permission)
        self.session.flush()

    def folder_grants_among(
        self, user_id: uuid.UUID, folder_ids: list[uuid.UUID]
    ) -> set[uuid.UUID]:
        rows = self.session.scalars(
            select(Permission.folder_id).where(
                Permission.grantee_id == user_id, Permission.folder_id.in_(folder_ids)
            )
        )
        return {row for row in rows if row is not None}

    def shared_with(
        self, user_id: uuid.UUID, limit: int, offset: int
    ) -> tuple[list[dict[str, object]], int]:
        """Direct grants only (the top of each shared tree), filtered and paged in the database."""
        owner = Workspace.owner_id
        folders = (
            select(
                literal("folder").label("resource_type"),
                Folder.id.label("id"),
                Folder.name.label("name"),
                Permission.role.label("role"),
                literal(None).label("size_bytes"),
                literal(None).label("content_type"),
                literal(None).label("status"),
                Folder.updated_at.label("updated_at"),
                User.display_name.label("owner_name"),
            )
            .join(Folder, Folder.id == Permission.folder_id)
            .join(Workspace, Workspace.id == Folder.workspace_id)
            .join(User, User.id == owner)
            .where(Permission.grantee_id == user_id, only_active(Folder))
        )
        files = (
            select(
                literal("file").label("resource_type"),
                File.id.label("id"),
                File.name.label("name"),
                Permission.role.label("role"),
                File.size_bytes.label("size_bytes"),
                File.content_type.label("content_type"),
                File.status.label("status"),
                File.updated_at.label("updated_at"),
                User.display_name.label("owner_name"),
            )
            .join(File, File.id == Permission.file_id)
            .join(Workspace, Workspace.id == File.workspace_id)
            .join(User, User.id == owner)
            .where(
                Permission.grantee_id == user_id,
                only_active(File),
                File.status == FileStatus.READY.value,
            )
        )
        union = folders.union_all(files).subquery("shared")
        total = self.session.scalar(select(func.count()).select_from(union))
        query: Select[tuple[object, ...]] = (
            select(union).order_by(union.c.name, union.c.id).limit(limit).offset(offset)
        )
        return [dict(row._mapping) for row in self.session.execute(query)], int(total or 0)
