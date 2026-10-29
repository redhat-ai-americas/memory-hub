"""FastAPI application factory for the MemoryHub UI BFF."""

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from src.accounts import router as accounts_router
from src.breakglass import BreakGlassAuditMiddleware
from src.breakglass import router as breakglass_router
from src.config import get_settings
from src.documents import router as documents_router
from src.dreaming import router as dreams_router
from src.features import router as features_router
from src.jobs import router as jobs_router
from src.knowledge import router as knowledge_router
from src.me import router as me_router
from src.notifications import router as notifications_router
from src.packs import router as packs_router
from src.quality import router as quality_router
from src.retrieval import router as retrieval_router
from src.routes import router
from src.routes_admin import router as admin_router
from src.routes_dashboard import router as dashboard_router
from src.routes_workspace import router as workspace_router
from src.teams import router as teams_router
from src.ui_common import auth_enabled, read_session_cookie
from src.verify import router as verify_router

# Reachable without a session when development API-key login is enabled.
_PUBLIC_API = ("/api/auth/", "/api/public-config")

logger = logging.getLogger(__name__)

# In the container, WORKDIR is /opt/app-root/src and frontend/dist is a sibling to src/.
# Locally, the frontend dist doesn't exist next to the backend — Vite proxy handles dev.
# Allow override via env var for flexibility.
_default_dist = Path(os.environ.get("FRONTEND_DIST", "/opt/app-root/src/frontend/dist"))
# Also check relative to this file (for local dev with a pre-built frontend)
_local_dist = Path(__file__).parent.parent.parent / "frontend" / "dist"
FRONTEND_DIST = _default_dist if _default_dist.is_dir() else _local_dist


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Start the background scheduler (dreams, knowledge pages) with the app."""
    from src import scheduler, schema

    settings = get_settings()
    if settings.ui_migrate_on_start:
        try:
            await schema.upgrade()
        except Exception as exc:  # database not reachable yet: tables are migrated on first use
            logger.warning("UI schema migration did not run at startup: %s", exc)
    scheduler.start(settings)
    yield
    await scheduler.stop()


def create_app() -> FastAPI:
    settings = get_settings()
    cors_origins = [origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()]
    if not cors_origins:
        cors_origins = ["*"]

    app = FastAPI(
        title="MemoryHub UI BFF",
        description="Read-only BFF API for the MemoryHub dashboard",
        version="0.1.0",
        lifespan=lifespan,
    )

    # Audits every user memory a super-user opens under an incident grant (#667).
    app.add_middleware(BreakGlassAuditMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def require_dev_session(request: Request, call_next):
        """Gate /api behind a session when local accounts or the dev API key
        are enabled.

        Behind the OpenShift OAuth proxy (X-Forwarded-User present) or with
        neither enabled (open development mode), this is a no-op.
        """
        current = get_settings()
        path = request.url.path
        if (
            auth_enabled(current)
            and path.startswith("/api/")
            and not path.startswith(_PUBLIC_API)
            and not request.headers.get("x-forwarded-user")
            and not read_session_cookie(request, current)
        ):
            return JSONResponse({"detail": "Log in to the dashboard first"}, status_code=401)
        return await call_next(request)

    # Dashboard routers first so their static paths (e.g. /api/memories/browse)
    # win over the parameterised routes in the original router.
    app.include_router(accounts_router)
    app.include_router(teams_router)
    app.include_router(dreams_router)
    app.include_router(me_router)
    app.include_router(knowledge_router)
    app.include_router(documents_router)
    app.include_router(features_router)
    app.include_router(jobs_router)
    app.include_router(packs_router)
    app.include_router(verify_router)
    app.include_router(breakglass_router)
    app.include_router(quality_router)
    app.include_router(retrieval_router)
    app.include_router(notifications_router)
    app.include_router(workspace_router)
    app.include_router(dashboard_router)
    app.include_router(admin_router)
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
