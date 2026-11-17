import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.modules.audit.constants import AuditAction, AuditResult, ResourceType


def _values(enum: type[AuditAction] | type[AuditResult] | type[ResourceType]) -> str:
    return ", ".join(f"'{member.value}'" for member in enum)


class AuditEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Append-only record of who did what to which resource. Ids and short codes only: never
    file names, file contents, emails or request bodies."""

    __tablename__ = "audit_events"
    __table_args__ = (
        CheckConstraint(f"action IN ({_values(AuditAction)})", name="action_valid"),
        CheckConstraint(f"result IN ({_values(AuditResult)})", name="result_valid"),
        CheckConstraint(f"resource_type IN ({_values(ResourceType)})", name="resource_type_valid"),
        Index("ix_audit_events_workspace_created", "workspace_id", text("created_at DESC")),
        Index("ix_audit_events_workspace_resource", "workspace_id", "resource_id"),
    )

    # clock_timestamp(), not now(): rows from one transaction still order by when they happened.
    created_at: Mapped[datetime] = mapped_column(server_default=text("clock_timestamp()"))
    # The workspace whose owner may read the event (the owner of the affected resource).
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    action: Mapped[str] = mapped_column(String(40))
    resource_type: Mapped[str] = mapped_column(String(10))
    # No foreign key: the trail must outlive a purged file or folder.
    resource_id: Mapped[uuid.UUID | None]
    target_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    detail: Mapped[str | None] = mapped_column(String(40))
    result: Mapped[str] = mapped_column(String(10))
    request_id: Mapped[str | None] = mapped_column(String(64))
