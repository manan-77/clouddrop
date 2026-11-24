import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.ai.chat import ChatClient, ChatUnavailableError
from app.core.config import Settings
from app.core.errors import ConflictError, NotFoundError
from app.modules.processing.repository import PipelineRepository
from app.modules.storage.constants import FileStatus
from app.modules.storage.models import File
from app.modules.summaries.dispatcher import SummaryDispatcher
from app.modules.summaries.generate import SummaryFailure, summarise
from app.modules.summaries.models import FileSummary
from app.modules.summaries.prompts import PROMPT_VERSION
from app.modules.summaries.repository import SummaryRepository

logger = logging.getLogger(__name__)


class SummaryUnavailable(Exception):
    "The model could not be reached; the task is tried again with a growing pause."


class SummaryService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.repo = SummaryRepository(session)

    # What a caller who may already read or write the file does (access is decided by FileService).

    def read(self, file: File) -> FileSummary:
        version_id = self.repo.latest_version_id(file.id)
        summary = self.repo.get(version_id) if version_id else None
        if summary is None:
            raise NotFoundError("No summary for this file yet", code="summary_not_found")
        return summary

    def request(self, file: File, dispatcher: SummaryDispatcher) -> FileSummary:
        """Asks for a new summary; asking while one is waiting does nothing more."""
        if file.status != FileStatus.READY.value:
            raise ConflictError("The file is not ready yet", code="file_not_ready")
        version_id = self.repo.latest_version_id(file.id)
        if version_id is None:  # a ready file always has a version
            raise NotFoundError("No summary for this file yet", code="summary_not_found")
        queued = self.repo.request_again(version_id, datetime.now(UTC))
        self.session.commit()
        if queued:  # after the commit: a task that starts at once must see the request
            dispatcher.enqueue(version_id)
        return self.read(file)

    # What the worker does. Ids only: the state is read from the database.

    def request_if_missing(self, version_id: uuid.UUID) -> bool:
        """After a file became ready: asks for its first summary. True when it must be queued."""
        version = PipelineRepository(self.session).get_version(version_id)
        file = (
            PipelineRepository(self.session).get_active_file(version.file_id) if version else None
        )
        if file is None or file.status != FileStatus.READY.value:
            return False
        created = self.repo.ensure(version_id, datetime.now(UTC))
        self.session.commit()
        return created

    def generate(self, version_id: uuid.UUID, chat: ChatClient) -> None:
        """Writes the summary for a waiting request. Safe to run twice: only a waiting request is
        worked on, and a finished one is left alone."""
        waiting = self.repo.claim(version_id)
        if waiting is None:
            self.session.rollback()
            return
        attempts = waiting.attempts
        # The attempt is counted before the slow part, and the connection is freed during it.
        self.session.commit()
        if attempts > self.settings.summary_max_attempts:
            self._fail(version_id, "too_many_attempts")
            return
        chunks = [text for _, text in PipelineRepository(self.session).chunk_texts(version_id)]
        self.session.commit()
        try:
            result = summarise(chat, chunks, self.settings)
        except SummaryFailure as failure:
            self._fail(version_id, failure.code)
            return
        except ChatUnavailableError as unavailable:
            if attempts >= self.settings.summary_max_attempts:
                self._fail(version_id, "chat_unavailable")
                return
            raise SummaryUnavailable from unavailable
        self.repo.finish(
            version_id,
            result.draft,
            partial=result.partial,
            model=self.settings.chat_model,
            prompt_version=PROMPT_VERSION,
            now=datetime.now(UTC),
        )
        self.session.commit()

    def sweep(self, dispatcher: SummaryDispatcher) -> int:
        """Asks for summaries nobody asked for, and sends again those nobody picked up."""
        now = datetime.now(UTC)
        limit = self.settings.summary_sweep_batch_size
        created = [
            version_id
            for version_id in self.repo.ready_versions_without_request(limit)
            if self.repo.ensure(version_id, now)
        ]
        stale = self.repo.stale_requests(
            now - timedelta(seconds=self.settings.summary_stale_seconds), limit
        )
        self.repo.touch(stale, now)  # so the next sweep takes other requests, not these again
        self.session.commit()
        for version_id in [*created, *stale]:
            dispatcher.enqueue(version_id)
        queued = len(created) + len(stale)
        if queued:
            logger.info("Summary sweeper queued %d versions", queued)
        return queued

    def _fail(self, version_id: uuid.UUID, code: str) -> None:
        logger.warning("Summary failed: %s", code)
        self.repo.fail(version_id, code)
        self.session.commit()
