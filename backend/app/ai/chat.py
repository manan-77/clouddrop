"""Chat answers from a local Ollama server, streamed, behind one small interface.

Everything that talks to the chat model goes through here. Prompts and answers are document and
user text: they are never logged, never put in an exception message, only counted (docs/adr/0015).
"""

import json
import logging
import re
import threading
import time
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol

import httpx2 as httpx

from app.core.config import Settings, get_settings
from app.core.errors import ServiceUnavailableError

logger = logging.getLogger(__name__)

Role = Literal["system", "user", "assistant"]

# Chat-template markers around each message and around the whole prompt (measured: 8 tokens for a
# single user message). Generous on purpose.
MESSAGE_OVERHEAD_TOKENS = 16
PROMPT_OVERHEAD_TOKENS = 16
# The longest a server may ask us to wait before a retry.
MAX_RETRY_WAIT_SECONDS = 10.0
_LONE_SURROGATES = re.compile("[\ud800-\udfff]")
# One streamed line is a few tokens; a line this long means something is wrong, not a long answer.
MAX_LINE_BYTES = 1024 * 1024


@dataclass(frozen=True)
class ChatMessage:
    role: Role
    content: str


@dataclass
class ChatUsage:
    "Counts only, never content. Filled in when the stream finishes."

    prompt_tokens: int = 0
    completion_tokens: int = 0
    # True when the model stopped at the output limit instead of finishing its answer.
    cut_off: bool = False


class ChatUnavailableError(ServiceUnavailableError):
    code = "chat_unavailable"
    message = "The assistant is unavailable right now"


class PromptTooLargeError(Exception):
    "The prompt cannot fit the model's window. Callers trim what they send; this is the backstop."

    def __init__(self, budget: int, needed: int | None = None) -> None:
        # `needed` is unknown when the server (not our own check) refused the prompt.
        detail = f"needs up to {needed} tokens, " if needed is not None else "does not fit; "
        super().__init__(f"the prompt {detail}the budget is {budget}")
        self.needed = needed
        self.budget = budget


class ChatStream(Protocol):
    usage: ChatUsage

    def __iter__(self) -> Iterator[str]: ...

    def close(self) -> None: ...


class ChatClient(Protocol):
    def stream(self, messages: Sequence[ChatMessage]) -> ChatStream: ...


def prompt_token_budget(settings: Settings) -> int:
    return settings.chat_num_ctx - settings.chat_max_output_tokens


def max_prompt_tokens(messages: Sequence[ChatMessage]) -> int:
    """An upper bound on the prompt's tokens, never an estimate that can come out low.

    The tokenizer is byte-level, so it never produces more tokens than UTF-8 bytes. Characters per
    token measured 5 for English prose but 1.0 for ids, hashes and Hindi, so a ratio would let an
    id-heavy prompt overflow. The price is that English is counted about 5x too high.
    """
    # surrogatepass: a lone surrogate counts as 3 bytes, the size of U+FFFD, which is what is sent.
    body = sum(len(message.content.encode("utf-8", errors="surrogatepass")) for message in messages)
    return body + MESSAGE_OVERHEAD_TOKENS * len(messages) + PROMPT_OVERHEAD_TOKENS


def check_prompt_fits(messages: Sequence[ChatMessage], settings: Settings) -> None:
    needed, budget = max_prompt_tokens(messages), prompt_token_budget(settings)
    if needed > budget:
        raise PromptTooLargeError(budget, needed)


class OllamaStream:
    """The answer as it is generated. Iterate for text; `close()` cancels the request.

    An object with an explicit close (not a bare generator): a generator that never started never
    runs its cleanup, and a cancelled answer must stop the model working.
    """

    def __init__(self, response: httpx.Response, settings: Settings) -> None:
        self.usage = ChatUsage()
        self._response = response
        self._settings = settings

    def __iter__(self) -> Iterator[str]:
        try:
            for line in _lines(self._response):
                if not line:
                    continue
                data = _parse(line)
                content = _content(data)
                if content:
                    yield content
                if data.get("done") is True:
                    self._finish(data)
                    return
            raise ChatUnavailableError  # the connection ended before the model said it was done
        except (httpx.TransportError, httpx.StreamError) as exc:  # StreamError: iterated twice
            raise ChatUnavailableError from exc
        finally:
            self.close()

    def close(self) -> None:
        self._response.close()

    def _finish(self, data: dict[str, Any]) -> None:
        # In place: a caller may already hold `usage` from before the first token.
        self.usage.prompt_tokens = _count(data.get("prompt_eval_count"))
        self.usage.completion_tokens = _count(data.get("eval_count"))
        self.usage.cut_off = data.get("done_reason") == "length"
        logger.info(
            "Chat finished: prompt_tokens=%d completion_tokens=%d cut_off=%s",
            self.usage.prompt_tokens,
            self.usage.completion_tokens,
            self.usage.cut_off,
        )
        if self.usage.prompt_tokens > prompt_token_budget(self._settings):
            logger.warning("Chat prompt was larger than its budget; the answer may be unreliable")


def _lines(response: httpx.Response) -> Iterator[str]:
    """Splits the body on newline bytes only.

    `iter_lines()` also splits on U+0085, U+2028 and other Unicode separators, which Ollama writes
    raw inside JSON strings: one valid line would arrive as two broken ones. Lines are decoded
    whole, so a character split across network chunks is never cut.
    """
    buffer = b""
    for chunk in response.iter_bytes():
        buffer += chunk
        while (end := buffer.find(b"\n")) != -1:
            line, buffer = buffer[:end], buffer[end + 1 :]
            yield _decode(line)
        if len(buffer) > MAX_LINE_BYTES:
            raise ChatUnavailableError
    if buffer.strip():
        yield _decode(buffer)  # a last line without its newline


def _decode(line: bytes) -> str:
    try:
        return line.decode("utf-8").strip()
    except UnicodeDecodeError:
        raise ChatUnavailableError from None


def _parse(line: str) -> dict[str, Any]:
    try:
        data = json.loads(line)
    except ValueError:
        # `from None`: the decode error holds the whole line, which is answer text.
        raise ChatUnavailableError from None
    # An {"error": ...} line is the server failing mid-answer; its text is not shown or logged.
    if not isinstance(data, dict) or "error" in data:
        raise ChatUnavailableError
    return data


def _content(data: dict[str, Any]) -> str:
    message = data.get("message")
    if message is None:
        return ""
    content = message.get("content", "") if isinstance(message, dict) else None
    if not isinstance(content, str):
        raise ChatUnavailableError
    return content


def _count(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


class OllamaChatClient:
    def __init__(
        self,
        settings: Settings,
        http: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.settings = settings
        self._sleep = sleep
        # One pooled client for the process, with explicit timeouts on every call.
        self.http = http or httpx.Client(
            base_url=settings.ollama_base_url,
            timeout=httpx.Timeout(
                connect=settings.chat_connect_timeout_seconds,
                read=settings.chat_read_timeout_seconds,
                write=settings.chat_connect_timeout_seconds,
                pool=settings.chat_connect_timeout_seconds,
            ),
            limits=httpx.Limits(max_connections=settings.chat_max_connections),
        )

    def stream(self, messages: Sequence[ChatMessage]) -> OllamaStream:
        if not messages:
            raise ValueError("a chat needs at least one message")
        # Text that cannot be encoded (a lone surrogate) is sent as the replacement character.
        messages = [ChatMessage(m.role, _sendable(m.content)) for m in messages]
        check_prompt_fits(messages, self.settings)  # before any network call
        payload = {
            "model": self.settings.chat_model,
            "stream": True,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "options": {
                "num_ctx": self.settings.chat_num_ctx,
                "num_predict": self.settings.chat_max_output_tokens,
                "temperature": self.settings.chat_temperature,
            },
        }
        return OllamaStream(self._open(payload), self.settings)

    def _open(self, payload: dict[str, Any]) -> httpx.Response:
        """Sends the request, retrying only what is safe: nothing has been produced yet, and only
        for a connection that failed or a server that says it is busy or broken. A timeout while
        waiting for the model is not retried (it would just wait again)."""
        attempts = self.settings.chat_max_attempts
        for attempt in range(1, attempts + 1):
            wait = self.settings.chat_retry_backoff_seconds * 2 ** (attempt - 1)
            try:
                response = self.http.send(
                    self.http.build_request("POST", "/api/chat", json=payload), stream=True
                )
            except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                if attempt == attempts:
                    raise ChatUnavailableError from exc
                self._sleep(wait)
                continue
            except httpx.TransportError as exc:
                raise ChatUnavailableError from exc
            if response.status_code == 200:
                return response
            status, retry_after = response.status_code, response.headers.get("Retry-After")
            try:
                too_large = status == 400 and _says_context_overflow(response)
            finally:
                response.close()  # whatever reading the error body did
            if too_large:
                raise PromptTooLargeError(prompt_token_budget(self.settings))
            if status != 429 and status < 500:
                raise ChatUnavailableError  # for example the model is not installed
            if attempt == attempts:
                raise ChatUnavailableError
            self._sleep(_retry_wait(retry_after, wait))
        raise ChatUnavailableError  # unreachable: the loop returns or raises


def _sendable(text: str) -> str:
    return _LONE_SURROGATES.sub("\ufffd", text)


def _says_context_overflow(response: httpx.Response) -> bool:
    try:
        body = response.read().decode("utf-8", errors="replace")
    except httpx.HTTPError:  # transport failure or an undecodable body
        return False
    return "context size" in body


def _retry_wait(retry_after: str | None, default: float) -> float:
    try:
        wait = float(retry_after) if retry_after else default
    except ValueError:
        return default
    # A negative or NaN value (sleep would raise) falls back to the default.
    return min(wait, MAX_RETRY_WAIT_SECONDS) if wait >= 0 else default


_client: ChatClient | None = None
_client_lock = threading.Lock()


def get_chat_client() -> ChatClient:
    "The shared client (created on first use; tests replace this function with a fake)."
    global _client
    with _client_lock:
        if _client is None:
            _client = OllamaChatClient(get_settings())
        return _client
