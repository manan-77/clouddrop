import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import CheckConstraint, ForeignKey, Index, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.ai.embeddings import EMBEDDING_DIM
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
    __table_args__ = (
        UniqueConstraint("file_version_id", "chunk_index"),
        CheckConstraint("chunk_index >= 0", name="chunk_index_non_negative"),
    )

    file_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("file_versions.id", ondelete="CASCADE")
    )
    chunk_index: Mapped[int]
    page: Mapped[int | None]
    content: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))


class ChunkEmbedding(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """The vector for one chunk. Model and size are stored so a model change is detectable."""

    __tablename__ = "chunk_embeddings"
    __table_args__ = (
        UniqueConstraint("chunk_id"),
        CheckConstraint("dim > 0", name="dim_positive"),
        # Approximate nearest neighbours by cosine distance (see docs/adr/0013).
        Index(
            "ix_chunk_embeddings_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    chunk_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("document_chunks.id", ondelete="CASCADE")
    )
    model: Mapped[str] = mapped_column(String(100))
    dim: Mapped[int]
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM))
