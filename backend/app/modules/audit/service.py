import uuid

from sqlalchemy.orm import Session

from app.core.logging import request_id_var
from app.core.pagination import PageParams
from app.modules.audit.constants import AuditAction, ResourceType
from app.modules.audit.models import AuditEvent
from app.modules.audit.repository import AuditEventView, AuditRepository
from app.modules.workspaces.service import WorkspaceService


class AuditService:
    """Writes and reads the audit trail.

    `record` joins the caller's transaction, so an action and its audit row commit together: an
    action that cannot be audited does not happen. Only outcomes of authenticated, authorised
    actions are recorded; denied attempts and failed logins are not (an unauthenticated caller
    must not be able to write into someone's trail).
    """

    def __init__(self, session: Session) -> None:
        self.session = session
        self.events = AuditRepository(session)

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
    ) -> None:
        request_id = request_id_var.get()
        self.events.add(
            AuditEvent(
                workspace_id=workspace_id,
                actor_id=actor_id,
                action=action.value,
                resource_type=resource_type.value,
                resource_id=resource_id,
                target_user_id=target_user_id,
                detail=detail,
                request_id=None if request_id == "-" else request_id,
            )
        )

    def list_events(
        self,
        user_id: uuid.UUID,
        params: PageParams,
        *,
        resource_type: ResourceType | None,
        resource_id: uuid.UUID | None,
    ) -> tuple[list[AuditEventView], int]:
        """The caller's own workspace trail, newest first; other workspaces are never visible."""
        workspace_id = WorkspaceService(self.session).get_for_user(user_id).id
        return self.events.list_for_workspace(
            workspace_id,
            resource_type=resource_type.value if resource_type else None,
            resource_id=resource_id,
            limit=params.page_size,
            offset=params.offset,
        )
