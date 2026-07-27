"""Shared test fixtures for memoryhub-local tests."""

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


@pytest.fixture
async def async_session():
    """Create an in-memory SQLite database with the full schema."""
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


@pytest.fixture
def backend():
    """SQLiteBackend instance."""
    return SQLiteBackend()
