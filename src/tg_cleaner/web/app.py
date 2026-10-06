"""FastAPI application factory and deployable ASGI entrypoint."""

from __future__ import annotations

import hmac
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles

from tg_cleaner.cleaner.backup import BackupManager
from tg_cleaner.core.db import DatabaseManager
from tg_cleaner.core.settings import settings
from tg_cleaner.web.routes.api import router as api_router


def get_static_dir() -> Path:
    """Resolve static assets for source and PyInstaller builds."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        bundle_root = Path(sys._MEIPASS)
        for candidate in (bundle_root / "tg_cleaner" / "web" / "static", bundle_root / "static"):
            if candidate.is_dir():
                return candidate
    return Path(__file__).parent / "static"


def create_app(
    db: DatabaseManager | None = None,
    client: Any | None = None,
    backup_dir: str | None = None,
) -> FastAPI:
    """Create the FastAPI application and initialize its database."""
    db_manager = db or DatabaseManager(settings.db_path)
    backup_manager = BackupManager(backup_dir or settings.backup_dir)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        db_manager.init_db()
        yield
        active_client = getattr(app.state, "client", None)
        disconnect = getattr(active_client, "disconnect", None)
        if callable(disconnect):
            try:
                result = disconnect()
                if hasattr(result, "__await__"):
                    await result
            except Exception:
                pass

    app = FastAPI(
        title="Telegram Archive Cleaner",
        description="Local tool for reviewing and cleaning Telegram archives.",
        version="1.0.0",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
    )
    app.state.db = db_manager
    app.state.client = client
    app.state.backup_manager = backup_manager
    app.state.thumb_dir = db_manager.db_path.parent / "thumbs"
    # Also initialize synchronously so programmatic callers that do not run ASGI lifespan
    # still receive a usable application (e.g. lightweight tests and embedded launchers).
    db_manager.init_db()

    @app.middleware("http")
    async def security_boundary(request: Request, call_next: Any) -> Any:
        protected_api = request.url.path.startswith("/api/")
        if settings.api_token and protected_api:
            auth_header = request.headers.get("authorization", "")
            bearer = auth_header.removeprefix("Bearer ").strip()
            supplied = bearer or request.headers.get("x-api-token", "")
            if not supplied or not hmac.compare_digest(supplied, settings.api_token):
                response: Any = JSONResponse(
                    status_code=401, content={"detail": "Valid API token required"}
                )
            else:
                response = await call_next(request)
        else:
            response = await call_next(request)

        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault(
            "Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=()"
        )
        if request.url.path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    app.include_router(api_router)

    static_dir = get_static_dir()
    if static_dir.is_dir():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    def _asset_response(filename: str) -> FileResponse | PlainTextResponse:
        file_path = static_dir / filename
        if not file_path.is_file():
            return PlainTextResponse("Dashboard asset is missing from this build.", status_code=503)
        return FileResponse(str(file_path))

    @app.get("/", response_model=None)
    def serve_index() -> Response:
        return _asset_response("index.html")

    @app.get("/app.js", response_model=None)
    def serve_app_js() -> Response:
        return _asset_response("app.js")

    @app.get("/alpine.min.js", response_model=None)
    def serve_alpine_js() -> Response:
        return _asset_response("alpine.min.js")

    @app.get("/tailwind.min.js", response_model=None)
    def serve_tailwind_js() -> Response:
        return _asset_response("tailwind.min.js")

    return app


# Deployment entrypoint used by Uvicorn, Docker, Railway, and Procfile.
app = create_app()
