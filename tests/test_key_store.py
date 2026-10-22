"""Runtime API key handling: validation, persistence and activation.

The web setup screen lets someone paste a Gemini key, so the rules around
accepting, storing and clearing it are security-relevant and are asserted here.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.key_store import ApiKeyError, KeyStore, normalise_key, write_key_to_env

GOOD_KEY = "AIzaSyD-ExampleKey_1234567890abcdefghij"


def test_normalise_trims_whitespace():
    assert normalise_key(f"  {GOOD_KEY}\n") == GOOD_KEY


def test_empty_key_is_rejected():
    with pytest.raises(ApiKeyError):
        normalise_key("   ")


def test_short_key_is_rejected():
    with pytest.raises(ApiKeyError):
        normalise_key("tooshort")


def test_key_with_spaces_is_rejected():
    with pytest.raises(ApiKeyError):
        normalise_key("AIza Sy D Example Key 1234567890")


def test_key_with_quotes_is_unwrapped():
    assert normalise_key(f'"{GOOD_KEY}"') == GOOD_KEY


def test_write_key_to_env_creates_the_file(tmp_path: Path):
    env = tmp_path / ".env"
    assert write_key_to_env(env, GOOD_KEY) is True
    assert f"GEMINI_API_KEY={GOOD_KEY}" in env.read_text(encoding="utf-8")


def test_write_key_to_env_replaces_an_existing_key(tmp_path: Path):
    env = tmp_path / ".env"
    env.write_text(
        "GEMINI_API_KEY=old-key-value-that-is-long-enough\nGETHU_PORT=8000\n",
        encoding="utf-8",
    )
    write_key_to_env(env, GOOD_KEY)
    text = env.read_text(encoding="utf-8")
    assert f"GEMINI_API_KEY={GOOD_KEY}" in text
    assert "old-key-value-that-is-long-enough" not in text
    # Other settings are preserved.
    assert "GETHU_PORT=8000" in text


def test_write_key_to_env_appends_when_absent(tmp_path: Path):
    env = tmp_path / ".env"
    env.write_text("GETHU_PORT=8000", encoding="utf-8")
    write_key_to_env(env, GOOD_KEY)
    text = env.read_text(encoding="utf-8")
    assert f"GEMINI_API_KEY={GOOD_KEY}" in text
    assert "GETHU_PORT=8000" in text


def test_env_file_is_not_world_readable(tmp_path: Path):
    env = tmp_path / ".env"
    write_key_to_env(env, GOOD_KEY)
    assert env.stat().st_mode & 0o077 == 0


def test_store_starts_with_the_startup_key():
    store = KeyStore(GOOD_KEY)
    assert store.key == GOOD_KEY
    assert store.configured is True
    assert store.from_runtime is False


def test_store_set_activates_the_new_key():
    store = KeyStore(None)
    assert store.configured is False
    store.set(GOOD_KEY)
    assert store.key == GOOD_KEY
    assert store.configured is True
    assert store.from_runtime is True


def test_store_set_persists_to_the_env_file(tmp_path: Path):
    env = tmp_path / ".env"
    store = KeyStore(None, env)
    store.set(GOOD_KEY)
    assert f"GEMINI_API_KEY={GOOD_KEY}" in env.read_text(encoding="utf-8")


def test_store_set_rejects_a_bad_key_and_keeps_the_old_one(tmp_path: Path):
    env = tmp_path / ".env"
    store = KeyStore(GOOD_KEY, env)
    with pytest.raises(ApiKeyError):
        store.set("nope")
    assert store.key == GOOD_KEY


def test_store_clear_removes_the_key(tmp_path: Path):
    env = tmp_path / ".env"
    store = KeyStore(None, env)
    store.set(GOOD_KEY)
    assert GOOD_KEY in env.read_text(encoding="utf-8")
    store.clear()
    assert store.key is None
    assert store.configured is False
    assert GOOD_KEY not in env.read_text(encoding="utf-8")


def test_store_clear_on_a_missing_env_file_is_safe(tmp_path: Path):
    store = KeyStore(GOOD_KEY, tmp_path / "nope.env")
    store.clear()  # must not raise
    assert store.key is None
