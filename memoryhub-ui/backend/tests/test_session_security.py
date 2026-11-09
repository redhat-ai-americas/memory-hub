"""Exercise the HTTP authentication boundary with real database state changes."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import Depends
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src import accounts
from src.access import current_viewer
from src.config import Settings, get_settings
from src.database import get_db
from src.main import create_app
from src.ui_common import SESSION_COOKIE, Viewer, make_session_cookie


@pytest.fixture
async def secured_app(monkeypatch):
    settings = Settings(ui_local_accounts=True, ui_session_secret="test-only", ui_tenant_id="tenant-a")
    app = create_app()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    account_id = uuid.uuid4()
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "CREATE TABLE memoryhub_ui_accounts "
                "(id TEXT, tenant_id TEXT, username TEXT, role TEXT, status TEXT, session_version INTEGER)"
            )
        )
        await connection.execute(
            text("INSERT INTO memoryhub_ui_accounts VALUES (:id, 'tenant-a', 'alice', 'admin', 'active', 0)"),
            {"id": account_id.hex},
        )
        await connection.execute(
            text(
                "CREATE TABLE memoryhub_ui_revoked_sessions "
                "(token_hash TEXT PRIMARY KEY, tenant_id TEXT, username TEXT, revoked_at TEXT, expires_at TEXT)"
            )
        )

    async def db_provider():
        async with factory() as db:
            yield db

    app.dependency_overrides[get_db] = db_provider
    app.dependency_overrides[get_settings] = lambda: settings
    monkeypatch.setattr(accounts, "ensure_tables", AsyncMock())

    @app.get("/api/protected")
    async def protected(viewer=Depends(current_viewer)):
        return {"username": viewer.username, "role": viewer.role}

    app.router.routes.insert(0, app.router.routes.pop())
    yield SimpleNamespace(app=app, settings=settings, factory=factory, account_id=account_id)
    await engine.dispose()


async def test_forwarded_headers_cannot_bypass_local_login(secured_app):
    async with AsyncClient(transport=ASGITransport(app=secured_app.app), base_url="http://test") as client:
        response = await client.get(
            "/api/protected",
            headers={
                "x-forwarded-user": "root",
                "x-forwarded-groups": "memoryhub-superusers",
            },
        )
    assert response.status_code == 401


async def test_local_identity_wins_over_forged_proxy_identity(secured_app):
    s = secured_app
    s.settings.ui_trust_proxy_headers = True
    cookie = make_session_cookie("alice", s.settings, source="account")
    async with AsyncClient(
        transport=ASGITransport(app=s.app), base_url="http://test", cookies={SESSION_COOKIE: cookie}
    ) as client:
        response = await client.get(
            "/api/protected", headers={"x-forwarded-user": "root", "x-forwarded-groups": "memoryhub-superusers"}
        )
    assert response.json() == {"username": "alice", "role": "admin"}


@pytest.mark.parametrize(
    "change", ["status = 'disabled'", "role = 'user'", "session_version = 1", "tenant_id = 'tenant-b'"]
)
async def test_existing_cookie_loses_access_on_account_change(secured_app, change):
    s = secured_app
    cookie = make_session_cookie("alice", s.settings, source="account")
    async with AsyncClient(
        transport=ASGITransport(app=s.app), base_url="http://test", cookies={SESSION_COOKIE: cookie}
    ) as client:
        assert (await client.get("/api/protected")).status_code == 200
        async with s.factory() as db:
            await db.execute(text(f"UPDATE memoryhub_ui_accounts SET {change}"))
            await db.commit()
        assert (await client.get("/api/protected")).status_code == 401


async def test_disabling_and_reenabling_does_not_revive_cookie(secured_app, monkeypatch):
    s = secured_app
    monkeypatch.setattr(accounts, "audit", AsyncMock())
    monkeypatch.setattr(accounts, "_account_row", lambda row: dict(row._mapping))
    second_admin_id = uuid.uuid4().hex
    # SQLite's text driver uses string UUIDs, unlike the PostgreSQL driver.
    monkeypatch.setattr(accounts.uuid, "UUID", lambda value: s.account_id.hex)
    admin = Viewer("bob", "Bob", None, "account", "admin")
    async with s.factory() as db:
        await db.execute(
            text("INSERT INTO memoryhub_ui_accounts VALUES (:id, 'tenant-a', 'bob', 'admin', 'active', 0)"),
            {"id": second_admin_id},
        )
        await accounts.update_account(
            str(s.account_id), accounts.AccountUpdate(status="disabled"), db, s.settings, admin
        )
        await accounts.update_account(str(s.account_id), accounts.AccountUpdate(status="active"), db, s.settings, admin)
        row = (await db.execute(text(
            "SELECT session_version FROM memoryhub_ui_accounts WHERE username = 'alice'"
        ))).scalar_one()
        assert row == 2
    cookie = make_session_cookie("alice", s.settings, source="account")
    async with AsyncClient(
        transport=ASGITransport(app=s.app), base_url="http://test", cookies={SESSION_COOKIE: cookie}
    ) as client:
        assert (await client.get("/api/protected")).status_code == 401
        client.cookies.set(SESSION_COOKIE, make_session_cookie("alice", s.settings, source="account", version=2))
        assert (await client.get("/api/protected")).status_code == 200


async def test_trusted_proxy_requires_identity_and_explicit_mode(secured_app):
    s = secured_app
    s.settings.ui_local_accounts = False
    s.settings.ui_trust_proxy_headers = True
    async with AsyncClient(transport=ASGITransport(app=s.app), base_url="http://test") as client:
        assert (await client.get("/api/protected")).status_code == 401
        response = await client.get("/api/protected", headers={"x-forwarded-user": "alice"})
        assert response.json() == {"username": "alice", "role": "user"}
