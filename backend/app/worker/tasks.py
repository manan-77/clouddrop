import logging
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta

from celery import Task
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_sessionmaker
from app.modules.processing.dispatcher import ProcessingDispatcher
from app.modules.processing.pipeline import run_pipeline
from app.modules.processing.stages import TransientStageError
from app.modules.processing.sweeper import sweep_stuck_files as sweep
from app.modules.storage.factory import build_storage
from app.modules.storage.s3 import S3Storage
from app.worker.celery_app import celery_app

logger = logging.getLogger(__name__)
_settings = get_settings()


@contextmanager
def open_session() -> Iterator[Session]:
    """Each task runs in its own session; sessions are never shared across tasks or threads."""
    with get_sessionmaker()() as session:
        yield session


def storage_for_worker() -> S3Storage:
    return build_storage(get_settings())


@celery_app.task(
    name="processing.process_file_version",
    bind=True,
    autoretry_for=(TransientStageError,),
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
    max_retries=_settings.processing_max_retries,
)
def process_file_version(self: Task, file_version_id: str) -> None:
    """Takes an id only; the state of the work is read from the database."""
    settings = get_settings()
    with open_session() as session:
        run_pipeline(
            session,
            storage_for_worker(),
            uuid.UUID(file_version_id),
            stale_after=timedelta(seconds=settings.processing_job_stale_seconds),
        )


@celery_app.task(name="processing.sweep_stuck_files")
def sweep_stuck_files() -> int:
    settings = get_settings()
    with open_session() as session:
        return sweep(
            session,
            ProcessingDispatcher(),
            stuck_after=timedelta(seconds=settings.sweeper_stuck_after_seconds),
            limit=settings.sweeper_batch_size,
        )
