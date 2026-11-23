"""The Ollama client, run against a fake Ollama that can stall, split lines, fail and lie."""

import json
import logging
import os
from collections.abc import Callable, Iterator

import httpx2 as httpx
import pytest
from pydantic import ValidationError

from app.ai.chat import (
    ChatMessage,
    ChatUnavailableError,
    OllamaChatClient,
    PromptTooLargeError,
    check_prompt_fits,
    max_prompt_tokens,
    prompt_token_budget,
)
from app.core.config import Settings, get_settings

SYSTEM = ChatMessage("system", "Answer only from the context.")
ASK = ChatMessage("user", "When is the invoice due? SECRET-QUESTION")


def _line(content: str = "", done: bool = False, **extra: object) -> bytes:
    body = {"message": {"role": "assistant", "content": content}, "done": done, **extra}
    return json.dumps(body).encode() + b"\n"


FINISH = _line("", True, done_reason="stop", prompt_eval_count=41, eval_count=7)


class Stream(httpx.SyncByteStream):
    "A response body that records whether it was closed and can fail part way."

    def __init__(self, parts: list[bytes], then: Exception | None = None) -> None:
        self.parts = parts
        self.then = then
        self.closed = False

    def __iter__(self) -> Iterator[bytes]:
        yield from self.parts
        if self.then:
            raise self.then

    def close(self) -> None:
        self.closed = True


class FakeOllama:
    def __init__(self, *replies: Callable[[httpx.Request], httpx.Response | Exception]) -> None:
        self.replies = list(replies)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        reply = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        result = reply(request)
        if isinstance(result, Exception):
            raise result
        return result


def ok(*parts: bytes, then: Exception | None = None) -> Callable[..., httpx.Response]:
    return lambda request: httpx.Response(200, stream=Stream(list(parts), then))


def status(code: int, body: bytes = b"", **headers: str) -> Callable[..., httpx.Response]:
    return lambda request: httpx.Response(code, content=body, headers=headers)


def raises(error: Exception) -> Callable[..., Exception]:
    return lambda request: error


def settings(**changes: object) -> Settings:
    return get_settings().model_copy(update={"chat_retry_backoff_seconds": 0.5, **changes})


def client_for(
    server: FakeOllama, sleeps: list[float] | None = None, **changes: object
) -> OllamaChatClient:
    http = httpx.Client(transport=httpx.MockTransport(server), base_url="http://ollama.test")
    record = sleeps if sleeps is not None else []
    return OllamaChatClient(settings(**changes), http=http, sleep=record.append)


def collect(client: OllamaChatClient, *messages: ChatMessage) -> tuple[str, "object"]:
    stream = client.stream(messages or (SYSTEM, ASK))
    text = "".join(stream)
    return text, stream.usage


class TestStreaming:
    def test_textArrivesInOrder_andUsageIsFilledWhenTheModelIsDone(self) -> None:
        server = FakeOllama(ok(_line("Due "), _line("on "), _line("5 March."), FINISH))
        text, usage = collect(client_for(server))
        assert text == "Due on 5 March."
        assert (usage.prompt_tokens, usage.completion_tokens, usage.cut_off) == (41, 7, False)  # type: ignore[attr-defined]

    def test_theRequestCarriesTheConfiguredModelAndLimits_andNoThinkSwitch(self) -> None:
        server = FakeOllama(ok(FINISH))
        collect(
            client_for(
                server,
                chat_model="m",
                chat_num_ctx=4096,
                chat_max_output_tokens=300,
                chat_temperature=0.2,
            )
        )
        request = server.requests[0]
        body = json.loads(request.content)
        assert (request.method, request.url.path) == ("POST", "/api/chat")
        assert body["model"] == "m" and body["stream"] is True
        assert body["options"] == {"num_ctx": 4096, "num_predict": 300, "temperature": 0.2}
        assert body["messages"] == [
            {"role": "system", "content": SYSTEM.content},
            {"role": "user", "content": ASK.content},
        ]
        assert "think" not in body

    def test_aJsonLineSplitAcrossNetworkChunksIsReassembled(self) -> None:
        whole = _line("Hello there")
        server = FakeOllama(ok(whole[:10], whole[10:25], whole[25:], FINISH))
        assert collect(client_for(server))[0] == "Hello there"

    def test_theUsageObjectTakenBeforeTheFirstTokenIsTheOneThatGetsFilled(self) -> None:
        stream = client_for(FakeOllama(ok(_line("a"), FINISH))).stream((SYSTEM, ASK))
        held = stream.usage
        list(stream)
        assert held.prompt_tokens == 41 and held is stream.usage

    def test_stoppingAtTheOutputLimitIsReported(self) -> None:
        server = FakeOllama(ok(_line("cut"), _line("", True, done_reason="length", eval_count=9)))
        assert collect(client_for(server))[1].cut_off is True  # type: ignore[attr-defined]

    def test_wrongTypedCountsInTheFinalLineBecomeZero(self) -> None:
        server = FakeOllama(ok(_line("x"), _line("", True, prompt_eval_count="9", eval_count=-1)))
        usage = collect(client_for(server))[1]
        assert (usage.prompt_tokens, usage.completion_tokens) == (0, 0)  # type: ignore[attr-defined]


class TestLineSplitting:
    @pytest.mark.parametrize("separator", ["\u0085", "\u2028", "\u2029", "\x0b", "\x0c", "\x1c"])
    def test_aUnicodeLineSeparatorInsideTheAnswerDoesNotSplitTheLine(self, separator: str) -> None:
        # Go's JSON encoder writes some of these raw; iter_lines() would cut the line in two.
        raw = json.dumps(
            {"message": {"content": f"before{separator}after"}, "done": False}, ensure_ascii=False
        )
        server = FakeOllama(ok(raw.encode() + b"\n", FINISH))
        assert collect(client_for(server))[0] == f"before{separator}after"

    def test_windowsLineEndingsAndAMissingFinalNewlineAreAccepted(self) -> None:
        server = FakeOllama(ok(_line("a").rstrip(b"\n") + b"\r\n", FINISH.rstrip(b"\n")))
        assert collect(client_for(server))[0] == "a"

    def test_aCharacterSplitAcrossNetworkChunksIsDecodedWhole(self) -> None:
        whole = json.dumps({"message": {"content": "नमस्ते"}, "done": False}, ensure_ascii=False)
        data = whole.encode() + b"\n"
        cut = data.index("स".encode()) + 1  # the middle of a three-byte character
        server = FakeOllama(ok(data[:cut], data[cut:], FINISH))
        assert collect(client_for(server))[0] == "नमस्ते"

    def test_aLineThatNeverEndsIsRefused_notBufferedForever(self) -> None:
        server = FakeOllama(ok(*[b"x" * 600_000] * 3))
        with pytest.raises(ChatUnavailableError):
            collect(client_for(server))

    def test_bytesThatAreNotUtf8AreUnavailable(self) -> None:
        with pytest.raises(ChatUnavailableError):
            collect(client_for(FakeOllama(ok(b"\xff\xfe\n", FINISH))))


class TestResourcesAndOddInput:
    def test_anErrorWhileReadingAnErrorBodyStillClosesTheConnection(self) -> None:
        body = Stream([], then=httpx.DecodingError("bad encoding"))
        server = FakeOllama(lambda request: httpx.Response(400, stream=body))
        with pytest.raises(ChatUnavailableError):
            client_for(server).stream((SYSTEM, ASK))
        assert body.closed

    def test_aLoneSurrogateIsSentAsTheReplacementCharacter_notACrash(self) -> None:
        server = FakeOllama(ok(_line("ok"), FINISH))
        message = ChatMessage("user", "price \ud800 total")
        assert collect(client_for(server), message)[0] == "ok"
        assert (
            json.loads(server.requests[0].content)["messages"][0]["content"] == "price \ufffd total"
        )
        assert max_prompt_tokens([message]) >= len("price  total") + 3  # counted as 3 bytes

    def test_iteratingTheSameStreamTwiceIsUnavailable_notARawRuntimeError(self) -> None:
        stream = client_for(FakeOllama(ok(_line("a"), FINISH))).stream((SYSTEM, ASK))
        assert "".join(stream) == "a"
        with pytest.raises(ChatUnavailableError):
            list(stream)


class TestPromptSize:
    def test_aPromptOverTheBudgetIsRefusedBeforeAnyRequest(self) -> None:
        server = FakeOllama(ok(FINISH))
        cfg = settings()
        too_big = ChatMessage("user", "x" * prompt_token_budget(cfg))
        with pytest.raises(PromptTooLargeError):
            client_for(server).stream((too_big,))
        assert server.requests == []

    def test_theBoundaryIsExact(self) -> None:
        cfg = settings()
        room = prompt_token_budget(cfg) - max_prompt_tokens([ChatMessage("user", "")])
        check_prompt_fits([ChatMessage("user", "x" * room)], cfg)
        with pytest.raises(PromptTooLargeError):
            check_prompt_fits([ChatMessage("user", "x" * (room + 1))], cfg)

    def test_nonAsciiTextIsCountedByBytes_soHindiCannotSlipPast(self) -> None:
        # About 1 token per character in practice, 3 bytes per character in UTF-8: the byte bound
        # is what guarantees the count can never come out low.
        text = "यह चालान पाँच मार्च तक चुकाया जाना चाहिए। " * 300
        assert max_prompt_tokens([ChatMessage("user", text)]) >= len(text)
        with pytest.raises(PromptTooLargeError):
            check_prompt_fits([ChatMessage("user", text)], settings())

    def test_whenTheServerRefusesTheContextItIsTheSameError(self) -> None:
        body = b'{"error":"request (4009 tokens) exceeds the available context size (2048 tokens)"}'
        server = FakeOllama(status(400, body))
        with pytest.raises(PromptTooLargeError):
            client_for(server).stream((SYSTEM, ASK))
        assert len(server.requests) == 1

    def test_anyOtherBadRequestIsUnavailable_notAPromptProblem(self) -> None:
        with pytest.raises(ChatUnavailableError):
            client_for(FakeOllama(status(400, b'{"error":"bad option"}'))).stream((SYSTEM, ASK))

    def test_noMessagesIsAProgrammingError(self) -> None:
        with pytest.raises(ValueError):
            client_for(FakeOllama(ok(FINISH))).stream(())


class TestRetries:
    def test_aMissingModelFailsAtOnceWithoutRetrying(self) -> None:
        server = FakeOllama(status(404, b'{"error":"model not found"}'))
        with pytest.raises(ChatUnavailableError):
            client_for(server).stream((SYSTEM, ASK))
        assert len(server.requests) == 1

    def test_aBusyServerIsRetriedWithGrowingWaits_thenSucceeds(self) -> None:
        server = FakeOllama(status(503), status(502), ok(_line("ok"), FINISH))
        sleeps: list[float] = []
        assert collect(client_for(server, sleeps))[0] == "ok"
        assert len(server.requests) == 3 and sleeps == [0.5, 1.0]

    def test_retryAfterIsHonouredButCapped(self) -> None:
        sleeps: list[float] = []
        server = FakeOllama(
            status(429, **{"Retry-After": "3"}), status(429, **{"Retry-After": "999"}), ok(FINISH)
        )
        collect(client_for(server, sleeps))
        assert sleeps == [3.0, 10.0]

    @pytest.mark.parametrize("header", ["-5", "nan", "soon"])
    def test_aNonsenseRetryAfterFallsBackToTheNormalWait(self, header: str) -> None:
        sleeps: list[float] = []
        collect(client_for(FakeOllama(status(503, **{"Retry-After": header}), ok(FINISH)), sleeps))
        assert sleeps == [0.5]

    def test_retriesStopAtTheCap(self) -> None:
        server = FakeOllama(status(503))
        with pytest.raises(ChatUnavailableError):
            client_for(server, chat_max_attempts=3).stream((SYSTEM, ASK))
        assert len(server.requests) == 3

    def test_aRefusedConnectionIsRetried(self) -> None:
        server = FakeOllama(raises(httpx.ConnectError("refused")), ok(_line("ok"), FINISH))
        assert collect(client_for(server))[0] == "ok"
        assert len(server.requests) == 2

    def test_aTimeoutWaitingForTheModelIsNotRetried(self) -> None:
        server = FakeOllama(raises(httpx.ReadTimeout("slow")))
        with pytest.raises(ChatUnavailableError):
            client_for(server).stream((SYSTEM, ASK))
        assert len(server.requests) == 1


class TestFailuresWhileStreaming:
    def test_theConnectionDroppingAfterSomeTextRaisesUnavailable_andClosesTheResponse(self) -> None:
        body = Stream([_line("part")], then=httpx.ReadError("dropped"))
        server = FakeOllama(lambda request: httpx.Response(200, stream=body))
        stream = client_for(server).stream((SYSTEM, ASK))
        iterator = iter(stream)
        assert next(iterator) == "part"
        with pytest.raises(ChatUnavailableError):
            next(iterator)
        assert body.closed

    def test_aStreamThatEndsWithoutDoneIsUnavailable_notAShortAnswer(self) -> None:
        with pytest.raises(ChatUnavailableError):
            collect(client_for(FakeOllama(ok(_line("half an ans")))))

    @pytest.mark.parametrize(
        "line",
        [b"not json\n", b'{"error":"out of memory"}\n', b"[1,2]\n", b'{"message":{"content":5}}\n'],
    )
    def test_garbageErrorsAndWrongShapesAreUnavailable(self, line: bytes) -> None:
        with pytest.raises(ChatUnavailableError):
            collect(client_for(FakeOllama(ok(line, FINISH))))

    def test_closingStopsTheRequest_evenBeforeTheFirstToken(self) -> None:
        body = Stream([_line("a"), FINISH])
        server = FakeOllama(lambda request: httpx.Response(200, stream=body))
        stream = client_for(server).stream((SYSTEM, ASK))
        stream.close()  # never iterated: a bare generator would never have cleaned up
        assert body.closed

    def test_closingHalfWayStopsTheRequest(self) -> None:
        body = Stream([_line("a"), _line("b"), FINISH])
        server = FakeOllama(lambda request: httpx.Response(200, stream=body))
        stream = client_for(server).stream((SYSTEM, ASK))
        assert next(iter(stream)) == "a"
        stream.close()
        assert body.closed


class TestPrivacy:
    def test_neitherThePromptNorTheAnswerNorTheServersErrorTextIsLogged(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.DEBUG):
            collect(client_for(FakeOllama(ok(_line("SECRET-ANSWER"), FINISH))))
            with pytest.raises(ChatUnavailableError) as raised:
                collect(client_for(FakeOllama(ok(b'{"error":"SECRET-SERVER-TEXT"}\n'))))
        assert "SECRET" not in caplog.text and "SECRET" not in repr(raised.value)
        assert "prompt_tokens=41" in caplog.text  # counts are logged

    def test_aBigPromptWarnsInTheLogsWithCountsOnly(self, caplog: pytest.LogCaptureFixture) -> None:
        server = FakeOllama(ok(_line("x"), _line("", True, prompt_eval_count=10**6)))
        with caplog.at_level(logging.WARNING):
            collect(client_for(server))
        assert "larger than its budget" in caplog.text


class TestSettings:
    def test_aWindowWithNoRoomForThePromptIsRefusedAtStartup(self) -> None:
        with pytest.raises(ValidationError):
            Settings(chat_num_ctx=2048, chat_max_output_tokens=1024)  # type: ignore[call-arg]

    def test_theSharedClientUsesTheConfiguredAddressAndTimeouts(self) -> None:
        cfg = settings(ollama_base_url="http://ollama.internal:1234")
        client = OllamaChatClient(cfg)
        assert str(client.http.base_url).startswith("http://ollama.internal:1234")
        assert client.http.timeout.read == cfg.chat_read_timeout_seconds
        assert client.http.timeout.connect == cfg.chat_connect_timeout_seconds


@pytest.mark.skipif(
    not os.environ.get("RUN_LOCAL_MODEL_TESTS"),
    reason="needs a running Ollama with the chat model; set RUN_LOCAL_MODEL_TESTS=1 to run",
)
class TestRealOllama:
    def test_itAnswersFromTheContextAndStreams(self) -> None:
        client = OllamaChatClient(get_settings())
        messages = (
            ChatMessage("system", "Answer in one short line using only the context. Cite the id."),
            ChatMessage("user", "Context: [c1] The invoice is due on 5 March.\nQuestion: When?"),
        )
        stream = client.stream(messages)
        pieces = list(stream)
        assert len(pieces) > 1 and "5 March" in "".join(pieces)
        assert stream.usage.prompt_tokens > 0 and stream.usage.completion_tokens > 0

    @pytest.mark.parametrize(
        "text",
        [
            "The quarterly invoice is due on the fifth of March. " * 30,
            "INV-2026-0042 4500.00 EUR 8f14e45f-ceea-467f-a0e6-5f1c0a2d4b11 " * 30,
            "यह चालान पाँच मार्च तक बैंक हस्तांतरण द्वारा चुकाया जाना चाहिए। " * 30,
            "发票应于三月五日前通过银行转账支付。" * 30,
        ],
    )
    def test_theByteBoundIsNeverBelowTheRealTokenCount(self, text: str) -> None:
        # Only the prompt count matters here, so the reply is kept tiny.
        client = OllamaChatClient(settings(chat_max_output_tokens=16))
        messages = (ChatMessage("user", text),)
        stream = client.stream(messages)
        list(stream)
        assert stream.usage.prompt_tokens <= max_prompt_tokens(messages)
