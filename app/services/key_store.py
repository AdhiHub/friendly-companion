"""Runtime management of the Gemini API key.

The key normally arrives from the environment or `.env` at startup. This store
also lets it be replaced from the web UI: a key set in the browser is written
back to `.env` so it survives a restart and keeps the command-line workflow
working.

The key is never logged and never returned to the frontend.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

logger = logging.getLogger("companion.keys")

_KEY_LINE = re.compile(r"^\s*(?:export\s+)?GEMINI_API_KEY\s*=.*$", re.MULTILINE)

MIN_KEY_LENGTH = 20
MAX_KEY_LENGTH = 200


class ApiKeyError(Exception):
    """The supplied key is not usable. Carries a user-facing message."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def normalise_key(raw: str) -> str:
    """Trim and sanity-check a user-supplied key.

    Rejects the obviously wrong early so the user gets a clear message
    instead of a confusing authentication error from the provider.
    """
    key = (raw or "").strip()
    if not key:
        raise ApiKeyError("Paste your Gemini API key to continue.")
    if len(key) < MIN_KEY_LENGTH:
        raise ApiKeyError(
            "That key looks too short. Copy the whole key from AI Studio."
        )
    if len(key) > MAX_KEY_LENGTH:
        raise ApiKeyError("That key is too long to be a Gemini API key.")
    if any(ch.isspace() for ch in key):
        raise ApiKeyError(
            "That key contains spaces. Copy it without any extra characters."
        )
    if key.startswith(('"', "'")) and key.endswith(('"', "'")):
        key = key[1:-1].strip()
    return key


def write_key_to_env(env_file: Path, key: str) -> bool:
    """Persist `key` as GEMINI_API_KEY in `env_file`, preserving other lines.

    Returns True when the file was written. A read-only install is not fatal:
    the key still works for this session, it just will not survive a restart.
    """
    try:
        env_file.parent.mkdir(parents=True, exist_ok=True)
        text = env_file.read_text(encoding="utf-8") if env_file.exists() else ""
        line = f"GEMINI_API_KEY={key}"
        if _KEY_LINE.search(text):
            text = _KEY_LINE.sub(line, text, count=1)
        else:
            if text and not text.endswith("\n"):
                text += "\n"
            text += line + "\n"
        env_file.write_text(text, encoding="utf-8")
        # The file holds a secret: keep it owner-only.
        try:
            env_file.chmod(0o600)
        except OSError:  # pragma: no cover - not every filesystem supports it
            pass
        return True
    except OSError:
        logger.warning("Could not persist the API key to %s", env_file)
        return False


class KeyStore:
    """Holds the active Gemini API key and can replace it at runtime."""

    def __init__(self, initial: str | None = None, env_file: Path | None = None) -> None:
        self._key = (initial or "").strip() or None
        self._env_file = env_file
        self._from_runtime = False

    @property
    def key(self) -> str | None:
        return self._key

    @property
    def configured(self) -> bool:
        return bool(self._key)

    @property
    def from_runtime(self) -> bool:
        """True when the key was supplied through the UI rather than the env."""
        return self._from_runtime

    def set(self, raw_key: str) -> str:
        """Validate, activate and persist a new key. Returns the stored key."""
        key = normalise_key(raw_key)
        self._key = key
        self._from_runtime = True
        if self._env_file is not None:
            write_key_to_env(self._env_file, key)
        return key

    def clear(self) -> None:
        """Forget the key and remove it from the persisted env file."""
        self._key = None
        self._from_runtime = False
        if self._env_file is None:
            return
        try:
            if not self._env_file.exists():
                return
            text = self._env_file.read_text(encoding="utf-8")
            if not _KEY_LINE.search(text):
                return
            cleaned = _KEY_LINE.sub("GEMINI_API_KEY=", text, count=1)
            self._env_file.write_text(cleaned, encoding="utf-8")
        except OSError:  # pragma: no cover - best effort
            logger.warning("Could not clear the API key from %s", self._env_file)
