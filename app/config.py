"""Application configuration for Gethu.

Reads the `.env` file and environment variables, validates them, and exposes a
single immutable settings object. No secret is ever returned to the frontend.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
UPLOADS_DIR = DATA_DIR / "uploads"

DEFAULT_MODEL = "gemini-3.5-flash"
DEFAULT_FALLBACKS = ("gemini-3.6-flash", "gemini-3.8-flash", "gemini-flash-latest")


def _split_csv(raw: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in raw.split(",") if part.strip())


def _int_env(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.environ.get(name, "").strip()
    try:
        value = int(raw) if raw else default
    except ValueError:
        value = default
    return max(minimum, min(maximum, value))


def _float_env(name: str, default: float, minimum: float, maximum: float) -> float:
    raw = os.environ.get(name, "").strip()
    try:
        value = float(raw) if raw else default
    except ValueError:
        value = default
    return max(minimum, min(maximum, value))


@dataclass(frozen=True)
class AppConfig:
    api_key: str | None = None
    model: str = DEFAULT_MODEL
    fallback_models: tuple[str, ...] = DEFAULT_FALLBACKS
    host: str = "127.0.0.1"
    port: int = 8000
    max_upload_mb: int = 20
    max_history_messages: int = 40
    stream_timeout: float = 45.0
    log_level: str = "INFO"
    data_dir: Path = field(default_factory=lambda: DATA_DIR)
    uploads_dir: Path = field(default_factory=lambda: UPLOADS_DIR)
    env_file: Path = field(default_factory=lambda: ROOT_DIR / ".env")

    @property
    def db_path(self) -> Path:
        return self.data_dir / "gethu.db"

    @property
    def settings_path(self) -> Path:
        return self.data_dir / "app_settings.json"

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def candidate_models(self) -> tuple[str, ...]:
        """Configured model first, then fallbacks, de-duplicated and ordered."""
        seen: list[str] = []
        for name in (self.model, *self.fallback_models):
            if name and name not in seen:
                seen.append(name)
        return tuple(seen)


def load_config(env_file: Path | None = None) -> AppConfig:
    env_path = Path(env_file) if env_file else ROOT_DIR / ".env"
    load_dotenv(env_path, override=False)

    api_key = os.environ.get("GEMINI_API_KEY", "").strip() or None
    model = os.environ.get("GEMINI_MODEL", "").strip() or DEFAULT_MODEL
    fallbacks = _split_csv(os.environ.get("GEMINI_FALLBACK_MODELS", "")) or DEFAULT_FALLBACKS
    log_level = os.environ.get("LOG_LEVEL", "INFO").strip().upper()
    if log_level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        log_level = "INFO"

    config = AppConfig(
        api_key=api_key,
        model=model,
        fallback_models=fallbacks,
        host=os.environ.get("GETHU_HOST", "127.0.0.1").strip() or "127.0.0.1",
        port=_int_env("GETHU_PORT", 8000, 1, 65535),
        max_upload_mb=_int_env("MAX_UPLOAD_MB", 20, 1, 100),
        max_history_messages=_int_env("MAX_HISTORY_MESSAGES", 40, 2, 500),
        stream_timeout=_float_env("GEMINI_TIMEOUT", 45.0, 5.0, 600.0),
        log_level=log_level,
        env_file=env_path,
    )
    config.data_dir.mkdir(parents=True, exist_ok=True)
    config.uploads_dir.mkdir(parents=True, exist_ok=True)
    return config
