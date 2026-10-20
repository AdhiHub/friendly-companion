"""GeminiService streaming internals.

Regression coverage for a real bug: an SDK chunk whose `text` is empty (for
example a thinking-only part) caused the raw client object to be yielded to the
SSE layer instead of being skipped.
"""

from __future__ import annotations

import json

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
