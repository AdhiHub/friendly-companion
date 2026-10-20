"""Shared fixtures: isolated app instance, test client, fake Gemini provider."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.config import AppConfig
from app.main import create_app
from app.services.gemini_service import GeminiError


class FakeGemini:
    """Stands in for GeminiService.stream_reply — no network, no key."""

    def __init__(self, chunks: tuple[str, ...] = ("Hey bro, ", "sollu!"), error=None) -> None:
        self.chunks = chunks
        self.error = error
        self.available = True
        self.calls: list[dict] = []

    async def stream_reply(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        for chunk in self.chunks:
            yield chunk


@pytest.fixture()
def config(tmp_path) -> AppConfig:
    data = tmp_path / "data"
    return AppConfig(
        api_key="test-key",
        model="gemini-3.5-flash",
        data_dir=data,
        uploads_dir=data / "uploads",
    )


@pytest.fixture()
def app(config: AppConfig):
    return create_app(config)


@pytest.fixture()
def client(app) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def fake_gemini(app) -> FakeGemini:
    fake = FakeGemini()
    app.state.chat_service.gemini = fake
    return fake


@pytest.fixture()
def read_sse():
    """Parse an SSE body into [(event, data), ...]."""

    def _read(body: str) -> list[tuple[str, dict]]:
        events: list[tuple[str, dict]] = []
        for frame in body.split("\n\n"):
            frame = frame.strip()
            if not frame:
                continue
            name = "message"
            data = ""
            for line in frame.split("\n"):
                if line.startswith("event:"):
                    name = line[6:].strip()
                elif line.startswith("data:"):
                    data += line[5:].strip()
            if data:
                import json

                events.append((name, json.loads(data)))
        return events

    return _read


@pytest.fixture()
def png_bytes() -> bytes:
    return b"\x89PNG\r\n\x1a\n" + b"0" * 64


@pytest.fixture()
def pdf_bytes() -> bytes:
    return b"%PDF-1.4\n" + b"0" * 64


__all__ = ["FakeGemini", "GeminiError"]
