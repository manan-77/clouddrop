import uuid
from enum import StrEnum

from sqlalchemy import ColumnElement, exists, literal, or_, select
from sqlalchemy.orm import Session, aliased

from app.core.errors import NotFoundError
from app.modules.sharing.models import Permission
from app.modules.storage.constants import MAX_FOLDER_DEPTH
from app.modules.storage.models import File, Folder
from app.modules.workspaces.service import WorkspaceService


class Action(StrEnum):
    READ = "read"
    WRITE = "write"
    DELETE = "delete"
    SHARE = "share"


class Role(StrEnum):
    VIEWER = "viewer"
    EDITOR = "editor"
    OWNER = "owner"


_RANK = {Role.VIEWER: 1, Role.EDITOR: 2, Role.OWNER: 3}
_ALLOWED: dict[Role, frozenset[Action]] = {
    Role.VIEWER: frozenset({Action.READ}),
    Role.EDITOR: frozenset({Action.READ, Action.WRITE}),
    Role.OWNER: frozenset(Action),
}


def allows(role: Role | None, action: Action) -> bool:
    return role is not None and action in _ALLOWED[role]


class AccessService:
    """The one place that decides who may do what. Deny by default; evaluated live per request.

    A grant on a folder covers everything inside it; the highest role along the path wins.
    """

    def __init__(self, session: Session) -> None:
        self.session = session
        self.workspaces = WorkspaceService(session)

    # Workspace-level check, used for operations on the caller's own root.
    def can_access(self, user_id: uuid.UUID, workspace_id: uuid.UUID, action: Action) -> bool:
        return self.workspaces.is_owner(user_id, workspace_id)

    def require(self, user_id: uuid.UUID, workspace_id: uuid.UUID, action: Action) -> None:
        # 404, not 403: a caller must not learn that a resource exists.
        if not self.can_access(user_id, workspace_id, action):
            raise NotFoundError()

    def folder_role(self, user_id: uuid.UUID, folder: Folder) -> Role | None:
        if self.workspaces.is_owner(user_id, folder.workspace_id):
            return Role.OWNER
        return self._granted_role(user_id, file_id=None, folder_id=folder.id)

    def file_role(self, user_id: uuid.UUID, file: File) -> Role | None:
        if self.workspaces.is_owner(user_id, file.workspace_id):
            return Role.OWNER
        return self._granted_role(user_id, file_id=file.id, folder_id=file.folder_id)

    def can_on_folder(self, user_id: uuid.UUID, folder: Folder, action: Action) -> bool:
        return allows(self.folder_role(user_id, folder), action)

    def can_on_file(self, user_id: uuid.UUID, file: File, action: Action) -> bool:
        return allows(self.file_role(user_id, file), action)

    def _granted_role(
        self, user_id: uuid.UUID, *, file_id: uuid.UUID | None, folder_id: uuid.UUID | None
    ) -> Role | None:
        conditions = []
        if file_id is not None:
            conditions.append(Permission.file_id == file_id)
        blocked: ColumnElement[bool] = literal(False)
        if folder_id is not None:
            chain = self._ancestors(folder_id)
            conditions.append(Permission.folder_id.in_(select(chain.c.id)))
            # A deleted folder anywhere above hides everything below it from non-owners. It rides
            # in the same statement, so the ancestor walk runs once.
            blocked = select(exists().where(chain.c.deleted)).scalar_subquery()
        if not conditions:
            return None
        rows = self.session.execute(
            select(Permission.role, blocked.label("blocked")).where(
                Permission.grantee_id == user_id, or_(*conditions)
            )
        ).all()
        if not rows or any(row.blocked for row in rows):
            return None
        return max((Role(row.role) for row in rows), key=_RANK.__getitem__)

    @staticmethod
    def _ancestors(folder_id: uuid.UUID):  # type: ignore[no-untyped-def]  # a recursive CTE
        chain = (
            select(
                Folder.id,
                Folder.parent_id,
                Folder.deleted_at.is_not(None).label("deleted"),
                literal(1).label("depth"),
            )
            .where(Folder.id == folder_id)
            .cte("ancestors", recursive=True)
        )
        parent = aliased(Folder)
        return chain.union_all(
            select(
                parent.id,
                parent.parent_id,
                parent.deleted_at.is_not(None),
                chain.c.depth + 1,
            )
            .join(chain, parent.id == chain.c.parent_id)
            .where(chain.c.depth < MAX_FOLDER_DEPTH)
        )
