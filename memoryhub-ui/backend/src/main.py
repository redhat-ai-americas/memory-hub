"""FastAPI application factory for the MemoryHub UI BFF."""

import logging
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from src.routes import router

logger = logging.getLogger(__name__)

# In the container, WORKDIR is /opt/app-root/src and frontend/dist is a sibling to src/.
# Locally, the frontend dist doesn't exist next to the backend — Vite proxy handles dev.
# Allow override via env var for flexibility.
_default_dist = Path(os.environ.get("FRONTEND_DIST", "/opt/app-root/src/frontend/dist"))
# Also check relative to this file (for local dev with a pre-built frontend)
_local_dist = Path(__file__).parent.parent.parent / "frontend" / "dist"
FRONTEND_DIST = _default_dist if _default_dist.is_dir() else _local_dist


def create_app() -> FastAPI:
    app = FastAPI(
        title="MemoryHub UI BFF",
        description="Read-only BFF API for the MemoryHub dashboard",
        version="0.1.0",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["GET"],
        allow_headers=["*"],
    )

    app.include_router(router)

    # Serve the compiled frontend if dist/ exists (single-container deployment)
    if FRONTEND_DIST.is_dir():
        logger.info("Serving frontend static files from %s", FRONTEND_DIST)
        app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIST / "assets")), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa_fallback(full_path: str):
            """Return index.html for any non-API path to support client-side routing."""
            index = FRONTEND_DIST / "index.html"
            if index.is_file():
                return FileResponse(str(index))
            return {"error": "index.html not found"}

    else:
        logger.info("Frontend dist not found at %s; skipping static file serving", FRONTEND_DIST)

    return app


app = create_app()
