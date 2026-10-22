"""Logging setup: readable console output without leaking secrets."""

from __future__ import annotations

import logging
import re

_SECRET_PATTERNS = (
    re.compile(r"(x-goog-api-key\s*[:=]\s*)\S+", re.IGNORECASE),
    re.compile(r"(GEMINI_API_KEY\s*=\s*)\S+", re.IGNORECASE),
    re.compile(r"(AIza[0-9A-Za-z_\-]{20,})"),
)


class SecretRedactingFilter(logging.Filter):
    """Drop anything that looks like an API key from log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # pragma: no cover - defensive
            return True
        redacted = message
        for pattern in _SECRET_PATTERNS:
            redacted = pattern.sub(r"\1[redacted]", redacted)
        if redacted != message:
            record.msg = redacted
            record.args = ()
        return True


def configure_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    if any(getattr(h, "_companion_handler", False) for h in root.handlers):
        return
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    handler.addFilter(SecretRedactingFilter())
    handler._companion_handler = True  # type: ignore[attr-defined]
    root.addHandler(handler)
    root.setLevel(level.upper())
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
