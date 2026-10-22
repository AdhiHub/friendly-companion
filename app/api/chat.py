"""Chat endpoint: POST /api/chat, streamed back as Server-Sent Events."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app.models.schemas import ChatRequest
from app.services.conversation_service import ChatError, ChatService, sse_frames
from app.services.gemini_service import GeminiError

logger = logging.getLogger("companion.api.chat")

router = APIRouter(prefix="/api", tags=["chat"])


def _chat_service(request: Request) -> ChatService:
    return request.app.state.chat_service


@router.post("/chat")
async def chat(payload: ChatRequest, request: Request) -> StreamingResponse:
    if not payload.message.strip():
        raise ChatError("Message cannot be empty.", status=422)

    service = _chat_service(request)
    if not service.gemini.available:
        raise ChatError(
            "No Gemini API key yet. Open Settings and paste your key to get started.",
            status=503,
            kind="missing_key",
        )

    # Validate attachments and persist the user turn *before* the stream opens,
    # so failures come back as normal HTTP errors.
    prepared = service.prepare(payload)

    try:
        stream = sse_frames(service.run(payload, prepared))
    except ChatError:
        raise
    except GeminiError as err:
        raise ChatError(err.message, status=502, kind=err.kind) from err

    return StreamingResponse(
        stream,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
