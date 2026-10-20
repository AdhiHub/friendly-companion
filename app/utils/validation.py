"""Small shared helpers: ids, timestamps and safe filenames."""

from __future__ import annotations

import re
import time
import uuid

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._ -]+")


def new_id(prefix: str = "") -> str:
    """Time-ordered, URL-safe identifier."""
    stamp = f"{int(time.time() * 1000):013x}"
    body = uuid.uuid4().hex[:16]
    return f"{prefix}{stamp}{body}"


def now_iso() -> str:
    now = time.time()
    base = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(now))
    return f"{base}.{int((now % 1) * 1000):03d}Z"


def safe_filename(name: str, fallback: str = "file") -> str:
    """Strip directory components and unsafe characters from a client filename."""
    name = name.replace("\\", "/").split("/")[-1].strip()
    name = _SAFE_NAME.sub("_", name).strip(" .")
    name = re.sub(r"\s+", " ", name)
    if not name:
        name = fallback
    if len(name) > 120:
        stem, dot, ext = name.rpartition(".")
        if dot and 0 < len(ext) <= 12:
            stem = stem[: 120 - len(ext) - 1]
            name = f"{stem}.{ext}"
        else:
            name = name[:120]
    return name


def title_from_message(message: str, limit: int = 48) -> str:
    """First non-empty line of a message, trimmed to a conversation title."""
    for line in message.splitlines():
        line = re.sub(r"\s+", " ", line).strip()
        if line:
            if len(line) > limit:
                return line[: limit - 1].rstrip() + "…"
            return line
    return "New chat"
