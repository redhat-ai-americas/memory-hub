"""Shared test fixtures for memoryhub-local tests.

Parameterized by backend_type to run the same tests across SQLite and
PostgreSQL (when available). To add PostgreSQL, install asyncpg and set
MEMORYHUB_TEST_PG_URL=postgresql+asyncpg://user:pass@host/db.
"""

import os

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from memoryhub_local.models import (  # noqa: F401 -- import registers all tables
    Campaign,
    CampaignMembership,
    ContradictionReport,
    ConversationExtraction,
    ConversationExtractionFailure,
    ConversationMessage,
    ConversationThread,
    CuratorRule,
    MemoryNode,
    MemoryRelationship,
    Project,
    ProjectMembership,
    PurgeLog,
    ReconciliationDecision,
    RoleAssignment,
)
from memoryhub_local.models.base import Base
from memoryhub_local.storage.sqlite import SQLiteBackend


def _available_backends():
    """Return list of available backend types based on environment."""
    backends = ["sqlite"]
    if os.environ.get("MEMORYHUB_TEST_PG_URL"):
        backends.append("postgres")
    return backends


@pytest.fixture(params=_available_backends())
async def async_session(request):
    """Create a database session for the parameterized backend."""
    if request.param == "sqlite":
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            await conn.execute(text("PRAGMA journal_mode=WAL"))
            await conn.run_sync(Base.metadata.create_all)

        session_factory = async_sessionmaker(
            engine, class_=AsyncSession, expire_on_commit=False,
        )
        async with session_factory() as session:
            yield session

        await engine.dispose()

    elif request.param == "postgres":
        pg_url = os.environ["MEMORYHUB_TEST_PG_URL"]
        engine = create_async_engine(pg_url)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        session_factory = async_sessionmaker(
            engine, class_=AsyncSession, expire_on_commit=False,
        )
        async with session_factory() as session:
            yield session

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await engine.dispose()


@pytest.fixture
def backend(async_session):
    """Return the RecallBackend matching the current session's dialect."""
    dialect = async_session.bind.dialect.name
    if dialect == "sqlite":
        return SQLiteBackend()
    elif dialect == "postgresql":
        from memoryhub_local.storage.postgres import PostgresBackend
        return PostgresBackend()
    raise ValueError(f"No backend for dialect: {dialect}")
