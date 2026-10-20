"""Data access for conversations, messages and attachment records."""

from __future__ import annotations

import json
from typing import Any

from app.database.connection import Database
from app.models.schemas import (
    MODES,
    AttachmentInfo,
    ConversationDetail,
    ConversationOut,
    MessageOut,
)
from app.utils.validation import new_id, now_iso, title_from_message


def _row_to_conversation(row: Any) -> ConversationOut:
    return ConversationOut(
        id=row["id"],
        title=row["title"],
        mode=row["mode"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_message(row: Any) -> MessageOut:
    try:
        raw = json.loads(row["attachments"] or "[]")
    except json.JSONDecodeError:
        raw = []
    attachments = [AttachmentInfo(**item) for item in raw if isinstance(item, dict)]
    return MessageOut(
        id=row["id"],
        conversation_id=row["conversation_id"],
        role=row["role"],
        content=row["content"],
        attachments=attachments,
        created_at=row["created_at"],
    )


class Repository:
    def __init__(self, db: Database) -> None:
        self.db = db

    # -- conversations -----------------------------------------------------
    def create_conversation(self, title: str = "New chat", mode: str = "friendly") -> ConversationOut:
        if mode not in MODES:
            mode = "friendly"
        cid = new_id("c_")
        stamp = now_iso()
        title = (title or "New chat").strip()[:120] or "New chat"
        self.db.execute(
            "INSERT INTO conversations (id, title, mode, created_at, updated_at) VALUES (?,?,?,?,?)",
            (cid, title, mode, stamp, stamp),
        )
        return ConversationOut(id=cid, title=title, mode=mode, created_at=stamp, updated_at=stamp)

    def list_conversations(self) -> list[ConversationOut]:
        rows = self.db.query(
            "SELECT * FROM conversations ORDER BY updated_at DESC, rowid DESC"
        )
        return [_row_to_conversation(r) for r in rows]

    def get_conversation(self, cid: str) -> ConversationOut | None:
        row = self.db.query_one("SELECT * FROM conversations WHERE id = ?", (cid,))
        return _row_to_conversation(row) if row else None

    def rename_conversation(self, cid: str, title: str) -> ConversationOut | None:
        title = (title or "").strip()[:120]
        if not title:
            return self.get_conversation(cid)
        self.db.execute(
            "UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?",
            (title, now_iso(), cid),
        )
        return self.get_conversation(cid)

    def set_mode(self, cid: str, mode: str) -> ConversationOut | None:
        if mode not in MODES:
            return self.get_conversation(cid)
        self.db.execute(
            "UPDATE conversations SET mode = ?, updated_at = ? WHERE id = ?",
            (mode, now_iso(), cid),
        )
        return self.get_conversation(cid)

    def delete_conversation(self, cid: str) -> bool:
        before = self.db.query_one("SELECT id FROM conversations WHERE id = ?", (cid,))
        if not before:
            return False
        self.db.execute("DELETE FROM conversations WHERE id = ?", (cid,))
        return True

    def clear_messages(self, cid: str) -> bool:
        if not self.get_conversation(cid):
            return False
        self.db.execute("DELETE FROM messages WHERE conversation_id = ?", (cid,))
        self.db.execute("UPDATE conversations SET updated_at = ? WHERE id = ?", (now_iso(), cid))
        return True

    def touch(self, cid: str) -> None:
        self.db.execute(
            "UPDATE conversations SET updated_at = ? WHERE id = ?", (now_iso(), cid)
        )

    def auto_title(self, cid: str, message: str) -> None:
        """Replace the placeholder title using the first user message."""
        row = self.db.query_one("SELECT title FROM conversations WHERE id = ?", (cid,))
        if row and row["title"] in {"New chat", ""}:
            self.db.execute(
                "UPDATE conversations SET title = ? WHERE id = ?",
                (title_from_message(message), cid),
            )

    # -- messages ----------------------------------------------------------
    def add_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        attachments: list[AttachmentInfo] | None = None,
        message_id: str | None = None,
    ) -> MessageOut:
        mid = message_id or new_id("m_")
        stamp = now_iso()
        payload = json.dumps([a.model_dump() for a in (attachments or [])])
        self.db.execute(
            "INSERT INTO messages (id, conversation_id, role, content, attachments, created_at)"
            " VALUES (?,?,?,?,?,?)",
            (mid, conversation_id, role, content, payload, stamp),
        )
        self.touch(conversation_id)
        return MessageOut(
            id=mid,
            conversation_id=conversation_id,
            role=role,  # type: ignore[arg-type]
            content=content,
            attachments=attachments or [],
            created_at=stamp,
        )

    def list_messages(self, conversation_id: str) -> list[MessageOut]:
        rows = self.db.query(
            "SELECT * FROM messages WHERE conversation_id = ? ORDER BY created_at, id",
            (conversation_id,),
        )
        return [_row_to_message(r) for r in rows]

    def get_message(self, message_id: str) -> MessageOut | None:
        row = self.db.query_one("SELECT * FROM messages WHERE id = ?", (message_id,))
        return _row_to_message(row) if row else None

    # -- attachments -------------------------------------------------------
    def add_attachment_record(
        self,
        *,
        attachment_id: str,
        conversation_id: str | None,
        filename: str,
        stored_name: str,
        mime: str,
        size: int,
    ) -> None:
        self.db.execute(
            "INSERT INTO attachments"
            " (id, conversation_id, message_id, filename, stored_name, mime, size, created_at)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (
                attachment_id,
                conversation_id,
                None,
                filename,
                stored_name,
                mime,
                size,
                now_iso(),
            ),
        )

    def get_attachment_record(self, attachment_id: str) -> dict[str, Any] | None:
        row = self.db.query_one("SELECT * FROM attachments WHERE id = ?", (attachment_id,))
        return dict(row) if row else None

    def bind_attachment_to_message(self, attachment_id: str, message_id: str) -> None:
        self.db.execute(
            "UPDATE attachments SET message_id = ? WHERE id = ?", (message_id, attachment_id)
        )

    def delete_attachment_record(self, attachment_id: str) -> None:
        self.db.execute("DELETE FROM attachments WHERE id = ?", (attachment_id,))

    # -- detail ------------------------------------------------------------
    def conversation_detail(self, cid: str) -> ConversationDetail | None:
        convo = self.get_conversation(cid)
        if not convo:
            return None
        return ConversationDetail(**convo.model_dump(), messages=self.list_messages(cid))
