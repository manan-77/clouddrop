import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.audit.models import AuditEvent
from app.modules.auth.models import User


@dataclass(frozen=True)
class AuditEventView:
    """One trail row plus the display name of the actor (null if the account is gone)."""

    id: uuid.UUID
    created_at: datetime
    action: str
    result: str
    resource_type: str
    resource_id: uuid.UUID | None
    actor_id: uuid.UUID | None
    actor_name: str | None
    target_user_id: uuid.UUID | None
    detail: str | None
    request_id: str | None


class AuditRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, event: AuditEvent) -> None:
        self.session.add(event)

    def list_for_workspace(
        self,
        workspace_id: uuid.UUID,
        *,
        resource_type: str | None,
        resource_id: uuid.UUID | None,
        limit: int,
        offset: int,
    ) -> tuple[list[AuditEventView], int]:
        where = [AuditEvent.workspace_id == workspace_id]
        if resource_type is not None:
            where.append(AuditEvent.resource_type == resource_type)
        if resource_id is not None:
            where.append(AuditEvent.resource_id == resource_id)
        total = self.session.scalar(select(func.count()).select_from(AuditEvent).where(*where))
        rows = self.session.execute(
            select(AuditEvent, User.display_name)
            .outerjoin(User, User.id == AuditEvent.actor_id)
            .where(*where)
            .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
            .limit(limit)
            .offset(offset)
        )
        views = [
            AuditEventView(
                id=event.id,
                created_at=event.created_at,
                action=event.action,
                result=event.result,
                resource_type=event.resource_type,
                resource_id=event.resource_id,
                actor_id=event.actor_id,
                actor_name=name,
                target_user_id=event.target_user_id,
                detail=event.detail,
                request_id=event.request_id,
            )
            for event, name in rows
        ]
        return views, int(total or 0)
