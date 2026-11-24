import logging
import uuid

from celery import Celery
from kombu.exceptions import OperationalError

from app.worker.celery_app import celery_app

logger = logging.getLogger(__name__)

GENERATE_TASK = "summaries.generate_summary"


class SummaryDispatcher:
    """Hands a file version to the worker to be summarised. Ids only."""

    def __init__(self, app: Celery | None = None) -> None:
        self.app = app or celery_app

    def enqueue(self, file_version_id: uuid.UUID) -> None:
        try:
            self.app.send_task(GENERATE_TASK, args=[str(file_version_id)])
        except (OperationalError, OSError):
            # The broker is down. The request stays pending and the sweeper sends it again.
            logger.warning("Could not enqueue a summary for version %s", file_version_id)


def get_summary_dispatcher() -> SummaryDispatcher:
    return SummaryDispatcher()
