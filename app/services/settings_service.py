"""Non-secret application preferences persisted to data/app_settings.json."""

from __future__ import annotations

import json
import logging
import threading
from typing import Any

from app.config import AppConfig
from app.services.prompt_service import DEFAULT_COMPANION_NAME

logger = logging.getLogger("gethu.settings")

_ALLOWED_KEYS = {"model", "companion_name"}

MAX_NAME_LENGTH = 40


class SettingsStore:
    def __init__(self, config: AppConfig) -> None:
        self.path = config.settings_path
        self._lock = threading.Lock()
        self._data: dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                self._data = {k: v for k, v in raw.items() if k in _ALLOWED_KEYS}
        except FileNotFoundError:
            self._data = {}
        except (OSError, json.JSONDecodeError):
            logger.warning("Ignoring unreadable settings file %s", self.path)
            self._data = {}

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return self._data.get(key, default)

    def update(self, values: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            for key, value in values.items():
                if key in _ALLOWED_KEYS and value:
                    self._data[key] = value
            try:
                tmp = self.path.with_suffix(".tmp")
                tmp.write_text(json.dumps(self._data, indent=2), encoding="utf-8")
                tmp.replace(self.path)
            except OSError:  # pragma: no cover
                logger.warning("Could not persist settings to %s", self.path)
        return dict(self._data)

    @property
    def model(self) -> str | None:
        value = self.get("model")
        return str(value) if value else None

    @property
    def companion_name(self) -> str:
        """The name the user gave the character. Never blank."""
        value = self.get("companion_name")
        name = " ".join(str(value).split()) if value else ""
        return name[:MAX_NAME_LENGTH] or DEFAULT_COMPANION_NAME
