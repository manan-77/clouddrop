import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.modules.processing.constants import JobStatus
from app.modules.processing.models import ProcessingJob
from app.modules.processing.repository import PipelineRepository
from app.modules.processing.stages import (
    DetectTypeStage,
    ExtractStage,
    PermanentStageError,
    ScanStage,
    Stage,
    TransientStageError,
    VerifyObjectStage,
)
from app.modules.storage.constants import FileStatus
from app.modules.storage.models import File
from app.modules.storage.s3 import S3Storage

logger = logging.getLogger(__name__)

# Order matters. Later branches add the malware scan, text extraction, chunking and embedding.
PIPELINE: tuple[Stage, ...] = (
    VerifyObjectStage(),
    ScanStage(),
    DetectTypeStage(),
    ExtractStage(),
)

# Set when the last stage exists. Until text extraction and embeddings are built a file rests in
# `processing`: marking it `ready` now would claim it is searchable when it is not.
FINAL_STATUS: FileStatus | None = None

RUNNABLE = (FileStatus.UPLOADED, FileStatus.SCANNING, FileStatus.PROCESSING)


def _fail(
    session: Session,
    file: File,
    job: ProcessingJob,
    code: str,
    status: FileStatus = FileStatus.FAILED,
) -> None:
    job.status = JobStatus.FAILED
    job.error_code = code
    job.finished_at = datetime.now(UTC)
    file.status = status
    session.commit()
    logger.warning("Stage %s failed for file %s: %s", job.stage, file.id, code)


def _release(session: Session, job: ProcessingJob) -> None:
    job.status = JobStatus.PENDING
    session.commit()


def run_pipeline(
    session: Session,
    storage: S3Storage,
    version_id: uuid.UUID,
    *,
    stale_after: timedelta = timedelta(minutes=10),
    max_attempts: int = 8,
    stages: tuple[Stage, ...] | None = None,
) -> None:
    """Runs every stage that has not succeeded yet. Safe to run twice and to resume after a crash.

    A transient or unexpected failure puts the job back to pending and raises
    `TransientStageError` (the task retries with back-off); a permanent one records an error code,
    fails the file and stops. A stage claimed `max_attempts` times is failed, so nothing is retried
    forever. Each stage commits on its own, and a stage's partial work is rolled back first.
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
        if job.attempts >= max_attempts:
            _fail(session, file, job, getattr(stage, "exhausted_code", "too_many_attempts"))
            return
        now = datetime.now(UTC)
        if not repo.claim(job.id, now, now - stale_after):
            return  # another worker is running this stage
        session.refresh(job)
        file.status = stage.file_status
        session.commit()
        try:
            stage.run(file, version, storage, session)
        except TransientStageError:
            session.rollback()
            _release(session, job)
            raise
        except PermanentStageError as exc:
            session.rollback()
            _fail(session, file, job, exc.code, exc.file_status)
            return
        except Exception as exc:  # unknown failure (database, timeout, a bug): retry, but capped
            session.rollback()
            _release(session, job)
            logger.exception("Unexpected error in stage %s for file %s", stage.name, file.id)
            raise TransientStageError("unexpected error") from exc
        job.status = JobStatus.SUCCEEDED
        job.finished_at = datetime.now(UTC)
        session.commit()
        logger.debug("Stage %s succeeded for file %s", stage.name, file.id)

    if FINAL_STATUS is not None:
        file.status = FINAL_STATUS
        session.commit()
