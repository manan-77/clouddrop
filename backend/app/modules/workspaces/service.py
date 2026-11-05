import uuid

from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.modules.workspaces.models import Workspace
from app.modules.workspaces.repository import WorkspaceRepository


class WorkspaceService:
    def __init__(self, session: Session) -> None:
        self.workspaces = WorkspaceRepository(session)

    def create_personal(self, owner_id: uuid.UUID, display_name: str) -> Workspace:
        workspace = Workspace(owner_id=owner_id, name=f"{display_name}'s files"[:100])
        self.workspaces.add(workspace)
        return workspace

    def get_for_user(self, user_id: uuid.UUID) -> Workspace:
        workspace = self.workspaces.get_by_owner(user_id)
        if workspace is None:
            raise NotFoundError("Workspace not found", code="workspace_not_found")
        return workspace

    def is_owner(self, user_id: uuid.UUID, workspace_id: uuid.UUID) -> bool:
        return self.workspaces.is_owner(user_id, workspace_id)
