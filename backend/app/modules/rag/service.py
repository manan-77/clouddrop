import functools
import logging
import threading
import uuid
import weakref
from collections.abc import Callable, Iterator

from sqlalchemy.orm import Session

from app.ai import chat as chat_module
from app.ai.chat import (
    ChatStream,
    ChatUnavailableError,
    PromptTooLargeError,
    max_prompt_tokens,
    prompt_token_budget,
)
from app.core.config import Settings
from app.core.errors import TooManyRequestsError, UnprocessableError
from app.modules.rag.prompts import NOT_FOUND_ANSWER, Prompt, build_prompt, cited_labels
from app.modules.rag.schemas import Citation, DoneEvent, ErrorEvent, TokenEvent
from app.modules.search.repository import ChunkMatch
from app.modules.search.service import SearchService

logger = logging.getLogger(__name__)


def _event(event: TokenEvent | DoneEvent | ErrorEvent) -> bytes:
    return b"data: " + event.model_dump_json().encode() + b"\n\n"


class _InProgress:
    """Answers running per user, in this process: each holds a server thread while it streams.

    The request rate limit counts starts, so on its own it would let one user hold dozens of
    long answers open and starve everyone else of threads.
    """

    def __init__(self) -> None:
        # Re-entrant: a finalizer that runs during garbage collection on a thread already holding
        # the lock must be able to release a slot instead of deadlocking.
        self._lock = threading.RLock()
        self._counts: dict[uuid.UUID, int] = {}

    def acquire(self, user_id: uuid.UUID, limit: int) -> bool:
        with self._lock:
            running = self._counts.get(user_id, 0)
            if running >= limit:
                return False
            self._counts[user_id] = running + 1
            return True

    def release(self, user_id: uuid.UUID) -> None:
        with self._lock:
            remaining = self._counts.get(user_id, 0) - 1
            if remaining > 0:
                self._counts[user_id] = remaining
            else:
                self._counts.pop(user_id, None)


_in_progress = _InProgress()
# What a rejected caller is told to wait; an answer takes seconds, not minutes, on this model.
BUSY_RETRY_AFTER_SECONDS = 5


def _cleanup(stream: ChatStream | None, release: Callable[[], None]) -> None:
    try:
        if stream is not None:
            stream.close()
    finally:
        release()


class Answer:
    """An answer that is ready to stream. `stream` is None when nothing relevant was found."""

    def __init__(
        self,
        stream: ChatStream | None,
        sources: dict[str, ChunkMatch],
        release: Callable[[], None] = lambda: None,
    ) -> None:
        self.stream = stream
        self.sources = sources
        # Runs once: from close(), or when this object is garbage collected without ever being
        # closed (a client that vanished before the response started). The arguments must not
        # refer back to `self`, or it could never be collected.
        self._cleanup = weakref.finalize(self, _cleanup, stream, release)

    def close(self) -> None:
        "Cancels the model request and frees the user's slot. Safe to call again."
        self._cleanup()

    def events(self) -> Iterator[bytes]:
        """Server-sent events: `token` pieces, then `done` with the verified sources.

        A failure after the answer has started becomes an `error` event (the status line has
        already gone). The model request is always closed, including when the client goes away.
        """
        stream = self.stream
        try:
            if stream is None:
                yield _event(TokenEvent(text=NOT_FOUND_ANSWER))
                yield _event(DoneEvent(citations=[]))
                return
            parts: list[str] = []
            try:
                for piece in stream:
                    parts.append(piece)
                    yield _event(TokenEvent(text=piece))
            except ChatUnavailableError:
                # The code only: the failure has no text worth keeping and none is safe to log.
                logger.warning("Answer stream failed: %s", ChatUnavailableError.code)
                yield _event(ErrorEvent(code=ChatUnavailableError.code))
                return
            citations = [
                Citation(
                    label=label,
                    file_id=self.sources[label].file_id,
                    file_name=self.sources[label].file_name,
                    chunk_id=self.sources[label].chunk_id,
                    page=self.sources[label].page,
                )
                for label in cited_labels("".join(parts), self.sources)
            ]
            yield _event(DoneEvent(citations=citations, cut_off=stream.usage.cut_off))
        finally:
            self.close()


class RagService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.search = SearchService(session, settings)

    def start(self, user_id: uuid.UUID, question: str, file_id: uuid.UUID | None = None) -> Answer:
        """Finds what the caller may read, builds the prompt and opens the model request.

        Everything that can fail with a proper HTTP status happens here, before any byte is
        streamed. Nothing relevant means no model call at all.
        """
        if not _in_progress.acquire(user_id, self.settings.rag_max_concurrent_per_user):
            raise TooManyRequestsError(BUSY_RETRY_AFTER_SECONDS)
        release = functools.partial(_in_progress.release, user_id)
        try:
            matches = self.search.matching_chunks(
                user_id, question, self.settings.rag_max_chunks, only_file_id=file_id
            )
            # Release the database connection now: the answer may stream for a long time.
            self.session.commit()
            if not matches:
                return Answer(None, {}, release)
            prompt = self._fit(question, matches)
            try:
                # Looked up at call time so tests can replace it.
                stream = chat_module.get_chat_client().stream(prompt.messages)
            except PromptTooLargeError:
                # The server judged the prompt too big although our own bound said it fits.
                raise UnprocessableError(
                    "Please ask a shorter question", code="question_too_long"
                ) from None
            return Answer(stream, prompt.sources, release)
        except BaseException:
            release()  # nothing is streaming, so nothing else will free the slot
            raise

    def _fit(self, question: str, matches: list[ChunkMatch]) -> Prompt:
        "As many of the best chunks as the prompt budget allows (a bound, never an estimate)."
        budget = prompt_token_budget(self.settings)
        chosen: list[ChunkMatch] = []
        for match in matches:
            if max_prompt_tokens(build_prompt(question, [*chosen, match]).messages) <= budget:
                chosen.append(match)
        if not chosen:
            raise UnprocessableError(
                "Please ask a shorter question about this file", code="question_too_long"
            )
        return build_prompt(question, chosen)
