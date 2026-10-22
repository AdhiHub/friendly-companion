"""Web setup: naming the companion and supplying the API key from the browser.

These are the endpoints a first-time user touches, so the happy path and the
rejections are both asserted here.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.config import AppConfig
from app.main import create_app


def _app(tmp_path: Path, api_key: str | None = None) -> TestClient:
    data = tmp_path / "data"
    config = AppConfig(
        api_key=api_key,
        data_dir=data,
        uploads_dir=data / "uploads",
        env_file=tmp_path / ".env",
    )
    return TestClient(create_app(config))


def test_default_settings_report_the_default_name(client: TestClient):
    settings = client.get("/api/settings").json()
    assert settings["companion_name"] == "Gethu"
    assert settings["setup_complete"] is True  # key comes from the test config


def test_companion_name_can_be_set(client: TestClient):
    updated = client.put("/api/settings", json={"companion_name": "Mithu"}).json()
    assert updated["companion_name"] == "Mithu"
    # It persists across requests.
    assert client.get("/api/settings").json()["companion_name"] == "Mithu"


def test_blank_name_is_rejected(client: TestClient):
    response = client.put("/api/settings", json={"companion_name": "   "})
    assert response.status_code == 400


def test_name_is_trimmed_and_whitespace_collapsed(client: TestClient):
    updated = client.put("/api/settings", json={"companion_name": "  My   Buddy  "}).json()
    assert updated["companion_name"] == "My Buddy"


def test_long_name_is_truncated_not_rejected(client: TestClient):
    """A pasted name must never produce an opaque validation error."""
    updated = client.put("/api/settings", json={"companion_name": "x" * 100}).json()
    assert len(updated["companion_name"]) == 40


def test_setup_is_incomplete_without_a_key(tmp_path: Path):
    with _app(tmp_path) as client:
        settings = client.get("/api/settings").json()
        assert settings["api_key_configured"] is False
        assert settings["setup_complete"] is False


def test_api_key_is_never_echoed_back(tmp_path: Path):
    """The key must not appear in any response the browser can read."""
    with _app(tmp_path) as client:
        response = client.post(
            "/api/settings/api-key", json={"api_key": "AIzaSyD-ExampleKey_1234567890abc"}
        )
        body = response.text
        assert "AIzaSyD" not in body


def test_short_key_is_rejected(tmp_path: Path):
    with _app(tmp_path) as client:
        response = client.post("/api/settings/api-key", json={"api_key": "short"})
        assert response.status_code == 400
        assert "too short" in response.json()["detail"].lower()


def test_rejected_key_does_not_get_stored(tmp_path: Path):
    with _app(tmp_path) as client:
        client.post("/api/settings/api-key", json={"api_key": "short"})
        assert client.get("/api/settings").json()["api_key_configured"] is False


def test_rejected_key_does_not_destroy_a_working_one(tmp_path: Path):
    """A bad key pasted over a good one must not leave the app unusable."""
    with _app(tmp_path, api_key="AIzaSyD-ExistingKey_1234567890abcdef") as client:
        app = client.app
        gemini = app.state.gemini

        async def fake_verify(key):
            return False, "Gemini rejected that key."

        gemini.verify_key = fake_verify

        response = client.post(
            "/api/settings/api-key", json={"api_key": "AIzaSyD-BadKey_1234567890abcdefg"}
        )
        assert response.status_code == 400
        # The original key is still in place and the app still works.
        assert client.get("/api/settings").json()["api_key_configured"] is True
        assert gemini.available is True
        assert gemini.api_key == "AIzaSyD-ExistingKey_1234567890abcdef"


def test_valid_key_is_accepted_and_activates_the_app(tmp_path: Path):
    with _app(tmp_path) as client:
        # The verification call is patched so the test never touches the network.
        app = client.app
        gemini = app.state.gemini

        async def fake_verify(key):
            return True, "ok"

        gemini.verify_key = fake_verify

        response = client.post(
            "/api/settings/api-key", json={"api_key": "AIzaSyD-ExampleKey_1234567890abc"}
        )
        assert response.status_code == 200
        assert response.json()["ok"] is True
        assert response.json()["api_key_configured"] is True
        # The app now has a working key.
        assert gemini.available is True


def test_key_rejected_by_gemini_is_not_kept(tmp_path: Path):
    with _app(tmp_path) as client:
        app = client.app
        gemini = app.state.gemini

        async def fake_verify(key):
            return False, "Gemini rejected that key."

        gemini.verify_key = fake_verify

        response = client.post(
            "/api/settings/api-key", json={"api_key": "AIzaSyD-ExampleKey_1234567890abc"}
        )
        assert response.status_code == 400
        assert client.get("/api/settings").json()["api_key_configured"] is False
        assert gemini.available is False


def test_name_is_used_in_the_system_prompt(tmp_path: Path):
    with _app(tmp_path) as client:
        client.put("/api/settings", json={"companion_name": "Mithu"})
        service = client.app.state.chat_service
        assert service.companion_name == "Mithu"
        prompt = service.prompts.system_prompt("friendly", service.companion_name)
        assert "You are Mithu," in prompt


def test_health_reports_the_companion_name(client: TestClient):
    assert client.get("/api/health").json()["companion_name"] == "Gethu"
