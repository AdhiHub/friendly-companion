"""Repository (SQLite) behaviour: conversations, messages, attachments."""

from __future__ import annotations

from app.database.connection import Database
from app.database.repository import Repository
from app.models.schemas import AttachmentInfo


def make_repo(tmp_path) -> Repository:
    return Repository(Database(tmp_path / "test.db"))


def test_create_and_list_conversations(tmp_path):
    repo = make_repo(tmp_path)
    first = repo.create_conversation(title="First", mode="friendly")
    second = repo.create_conversation(title="Second", mode="focused")
    titles = [c.title for c in repo.list_conversations()]
    assert titles[:2] == ["Second", "First"]  # newest first
    assert first.mode == "friendly"
    assert second.mode == "focused"


def test_invalid_mode_defaults_to_friendly(tmp_path):
    repo = make_repo(tmp_path)
    convo = repo.create_conversation(mode="not-a-mode")
    assert convo.mode == "friendly"


def test_rename_and_set_mode(tmp_path):
    repo = make_repo(tmp_path)
    convo = repo.create_conversation()
    renamed = repo.rename_conversation(convo.id, "  Renamed chat  ")
    assert renamed is not None and renamed.title == "Renamed chat"
    assert repo.rename_conversation(convo.id, "   ").title == "Renamed chat"  # blank ignored
    assert repo.set_mode(convo.id, "respectful").mode == "respectful"
    assert repo.set_mode(convo.id, "bogus").mode == "respectful"  # invalid ignored
    assert repo.get_conversation("missing") is None


def test_messages_persist_with_attachments(tmp_path):
    repo = make_repo(tmp_path)
    convo = repo.create_conversation()
    att = AttachmentInfo(id="a_1", filename="pic.png", mime="image/png", size=10)
    repo.add_message(convo.id, "user", "look at this", [att])
    repo.add_message(convo.id, "assistant", "nice pic")

    messages = repo.list_messages(convo.id)
    assert [m.role for m in messages] == ["user", "assistant"]
    assert messages[0].attachments[0].filename == "pic.png"
    assert messages[1].content == "nice pic"


def test_message_ordering_and_get(tmp_path):
    repo = make_repo(tmp_path)
    convo = repo.create_conversation()
    m1 = repo.add_message(convo.id, "user", "one")
    m2 = repo.add_message(convo.id, "assistant", "two")
    assert [m.id for m in repo.list_messages(convo.id)] == [m1.id, m2.id]
    assert repo.get_message(m1.id).content == "one"
    assert repo.get_message("nope") is None


def test_delete_conversation_cascades_messages(tmp_path):
    repo = make_repo(tmp_path)
    convo = repo.create_conversation()
    repo.add_message(convo.id, "user", "bye")
    assert repo.delete_conversation(convo.id) is True
    assert repo.get_conversation(convo.id) is None
    assert repo.list_messages(convo.id) == []
    assert repo.delete_conversation(convo.id) is False


def test_clear_messages_keeps_conversation(tmp_path):
    repo = make_repo(tmp_path)
    convo = repo.create_conversation(title="Keep me")
    repo.add_message(convo.id, "user", "x")
    assert repo.clear_messages(convo.id) is True
    assert repo.list_messages(convo.id) == []
    assert repo.get_conversation(convo.id).title == "Keep me"
    assert repo.clear_messages("missing") is False


def test_auto_title_only_replaces_placeholder(tmp_path):
    repo = make_repo(tmp_path)
    convo = repo.create_conversation()  # placeholder title
    repo.auto_title(convo.id, "Enna scene? Innaiku plan enna?")
    assert repo.get_conversation(convo.id).title == "Enna scene? Innaiku plan enna?"

    named = repo.create_conversation(title="My named chat")
    repo.auto_title(named.id, "should not win")
    assert repo.get_conversation(named.id).title == "My named chat"


def test_auto_title_uses_first_line_and_trims(tmp_path):
    repo = make_repo(tmp_path)
    convo = repo.create_conversation()
    long_line = "x" * 80
    repo.auto_title(convo.id, f"\n\n  {long_line}\nsecond line")
    title = repo.get_conversation(convo.id).title
    assert len(title) <= 48
    assert title.endswith("…")


def test_attachment_records(tmp_path):
    repo = make_repo(tmp_path)
    repo.add_attachment_record(
        attachment_id="a_abc",
        conversation_id=None,
        filename="doc.pdf",
        stored_name="a_abc.pdf",
        mime="application/pdf",
        size=123,
    )
    record = repo.get_attachment_record("a_abc")
    assert record["filename"] == "doc.pdf"
    assert record["size"] == 123

    convo = repo.create_conversation()
    message = repo.add_message(convo.id, "user", "here is the doc")
    repo.bind_attachment_to_message("a_abc", message.id)
    assert repo.get_attachment_record("a_abc")["message_id"] == message.id
    repo.delete_attachment_record("a_abc")
    assert repo.get_attachment_record("a_abc") is None


def test_conversation_detail_includes_messages(tmp_path):
    repo = make_repo(tmp_path)
    convo = repo.create_conversation(title="Detail")
    repo.add_message(convo.id, "user", "hi")
    detail = repo.conversation_detail(convo.id)
    assert detail is not None
    assert detail.title == "Detail"
    assert len(detail.messages) == 1
    assert repo.conversation_detail("missing") is None
