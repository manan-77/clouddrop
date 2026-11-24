"""Runs the text stages again for files that are already processed.

Needed after a change to how text is chunked or embedded: existing files keep what they were
processed with until this runs. Only the extract and embed stages are repeated (the object has not
changed, so it is not scanned again). While a file is processed again it is not `ready`, so it
drops out of search for a moment.

    python -m app.worker.reprocess
"""

import logging
import uuid

from sqlalchemy.orm import Session

from app.db import models as all_models  # noqa: F401  (a script must know every table)
from app.db.session import get_sessionmaker
from app.modules.processing.dispatcher import ProcessingDispatcher, get_dispatcher
from app.modules.processing.repository import PipelineRepository

logger = logging.getLogger(__name__)

BATCH_SIZE = 100


def reprocess_ready_files(session: Session, dispatcher: ProcessingDispatcher) -> int:
    """Queues every ready file for chunking and embedding again; returns how many."""
    repo = PipelineRepository(session)
    queued = 0
    last: uuid.UUID | None = None
    while True:
        version_ids = repo.ready_version_ids(last, BATCH_SIZE)
        if not version_ids:
            return queued
        for version_id in version_ids:
            repo.reset_text_stages(version_id)
        # Commit before queueing: a task that starts early must see the reset.
        session.commit()
        for version_id in version_ids:
            dispatcher.enqueue(version_id)
        queued += len(version_ids)
        last = version_ids[-1]


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    with get_sessionmaker()() as session:
        queued = reprocess_ready_files(session, get_dispatcher())
    print(f"{queued} files queued for chunking and embedding again")


if __name__ == "__main__":
    main()
