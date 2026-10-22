"""Configuration parsing and validation."""

from __future__ import annotations

import pytest

from app.config import AppConfig, load_config

ENV_KEYS = [
    "GEMINI_API_KEY",
    "GEMINI_MODEL",
    "GEMINI_FALLBACK_MODELS",
    "GETHU_HOST",
    "GETHU_PORT",
    "MAX_UPLOAD_MB",
    "MAX_HISTORY_MESSAGES",
    "GEMINI_TIMEOUT",
    "LOG_LEVEL",
]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """load_dotenv writes to os.environ — isolate each test from that."""
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)



def test_defaults_when_env_missing(tmp_path):
    cfg = load_config(env_file=tmp_path / "missing.env")
    assert cfg.model == "gemini-3.5-flash"
    assert cfg.host == "127.0.0.1"
    assert cfg.port == 8000
    assert cfg.max_upload_mb == 20
    assert cfg.stream_timeout == 45.0
    assert cfg.configured is False
    assert cfg.data_dir.is_dir() and cfg.uploads_dir.is_dir()


def test_env_file_values_are_read(tmp_path):
    env = tmp_path / ".env"
    env.write_text(
        "\n".join(
            [
                "GEMINI_API_KEY=abc123",
                "GEMINI_MODEL=gemini-3.8-flash",
                "GEMINI_FALLBACK_MODELS=a-model, b-model ,,",
                "GETHU_PORT=9999",
                "MAX_UPLOAD_MB=5",
                "GEMINI_TIMEOUT=90",
                "LOG_LEVEL=weird",
            ]
        ),
        encoding="utf-8",
    )
    cfg = load_config(env_file=env)
    assert cfg.api_key == "abc123"
    assert cfg.configured is True
    assert cfg.model == "gemini-3.8-flash"
    assert cfg.fallback_models == ("a-model", "b-model")
    assert cfg.port == 9999
    assert cfg.max_upload_mb == 5
    assert cfg.stream_timeout == 90.0
    assert cfg.log_level == "INFO"  # invalid level falls back


def test_bad_numbers_are_clamped(tmp_path):
    env = tmp_path / ".env"
    env.write_text(
        "GETHU_PORT=notanumber\nMAX_UPLOAD_MB=99999\nGEMINI_TIMEOUT=nope\n",
        encoding="utf-8",
    )
    cfg = load_config(env_file=env)
    assert cfg.port == 8000
    assert cfg.max_upload_mb == 100  # upper bound
    assert cfg.stream_timeout == 45.0  # unparseable -> default


def test_stream_timeout_is_clamped(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("GEMINI_TIMEOUT=10000\n", encoding="utf-8")
    assert load_config(env_file=env).stream_timeout == 600.0
    # load_dotenv does not override an existing variable, so clear it first.
    monkeypatch.delenv("GEMINI_TIMEOUT", raising=False)
    env.write_text("GEMINI_TIMEOUT=1\n", encoding="utf-8")
    assert load_config(env_file=env).stream_timeout == 5.0


def test_candidate_models_deduplicated():
    cfg = AppConfig(model="m1", fallback_models=("m1", "m2"))
    assert cfg.candidate_models() == ("m1", "m2")


def test_upload_bytes_matches_mb():
    assert AppConfig(max_upload_mb=7).max_upload_bytes == 7 * 1024 * 1024
