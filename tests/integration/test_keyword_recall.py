"""Integration tests for keyword recall in the non-focus search_memories() path.

Requires the compose stack (PostgreSQL + pgvector + tsvector):
podman compose -f tests/integration/compose.yaml up -d
    pytest tests/integration/test_keyword_recall.py
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from memoryhub_core.models.schemas import MemoryNodeCreate, MemoryScope
from memoryhub_core.services.memory import (
    create_memory as _svc_create_memory,
    search_memories as _svc_search_memories,
)

pytestmark = pytest.mark.integration

_TENANT = "default"


async def _create(content, session, embedding_service, **kwargs):
    return await _svc_create_memory(
        MemoryNodeCreate(content=content, scope="user", owner_id="test-user", **kwargs),
        session, embedding_service, tenant_id=_TENANT,
    )


async def _search(query, session, embedding_service, **kwargs):
    return await _svc_search_memories(
        query, session, embedding_service, tenant_id=_TENANT,
        owner_id="test-user", **kwargs,
    )


@pytest.fixture
async def _keyword_corpus(async_session, embedding_service):
    """Seed memories where keyword and vector recall diverge.

    MockEmbeddingService produces deterministic embeddings based on content
    hash. The keyword signal finds exact term matches that vector similarity
    might rank lower.
    """
    ids = {}
    docs = {
        "postgresql": "PostgreSQL is a powerful relational database management system with advanced JSONB support",
        "fastapi": "FastAPI is a modern high-performance Python web framework built on Starlette and Pydantic",
        "kubernetes": "Kubernetes orchestrates containerized applications across clusters of machines",
        "redis": "Redis provides blazing fast in-memory data caching and pub/sub messaging patterns",
    }
    for key, content in docs.items():
        result, _ = await _create(content, async_session, embedding_service)
        ids[key] = result.id
    return ids


@pytest.mark.asyncio
async def test_keyword_recall_finds_exact_term(
    async_session, embedding_service, _keyword_corpus
):
    """Keyword recall surfaces nodes matching exact query terms."""
    results = await _search(
        "PostgreSQL", async_session, embedding_service,
    )
    result_ids = {r[0].id for r in results}
    assert _keyword_corpus["postgresql"] in result_ids


@pytest.mark.asyncio
async def test_keyword_disabled_still_returns_results(
    async_session, embedding_service, _keyword_corpus
):
    """Disabling keyword still returns cosine results."""
    results = await _search(
        "database management", async_session, embedding_service,
        disabled_signals={"keyword"},
    )
    assert len(results) > 0


@pytest.mark.asyncio
async def test_keyword_on_off_may_differ(
    async_session, embedding_service, _keyword_corpus
):
    """Keyword on vs off can produce different ranking or candidate sets."""
    results_on = await _search(
        "PostgreSQL JSONB", async_session, embedding_service,
    )
    results_off = await _search(
        "PostgreSQL JSONB", async_session, embedding_service,
        disabled_signals={"keyword"},
    )

    ids_on = [r[0].id for r in results_on]
    ids_off = [r[0].id for r in results_off]

    scores_on = {r[0].id: r[1] for r in results_on}
    scores_off = {r[0].id: r[1] for r in results_off}

    # With keyword active, the PostgreSQL node should get a keyword boost.
    # The ranking or scores should differ (even if the same nodes appear).
    differs = (ids_on != ids_off) or (scores_on != scores_off)
    assert differs, (
        "keyword on/off produced identical results -- keyword recall may not be active"
    )


@pytest.mark.asyncio
async def test_keyword_boost_weight_zero_disables(
    async_session, embedding_service, _keyword_corpus
):
    """keyword_boost_weight=0.0 disables keyword, equivalent to disabled_signals."""
    results_zero = await _search(
        "PostgreSQL", async_session, embedding_service,
        keyword_boost_weight=0.0,
    )
    results_disabled = await _search(
        "PostgreSQL", async_session, embedding_service,
        disabled_signals={"keyword"},
    )

    ids_zero = [r[0].id for r in results_zero]
    ids_disabled = [r[0].id for r in results_disabled]
    assert ids_zero == ids_disabled


@pytest.mark.asyncio
async def test_rrf_scores_positive_and_sorted(
    async_session, embedding_service, _keyword_corpus
):
    """RRF blended scores are positive and in descending order."""
    results = await _search(
        "database caching", async_session, embedding_service,
    )
    scores = [s for _, s in results]
    assert all(s > 0.0 for s in scores)
    assert scores == sorted(scores, reverse=True)
