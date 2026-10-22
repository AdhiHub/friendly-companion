"""GeminiService streaming internals.

Regression coverage for a real bug: an SDK chunk whose `text` is empty (for
example a thinking-only part) caused the raw client object to be yielded to the
SSE layer instead of being skipped.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from app.config import AppConfig
from app.services.conversation_service import sse_frames
from app.services.gemini_service import GeminiError, GeminiService


class FakeChunk:
    """Mimics google.genai GenerateContentResponse enough for our extraction."""

    def __init__(self, text=None, parts=None, raise_on_text=False):
        self._text = text
        self.parts = parts or []
        if raise_on_text:
            # The real SDK raises when a chunk has no text part.
            type(self).text = property(lambda self: (_ for _ in ()).throw(ValueError("no text")))
        else:
            type(self).text = property(lambda self: self._text)


class TextPart:
    def __init__(self, text, thought=False):
        self.text = text
        self.thought = thought


def make_service() -> GeminiService:
    return GeminiService(AppConfig(api_key="test-key"))


def test_chunk_text_returns_plain_text():
    service = make_service()
    assert service._chunk_text(FakeChunk(text="Hey bro")) == "Hey bro"


def test_chunk_text_skips_empty_chunks():
    service = make_service()
    assert service._chunk_text(FakeChunk(text="")) == ""
    assert service._chunk_text(FakeChunk(text=None)) == ""
    assert service._chunk_text(None) == ""


def test_chunk_text_ignores_thinking_parts():
    service = make_service()
    chunk = FakeChunk(
        text=None,
        parts=[TextPart("internal reasoning", thought=True), TextPart("actual answer")],
    )
    assert service._chunk_text(chunk) == "actual answer"


def test_chunk_text_survives_sdk_raising_on_missing_text():
    service = make_service()
    chunk = FakeChunk(parts=[TextPart("recovered text")], raise_on_text=True)
    assert service._chunk_text(chunk) == "recovered text"


def test_chunk_text_never_returns_a_non_string():
    service = make_service()
    for chunk in (FakeChunk(), FakeChunk(text=123), FakeChunk(parts=[TextPart(None)])):
        assert isinstance(service._chunk_text(chunk), str)


async def test_stream_reply_never_yields_non_text_objects(monkeypatch):
    """A thinking-only chunk must be skipped, not forwarded to the SSE layer."""
    service = make_service()

    class FakeAio:
        class models:
            @staticmethod
            async def generate_content_stream(**kwargs):
                async def gen():
                    yield FakeChunk(text=None, parts=[TextPart("hmm", thought=True)])
                    yield FakeChunk(text="Hey bro!")
                return gen()

    class FakeClient:
        aio = FakeAio()

    monkeypatch.setattr(service, "_get_client", lambda: FakeClient())
    chunks = [c async for c in service.stream_reply(system="s", contents=[])]
    assert chunks == ["Hey bro!"]
    assert all(isinstance(c, str) for c in chunks)


async def test_stream_reply_reports_error_when_no_text_at_all(monkeypatch):
    service = make_service()

    class FakeAio:
        class models:
            @staticmethod
            async def generate_content_stream(**kwargs):
                async def gen():
                    yield FakeChunk(text=None, parts=[TextPart("thinking", thought=True)])
                return gen()

    class FakeClient:
        aio = FakeAio()

    monkeypatch.setattr(service, "_get_client", lambda: FakeClient())
    with_text = [c async for c in service.stream_reply(system="s", contents=[])]
    assert with_text == []  # no garbage objects, caller turns this into a clear error


async def test_missing_api_key_raises_safe_error():
    service = GeminiService(AppConfig(api_key=None))
    try:
        [c async for c in service.stream_reply(system="s", contents=[])]
    except GeminiError as err:
        assert err.kind == "missing_key"
        assert "GEMINI_API_KEY" in err.message
    else:
        raise AssertionError("expected GeminiError")


async def test_sse_frames_rejects_malformed_events_without_raising():
    async def producers():
        yield {"event": "delta", "data": {"text": "ok"}}
        yield object()  # a raw SDK object would look like this
        yield {"event": "delta", "data": {"weird": {1, 2}}}  # not JSON serialisable
        yield {"data": {"text": "no name"}}
        yield {"event": "done", "data": {"text": "bye"}}

    frames = [frame async for frame in sse_frames(producers())]
    assert len(frames) == 3
    assert all(frame.startswith("event: ") for frame in frames)
    assert json.loads(frames[0].split("data: ")[1])["text"] == "ok"
    # Non-serialisable values degrade to text rather than breaking the stream.
    assert json.loads(frames[1].split("data: ")[1])["weird"] == "{1, 2}"
    assert json.loads(frames[2].split("data: ")[1])["text"] == "bye"


# --------------------------------------------------------------- failover


class FakeServerError(Exception):
    """Mimics the SDK's 503 ServerError."""

    def __init__(self, status=503):
        super().__init__("503 UNAVAILABLE")
        self.code = status


class FakeAuthError(Exception):
    """Mimics the SDK's 401 error."""

    def __init__(self):
        super().__init__("401 API key not valid")
        self.code = 401


class FakeRateLimitError(Exception):
    """Mimics the SDK's 429 error."""

    def __init__(self):
        super().__init__("429 RESOURCE_EXHAUSTED")
        self.code = 429


def _client_for(models: dict[str, object]):
    """Build a fake client where each model name has its own behaviour.

    A behaviour is either a list of chunk texts (success) or an exception
    instance to raise.
    """
    used: list[str] = []

    class FakeAio:
        class models:
            @staticmethod
            async def generate_content_stream(**kwargs):
                name = kwargs.get("model")
                used.append(name)
                behaviour = models[name]
                if isinstance(behaviour, Exception):
                    raise behaviour

                async def gen():
                    for text in behaviour:
                        yield FakeChunk(text=text)

                return gen()

    class FakeClient:
        aio = FakeAio()

    return FakeClient(), used


def _service_with_models(monkeypatch, behaviour: dict[str, object]) -> tuple:
    service = GeminiService(
        AppConfig(
            api_key="test-key",
            model="model-a",
            fallback_models=("model-b", "model-c"),
        )
    )
    client, used = _client_for(behaviour)
    monkeypatch.setattr(service, "_get_client", lambda: client)
    # Keep the test fast: no real backoff sleeps.
    monkeypatch.setattr(service, "_backoff", lambda attempt: 0)
    return service, used


async def test_a_busy_model_falls_over_to_the_next_one(monkeypatch):
    """A 503 on the first model must not end the conversation.

    Regression: the stream-failure path retried the same model and then
    gave up, never reaching the configured fallbacks.
    """
    service, used = _service_with_models(
        monkeypatch,
        {
            "model-a": FakeServerError(),
            "model-b": ["Answer from the fallback. "],
        },
    )
    chunks = [c async for c in service.stream_reply(system="s", contents=[])]
    assert chunks == ["Answer from the fallback. "]
    assert "model-a" in used
    assert "model-b" in used

async def test_failover_keeps_going_until_a_model_works(monkeypatch):
    service, used = _service_with_models(
        monkeypatch,
        {
            "model-a": FakeServerError(),
            "model-b": FakeServerError(),
            "model-c": ["Finally. "],
        },
    )
    chunks = [c async for c in service.stream_reply(system="s", contents=[])]
    assert chunks == ["Finally. "]
    # A busy model is skipped straight away - no point asking it again.
    assert used == ["model-a", "model-b", "model-c"]


async def test_a_busy_model_is_not_asked_again(monkeypatch):
    """A 503 means that model is overloaded; asking again just wastes time."""
    service, used = _service_with_models(
        monkeypatch,
        {
            "model-a": FakeServerError(),
            "model-b": ["Second model answers. "],
        },
    )
    chunks = [c async for c in service.stream_reply(system="s", contents=[])]
    assert chunks == ["Second model answers. "]
    assert used == ["model-a", "model-b"]


async def test_a_rate_limit_retries_the_same_model(monkeypatch):
    """A 429 clears on its own, so the same model is asked again first."""
    service, used = _service_with_models(
        monkeypatch,
        {
            "model-a": FakeRateLimitError(),
            "model-b": ["Second model answers. "],
        },
    )
    chunks = [c async for c in service.stream_reply(system="s", contents=[])]
    assert chunks == ["Second model answers. "]
    # The same model was tried more than once before switching.
    assert used.count("model-a") > 1


async def test_failover_gives_up_when_every_model_fails(monkeypatch):
    service, _ = _service_with_models(
        monkeypatch,
        {
            "model-a": FakeServerError(),
            "model-b": FakeServerError(),
            "model-c": FakeServerError(),
        },
    )
    try:
        [c async for c in service.stream_reply(system="s", contents=[])]
    except GeminiError as err:
        assert err.kind == "provider"
    else:
        raise AssertionError("expected GeminiError")


async def test_an_auth_error_does_not_fail_over(monkeypatch):
    """Every model uses the same key, so another model would fail the same way."""
    service, used = _service_with_models(
        monkeypatch,
        {
            "model-a": FakeAuthError(),
            "model-b": ["Should never be reached."],
        },
    )
    try:
        [c async for c in service.stream_reply(system="s", contents=[])]
    except GeminiError as err:
        assert err.kind == "auth"
    else:
        raise AssertionError("expected GeminiError")
    assert used == ["model-a"]


async def test_failover_does_not_happen_after_text_was_sent(monkeypatch):
    """Once text has been shown, switching models would mix two replies."""
    service = GeminiService(
        AppConfig(
            api_key="test-key",
            model="model-a",
            fallback_models=("model-b",),
        )
    )
    used: list[str] = []

    class FakeAio:
        class models:
            @staticmethod
            async def generate_content_stream(**kwargs):
                name = kwargs.get("model")
                used.append(name)

                async def gen():
                    if name == "model-a":
                        yield FakeChunk(text="Partial ")
                        raise FakeServerError()
                    yield FakeChunk(text="wrong model")

                return gen()

    class FakeClient:
        aio = FakeAio()

    monkeypatch.setattr(service, "_get_client", lambda: FakeClient())
    monkeypatch.setattr(service, "_backoff", lambda attempt: 0)

    seen: list[str] = []
    try:
        async for chunk in service.stream_reply(system="s", contents=[]):
            seen.append(chunk)
    except GeminiError:
        pass  # the partial reply is reported to the user as an error
    assert seen == ["Partial "]
    assert "model-b" not in used


# --------------------------------------------------------------- timeouts


SILENT = "silent"  # a stream that opens and then never says anything


def _client_with_behaviours(behaviour: dict[str, object]):
    """A fake client where each model has its own behaviour.

    A behaviour is either a list of chunk texts (a normal answer), the
    string ``SILENT`` (opens, then goes quiet forever) or a one-item list
    ``[text, SILENT]`` (says one thing, then goes quiet).
    """
    used: list[str] = []

    class FakeAio:
        class models:
            @staticmethod
            async def generate_content_stream(**kwargs):
                name = kwargs.get("model")
                used.append(name)
                spec = behaviour[name]

                async def gen():
                    if spec == SILENT:
                        await asyncio.sleep(30)
                        yield FakeChunk(text="too late")
                        return
                    texts, silent = spec if isinstance(spec, tuple) else (spec, False)
                    for text in texts:
                        yield FakeChunk(text=text)
                    if silent:
                        await asyncio.sleep(30)
                        yield FakeChunk(text="too late")

                return gen()

    class FakeClient:
        aio = FakeAio()

    return FakeClient(), used


async def test_a_silent_stream_times_out_and_fails_over(monkeypatch):
    """A model that opens a stream and never answers must not hang the app."""
    service = GeminiService(
        AppConfig(
            api_key="test-key",
            model="model-a",
            fallback_models=("model-b",),
            stream_timeout=0.05,
        )
    )
    client, used = _client_with_behaviours(
        {"model-a": SILENT, "model-b": ["Second model answers. "]}
    )
    monkeypatch.setattr(service, "_get_client", lambda: client)
    monkeypatch.setattr(service, "_backoff", lambda attempt: 0)

    chunks = [c async for c in service.stream_reply(system="s", contents=[])]
    assert chunks == ["Second model answers. "]
    # The silent model was abandoned rather than waited on.
    assert used == ["model-a", "model-b"]


async def test_a_silent_stream_reports_a_timeout(monkeypatch):
    """With no fallback the user gets a clear message instead of a hang."""
    service = GeminiService(
        AppConfig(
            api_key="test-key",
            model="model-a",
            fallback_models=(),
            stream_timeout=0.05,
        )
    )
    client, _ = _client_with_behaviours({"model-a": SILENT})
    monkeypatch.setattr(service, "_get_client", lambda: client)

    with pytest.raises(GeminiError) as excinfo:
        [c async for c in service.stream_reply(system="s", contents=[])]
    assert excinfo.value.kind == "network"
    assert "too long" in excinfo.value.message


async def test_text_was_shown_so_a_silent_stream_is_not_retried(monkeypatch):
    """Retrying after a partial reply would send the same text twice."""
    service = GeminiService(
        AppConfig(
            api_key="test-key",
            model="model-a",
            fallback_models=("model-b",),
            stream_timeout=0.05,
        )
    )
    client, used = _client_with_behaviours(
        {"model-a": (["Partial "], True), "model-b": ["Should not be reached. "]}
    )
    monkeypatch.setattr(service, "_get_client", lambda: client)

    seen: list[str] = []
    with pytest.raises(GeminiError):
        async for chunk in service.stream_reply(system="s", contents=[]):
            seen.append(chunk)
    assert seen == ["Partial "]
    assert "model-b" not in used
