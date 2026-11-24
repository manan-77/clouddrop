import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.modules.summaries.constants import SummaryStatus

_STATUS_VALUES = ", ".join(f"'{status.value}'" for status in SummaryStatus)


class FileSummary(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """What a model made of one version of a file. One row per version: new content is a new
    version, so a summary is made again only for new content or when someone asks."""

    __tablename__ = "file_summaries"
    # The unique constraint also indexes file_version_id for the foreign key.
    __table_args__ = (
        UniqueConstraint("file_version_id"),
        CheckConstraint(f"status IN ({_STATUS_VALUES})", name="status_valid"),
    )

    file_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("file_versions.id", ondelete="CASCADE")
    )
    status: Mapped[str] = mapped_column(
        String(10), default=SummaryStatus.PENDING.value, server_default=text("'pending'")
    )
    summary: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(String(40))
    tags: Mapped[list[str]] = mapped_column(
        ARRAY(String(40)), default=list, server_default=text("'{}'")
    )
    # True when the document was longer than what was read (only the start was summarised).
    partial: Mapped[bool] = mapped_column(default=False, server_default=text("false"))
    # Which model and prompt wrote it, so a better prompt can be told apart from an old result.
    model: Mapped[str | None] = mapped_column(String(100))
    prompt_version: Mapped[str | None] = mapped_column(String(20))
    # A short machine code, never an exception message: it may reach the user interface.
    error_code: Mapped[str | None] = mapped_column(String(50))
    attempts: Mapped[int] = mapped_column(default=0, server_default=text("0"))
    # When it was last asked for: the sweeper looks for requests nobody picked up.
    requested_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    generated_at: Mapped[datetime | None]
