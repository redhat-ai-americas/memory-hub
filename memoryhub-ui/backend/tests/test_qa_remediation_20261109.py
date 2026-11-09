"""Regression tests for the 2026-11-06 acceptance findings (PA-004b, SA-010, SEC-COOKIE, SA-028)."""

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import Depends, HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src import accounts
from src.access import current_viewer
from src.config import Settings, get_settings
from src.database import get_db
from src.main import create_app
from src.ui_common import SESSION_COOKIE, Viewer, make_session_cookie, session_cookie_kwargs

SUPER = Viewer("root", "Root", None, "account", "superuser")
PA = Viewer("pa", "PA", None, "account", "admin")


@pytest.fixture
async def env(monkeypatch):
    settings = Settings(
        ui_local_accounts=True,
        ui_session_secret="test-only",
        ui_tenant_id="tenant-a",
        ui_superuser_users="root",
        ui_public_base_url="https://dash.example.com",
    )
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    @event.listens_for(engine.sync_engine, "connect")
    def _fns(conn, _):
        conn.create_function("now", 0, lambda: datetime.now(UTC).isoformat())

    factory = async_sessionmaker(engine, expire_on_commit=False)
    ids = {}
    async with engine.begin() as c:
        await c.execute(
            text(
                "CREATE TABLE memoryhub_ui_accounts "
                "(id TEXT, tenant_id TEXT, username TEXT, role TEXT, status TEXT, session_version INTEGER)"
            )
        )
        await c.execute(
            text(
                "CREATE TABLE memoryhub_ui_revoked_sessions "
                "(token_hash TEXT PRIMARY KEY, tenant_id TEXT, username TEXT, revoked_at TEXT, expires_at TEXT)"
            )
        )
        await c.execute(
            text(
                "CREATE TABLE memoryhub_ui_invites (code TEXT PRIMARY KEY, tenant_id TEXT, role TEXT, email TEXT, "
                "note TEXT, created_by TEXT, "
                "created_at TEXT DEFAULT (datetime('now')), expires_at TEXT, used_by TEXT, used_at TEXT, "
                "revoked_at TEXT, revoked_by TEXT, revoke_reason TEXT)"
            )
        )
        for name, role in [("root", "admin"), ("pa", "admin"), ("pa2", "admin"), ("bob", "user")]:
            ids[name] = uuid.uuid4().hex
            await c.execute(
                text("INSERT INTO memoryhub_ui_accounts VALUES (:i, 'tenant-a', :u, :r, 'active', 0)"),
                {"i": ids[name], "u": name, "r": role},
            )
    monkeypatch.setattr(accounts, "ensure_tables", AsyncMock())
    monkeypatch.setattr(accounts, "audit", AsyncMock())
    monkeypatch.setattr(accounts, "_account_row", lambda row: dict(row._mapping))
    monkeypatch.setattr(accounts.uuid, "UUID", lambda value: value)
    yield SimpleNamespace(settings=settings, factory=factory, ids=ids)
    await engine.dispose()


async def _row(env, user):
    async with env.factory() as db:
        return (
            await db.execute(text("SELECT role, status FROM memoryhub_ui_accounts WHERE username = :u"), {"u": user})
        ).one()


@pytest.mark.parametrize("change", [{"role": "user"}, {"status": "disabled"}])
async def test_platform_admin_cannot_change_super_user(env, change):
    async with env.factory() as db:
        with pytest.raises(HTTPException) as exc:
            await accounts.update_account(env.ids["root"], accounts.AccountUpdate(**change), db, env.settings, PA)
    assert exc.value.status_code == 403
    assert tuple(await _row(env, "root")) == ("admin", "active")


async def test_regular_user_cannot_change_super_user(env):
    user = Viewer("bob", "Bob", None, "account", "user")
    async with env.factory() as db:
        with pytest.raises(HTTPException) as exc:
            await accounts.update_account(
                env.ids["root"], accounts.AccountUpdate(status="disabled"), db, env.settings, user
            )
    assert exc.value.status_code == 403


async def test_super_user_can_still_manage_platform_admins(env):
    async with env.factory() as db:
        await accounts.update_account(env.ids["pa"], accounts.AccountUpdate(role="user"), db, env.settings, SUPER)
    assert tuple(await _row(env, "pa")) == ("user", "active")


async def test_another_super_user_may_demote_a_super_user_while_one_remains(env):
    env.settings.ui_superuser_users = "root,pa2"
    other_super = Viewer("pa2", "PA2", None, "account", "superuser")
    async with env.factory() as db:
        await accounts.update_account(
            env.ids["root"], accounts.AccountUpdate(role="user"), db, env.settings, other_super
        )
    assert tuple(await _row(env, "root")) == ("user", "active")


async def test_removing_the_only_active_super_user_is_a_conflict(env):
    # Acting viewer holds a super-user session; the configured list names only "root".
    acting = Viewer("pa2", "PA2", None, "account", "superuser")
    async with env.factory() as db:
        with pytest.raises(HTTPException) as exc:
            await accounts.update_account(
                env.ids["root"], accounts.AccountUpdate(status="disabled"), db, env.settings, acting
            )
    assert exc.value.status_code == 409
    assert tuple(await _row(env, "root")) == ("admin", "active")


def test_session_cookie_is_secure_on_https():
    s = Settings(ui_public_base_url="https://dash.example.com")
    assert session_cookie_kwargs(s)["secure"] is True
    assert session_cookie_kwargs(Settings(ui_public_base_url="http://localhost:8080"))["secure"] is False
    assert session_cookie_kwargs(Settings(ui_public_base_url="http://x", ui_cookie_secure=True))["secure"] is True


async def test_logged_out_cookie_is_rejected_from_a_clean_client(env, monkeypatch):
    app = create_app()

    async def provider():
        async with env.factory() as db:
            yield db

    app.dependency_overrides[get_db] = provider
    app.dependency_overrides[get_settings] = lambda: env.settings
    monkeypatch.setattr("src.routes_admin.audit", AsyncMock())

    @app.get("/api/protected")
    async def protected(viewer=Depends(current_viewer)):
        return {"u": viewer.username}

    app.router.routes.insert(0, app.router.routes.pop())
    cookie = make_session_cookie("bob", env.settings, role="user", source="account")
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://t", cookies={SESSION_COOKIE: cookie}
    ) as c:
        assert (await c.get("/api/protected")).status_code == 200
        r = await c.post("/api/auth/logout")
        assert r.status_code == 200
        set_cookie = r.headers.get("set-cookie", "").lower()
        assert "secure" in set_cookie and "httponly" in set_cookie
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://t", cookies={SESSION_COOKIE: cookie}
    ) as clean:
        assert (await clean.get("/api/protected")).status_code == 401
    fresh = make_session_cookie("bob", env.settings, role="user", source="account", hours=13)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://t", cookies={SESSION_COOKIE: fresh}
    ) as c2:
        assert (await c2.get("/api/protected")).status_code == 200


async def _invite(env, viewer, **body):
    async with env.factory() as db:
        return await accounts.create_invite(accounts.InviteRequest(**body), MagicMock(), db, env.settings, viewer)


async def test_second_invite_for_same_email_supersedes_the_first(env):
    first = await _invite(env, PA, role="user", email="x@example.com")
    second = await _invite(env, PA, role="admin", email="X@example.com")
    assert second["superseded"] == [first["id"]]
    async with env.factory() as db:
        rows = (
            await db.execute(
                text("SELECT code, revoked_at IS NOT NULL, revoke_reason FROM memoryhub_ui_invites ORDER BY created_at")
            )
        ).all()
    states = {r[0]: (r[1], r[2]) for r in rows}
    assert states[first["code"]] == (1, "superseded") and states[second["code"]][0] == 0


async def test_revoked_invite_cannot_be_used_and_revoke_is_idempotent(env):
    inv = await _invite(env, PA, role="user", email="y@example.com")
    async with env.factory() as db:
        assert (await accounts.revoke_invite(inv["id"], db, env.settings, PA))["state"] == "revoked"
    async with env.factory() as db:
        with pytest.raises(HTTPException) as exc:
            await accounts.revoke_invite(inv["id"], db, env.settings, PA)
    assert exc.value.status_code == 404
    async with env.factory() as db:
        row = (
            await db.execute(
                text(
                    "SELECT count(*) FROM memoryhub_ui_invites "
                    "WHERE code = :c AND used_at IS NULL AND revoked_at IS NULL"
                ),
                {"c": inv["code"]},
            )
        ).scalar_one()
    assert row == 0


async def test_invite_from_other_tenant_cannot_be_revoked(env):
    inv = await _invite(env, PA, role="user", email="z@example.com")
    other = Settings(ui_local_accounts=True, ui_tenant_id="tenant-b", ui_session_secret="x")
    async with env.factory() as db:
        with pytest.raises(HTTPException) as exc:
            await accounts.revoke_invite(inv["id"], db, other, PA)
    assert exc.value.status_code == 404


async def test_dashboard_cannot_write_into_another_users_private_memory(monkeypatch):
    from src import routes_dashboard

    monkeypatch.setattr(routes_dashboard, "_writable_scope", AsyncMock())
    body = routes_dashboard.WriteMemoryRequest(content="planted", scope="user", owner_id="alice")
    with pytest.raises(HTTPException) as exc:
        await routes_dashboard.create_dashboard_memory(MagicMock(), Settings(ui_tenant_id="t"), SUPER, body)
    assert exc.value.status_code == 403


async def test_linking_a_foreign_tenant_agent_is_refused(monkeypatch):
    from src import routes, routes_admin

    monkeypatch.setattr("src.ownership.explicit_owners", AsyncMock(return_value={}))
    monkeypatch.setattr("src.ownership.verify_client_secret", AsyncMock(return_value=True))
    monkeypatch.setattr(routes, "client_in_tenant", AsyncMock(return_value=False))
    monkeypatch.setattr(routes_admin, "viewer_from_request", lambda *a: Viewer("bob", "Bob", None, "account", "user"))
    with pytest.raises(HTTPException) as exc:
        await routes_admin.link_agent(
            routes_admin.LinkAgentRequest(client_id="xu-agent", client_secret="s"), MagicMock(), MagicMock(), Settings()
        )
    assert exc.value.status_code == 403
