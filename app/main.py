"""FastAPI application factory for the Gethu companion."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api import attachments, chat, conversations, settings
from app.config import AppConfig, load_config
from app.database.connection import Database
from app.database.repository import Repository
from app.services.attachment_service import AttachmentError, AttachmentService
from app.services.conversation_service import ChatError, ChatService
from app.services.gemini_service import GeminiError, GeminiService
from app.services.key_store import KeyStore
from app.services.prompt_service import PromptService
from app.services.settings_service import SettingsStore
from app.utils.logging_config import configure_logging
from app.utils.net import prefer_ipv4

logger = logging.getLogger("gethu")

VERSION = "0.1.0"
STATIC_DIR = Path(__file__).resolve().parent / "static"


def create_app(config: AppConfig | None = None) -> FastAPI:
    config = config or load_config()
    configure_logging(config.log_level)
    prefer_ipv4()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logger.info("Gethu starting (model=%s, key=%s)", config.model,
                    "set" if key_store.configured else "MISSING")
        yield
        db = getattr(app.state, "db", None)
        if db is not None:
            db.close()

    app = FastAPI(title="Gethu", version=VERSION, lifespan=lifespan, docs_url=None, redoc_url=None)

    db = Database(config.db_path)
    repo = Repository(db)
    key_store = KeyStore(config.api_key, config.env_file)
    gemini = GeminiService(config, key_store)
    attachment_service = AttachmentService(config)

    app.state.config = config
    app.state.db = db
    app.state.repo = repo
    app.state.gemini = gemini
    app.state.attachment_service = attachment_service
    app.state.key_store = key_store
    app.state.settings_store = SettingsStore(config)
    app.state.prompt_service = PromptService()
    app.state.chat_service = ChatService(
        repo=repo,
        prompts=app.state.prompt_service,
        gemini=gemini,
        attachments=attachment_service,
        history_limit=config.max_history_messages,
        settings=app.state.settings_store,
    )

    # -- error handling ----------------------------------------------------
    @app.exception_handler(ChatError)
    async def chat_error_handler(_: Request, exc: ChatError) -> JSONResponse:
        return JSONResponse(status_code=exc.status, content={"detail": exc.message, "kind": exc.kind})

    @app.exception_handler(AttachmentError)
    async def attachment_error_handler(_: Request, exc: AttachmentError) -> JSONResponse:
        return JSONResponse(status_code=exc.status, content={"detail": exc.message})

    @app.exception_handler(GeminiError)
    async def gemini_error_handler(_: Request, exc: GeminiError) -> JSONResponse:
        return JSONResponse(status_code=502, content={"detail": exc.message, "kind": exc.kind})

    @app.exception_handler(Exception)
    async def unexpected_error_handler(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled error: %s", type(exc).__name__)
        return JSONResponse(status_code=500, content={"detail": "Something went wrong on Gethu's side."})

    # -- api ---------------------------------------------------------------
    app.include_router(chat.router)
    app.include_router(conversations.router)
    app.include_router(attachments.router)
    app.include_router(settings.router)

    @app.get("/api/health")
    async def health() -> dict:
        return {
            "status": "ok",
            "api_key_configured": key_store.configured,
            "model": app.state.settings_store.model or config.model,
            "companion_name": app.state.settings_store.companion_name,
            "version": VERSION,
        }

    # -- frontend ----------------------------------------------------------
    # Local dev app: never let the browser cache the frontend. Stale JS/CSS in
    # the browser cache silently runs old code (replies that never render),
    # which is far more confusing than a slightly slower reload.
    @app.middleware("http")
    async def no_store_frontend(request, call_next):
        response = await call_next(request)
        path = request.url.path
        if path == "/" or path.startswith("/static"):
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response.headers["Pragma"] = "no-cache"
            if "etag" in response.headers:
                del response.headers["etag"]
        return response

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    return app


app = create_app()


def main() -> None:  # pragma: no cover - manual entry point
    import uvicorn

    cfg = load_config()
    uvicorn.run(
        "app.main:app",
        host=cfg.host,
        port=cfg.port,
        log_level=cfg.log_level.lower(),
    )


if __name__ == "__main__":  # pragma: no cover
    main()
