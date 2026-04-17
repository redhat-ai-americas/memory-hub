"""Shared test fixtures for memoryhub-auth."""
import os
import uuid
from datetime import UTC, datetime

import bcrypt
import pytest
import pytest_asyncio
import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Set env vars before importing src modules so AuthSettings picks them up.
os.environ.setdefault("AUTH_ISSUER", "https://test-auth.example.com")
os.environ.setdefault("AUTH_KEYS_DIR", "/tmp/memoryhub-auth-test-keys")
os.environ.setdefault("AUTH_ACCESS_TOKEN_TTL", "300")
os.environ.setdefault("AUTH_REFRESH_TOKEN_TTL", "3600")

from src.keys import load_keys  # noqa: E402
from src.models import Base, OAuthClient  # noqa: E402

# ---------------------------------------------------------------------------
# Key loading — once per session
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session", autouse=True)
def _load_test_keys():
    """Generate (or reuse) RSA keys once for the entire test session."""
    load_keys()


# ---------------------------------------------------------------------------
# SQLite-compatible engine
# ---------------------------------------------------------------------------


def _strip_pg_server_defaults(metadata: sa.MetaData) -> dict:
    """Remove PostgreSQL-only server defaults and return them for restoration."""
    stripped: dict[tuple[str, str], sa.schema.FetchedValue | sa.schema.DefaultClause] = {}
    for table in metadata.sorted_tables:
        for col in table.columns:
            if col.server_default is not None:
                default_str = ""
                if hasattr(col.server_default, "arg"):
                    default_str = str(col.server_default.arg)
                if "uuid_generate" in default_str:
                    stripped[(table.name, col.name)] = col.server_default
                    col.server_default = None
    return stripped


def _restore_server_defaults(metadata: sa.MetaData, stripped: dict) -> None:
    """Restore previously removed server defaults."""
    for (table_name, col_name), default in stripped.items():
        metadata.tables[table_name].columns[col_name].server_default = default


def _attach_uuid_listener(engine):
    """Attach an event listener that assigns Python-side UUIDs before INSERT.

    This compensates for the missing uuid_generate_v4() server default on SQLite.
    The production code (token routes) creates RefreshToken without an explicit id,
    so we must supply one here.
    """

    @event.listens_for(engine.sync_engine, "before_cursor_execute", retval=True)
    def _noop(conn, cursor, statement, parameters, context, executemany):
        return statement, parameters

    # Use a session-level before_flush hook instead, so it fires for ORM inserts.
    # This is attached per-session in the db_session fixture.


def _ensure_uuid(instance):
    """Set id to a new UUID string if the instance has no id yet."""
    if hasattr(instance, "id") and not instance.id:
        instance.id = str(uuid.uuid4())


@pytest_asyncio.fixture
async def db_engine():
    """In-memory SQLite engine with tables created from Base.metadata."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    stripped = _strip_pg_server_defaults(Base.metadata)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    finally:
        _restore_server_defaults(Base.metadata, stripped)

    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine):
    """Yield an async session; roll back after each test."""
    session_factory = async_sessionmaker(
        db_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with session_factory() as session:
        # Auto-assign UUIDs for any ORM object that lacks one before flush.
        @event.listens_for(session.sync_session, "before_flush")
        def _assign_uuids(sess, flush_context, instances):
            for obj in sess.new:
                _ensure_uuid(obj)

        yield session
        await session.rollback()


# ---------------------------------------------------------------------------
# FastAPI app + httpx client
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def client(db_engine):
    """AsyncClient wired to the FastAPI app, using the test SQLite database."""
    # Import app late so env vars are already set when the module loads.
    from src.database import get_session
    from src.main import app

    session_factory = async_sessionmaker(
        db_engine, class_=AsyncSession, expire_on_commit=False
    )

    async def _override_get_session():
        async with session_factory() as session:
            @event.listens_for(session.sync_session, "before_flush")
            def _assign_uuids(sess, flush_context, instances):
                for obj in sess.new:
                    _ensure_uuid(obj)

            yield session

    app.dependency_overrides[get_session] = _override_get_session

    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as ac:
        yield ac

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Sample data fixtures
# ---------------------------------------------------------------------------

TEST_CLIENT_SECRET = "test-secret-123"
TEST_CLIENT_SECRET_HASH = bcrypt.hashpw(
    TEST_CLIENT_SECRET.encode(), bcrypt.gensalt()
).decode()


@pytest_asyncio.fixture
async def sample_client(db_session) -> OAuthClient:
    """Active OAuth client available for most tests."""
    obj = OAuthClient(
        id=str(uuid.uuid4()),
        client_id="test-agent",
        client_secret_hash=TEST_CLIENT_SECRET_HASH,
        client_name="Test Agent",
        identity_type="user",
        tenant_id="test-tenant",
        default_scopes=["memory:read", "memory:write:user"],
        active=True,
        redirect_uris=["https://example.com/callback"],
        public=False,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    db_session.add(obj)
    await db_session.commit()
    return obj


@pytest_asyncio.fixture
async def inactive_client(db_session) -> OAuthClient:
    """Inactive OAuth client for rejection tests."""
    obj = OAuthClient(
        id=str(uuid.uuid4()),
        client_id="inactive-agent",
        client_secret_hash=bcrypt.hashpw(b"inactive-secret", bcrypt.gensalt()).decode(),
        client_name="Inactive Agent",
        identity_type="user",
        tenant_id="test-tenant",
        default_scopes=["memory:read"],
        active=False,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    db_session.add(obj)
    await db_session.commit()
    return obj


@pytest_asyncio.fixture
async def public_client(db_session) -> OAuthClient:
    """Public OAuth client (no secret required, PKCE only)."""
    obj = OAuthClient(
        id=str(uuid.uuid4()),
        client_id="librechat",
        client_secret_hash="",  # public clients have no secret
        client_name="LibreChat",
        identity_type="user",
        tenant_id="default",
        default_scopes=["memory:read:user", "memory:write:user"],
        active=True,
        redirect_uris=["https://librechat.example.com/api/mcp/memoryhub/oauth/callback"],
        public=True,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    db_session.add(obj)
    await db_session.commit()
    return obj
