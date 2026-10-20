"""Non-secret application settings exposed to the frontend."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.models.schemas import MODES, SettingsOut, SettingsPatch

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("", response_model=SettingsOut)
async def get_settings(request: Request) -> SettingsOut:
    config = request.app.state.config
    store = request.app.state.settings_store
    model = store.model or config.model
    available = [model, *[m for m in config.candidate_models() if m != model]]
    return SettingsOut(
        api_key_configured=config.configured,
        model=model,
        available_models=available,
        max_upload_mb=config.max_upload_mb,
        modes=list(MODES),
    )


@router.put("", response_model=SettingsOut)
async def update_settings(payload: SettingsPatch, request: Request) -> SettingsOut:
    config = request.app.state.config
    store = request.app.state.settings_store
    if payload.model is not None:
        allowed = set(config.candidate_models())
        if payload.model not in allowed and not config.configured:
            raise HTTPException(
                status_code=400,
                detail="Configure GEMINI_API_KEY before choosing a custom model.",
            )
        # A user-configured account may expose models outside the fallback list;
        # accept any plausible model id and let Gemini validate it on first use.
        if not payload.model.replace("-", "").replace("_", "").replace(".", "").isalnum():
            raise HTTPException(status_code=422, detail="Invalid model name.")
        store.update({"model": payload.model})
    return await get_settings(request)
