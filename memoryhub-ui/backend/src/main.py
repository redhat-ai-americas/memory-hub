"""FastAPI application factory for the MemoryHub UI BFF."""

import logging
import os
from contextlib import aclosing, asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from src.accounts import router as accounts_router
from src.breakglass import BreakGlassAuditMiddleware
from src.breakglass import router as breakglass_router
from src.config import get_settings
from src.database import get_db
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
from src.ui_common import auth_enabled, proxy_auth_enabled, read_session
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
        """Validate local accounts on every request; trust headers only in proxy mode."""
        current = app.dependency_overrides.get(get_settings, get_settings)()
        path = request.url.path
        if not path.startswith("/api/"):
            return await call_next(request)
        session = read_session(request, current)
        if session and session.source == "account":
            from sqlalchemy import text

            from src.accounts import ACCOUNTS, ensure_tables

            provider = app.dependency_overrides.get(get_db, get_db)
            async with aclosing(provider()) as connection:
                db = await anext(connection)
                await ensure_tables(db)
                row = (
                    await db.execute(
                        text(
                            f"SELECT role, status, session_version FROM {ACCOUNTS} "
                            "WHERE tenant_id = :tenant AND username = :username"
                        ),
                        {"tenant": current.ui_tenant_id, "username": session.username},
                    )
                ).first()
                if (
                    row is None
                    or row._mapping["status"] != "active"
                    or row._mapping["role"] != session.role
                    or row._mapping["session_version"] != session.version
                ):
                    session = None
                else:
                    from src.ui_common import SESSION_COOKIE, session_token_hash

                    revoked = (
                        await db.execute(
                            text("SELECT 1 FROM memoryhub_ui_revoked_sessions WHERE token_hash = :h"),
                            {"h": session_token_hash(request.cookies.get(SESSION_COOKIE, ""))},
                        )
                    ).first()
                    if revoked is not None:
                        session = None
            request.state.account_session = session
        proxy_identity = proxy_auth_enabled(current) and (
            request.headers.get("x-forwarded-preferred-username") or request.headers.get("x-forwarded-user")
        )
        if auth_enabled(current) and not path.startswith(_PUBLIC_API) and not (proxy_identity or session):
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
