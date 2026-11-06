import logging
import uuid

from kombu.exceptions import OperationalError

from app.worker.celery_app import celery_app

logger = logging.getLogger(__name__)

PROCESS_TASK = "processing.process_file_version"


class ProcessingDispatcher:
    """Hands a file version to the worker. Ids only: tasks re-read their own state."""

    def enqueue(self, file_version_id: uuid.UUID) -> None:
        try:
            celery_app.send_task(PROCESS_TASK, args=[str(file_version_id)])
        except (OperationalError, OSError):
            # The broker is down. The upload still succeeded; the sweeper re-enqueues the file.
            logger.warning("Could not enqueue processing for version %s", file_version_id)


def get_dispatcher() -> ProcessingDispatcher:
    return ProcessingDispatcher()
