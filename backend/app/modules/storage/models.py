import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    literal_column,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.modules.storage.constants import FileStatus

_STATUS_VALUES = ", ".join(f"'{status.value}'" for status in FileStatus)


class Folder(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "folders"
    __table_args__ = (
        # Sibling names are unique case-insensitively among live folders; root has NULL parent.
        Index(
            "uq_folders_sibling_name",
            "workspace_id",
            literal_column("coalesce(parent_id, '00000000-0000-0000-0000-000000000000'::uuid)"),
            literal_column("lower(name)"),
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("folders.id", ondelete="RESTRICT"), index=True
    )
    name: Mapped[str] = mapped_column(String(255))


class File(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "files"
    __table_args__ = (CheckConstraint(f"status IN ({_STATUS_VALUES})", name="status_valid"),)

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    folder_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("folders.id", ondelete="RESTRICT"), index=True
    )
    name: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(255))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(20), default=FileStatus.PENDING_UPLOAD.value)


class FileVersion(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "file_versions"
    # The (file_id, version) unique constraint also indexes file_id for the FK.
    __table_args__ = (UniqueConstraint("file_id", "version"),)

    file_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("files.id", ondelete="CASCADE"))
    version: Mapped[int]
    s3_key: Mapped[str] = mapped_column(String(1024), unique=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    content_type: Mapped[str] = mapped_column(String(255))
    etag: Mapped[str | None] = mapped_column(String(128))
    # When processing was last handed to the worker; the sweeper orders on it so no file starves.
    enqueued_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
