"""Google Gemini integration: one shared client, streaming, bounded retries.

All provider-specific behaviour lives here so the rest of the application only
ever sees `GeminiError` with a user-friendly message.
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import AsyncIterator
from typing import Any

from app.config import AppConfig
from app.services.key_store import KeyStore

logger = logging.getLogger("gethu.gemini")


class GeminiError(Exception):
    """Provider failure with a safe, user-facing message."""

    def __init__(self, message: str, *, kind: str = "provider") -> None:
        super().__init__(message)
        self.message = message
        self.kind = kind  # missing_key | auth | quota | rate_limit | network | model | provider


def _status_code(exc: BaseException) -> int | None:
    code = getattr(exc, "code", None)
    if isinstance(code, int):
        return code
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    return status if isinstance(status, int) else None


def _classify(exc: BaseException) -> GeminiError:
    status = _status_code(exc)
    name = type(exc).__name__.lower()
    text = str(exc).lower()

    if status in (401, 403) or "api key not valid" in text or "unauthenticated" in name:
        return GeminiError(
            "Gethu couldn't authenticate with Gemini. Check GEMINI_API_KEY in your .env file.",
            kind="auth",
        )
    if status == 429 or "resource_exhausted" in name or "rate limit" in text:
        return GeminiError(
            "Gemini is rate limiting us right now. Wait a few seconds and try again.",
            kind="rate_limit",
        )
    if status in (404, 400) and ("model" in text or "not found" in text):
        return GeminiError("That model isn't available on your API account.", kind="model")
    if status in (500, 502, 503, 504) or "unavailable" in name or "503" in text:
        return GeminiError("Gemini is temporarily unavailable. Try again shortly.", kind="provider")
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return GeminiError("Gemini took too long to respond. Try again.", kind="network")
    if isinstance(exc, ConnectionError, ) or "unreachable" in text or "connection" in text:
        return GeminiError("Couldn't reach Gemini. Check your internet connection.", kind="network")
    return GeminiError("Gemini returned an error. Try again in a moment.", kind="provider")


def _is_retryable(exc: BaseException) -> bool:
    status = _status_code(exc)
    if status in (429, 500, 502, 503, 504):
        return True
    name = type(exc).__name__.lower()
    return any(token in name for token in ("resourceexhausted", "unavailable", "internal", "deadline"))


def _is_model_problem(exc: BaseException) -> bool:
    status = _status_code(exc)
    text = str(exc).lower()
    return status == 404 or ("model" in text and ("not found" in text or "invalid" in text))


class GeminiService:
    """Streams assistant replies from Gemini with failover across model names."""

    def __init__(self, config: AppConfig, keys: "KeyStore | None" = None) -> None:
        self.config = config
        self.keys = keys
        self._client: Any = None

    # -- client ------------------------------------------------------------
    @property
    def api_key(self) -> str | None:
        """The active key: the runtime store wins over the startup config."""
        if self.keys is not None:
            return self.keys.key
        return self.config.api_key

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def _get_client(self) -> Any:
        if self._client is None:
            key = self.api_key
            if not key:
                raise GeminiError(
                    "GEMINI_API_KEY is not set. Add your key in Settings, or copy "
                    ".env.example to .env and add it there.",
                    kind="missing_key",
                )
            from google import genai  # imported lazily so tests never need the SDK

            self._client = genai.Client(api_key=key)
        return self._client

    def reset(self) -> None:
        """Drop the cached client (used when the key or settings change)."""
        self._client = None

    async def verify_key(self, key: str) -> tuple[bool, str]:
        """Check a key against Gemini. Returns (ok, message).

        Used by the web setup screen so a mistyped key is reported straight
        away rather than at the first reply. Never raises.
        """
        from google import genai

        try:
            client = genai.Client(api_key=key)
            await client.aio.models.list()
        except Exception as exc:  # noqa: BLE001 - normalised into a message
            error = _classify(exc)
            if error.kind == "auth":
                return False, "Gemini rejected that key. Copy it again from AI Studio."
            if error.kind in {"network", "rate_limit", "provider"}:
                # The key may well be fine - we could not reach Gemini to check.
                return True, "Key saved (could not verify it just now)."
            return False, error.message
        return True, "API key verified."

    # -- streaming ---------------------------------------------------------
    async def stream_reply(
        self,
        *,
        system: str,
        contents: list[Any],
        model: str | None = None,
    ) -> AsyncIterator[str]:
        """Yield assistant *text* chunks. Raises GeminiError with a safe message.

        This generator must never leak a raw SDK object: parts with no text
        (thinking blocks, safety-only parts) are skipped, and if a whole
        response yields no text the retry/model-failover path handles it.
        """
        client = self._get_client()
        candidates = self._candidate_models(model)
        last_error: GeminiError | None = None

        for index, model_name in enumerate(candidates):
            attempt = 0
            while attempt < 3:
                try:
                    stream = await self._open_stream(client, model_name, system, contents)
                except Exception as exc:  # noqa: BLE001 - normalised below
                    logger.warning(
                        "Gemini open failed on %s: %s", model_name, type(exc).__name__
                    )
                    error = _classify(exc)
                    last_error = error
                    if _is_model_problem(exc) and index < len(candidates) - 1:
                        break  # try the next configured model
                    if _is_retryable(exc) and attempt < 2:
                        attempt += 1
                        await asyncio.sleep(self._backoff(attempt))
                        continue
                    raise error from exc

                yielded = False
                try:
                    async for chunk in stream:
                        text = self._chunk_text(chunk)
                        if not text:
                            continue  # thinking / non-text part — never yield objects
                        yielded = True
                        yield text
                    return
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "Gemini stream failed on %s (yielded=%s): %s",
                        model_name,
                        yielded,
                        type(exc).__name__,
                    )
                    error = _classify(exc)
                    last_error = error
                    if not yielded and _is_retryable(exc) and attempt < 2:
                        attempt += 1
                        await asyncio.sleep(self._backoff(attempt))
                        continue
                    raise error from exc

        raise last_error or GeminiError("Gemini returned no response.", kind="provider")

    @staticmethod
    def _chunk_text(chunk: Any) -> str:
        """Extract plain text from a streamed chunk, ignoring non-text parts."""
        if chunk is None:
            return ""
        try:
            text = chunk.text
        except Exception:  # noqa: BLE001 - SDK raises when a chunk has no text part
            text = None
        if isinstance(text, str) and text:
            return text
        # Fall back to walking parts: keeps text', skips thought/signature parts.
        parts = getattr(chunk, "parts", None) or []
        collected = []
        for part in parts:
            if getattr(part, "thought", False):
                continue
            part_text = getattr(part, "text", None)
            if isinstance(part_text, str) and part_text:
                collected.append(part_text)
        return "".join(collected)


    @staticmethod
    def _backoff(attempt: int) -> float:
        return (0.75 * (2 ** (attempt - 1))) + random.uniform(0, 0.35)

    async def _open_stream(
        self, client: Any, model: str, system: str, contents: list[Any]
    ) -> AsyncIterator[Any]:
        from google.genai import types

        config = types.GenerateContentConfig(
            system_instruction=system,
            temperature=0.9,
            max_output_tokens=4096,
        )
        stream = await client.aio.models.generate_content_stream(
            model=model,
            contents=contents,
            config=config,
        )
        return stream

    def _candidate_models(self, model: str | None) -> tuple[str, ...]:
        ordered: list[str] = []
        for name in (model, self.config.model, *self.config.fallback_models):
            if name and name not in ordered:
                ordered.append(name)
        return tuple(ordered)
