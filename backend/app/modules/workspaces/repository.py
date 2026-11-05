import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.workspaces.models import Workspace


class WorkspaceRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, workspace: Workspace) -> None:
        self.session.add(workspace)
        self.session.flush()

    def get_by_owner(self, owner_id: uuid.UUID) -> Workspace | None:
        return self.session.scalar(select(Workspace).where(Workspace.owner_id == owner_id))

    def is_owner(self, owner_id: uuid.UUID, workspace_id: uuid.UUID) -> bool:
        return (
            self.session.scalar(
                select(Workspace.id).where(
                    Workspace.id == workspace_id, Workspace.owner_id == owner_id
                )
            )
            is not None
        )
