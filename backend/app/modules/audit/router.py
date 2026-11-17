import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.core.deps import SessionDep
from app.core.pagination import Page, PageParamsDep
from app.modules.audit.constants import ResourceType
from app.modules.audit.schemas import AuditEventRead
from app.modules.audit.service import AuditService
from app.modules.auth.deps import CurrentUser

router = APIRouter(prefix="/api/v1/audit-events", tags=["audit"])


def get_audit_service(session: SessionDep) -> AuditService:
    return AuditService(session)


AuditServiceDep = Annotated[AuditService, Depends(get_audit_service)]


@router.get("", response_model=Page[AuditEventRead], status_code=status.HTTP_200_OK)
def list_audit_events(
    user: CurrentUser,
    service: AuditServiceDep,
    params: PageParamsDep,
    resource_type: Annotated[ResourceType | None, Query()] = None,
    resource_id: Annotated[uuid.UUID | None, Query()] = None,
) -> Page[AuditEventRead]:
    """Activity on the caller's own files and folders (their whole workspace), newest first."""
    rows, total = service.list_events(
        user.id, params, resource_type=resource_type, resource_id=resource_id
    )
    return Page[AuditEventRead](
        items=[
            AuditEventRead.model_validate(
                {
                    "id": event.id,
                    "created_at": event.created_at,
                    "action": event.action,
                    "result": event.result,
                    "resource_type": event.resource_type,
                    "resource_id": event.resource_id,
                    "actor_id": event.actor_id,
                    "actor_name": actor_name,
                    "target_user_id": event.target_user_id,
                    "detail": event.detail,
                    "request_id": event.request_id,
                }
            )
            for event, actor_name in rows
        ],
        total=total,
        page=params.page,
        page_size=params.page_size,
    )
