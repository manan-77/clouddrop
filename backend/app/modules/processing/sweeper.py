import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.modules.processing.dispatcher import ProcessingDispatcher
from app.modules.processing.pipeline import PIPELINE, RUNNABLE
from app.modules.processing.repository import PipelineRepository

logger = logging.getLogger(__name__)


def sweep_stuck_files(
    session: Session,
    dispatcher: ProcessingDispatcher,
    *,
    stuck_after: timedelta,
    limit: int,
    expected_stages: int | None = None,
) -> int:
    """Re-enqueues files whose processing stopped (lost message, crashed worker, broker outage).

    Re-running is a no-op for stages that already succeeded, so this is always safe to repeat.
    """
    repo = PipelineRepository(session)
    version_ids = repo.stuck_version_ids(
        tuple(status.value for status in RUNNABLE),
        datetime.now(UTC) - stuck_after,
        len(PIPELINE) if expected_stages is None else expected_stages,
        limit,
    )
    for version_id in version_ids:
        dispatcher.enqueue(version_id)
    if version_ids:
        logger.info("Sweeper re-enqueued %d file versions", len(version_ids))
    return len(version_ids)
