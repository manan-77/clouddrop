"""Reads and writes pipeline state.

The processing module is the worker side of storage: it reads the file tables directly because the
worker has no user and needs rows that are not scoped to a workspace. Only the services in
`storage` change what users see; this module only moves a file's status along the state machine.
"""

import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any, cast

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session, aliased

from app.db.soft_delete import only_active
from app.modules.processing.constants import JobStatus
from app.modules.processing.extraction.chunking import Chunk
from app.modules.processing.models import DocumentChunk, ProcessingJob
from app.modules.storage.models import File, FileVersion


class PipelineRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_version(self, version_id: uuid.UUID) -> FileVersion | None:
        return self.session.get(FileVersion, version_id)

    def get_active_file(self, file_id: uuid.UUID) -> File | None:
        return self.session.scalar(select(File).where(File.id == file_id, only_active(File)))

    def ensure_job(self, version_id: uuid.UUID, stage: str) -> ProcessingJob:
        # The unique constraint is the arbiter when two workers create the same job.
        self.session.execute(
            insert(ProcessingJob)
            .values(file_version_id=version_id, stage=stage, status=JobStatus.PENDING.value)
            .on_conflict_do_nothing(index_elements=["file_version_id", "stage"])
        )
        job = self.session.scalar(
            select(ProcessingJob).where(
                ProcessingJob.file_version_id == version_id, ProcessingJob.stage == stage
            )
        )
        if job is None:  # inserted above or already present, so this cannot happen
            raise RuntimeError("processing job missing after insert")
        return job

    def claim(self, job_id: uuid.UUID, now: datetime, stale_before: datetime) -> bool:
        """Atomically take a job: pending, or running but abandoned by a crashed worker."""
        result = cast(
            CursorResult[Any],
            self.session.execute(
                update(ProcessingJob)
                .where(
                    ProcessingJob.id == job_id,
                    or_(
                        ProcessingJob.status == JobStatus.PENDING.value,
                        (ProcessingJob.status == JobStatus.RUNNING.value)
                        & (ProcessingJob.started_at < stale_before),
                    ),
                )
                .values(
                    status=JobStatus.RUNNING.value,
                    attempts=ProcessingJob.attempts + 1,
                    started_at=now,
                    finished_at=None,
                    error_code=None,
                )
            ),
        )
        self.session.flush()
        return result.rowcount == 1

    def stuck_version_ids(
        self,
        statuses: tuple[str, ...],
        stuck_before: datetime,
        expected_stages: int,
        limit: int,
    ) -> list[uuid.UUID]:
        """Latest versions of live files that stopped moving and have unfinished stages."""
        other = aliased(
            FileVersion
        )  # a separate alias, or the subquery correlates to the outer one
        latest = select(func.max(other.version)).where(other.file_id == File.id).scalar_subquery()
        succeeded = (
            select(func.count())
            .select_from(ProcessingJob)
            .where(
                ProcessingJob.file_version_id == FileVersion.id,
                ProcessingJob.status == JobStatus.SUCCEEDED.value,
            )
            .scalar_subquery()
        )
        # When the file last moved or was last handed to the worker, whichever is later.
        marker = func.coalesce(FileVersion.enqueued_at, File.updated_at)
        rows = self.session.scalars(
            select(FileVersion.id)
            .join(File, File.id == FileVersion.file_id)
            .where(
                only_active(File),
                File.status.in_(statuses),
                marker < stuck_before,
                FileVersion.version == latest,
                succeeded < expected_stages,
            )
            .order_by(marker)
            .limit(limit)
        )
        return list(rows)

    def mark_enqueued(self, version_ids: list[uuid.UUID], when: datetime) -> None:
        if version_ids:
            self.session.execute(
                update(FileVersion).where(FileVersion.id.in_(version_ids)).values(enqueued_at=when)
            )

    def replace_chunks(self, version_id: uuid.UUID, chunks: Sequence[Chunk]) -> None:
        """Delete and insert in the caller's transaction: a rerun yields exactly the same rows."""
        self.session.execute(
            delete(DocumentChunk).where(DocumentChunk.file_version_id == version_id)
        )
        rows = [
            {
                "file_version_id": version_id,
                "chunk_index": chunk.index,
                "page": chunk.page,
                "content": chunk.content,
                "content_hash": chunk.content_hash,
            }
            for chunk in chunks
        ]
        for start in range(0, len(rows), 500):
            self.session.execute(insert(DocumentChunk), rows[start : start + 500])
