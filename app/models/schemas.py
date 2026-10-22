"""Pydantic request/response schemas for the Friendly Companion API."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

Mode = Literal["friendly", "respectful", "playful", "supportive", "focused"]
ROLE = Literal["user", "assistant"]

MODES: tuple[Mode, ...] = ("friendly", "respectful", "playful", "supportive", "focused")


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=32_000)
    conversation_id: str | None = Field(default=None, max_length=64)
    mode: Mode | None = None
    attachment_ids: list[str] = Field(default_factory=list, max_length=8)
    model: str | None = Field(default=None, max_length=100)


class AttachmentInfo(BaseModel):
    id: str
    filename: str
    mime: str
    size: int


class MessageOut(BaseModel):
    id: str
    conversation_id: str
    role: ROLE
    content: str
    attachments: list[AttachmentInfo] = Field(default_factory=list)
    created_at: str


class ConversationOut(BaseModel):
    id: str
    title: str
    mode: Mode
    created_at: str
    updated_at: str


class ConversationDetail(ConversationOut):
    messages: list[MessageOut] = Field(default_factory=list)


class ConversationCreate(BaseModel):
    title: str = Field(default="New chat", max_length=120)
    mode: Mode = "friendly"


class ConversationPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=120)
    mode: Mode | None = None


class SettingsOut(BaseModel):
    api_key_configured: bool
    model: str
    available_models: list[str]
    max_upload_mb: int
    modes: list[str]
    companion_name: str
    setup_complete: bool


class SettingsPatch(BaseModel):
    model: str | None = Field(default=None, max_length=100)
    # Accepted longer than the stored limit on purpose: the server truncates
    # rather than rejecting, so a pasted name never produces an opaque 422.
    companion_name: str | None = Field(default=None, max_length=200)


class ApiKeyIn(BaseModel):
    """A Gemini API key supplied through the web setup screen."""

    api_key: str = Field(min_length=1, max_length=200)


class ApiKeyOut(BaseModel):
    ok: bool
    api_key_configured: bool
    companion_name: str
    message: str


class HealthOut(BaseModel):
    status: str
    api_key_configured: bool
    model: str
    version: str


def as_dict(model: BaseModel) -> dict[str, Any]:
    return model.model_dump(mode="json")
