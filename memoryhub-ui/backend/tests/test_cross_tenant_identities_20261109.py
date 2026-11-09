"""QA 2026-11-09 RT-XT-01..04: identities from another tenant are refused by the dashboard."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src import routes
from src.config import Settings


@pytest.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    @event.listens_for(engine.sync_engine, "connect")
    def _fns(conn, _):
        conn.create_function("now", 0, lambda: datetime.now(UTC).isoformat())

    async with engine.begin() as c:
        await c.execute(text("CREATE TABLE memoryhub_ui_accounts (tenant_id TEXT, username TEXT)"))
        await c.execute(text("INSERT INTO memoryhub_ui_accounts VALUES ('tenant-a','alice'), ('tenant-b','bob')"))
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        yield session
    await engine.dispose()


def _settings(local=True):
    return Settings(ui_local_accounts=local, ui_tenant_id="tenant-a", ui_session_secret="t")


async def test_own_tenant_account_is_accepted(db, monkeypatch):
    monkeypatch.setattr(routes, "client_in_tenant", AsyncMock(return_value=False))
    assert await routes.require_identity_in_tenant(db, _settings(), " alice ") == "alice"


async def test_account_of_other_tenant_is_refused(db, monkeypatch):
    monkeypatch.setattr(routes, "client_in_tenant", AsyncMock(return_value=False))
    with pytest.raises(HTTPException) as exc:
        await routes.require_identity_in_tenant(db, _settings(), "bob")
    assert exc.value.status_code == 422


async def test_agent_known_in_own_tenant_is_accepted(db, monkeypatch):
    check = AsyncMock(return_value=True)
    monkeypatch.setattr(routes, "client_in_tenant", check)
    assert await routes.require_identity_in_tenant(db, _settings(), "a-agent") == "a-agent"
    check.assert_awaited_once()


async def test_foreign_or_unknown_agent_is_refused(db, monkeypatch):
    monkeypatch.setattr(routes, "client_in_tenant", AsyncMock(return_value=False))
    with pytest.raises(HTTPException):
        await routes.require_identity_in_tenant(db, _settings(), "b-agent")


async def test_empty_identity_is_refused(db):
    with pytest.raises(HTTPException):
        await routes.require_identity_in_tenant(db, _settings(), "  ")


async def test_sso_mode_cannot_enumerate_people_and_defers_to_mcp(db, monkeypatch):
    """Documented limitation: without local accounts, people are not enumerable here."""
    monkeypatch.setattr(routes, "client_in_tenant", AsyncMock(return_value=False))
    assert await routes.require_identity_in_tenant(db, _settings(local=False), "sso-user") == "sso-user"
