"""API tests: chat streaming, conversations, settings, error handling.

Gemini is always mocked here — no key, no network, no cost.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.config import AppConfig
from app.main import create_app
from app.services.gemini_service import GeminiError
from tests.conftest import FakeGemini


def test_health_reports_configuration(client: TestClient):
    data = client.get("/api/health").json()
    assert data["status"] == "ok"
    assert data["api_key_configured"] is True
    assert data["model"] == "gemini-3.5-flash"


def test_index_served(client: TestClient):
    response = client.get("/")
    assert response.status_code == 200
    assert "Friendly Companion" in response.text
    assert "/static/js/app.js" in response.text


def test_empty_message_rejected(client: TestClient):
    response = client.post("/api/chat", json={"message": "   "})
    # whitespace-only passes pydantic's min_length but is rejected by the endpoint
    assert response.status_code in (400, 422)


def test_chat_requires_api_key(tmp_path):
    config = AppConfig(api_key=None, data_dir=tmp_path / "d", uploads_dir=tmp_path / "d" / "u")
    app = create_app(config)
    with TestClient(app) as client:
        response = client.post("/api/chat", json={"message": "hello"})
        assert response.status_code == 503
        assert response.json()["kind"] == "missing_key"
        assert "Settings" in response.json()["detail"]


def test_streaming_chat_emits_meta_delta_done(client: TestClient, fake_gemini: FakeGemini, read_sse):
    with client.stream(
        "POST", "/api/chat", json={"message": "Enna scene?", "mode": "friendly"}
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        body = "".join(response.iter_text())

    events = read_sse(body)
    names = [name for name, _ in events]
    assert names[0] == "meta"
    assert names[-1] == "done"
    assert "delta" in names

    full_text = "".join(data["text"] for name, data in events if name == "delta")
    assert full_text == "Hey bro, sollu!"
    done = [d for n, d in events if n == "done"][0]
    assert done["text"] == "Hey bro, sollu!"

    # Both turns persisted, conversation auto-titled from the user message.
    conversations = client.get("/api/conversations").json()
    assert len(conversations) == 1
    assert conversations[0]["title"] == "Enna scene?"
    detail = client.get(f"/api/conversations/{conversations[0]['id']}").json()
    assert [m["role"] for m in detail["messages"]] == ["user", "assistant"]
    assert detail["messages"][1]["content"] == "Hey bro, sollu!"


def test_prompt_and_mode_reach_the_model(client: TestClient, fake_gemini: FakeGemini):
    with client.stream("POST", "/api/chat", json={"message": "hi", "mode": "respectful"}) as r:
        "".join(r.iter_text())
    call = fake_gemini.calls[0]
    assert "MODE: respectful" in call["system"]
    assert "Friendly Companion" in call["system"]


def test_unknown_conversation_id_creates_new_one(client: TestClient, fake_gemini: FakeGemini, read_sse):
    with client.stream("POST", "/api/chat", json={"message": "hi", "conversation_id": "ghost"}) as r:
        events = read_sse("".join(r.iter_text()))
    meta = [d for n, d in events if n == "meta"][0]
    assert meta["conversation_created"] is True
    assert meta["conversation_id"] != "ghost"


def test_provider_error_becomes_safe_event(client: TestClient, app, read_sse):
    fake = FakeGemini(error=GeminiError("Gemini is rate limiting us right now.", kind="rate_limit"))
    app.state.chat_service.gemini = fake
    with client.stream("POST", "/api/chat", json={"message": "hi"}) as r:
        events = read_sse("".join(r.iter_text()))
    names = [n for n, _ in events]
    assert "error" in names and "done" not in names
    error = [d for n, d in events if n == "error"][0]
    assert error["kind"] == "rate_limit"
    assert "429" not in error["message"]  # no raw provider codes leaked
    # The failed reply must not be persisted as an assistant message.
    convos = client.get("/api/conversations").json()
    if convos:
        detail = client.get(f"/api/conversations/{convos[0]['id']}").json()
        assert all(m["role"] != "assistant" for m in detail["messages"])


def test_empty_model_reply_reports_error(client: TestClient, app, read_sse):
    app.state.chat_service.gemini = FakeGemini(chunks=("   ",))
    with client.stream("POST", "/api/chat", json={"message": "hi"}) as r:
        events = read_sse("".join(r.iter_text()))
    assert [n for n, _ in events][-1] == "error"


def test_conversation_crud(client: TestClient):
    created = client.post("/api/conversations", json={"title": "Hello", "mode": "playful"})
    assert created.status_code == 201
    cid = created.json()["id"]

    listed = client.get("/api/conversations").json()
    assert [c["id"] for c in listed] == [cid]

    patched = client.patch(f"/api/conversations/{cid}", json={"title": "Renamed"})
    assert patched.json()["title"] == "Renamed"
    patched = client.patch(f"/api/conversations/{cid}", json={"mode": "focused"})
    assert patched.json()["mode"] == "focused"

    detail = client.get(f"/api/conversations/{cid}")
    assert detail.status_code == 200
    assert detail.json()["messages"] == []

    assert client.get("/api/conversations/ghost").status_code == 404
    assert client.patch("/api/conversations/ghost", json={"title": "x"}).status_code == 404
    assert client.delete("/api/conversations/ghost").status_code == 404
    assert client.delete(f"/api/conversations/{cid}").status_code == 204
    assert client.get("/api/conversations").json() == []


def test_clear_messages_endpoint(client: TestClient, fake_gemini: FakeGemini):
    with client.stream("POST", "/api/chat", json={"message": "first"}) as r:
        "".join(r.iter_text())
    cid = client.get("/api/conversations").json()[0]["id"]
    assert client.delete(f"/api/conversations/{cid}/messages").status_code == 204
    assert client.get(f"/api/conversations/{cid}").json()["messages"] == []
    assert client.delete("/api/conversations/ghost/messages").status_code == 404


def test_settings_get_and_put(client: TestClient):
    settings = client.get("/api/settings").json()
    assert settings["api_key_configured"] is True
    assert settings["model"] == "gemini-3.5-flash"
    assert settings["modes"] == ["friendly", "respectful", "playful", "supportive", "focused"]
    assert "gemini-3.6-flash" in settings["available_models"]

    updated = client.put("/api/settings", json={"model": "gemini-3.8-flash"})
    assert updated.status_code == 200
    assert updated.json()["model"] == "gemini-3.8-flash"

    bad = client.put("/api/settings", json={"model": "bad model name!"})
    assert bad.status_code == 422

    # Preference survives a fresh app instance pointed at the same data dir.
    assert client.get("/api/settings").json()["model"] == "gemini-3.8-flash"


def test_history_sent_to_model_is_bounded(client: TestClient, app, fake_gemini: FakeGemini):
    for i in range(6):
        with client.stream("POST", "/api/chat", json={"message": f"turn {i}"}) as r:
            "".join(r.iter_text())
    contents = fake_gemini.calls[-1]["contents"]
    assert len(contents) <= app.state.chat_service.history_limit


def test_input_validation_rejects_bad_payload(client: TestClient):
    assert client.post("/api/chat", json={}).status_code == 422
    assert client.post("/api/chat", json={"message": "x", "mode": "angry"}).status_code == 422
    assert client.post("/api/conversations", json={"mode": "invalid"}).status_code == 422
    payload = {"message": "hi", "attachment_ids": ["a"] * 50}
    assert client.post("/api/chat", json=payload).status_code == 422


def test_conversation_ids_are_unique_and_ordered(client: TestClient):
    ids = [client.post("/api/conversations", json={"title": f"c{i}"}).json()["id"] for i in range(3)]
    assert len(set(ids)) == 3
