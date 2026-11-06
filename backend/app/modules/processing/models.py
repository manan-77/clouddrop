import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.modules.processing.constants import JobStatus

_STATUS_VALUES = ", ".join(f"'{status.value}'" for status in JobStatus)


class ProcessingJob(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One row per stage per file version. The pipeline state lives here, never in the broker."""

    __tablename__ = "processing_jobs"
    # The unique constraint also indexes file_version_id for the foreign key.
    __table_args__ = (
        UniqueConstraint("file_version_id", "stage"),
        CheckConstraint(f"status IN ({_STATUS_VALUES})", name="status_valid"),
    )

    file_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("file_versions.id", ondelete="CASCADE")
    )
    stage: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(
        String(20), default=JobStatus.PENDING.value, server_default=text("'pending'")
    )
    attempts: Mapped[int] = mapped_column(default=0, server_default=text("0"))
    # A short machine code, never a raw exception message: it may reach the user interface.
    error_code: Mapped[str | None] = mapped_column(String(50))
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]


class DocumentChunk(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A piece of extracted text. Rewritten as a whole for a version, so re-running is safe."""

    __tablename__ = "document_chunks"
    # The unique constraint also indexes file_version_id for the foreign key.
    __table_args__ = (UniqueConstraint("file_version_id", "chunk_index"),)

    file_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("file_versions.id", ondelete="CASCADE")
    )
    chunk_index: Mapped[int]
    page: Mapped[int | None]
    content: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
