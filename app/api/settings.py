"""Non-secret application settings exposed to the frontend, plus the one
secret the user may set through the web UI: the Gemini API key.

The key is accepted over HTTP only on a local machine, validated against the
real Gemini API before it is accepted, and never echoed back to the browser.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request

from app.models.schemas import (
    MODES,
    ApiKeyIn,
    ApiKeyOut,
    SettingsOut,
    SettingsPatch,
)
from app.services.key_store import ApiKeyError, normalise_key

router = APIRouter(prefix="/api/settings", tags=["settings"])

logger = logging.getLogger("companion.settings")


def _name_from(payload: str | None) -> str:
    """Clean a user-supplied companion name."""
    name = " ".join((payload or "").split())
    if not name:
        raise HTTPException(
            status_code=400,
            detail="Give your companion a name, or use the default.",
        )
    return name[:40]


@router.get("", response_model=SettingsOut)
async def get_settings(request: Request) -> SettingsOut:
    config = request.app.state.config
    store = request.app.state.settings_store
    keys = request.app.state.key_store
    model = store.model or config.model
    available = [model, *[m for m in config.candidate_models() if m != model]]
    name = store.companion_name
    return SettingsOut(
        api_key_configured=keys.configured,
        model=model,
        available_models=available,
        max_upload_mb=config.max_upload_mb,
        modes=list(MODES),
        companion_name=name,
        setup_complete=keys.configured and bool(name),
    )


@router.put("", response_model=SettingsOut)
async def update_settings(payload: SettingsPatch, request: Request) -> SettingsOut:
    config = request.app.state.config
    store = request.app.state.settings_store
    keys = request.app.state.key_store
    if payload.model is not None:
        allowed = set(config.candidate_models())
        if payload.model not in allowed and not keys.configured:
            raise HTTPException(
                status_code=400,
                detail="Add your Gemini API key before choosing a custom model.",
            )
        # A user-configured account may expose models outside the fallback list;
        # accept any plausible model id and let Gemini validate it on first use.
        if not payload.model.replace("-", "").replace("_", "").replace(".", "").isalnum():
            raise HTTPException(status_code=422, detail="Invalid model name.")
        store.update({"model": payload.model})
    if payload.companion_name is not None:
        store.update({"companion_name": _name_from(payload.companion_name)})
    return await get_settings(request)


@router.post("/api-key", response_model=ApiKeyOut)
async def set_api_key(payload: ApiKeyIn, request: Request) -> ApiKeyOut:
    """Accept a Gemini API key typed into the web UI.

    The key is verified against Gemini before it is stored, so a typo is
    reported immediately instead of failing on the first reply.
    """
    keys = request.app.state.key_store
    gemini = request.app.state.gemini
    store = request.app.state.settings_store

    # Validate the shape of the key first, but do not activate it yet: a key
    # that Gemini rejects must not destroy a working one that is already set.
    try:
        candidate = normalise_key(payload.api_key)
    except ApiKeyError as err:
        raise HTTPException(status_code=400, detail=err.message) from err

    ok, detail = await gemini.verify_key(candidate)
    if not ok:
        raise HTTPException(status_code=400, detail=detail)

    # Only now replace the live key and persist it.
    keys.set(candidate)

    # The client caches the old key: drop it so the next reply uses the new one.
    gemini.reset()
    name = store.companion_name
    return ApiKeyOut(
        ok=True,
        api_key_configured=True,
        companion_name=name,
        message="API key saved. Friendly Companion is ready to chat.",
    )
