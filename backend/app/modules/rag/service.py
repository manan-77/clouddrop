import logging
import uuid
from collections.abc import Iterator
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.ai import chat as chat_module
from app.ai.chat import ChatStream, ChatUnavailableError, max_prompt_tokens, prompt_token_budget
from app.core.config import Settings
from app.core.errors import UnprocessableError
from app.modules.rag.prompts import NOT_FOUND_ANSWER, Prompt, build_prompt, cited_labels
from app.modules.rag.schemas import Citation, DoneEvent, ErrorEvent, TokenEvent
from app.modules.search.repository import ChunkMatch
from app.modules.search.service import SearchService

logger = logging.getLogger(__name__)


def _event(event: TokenEvent | DoneEvent | ErrorEvent) -> bytes:
    return b"data: " + event.model_dump_json().encode() + b"\n\n"


@dataclass
class Answer:
    """An answer that is ready to stream. `stream` is None when nothing relevant was found."""

    stream: ChatStream | None
    sources: dict[str, ChunkMatch]

    def close(self) -> None:
        "Cancels the model request. Safe to call again; also needed when `events` never started."
        if self.stream is not None:
            self.stream.close()

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
        matches = self.search.matching_chunks(
            user_id, question, self.settings.rag_max_chunks, only_file_id=file_id
        )
        # Release the database connection now: the answer may stream for a long time.
        self.session.commit()
        if not matches:
            return Answer(None, {})
        prompt = self._fit(question, matches)
        # Looked up at call time so tests can replace it.
        return Answer(chat_module.get_chat_client().stream(prompt.messages), prompt.sources)

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
