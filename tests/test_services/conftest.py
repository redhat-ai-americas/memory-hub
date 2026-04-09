"""Shared fixtures for test_services tests.

Provides the SQLite-compatible async session and embedding service used across
all service-layer tests. The pgvector Vector column is swapped for a JSON-encoded
TEXT column so the schema can be created without the pgvector extension.
"""

import json

import pytest
from sqlalchemy import Text, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.types import TypeDecorator

from memoryhub_core.models.base import Base
from memoryhub_core.models.campaign import Campaign, CampaignMembership  # noqa: F401 — import registers tables with Base
from memoryhub_core.models.contradiction import ContradictionReport
from memoryhub_core.models.curation import CuratorRule
from memoryhub_core.models.memory import MemoryNode, MemoryRelationship
from memoryhub_core.services.embeddings import MockEmbeddingService


class _JsonEncodedVector(TypeDecorator):
    """Store embedding vectors as JSON text in SQLite for testing."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None:
            return json.dumps(value)
        return None

    def process_result_value(self, value, dialect):
        if value is not None:
            return json.loads(value)
        return None


@pytest.fixture
async def async_session():
    """Create an in-memory SQLite database with the schema for testing.

    Patches the pgvector Vector column to a JSON-encoded TEXT column
    so that SQLite can store and retrieve embeddings.
    """
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    embedding_col = MemoryNode.__table__.c.embedding
    original_type = embedding_col.type
    embedding_col.type = _JsonEncodedVector()

    # Patch PostgreSQL-specific server_defaults ('{}'::jsonb casts) so
    # SQLite can create the tables.
    rel_metadata_col = MemoryRelationship.__table__.c.metadata_
    original_rel_metadata_default = rel_metadata_col.server_default
    rel_metadata_col.server_default = None

    rule_config_col = CuratorRule.__table__.c.config
    original_rule_config_default = rule_config_col.server_default
    rule_config_col.server_default = None

    # Patch ARRAY(Text) domains column to JSON-encoded TEXT for SQLite.
    domains_col = MemoryNode.__table__.c.domains
    original_domains_type = domains_col.type
    original_domains_default = domains_col.server_default
    domains_col.type = _JsonEncodedVector()  # reuse: list[str] ↔ JSON text
    domains_col.server_default = None

    try:
        async with engine.begin() as conn:
            await conn.execute(text("PRAGMA journal_mode=WAL"))
            await conn.run_sync(Base.metadata.create_all)

        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with session_factory() as session:
            yield session
    finally:
        embedding_col.type = original_type
        rel_metadata_col.server_default = original_rel_metadata_default
        rule_config_col.server_default = original_rule_config_default
        domains_col.type = original_domains_type
        domains_col.server_default = original_domains_default
        await engine.dispose()


@pytest.fixture
def embedding_service():
    return MockEmbeddingService()
