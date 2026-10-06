"""FastAPI Application factory configuring routes, state, and static SPA serving."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from tg_cleaner.cleaner.backup import BackupManager
from tg_cleaner.core.db import DatabaseManager
from tg_cleaner.core.settings import settings
from tg_cleaner.web.routes.api import router as api_router


def create_app(
    db: DatabaseManager | None = None,
    client: Any | None = None,
    backup_dir: str | None = None,
) -> FastAPI:
    """Create and configure FastAPI application instance."""
    app = FastAPI(
        title="Telegram Archive Cleaner",
        description="Visual dashboard for deduplicating, auditing, and safely cleaning Telegram chats and archives.",
        version="1.0.0",
    )

    # State dependencies
    app.state.db = db or DatabaseManager(settings.db_path)
    app.state.client = client
    app.state.backup_manager = BackupManager(backup_dir or settings.backup_dir)

    # CORS middleware for local or containerized usage
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # API routes
    app.include_router(api_router)

    # Static assets and index.html serving
    static_dir = Path(__file__).parent / "static"
    static_dir.mkdir(parents=True, exist_ok=True)

    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    @app.get("/")
    def serve_index() -> FileResponse:
        index_file = static_dir / "index.html"
        if not index_file.is_file():
            # Return basic HTML placeholder if index.html is still generating
            return FileResponse(__file__)
        return FileResponse(str(index_file))

    return app
