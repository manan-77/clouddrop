import uuid
from enum import StrEnum

from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.modules.workspaces.service import WorkspaceService


class Action(StrEnum):
    READ = "read"
    WRITE = "write"
    DELETE = "delete"


class AccessService:
    def __init__(self, session: Session) -> None:
        self.workspaces = WorkspaceService(session)

    def can_access(self, user_id: uuid.UUID, workspace_id: uuid.UUID, action: Action) -> bool:
        # Deny by default. Owner-only until sharing (Phase 4) adds grants and roles.
        return self.workspaces.is_owner(user_id, workspace_id)

    def require(self, user_id: uuid.UUID, workspace_id: uuid.UUID, action: Action) -> None:
        # 404, not 403: a caller must not learn that a resource exists.
        if not self.can_access(user_id, workspace_id, action):
            raise NotFoundError()
