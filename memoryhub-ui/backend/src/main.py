"""FastAPI application factory for the MemoryHub UI BFF."""

import logging
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from src.access_admin import router as access_admin_router
from src.config import get_settings
from src.csrf import CrossSiteRequestGuard
from src.export_adapter import router as export_router
from src.graph_adapters import router as graph_router
from src.human_adapters import router as human_router
from src.memory_context import router as context_router
from src.routes import router
from src.search_adapter import router as search_router

logger = logging.getLogger(__name__)

# In the container, WORKDIR is /opt/app-root/src and frontend/dist is a sibling to src/.
# Locally, the frontend dist doesn't exist next to the backend — Vite proxy handles dev.
# Allow override via env var for flexibility.
_default_dist = Path(os.environ.get("FRONTEND_DIST", "/opt/app-root/src/frontend/dist"))
# Also check relative to this file (for local dev with a pre-built frontend)
_local_dist = Path(__file__).parent.parent.parent / "frontend" / "dist"
FRONTEND_DIST = _default_dist if _default_dist.is_dir() else _local_dist


def create_app() -> FastAPI:
    settings = get_settings()
    # Say at startup how people are identified, so a misconfiguration shows in
    # the pod log rather than as every request being refused.
    if settings.ui_role_source == "openshift-rbac":
        logger.info("Dashboard identity: mode=%s, roles=openshift-rbac (%s check, namespace %s), tenant=%s",
                    settings.ui_auth_mode, settings.ui_rbac_check, settings.rbac_namespace(),
                    settings.ui_tenant_id)
    else:
        admins, users = settings.human_access()
        logger.info("Dashboard identity: mode=%s, roles=lists, %d admin(s), %d user(s), tenant=%s",
                    settings.ui_auth_mode, len(admins), len(users), settings.ui_tenant_id)
    if settings.ui_auth_mode == "local":
        logger.warning("LOCAL identity mode: every request acts as %r; never use this in a cluster",
                       settings.ui_local_user)
    problem = settings.identity_problem()
    if problem:
        logger.error("Dashboard cannot authenticate anyone: %s", problem)
    cors_origins = [origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()]
    # Only explicitly configured origins may change state besides the dashboard's own.
    trusted_origins = [origin for origin in cors_origins if origin != "*"]
    if not cors_origins:
        cors_origins = ["*"]

    app = FastAPI(
        title="MemoryHub UI BFF",
        description="BFF API for the MemoryHub dashboard",
        version="0.1.0",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )

    # Refuse state-changing requests that another site's page triggers with the
    # dashboard's session cookie (src/csrf.py).
    app.add_middleware(CrossSiteRequestGuard, allowed_origins=trusted_origins)

    app.include_router(router)
    app.include_router(human_router)
    app.include_router(context_router)
    app.include_router(graph_router)
    app.include_router(search_router)
    app.include_router(export_router)
    app.include_router(access_admin_router)

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
