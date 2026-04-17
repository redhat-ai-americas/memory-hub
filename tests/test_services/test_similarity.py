"""Unit tests for the curation similarity service.

Uses the same async in-memory SQLite fixtures as the other
test_services modules. The pgvector Vector column is swapped for a
JSON-encoded TEXT column so the fallback path inside ``check_similarity``
short-circuits gracefully on SQLite; ``get_similar_memories`` uses the
``cosine_distance`` operator unconditionally, so the pgvector-specific
behaviour is covered by the integration suite. What we cover here is the
tenant filtering logic, which applies regardless of backend.
"""

import pytest

from memoryhub_core.models.schemas import MemoryNodeCreate, MemoryScope
from memoryhub_core.services.curation.similarity import (
    check_similarity as _svc_check_similarity,
)
from memoryhub_core.services.curation.similarity import (
    get_similar_memories as _svc_get_similar_memories,
)
from memoryhub_core.services.exceptions import MemoryNotFoundError
from memoryhub_core.services.memory import create_memory as _svc_create_memory

_TEST_TENANT_ID = "default"


def _make_create_data(**overrides) -> MemoryNodeCreate:
    defaults = {
        "content": "prefers Podman over Docker",
        "scope": MemoryScope.USER,
        "weight": 0.9,
        "owner_id": "user-123",
    }
    defaults.update(overrides)
    return MemoryNodeCreate(**defaults)


# -- check_similarity tenant isolation --


async def test_check_similarity_sqlite_fallback_is_tenant_safe(
    async_session, embedding_service
):
    """On SQLite the check_similarity pgvector call raises and we fall
    back to a clean "no similar" result -- but the function must still
    enforce tenant_id as a required kwarg so forgotten callers fail
    loudly rather than silently defaulting."""
    import inspect

    sig = inspect.signature(_svc_check_similarity)
    tenant_param = sig.parameters["tenant_id"]
    assert tenant_param.kind == inspect.Parameter.KEYWORD_ONLY
    assert tenant_param.default is inspect.Parameter.empty


# -- get_similar_memories tenant isolation --


async def test_get_similar_memories_returns_not_found_for_cross_tenant(
    async_session, embedding_service
):
    """A get_similar_memories call from tenant B targeting a tenant-A
    source ID must raise MemoryNotFoundError. The cross-tenant source
    lookup fires BEFORE the similarity scan, so it works on SQLite --
    the scan itself uses pgvector's cosine_distance and is covered by
    the integration suite.
    """
    created, _ = await _svc_create_memory(
        _make_create_data(content="tenant A source"),
        async_session,
        embedding_service,
        tenant_id="tenant_a",
    )

    # Cross-tenant call raises MemoryNotFoundError at the source
    # lookup, never reaching the pgvector-dependent scan.
    with pytest.raises(MemoryNotFoundError) as exc_info:
        await _svc_get_similar_memories(
            created.id, async_session, tenant_id="tenant_b"
        )
    assert exc_info.value.memory_id == created.id


async def test_get_similar_memories_cross_tenant_source_not_found_even_without_scan(
    async_session, embedding_service
):
    """A nonexistent tenant_id raises MemoryNotFoundError regardless of
    whether the scan would have fired. This verifies the source-level
    tenant filter alone is sufficient for cross-tenant isolation of the
    source ID."""
    created, _ = await _svc_create_memory(
        _make_create_data(content="tenant A source 2"),
        async_session,
        embedding_service,
        tenant_id="tenant_a",
    )
    # Arbitrary tenant ID that never existed.
    with pytest.raises(MemoryNotFoundError):
        await _svc_get_similar_memories(
            created.id, async_session, tenant_id="tenant_never_existed"
        )


async def test_get_similar_memories_tenant_id_is_keyword_only():
    """tenant_id must be keyword-only and required on get_similar_memories."""
    import inspect

    sig = inspect.signature(_svc_get_similar_memories)
    tenant_param = sig.parameters["tenant_id"]
    assert tenant_param.kind == inspect.Parameter.KEYWORD_ONLY
    assert tenant_param.default is inspect.Parameter.empty
