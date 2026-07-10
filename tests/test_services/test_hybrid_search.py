"""Tests for hybrid search (keyword recall + RRF blend, #305).

The keyword recall path uses PostgreSQL tsvector operators that aren't
available in SQLite. These unit tests verify:
1. The SQLite fallback path skips keyword recall gracefully.
2. The keyword_boost_weight=0 path disables keyword recall entirely.
3. The FocusedSearchResult includes keyword_matches metadata.

Full keyword recall + RRF integration tests live in tests/integration/
and require a running PostgreSQL+pgvector instance.
"""

import pytest

from memoryhub_core.models.schemas import MemoryNodeCreate
from memoryhub_core.services.memory import (
    create_memory,
    search_memories_with_focus,
)


@pytest.fixture
async def _seeded_memories(async_session, embedding_service):
    """Create a small corpus for search tests."""
    memories = [
        "Use kubectl apply -f deployment.yaml to deploy",
        "The CORS_ALLOWED_ORIGINS config key controls cross-origin requests",
        "React useState hook manages component state",
    ]
    ids = []
    for content in memories:
        data = MemoryNodeCreate(
            content=content,
            scope="user",
            owner_id="test-user",
        )
        result, _ = await create_memory(
            data=data,
            session=async_session,
            embedding_service=embedding_service,
            tenant_id="test-tenant",
        )
        ids.append(result.id)
    return ids


@pytest.mark.asyncio
async def test_keyword_boost_disabled_returns_results(
    async_session, embedding_service, _seeded_memories
):
    """With keyword_boost_weight=0, keyword recall is skipped entirely."""
    result = await search_memories_with_focus(
        query="kubectl deployment",
        session=async_session,
        embedding_service=embedding_service,
        tenant_id="test-tenant",
        focus_string="kubernetes operations",
        keyword_boost_weight=0.0,
        owner_id="test-user",
    )
    assert result.keyword_matches == 0
    assert len(result.results) > 0


@pytest.mark.asyncio
async def test_sqlite_skips_keyword_recall_gracefully(
    async_session, embedding_service, _seeded_memories
):
    """On SQLite, keyword recall fails silently and search still works."""
    result = await search_memories_with_focus(
        query="CORS_ALLOWED_ORIGINS",
        session=async_session,
        embedding_service=embedding_service,
        tenant_id="test-tenant",
        focus_string="configuration",
        keyword_boost_weight=0.15,
        owner_id="test-user",
    )
    # Keyword recall should have failed silently on SQLite
    assert result.keyword_matches == 0
    # But the search still returns results via vector recall
    assert len(result.results) > 0


@pytest.mark.asyncio
async def test_focused_search_result_has_keyword_matches_field(
    async_session, embedding_service, _seeded_memories
):
    """FocusedSearchResult always includes keyword_matches metadata."""
    result = await search_memories_with_focus(
        query="React",
        session=async_session,
        embedding_service=embedding_service,
        tenant_id="test-tenant",
        focus_string="frontend development",
        owner_id="test-user",
    )
    assert hasattr(result, "keyword_matches")
    assert isinstance(result.keyword_matches, int)
