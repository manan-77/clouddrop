"""Turns the text of a document into a summary, a category and tags, one model call at a time.

A short document is one call. A long one is read in parts (each summarised on its own), and the
summaries of the parts are then described together, so no prompt ever outgrows the model's window.
The work is bounded: at most `summary_max_parts` parts and `summary_time_budget_seconds`, after
which the result covers only what was read and is marked partial.
"""

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from app.ai.chat import ChatClient, ChatMessage, PromptTooLargeError
from app.core.config import Settings
from app.modules.summaries.draft import SummaryDraft, parse_draft, shorten
from app.modules.summaries.prompts import combine_messages, describe_messages, part_messages

# What a model may be asked for the same prompt before the reply is given up on.
ATTEMPTS_FOR_VALID_JSON = 2
MAX_PART_SUMMARY_CHARS = 600


class SummaryFailure(Exception):
    """The document cannot be summarised; `code` is a short machine value, safe to store."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class Generated:
    draft: SummaryDraft
    partial: bool


def make_parts(chunks: Sequence[str], part_bytes: int) -> list[str]:
    """Consecutive chunks joined into parts of at most `part_bytes` bytes (a chunk is never cut)."""
    parts: list[str] = []
    current: list[str] = []
    size = 0
    for chunk in chunks:
        cost = len(chunk.encode("utf-8")) + 2
        if current and size + cost > part_bytes:
            parts.append("\n\n".join(current))
            current, size = [], 0
        current.append(chunk)
        size += cost
    if current:
        parts.append("\n\n".join(current))
    return parts


def _complete(
    chat: ChatClient, messages: list[ChatMessage], *, json_output: bool, max_tokens: int
) -> str:
    stream = chat.stream(messages, json_output=json_output, max_output_tokens=max_tokens)
    try:
        return "".join(stream)
    finally:
        stream.close()


def _describe(chat: ChatClient, messages: list[ChatMessage], max_tokens: int) -> SummaryDraft:
    for _ in range(ATTEMPTS_FOR_VALID_JSON):
        draft = parse_draft(_complete(chat, messages, json_output=True, max_tokens=max_tokens))
        if draft is not None:
            return draft
    raise SummaryFailure("bad_output")


def summarise(
    chat: ChatClient,
    chunks: Sequence[str],
    settings: Settings,
    clock: Callable[[], float] = time.monotonic,
) -> Generated:
    """The summary of a document given as its chunks, in order. ChatUnavailableError passes up:
    the task retries it, so a model that is briefly down does not fail the summary."""
    started = clock()
    all_parts = make_parts(chunks, settings.summary_part_bytes)
    if not all_parts:
        raise SummaryFailure("no_text")
    parts = all_parts[: settings.summary_max_parts]
    partial = len(parts) < len(all_parts)
    try:
        if len(parts) == 1:
            return Generated(
                _describe(chat, describe_messages(parts[0]), settings.summary_max_output_tokens),
                partial=partial,
            )
        partials: list[str] = []
        for part in parts:
            if partials and clock() - started > settings.summary_time_budget_seconds:
                partial = True  # out of time: describe what has been read so far
                break
            partials.append(
                shorten(
                    _complete(
                        chat,
                        part_messages(part),
                        json_output=False,
                        max_tokens=settings.summary_max_output_tokens,
                    ),
                    MAX_PART_SUMMARY_CHARS,
                )
            )
        return Generated(
            _describe(chat, combine_messages(partials), settings.summary_max_output_tokens),
            partial=partial,
        )
    except PromptTooLargeError as exc:  # the configured part size does not fit the chat window
        raise SummaryFailure("prompt_too_large") from exc
