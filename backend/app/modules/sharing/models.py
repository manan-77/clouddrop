import uuid

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Permission(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A grant of `viewer` or `editor` on one folder or one file. The owner is never stored."""

    __tablename__ = "permissions"
    __table_args__ = (
        CheckConstraint("num_nonnulls(file_id, folder_id) = 1", name="exactly_one_resource"),
        CheckConstraint("role IN ('viewer', 'editor')", name="role_valid"),
        # One grant per person per resource; these also serve as the foreign-key indexes.
        Index(
            "uq_permissions_folder_grantee",
            "folder_id",
            "grantee_id",
            unique=True,
            postgresql_where=text("folder_id IS NOT NULL"),
        ),
        Index(
            "uq_permissions_file_grantee",
            "file_id",
            "grantee_id",
            unique=True,
            postgresql_where=text("file_id IS NOT NULL"),
        ),
    )

    file_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("files.id", ondelete="CASCADE"))
    folder_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("folders.id", ondelete="CASCADE")
    )
    grantee_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    granted_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    role: Mapped[str] = mapped_column(String(10))
