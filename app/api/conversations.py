"""Conversation history endpoints: list, create, rename, mode, delete, messages."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.models.schemas import (
    ConversationCreate,
    ConversationDetail,
    ConversationOut,
    ConversationPatch,
)

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


def _repo(request: Request):
    return request.app.state.repo


def _must_find(request: Request, conversation_id: str) -> ConversationOut:
    convo = _repo(request).get_conversation(conversation_id)
    if convo is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return convo


@router.get("", response_model=list[ConversationOut])
async def list_conversations(request: Request) -> list[ConversationOut]:
    return _repo(request).list_conversations()


@router.post("", response_model=ConversationOut, status_code=201)
async def create_conversation(payload: ConversationCreate, request: Request) -> ConversationOut:
    return _repo(request).create_conversation(title=payload.title, mode=payload.mode)


@router.get("/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(conversation_id: str, request: Request) -> ConversationDetail:
    detail = _repo(request).conversation_detail(conversation_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return detail


@router.patch("/{conversation_id}", response_model=ConversationOut)
async def patch_conversation(
    conversation_id: str, payload: ConversationPatch, request: Request
) -> ConversationOut:
    repo = _repo(request)
    if payload.title is not None:
        if repo.get_conversation(conversation_id) is None:
            raise HTTPException(status_code=404, detail="Conversation not found")
        repo.rename_conversation(conversation_id, payload.title)
    if payload.mode is not None:
        if repo.get_conversation(conversation_id) is None:
            raise HTTPException(status_code=404, detail="Conversation not found")
        repo.set_mode(conversation_id, payload.mode)
    return _must_find(request, conversation_id)


@router.delete("/{conversation_id}", status_code=204)
async def delete_conversation(conversation_id: str, request: Request) -> None:
    if not _repo(request).delete_conversation(conversation_id):
        raise HTTPException(status_code=404, detail="Conversation not found")


@router.delete("/{conversation_id}/messages", status_code=204)
async def clear_conversation(conversation_id: str, request: Request) -> None:
    if not _repo(request).clear_messages(conversation_id):
        raise HTTPException(status_code=404, detail="Conversation not found")
