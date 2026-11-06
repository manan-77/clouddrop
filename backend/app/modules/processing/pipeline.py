import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.modules.processing.constants import JobStatus
from app.modules.processing.repository import PipelineRepository
from app.modules.processing.stages import (
    DetectTypeStage,
    PermanentStageError,
    Stage,
    TransientStageError,
    VerifyObjectStage,
)
from app.modules.storage.constants import FileStatus
from app.modules.storage.s3 import S3Storage

logger = logging.getLogger(__name__)

# Order matters. Later branches add the malware scan, text extraction, chunking and embedding.
PIPELINE: tuple[Stage, ...] = (VerifyObjectStage(), DetectTypeStage())

# Set when the last stage exists. Until text extraction and embeddings are built a file rests in
# `processing`: marking it `ready` now would claim it is searchable when it is not.
FINAL_STATUS: FileStatus | None = None

RUNNABLE = (FileStatus.UPLOADED, FileStatus.SCANNING, FileStatus.PROCESSING)


def run_pipeline(
    session: Session,
    storage: S3Storage,
    version_id: uuid.UUID,
    *,
    stale_after: timedelta = timedelta(minutes=15),
    stages: tuple[Stage, ...] | None = None,
) -> None:
    """Runs every stage that has not succeeded yet. Safe to run twice and to resume after a crash.

    A transient failure raises `TransientStageError` (the task retries); a permanent one records
    an error code, fails the file and stops. Each stage commits on its own.
    """
    stages = PIPELINE if stages is None else stages
    repo = PipelineRepository(session)
    version = repo.get_version(version_id)
    file = repo.get_active_file(version.file_id) if version else None
    if version is None or file is None or file.status not in RUNNABLE:
        return

    for stage in stages:
        job = repo.ensure_job(version.id, stage.name.value)
        if job.status == JobStatus.SUCCEEDED:
            continue
        if job.status == JobStatus.FAILED:
            return
        now = datetime.now(UTC)
        if not repo.claim(job.id, now, now - stale_after):
            return  # another worker is running this stage
        session.refresh(job)
        file.status = stage.file_status
        session.commit()
        try:
            stage.run(file, version, storage)
        except TransientStageError:
            job.status = JobStatus.PENDING
            session.commit()
            raise
        except PermanentStageError as exc:
            job.status = JobStatus.FAILED
            job.error_code = exc.code
            job.finished_at = datetime.now(UTC)
            file.status = FileStatus.FAILED
            session.commit()
            logger.warning("Stage %s failed for version %s: %s", stage.name, version.id, exc.code)
            return
        job.status = JobStatus.SUCCEEDED
        job.finished_at = datetime.now(UTC)
        session.commit()

    if FINAL_STATUS is not None:
        file.status = FINAL_STATUS
        session.commit()
