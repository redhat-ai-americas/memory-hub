"""Cross-site request guard (src/csrf.py)."""

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from src.config import Settings
from src.csrf import CrossSiteRequestGuard
from src.main import app as dashboard_app
from src.main import create_app


def _app(allowed=None) -> FastAPI:
    app = FastAPI()
    app.add_middleware(CrossSiteRequestGuard, allowed_origins=allowed or [])

    @app.post("/api/clients/agent/rotate-secret")
    async def rotate():
        return {"rotated": True}

    @app.get("/api/me")
    async def me():
        return {"ok": True}

    return app


async def _post(app, headers, host="dash.apps.example.com"):
    async with AsyncClient(transport=ASGITransport(app=app), base_url=f"https://{host}") as client:
        return await client.post("/api/clients/agent/rotate-secret", headers=headers)


@pytest.mark.asyncio
@pytest.mark.parametrize("headers", [
    {"sec-fetch-site": "cross-site", "origin": "https://evil.example.org"},
    # Another Route on the cluster's *.apps domain is the same *site*.
    {"sec-fetch-site": "same-site", "origin": "https://other.apps.example.com"},
    {"origin": "https://evil.example.org"},
    {"origin": "null"},
    {"sec-fetch-site": "same-origin", "origin": "https://evil.example.org"},
])
async def test_cross_site_state_change_is_refused(headers):
    response = await _post(_app(), headers)
    assert response.status_code == 403
    assert response.json() == {"detail": "Cross-site request refused"}


@pytest.mark.asyncio
@pytest.mark.parametrize("headers", [
    {"sec-fetch-site": "same-origin", "origin": "https://dash.apps.example.com"},
    {"origin": "https://dash.apps.example.com:443"},
    {"sec-fetch-site": "none"},
    {},  # not a browser page: no ambient cookie to abuse
])
async def test_same_origin_and_non_browser_requests_pass(headers):
    response = await _post(_app(), headers)
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_forwarded_host_and_configured_origins_are_own():
    forwarded = {"origin": "https://memoryhub-ui-redhat-ods-applications.apps.example.com",
                 "x-forwarded-host": "memoryhub-ui-redhat-ods-applications.apps.example.com"}
    assert (await _post(_app(), forwarded, host="127.0.0.1:8080")).status_code == 200
    dev = {"origin": "http://localhost:5173"}
    assert (await _post(_app(["http://localhost:5173"]), dev, host="localhost:8080")).status_code == 200
    assert (await _post(_app(), dev, host="localhost:8080")).status_code == 403


@pytest.mark.asyncio
async def test_documented_vite_origin_uses_configured_csrf_allowlist(monkeypatch):
    # Vite proxies /api to :8080; the browser's Origin is still :3000.
    monkeypatch.setenv("MEMORYHUB_CORS_ORIGINS", "http://localhost:3000")
    monkeypatch.setattr("src.main.get_settings", lambda: Settings())
    app = create_app()

    @app.post("/api/vite-csrf-test")
    async def write():
        return {"saved": True}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://localhost:8080") as client:
        allowed = await client.post("/api/vite-csrf-test", headers={
            "origin": "http://localhost:3000", "sec-fetch-site": "same-origin",
        })
        refused = await client.post("/api/vite-csrf-test", headers={
            "origin": "http://localhost:3001", "sec-fetch-site": "same-origin",
        })
    assert allowed.status_code == 200
    assert allowed.json() == {"saved": True}
    assert refused.status_code == 403

    monkeypatch.setenv("MEMORYHUB_CORS_ORIGINS", "")
    unconfigured = create_app()
    response = await _post(unconfigured, {
        "origin": "http://localhost:3000", "sec-fetch-site": "same-origin",
    }, host="localhost:8080")
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_safe_methods_are_untouched():
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="https://dash") as client:
        response = await client.get("/api/me", headers={"sec-fetch-site": "cross-site",
                                                        "origin": "https://evil.example.org"})
    assert response.status_code == 200


def test_dashboard_app_installs_the_guard():
    assert any(m.cls is CrossSiteRequestGuard for m in dashboard_app.user_middleware)
