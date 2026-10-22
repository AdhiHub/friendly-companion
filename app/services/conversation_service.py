"""Chat orchestration: persist the user turn, stream Gemini, persist the reply.

Yields simple event dicts; the HTTP layer only serialises them to SSE. This
keeps the flow testable without a server or a real provider.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from app.database.repository import Repository
from app.models.schemas import MODES, AttachmentInfo, ChatRequest, ConversationOut
from app.services.attachment_service import AttachmentError, AttachmentService
from app.services.gemini_service import GeminiError, GeminiService
from app.services.prompt_service import DEFAULT_COMPANION_NAME, PromptService
from app.utils.validation import new_id

logger = logging.getLogger("companion.chat")


class ChatError(Exception):
    def __init__(self, message: str, status: int = 400, kind: str = "bad_request") -> None:
        super().__init__(message)
        self.message = message
        self.status = status
        self.kind = kind


def _event(name: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {"event": name, "data": payload}


class ChatService:
    def __init__(
        self,
        *,
        repo: Repository,
        prompts: PromptService,
        gemini: GeminiService,
        attachments: AttachmentService,
        history_limit: int = 40,
        settings: Any = None,
    ) -> None:
        self.repo = repo
        self.prompts = prompts
        self.gemini = gemini
        self.attachments = attachments
        self.history_limit = history_limit
        self.settings = settings

    @property
    def companion_name(self) -> str:
        """The name the user gave the character (default: Friendly Companion)."""
        store = self.settings
        if store is None:
            return DEFAULT_COMPANION_NAME
        try:
            return store.companion_name
        except Exception:  # noqa: BLE001 - never break a chat over a name
            return DEFAULT_COMPANION_NAME

    def prepare(self, request: ChatRequest) -> dict[str, Any]:
        """Resolve conversation, validate attachments, persist the user turn.

        Runs before the SSE response starts so that ChatError / AttachmentError
        surface as proper HTTP status codes instead of mid-stream failures.
        """
        conversation, created = self._resolve_conversation(request)
        mode = request.mode or conversation.mode

        history = [
            {"role": m.role, "content": m.content}
            for m in self.repo.list_messages(conversation.id)
        ]

        attachment_infos, attachment_parts = self._load_attachments(
            request.attachment_ids, conversation.id
        )

        contents = self.prompts.build_contents(
            history,
            request.message,
            attachment_parts,
            limit=self.history_limit,
        )
        system = self.prompts.system_prompt(mode, self.companion_name)

        user_msg = self.repo.add_message(
            conversation.id, "user", request.message, attachment_infos
        )
        for info in attachment_infos:
            self.repo.bind_attachment_to_message(info.id, user_msg.id)
        self.repo.auto_title(conversation.id, request.message)

        assistant_id = new_id("m_")
        return {
            "conversation": conversation,
            "created": created,
            "mode": mode,
            "system": system,
            "contents": contents,
            "assistant_id": assistant_id,
            "meta": {
                "conversation_id": conversation.id,
                "conversation_created": created,
                "mode": mode,
                "user_message_id": user_msg.id,
                "assistant_message_id": assistant_id,
            },
        }

    async def run(
        self, request: ChatRequest, prepared: dict[str, Any] | None = None
    ) -> AsyncIterator[dict[str, Any]]:
        prepared = prepared or self.prepare(request)
        assistant_id = prepared["assistant_id"]
        yield _event("meta", prepared["meta"])

        buffer: list[str] = []
        conversation = prepared["conversation"]
        try:
            async for chunk in self.gemini.stream_reply(
                system=prepared["system"], contents=prepared["contents"], model=request.model
            ):
                buffer.append(chunk)
                yield _event("delta", {"text": chunk})
        except GeminiError as err:
            logger.warning("Chat stream failed: %s (%s)", err.kind, err.message)
            yield _event(
                "error",
                {
                    "message": err.message,
                    "kind": err.kind,
                    "partial_text": "".join(buffer),
                },
            )
            return
        except asyncio.CancelledError:
            # Client navigated away: keep whatever already arrived.
            self._persist_partial(conversation.id, "".join(buffer))
            raise

        full_text = "".join(buffer)
        if not full_text.strip():
            yield _event("error", {"message": "Friendly Companion returned an empty reply.", "kind": "empty"})
            return

        assistant_msg = self.repo.add_message(
            conversation.id, "assistant", full_text, message_id=assistant_id
        )
        yield _event(
            "done",
            {
                "message_id": assistant_msg.id,
                "conversation_id": conversation.id,
                "text": full_text,
            },
        )

    # -- helpers -----------------------------------------------------------
    def _resolve_conversation(self, request: ChatRequest) -> tuple[ConversationOut, bool]:
        if request.conversation_id:
            conversation = self.repo.get_conversation(request.conversation_id)
            if conversation:
                return conversation, False
            if request.conversation_id.strip():
                # Unknown id: start a fresh conversation rather than failing the chat.
                logger.info("Unknown conversation id, creating a new one")
        return self.repo.create_conversation(mode=request.mode or "friendly"), True

    def _load_attachments(
        self, attachment_ids: list[str], conversation_id: str
    ) -> tuple[list[AttachmentInfo], list[dict[str, Any]]]:
        infos: list[AttachmentInfo] = []
        parts: list[dict[str, Any]] = []
        for att_id in attachment_ids:
            record = self.repo.get_attachment_record(att_id)
            if not record:
                raise AttachmentError("One of the attachments is no longer available.", status=404)
            try:
                data = self.attachments.load_bytes(record["stored_name"])
                parts.append(self.attachments.gemini_part(record["mime"], data))
            except AttachmentError as err:
                raise ChatError(err.message, status=err.status, kind="attachment") from err
            infos.append(
                AttachmentInfo(
                    id=record["id"],
                    filename=record["filename"],
                    mime=record["mime"],
                    size=record["size"],
                )
            )
            self.repo.db.execute(
                "UPDATE attachments SET conversation_id = ? WHERE id = ?",
                (conversation_id, att_id),
            )
        return infos, parts

    def _records_for(self, attachment_ids: list[str]) -> list[dict[str, Any]]:
        """Attachment records for ids that exist (used by tests and diagnostics)."""
        records = []
        for att_id in attachment_ids:
            record = self.repo.get_attachment_record(att_id)
            if record:
                records.append(record)
        return records

    def _persist_partial(self, conversation_id: str, text: str) -> None:
        text = text.strip()
        if not text:
            return
        try:
            self.repo.add_message(conversation_id, "assistant", text)
        except Exception:  # pragma: no cover - best effort on teardown
            logger.warning("Could not persist partial reply")


async def sse_frames(events: AsyncIterator[dict[str, Any]]) -> AsyncIterator[str]:
    """Serialise event dicts into SSE wire format.

    Defensive by design: a malformed producer must never abort the response
    mid-stream, so anything unsupported becomes a JSON-safe string.
    """
    async for event in events:
        if not isinstance(event, dict) or "event" not in event:
            logger.error("Dropping malformed SSE event of type %s", type(event).__name__)
            continue
        try:
            payload = json.dumps(event.get("data", {}), ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            logger.exception("Dropping unserialisable SSE event %r", event.get("event"))
            continue
        yield f"event: {event['event']}\ndata: {payload}\n\n"


def validate_mode(mode: str | None) -> str:
    if mode is None:
        return "friendly"
    if mode not in MODES:
        raise ChatError(f"Unknown conversation mode: {mode}", status=422, kind="mode")
    return mode
