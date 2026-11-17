import logging
import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.logging import request_id_var
from app.core.pagination import PageParams
from app.modules.audit.constants import AuditAction, AuditResult, ResourceType
from app.modules.audit.models import AuditEvent
from app.modules.auth.models import User
from app.modules.workspaces.service import WorkspaceService

logger = logging.getLogger(__name__)


class AuditService:
    """Writes and reads the audit trail.

    `record` joins the caller's transaction, so an action and its audit row commit together: an
    action that cannot be audited does not happen. `record_failure` is for outcomes with nothing
    else to commit (a failed login); it never raises, so it cannot hide the original error.
    """

    def __init__(self, session: Session) -> None:
        self.session = session

    def record(
        self,
        *,
        workspace_id: uuid.UUID,
        actor_id: uuid.UUID | None,
        action: AuditAction,
        resource_type: ResourceType,
        resource_id: uuid.UUID | None,
        target_user_id: uuid.UUID | None = None,
        detail: str | None = None,
        result: AuditResult = AuditResult.SUCCESS,
    ) -> None:
        request_id = request_id_var.get()
        self.session.add(
            AuditEvent(
                workspace_id=workspace_id,
                actor_id=actor_id,
                action=action.value,
                resource_type=resource_type.value,
                resource_id=resource_id,
                target_user_id=target_user_id,
                detail=detail,
                result=result.value,
                request_id=None if request_id == "-" else request_id,
            )
        )

    def record_failure(
        self,
        *,
        workspace_id: uuid.UUID,
        actor_id: uuid.UUID | None,
        action: AuditAction,
        resource_type: ResourceType,
        resource_id: uuid.UUID | None,
    ) -> None:
        try:
            self.record(
                workspace_id=workspace_id,
                actor_id=actor_id,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                result=AuditResult.FAILURE,
            )
            self.session.commit()
        except SQLAlchemyError:
            self.session.rollback()
            # Ids only: the audit row's content must not reach the log.
            logger.exception("Could not write an audit row for %s", action.value)

    def list_events(
        self,
        user_id: uuid.UUID,
        params: PageParams,
        *,
        resource_type: ResourceType | None,
        resource_id: uuid.UUID | None,
    ) -> tuple[list[tuple[AuditEvent, str | None]], int]:
        """The caller's own workspace trail, newest first; other workspaces are never visible."""
        workspace_id = WorkspaceService(self.session).get_for_user(user_id).id
        where = [AuditEvent.workspace_id == workspace_id]
        if resource_type is not None:
            where.append(AuditEvent.resource_type == resource_type.value)
        if resource_id is not None:
            where.append(AuditEvent.resource_id == resource_id)
        total = self.session.scalar(select(func.count()).select_from(AuditEvent).where(*where))
        rows = self.session.execute(
            select(AuditEvent, User.display_name)
            .outerjoin(User, User.id == AuditEvent.actor_id)
            .where(*where)
            .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
            .limit(params.page_size)
            .offset(params.offset)
        )
        return [(event, name) for event, name in rows], int(total or 0)
