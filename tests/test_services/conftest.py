"""Shared fixtures for test_services tests.

Provides the SQLite-compatible async session and embedding service used across
all service-layer tests. PostgreSQL-specific column types are swapped for
portable equivalents from memoryhub_local.models.dialect so the schema can
be created on SQLite without the pgvector extension or JSONB casts.

New PostgreSQL-specific features (ARRAY columns, GIN indexes, custom operators,
JSONB casts) should be tested against real PostgreSQL via tests/integration/.
Run ``make test-integration`` to exercise those paths.
"""

from contextlib import contextmanager

import pytest
from memoryhub_local.models.dialect import JsonEncodedList, JsonEncodedVector
from sqlalchemy import Text, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from memoryhub_core.models.base import Base
from memoryhub_core.models.campaign import (  # noqa: F401
    Campaign,
    CampaignMembership,
)
from memoryhub_core.models.conversation import (  # noqa: F401
    ConversationExtraction,
    ConversationThread,
)
from memoryhub_core.models.curation import CuratorRule
from memoryhub_core.models.memory import MemoryNode, MemoryRelationship
from memoryhub_core.models.project import Project, ProjectMembership  # noqa: F401
from memoryhub_core.models.reconciliation import ReconciliationDecision  # noqa: F401
from memoryhub_core.services.embeddings import MockEmbeddingService


@contextmanager
def _sqlite_schema_patches():
    """Temporarily swap PostgreSQL-specific column types for SQLite-portable equivalents.

    Uses production type decorators from memoryhub_local.models.dialect
    instead of test-only copies. Restores all original types on exit.
    """
    patches = []

    def _swap_type(col, new_type):
        patches.append(("type", col, col.type))
        col.type = new_type

    def _swap_default(col):
        patches.append(("default", col, col.server_default))
        col.server_default = None

    # Vector column: pgvector Vector -> JSON-encoded TEXT
    _swap_type(MemoryNode.__table__.c.embedding, JsonEncodedVector())

    # ARRAY(Text) columns -> JSON-encoded TEXT
    _swap_type(MemoryNode.__table__.c.domains, JsonEncodedList())
    _swap_default(MemoryNode.__table__.c.domains)

    _swap_type(ConversationThread.__table__.c.participant_ids, JsonEncodedList())
    _swap_default(ConversationThread.__table__.c.participant_ids)

    _swap_type(ConversationExtraction.__table__.c.source_messages, JsonEncodedList())
    _swap_default(ConversationExtraction.__table__.c.source_messages)

    # JSONB server_defaults ('{}'::jsonb casts)
    _swap_default(MemoryRelationship.__table__.c.metadata_)
    _swap_default(CuratorRule.__table__.c.config)

    # jsonb_typeof check constraint (PostgreSQL-only function)
    thread_table = ConversationThread.__table__
    removed_constraints = {
        c for c in thread_table.constraints
        if hasattr(c, "sqltext") and "jsonb_typeof" in str(c.sqltext)
    }
    thread_table.constraints -= removed_constraints

    # TSVECTOR search_vector: Computed(TSVECTOR) -> nullable Text
    memory_table = MemoryNode.__table__
    sv_col = memory_table.c.get("search_vector")
    original_sv_computed = None
    removed_sv_indexes = set()
    if sv_col is not None:
        _swap_type(sv_col, Text())
        original_sv_computed = sv_col.computed
        sv_col.computed = None
        removed_sv_indexes = {
            idx for idx in memory_table.indexes
            if any(c.name == "search_vector" for c in idx.columns)
        }
        memory_table.indexes -= removed_sv_indexes

    try:
        yield
    finally:
        for kind, col, original in reversed(patches):
            if kind == "type":
                col.type = original
            elif kind == "default":
                col.server_default = original
        thread_table.constraints |= removed_constraints
        if sv_col is not None and original_sv_computed is not None:
            sv_col.computed = original_sv_computed
            memory_table.indexes |= removed_sv_indexes


@pytest.fixture
async def async_session():
    """Create an in-memory SQLite database with the full schema."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    with _sqlite_schema_patches():
        async with engine.begin() as conn:
            await conn.execute(text("PRAGMA journal_mode=WAL"))
            await conn.run_sync(Base.metadata.create_all)

        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with session_factory() as session:
            yield session

    await engine.dispose()


@pytest.fixture
def embedding_service():
    return MockEmbeddingService()
