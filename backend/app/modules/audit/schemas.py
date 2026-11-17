import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.modules.audit.constants import AuditAction, AuditResult, ResourceType


class AuditEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime
    action: AuditAction
    result: AuditResult
    resource_type: ResourceType
    resource_id: uuid.UUID | None
    actor_id: uuid.UUID | None
    actor_name: str | None
    target_user_id: uuid.UUID | None
    detail: str | None
    request_id: str | None
