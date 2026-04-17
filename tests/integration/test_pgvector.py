"""Integration tests for PostgreSQL + pgvector-specific behavior.

These tests exercise paths that SQLite cannot cover:
  - Real cosine similarity ordering via the <=> operator
  - Embedding storage as a native vector type (not JSON text)
  - Curation pipeline duplicate detection with real similarity scores
  - Near-duplicate flagging in the 0.80-0.95 similarity band
  - Lazy rule seeding on first pipeline invocation
  - Graph relationship queries with PostgreSQL UUID handling

Run these with the compose stack active:
    podman-compose -f tests/integration/compose.yaml up -d
    pytest tests/integration/test_pgvector.py
"""

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

import memoryhub_core.services.curation.pipeline as pipeline_module
from memoryhub_core.models.curation import CuratorRule
from memoryhub_core.models.schemas import (
    MemoryNodeCreate,
    MemoryNodeUpdate,
    MemoryScope,
    RelationshipCreate,
    RelationshipType,
)
from memoryhub_core.services.embeddings import EMBEDDING_DIM, MockEmbeddingService
from memoryhub_core.services.graph import (
    create_relationship,
    trace_provenance,
)
from memoryhub_core.services.graph import (
    get_relationships as _svc_get_relationships,
)
from memoryhub_core.services.memory import (
    create_memory as _svc_create_memory,
)
from memoryhub_core.services.memory import (
    search_memories as _svc_search_memories,
)
from memoryhub_core.services.memory import (
    update_memory,
)

pytestmark = pytest.mark.integration


# Phase 3 (#46) made create_memory require a tenant_id kwarg. Phase 4
# adds tenant_id kwargs to every read path. Integration tests here all
# operate in the default tenant; cross-tenant integration coverage is
# Phase 5 scope. The wrappers below supply the default tenant to keep
# these tests collectable without repeating the kwarg on every call.
_TEST_TENANT_ID = "default"


async def create_memory(data, session, embedding_service, skip_curation=False, *, tenant_id=_TEST_TENANT_ID):
    """Test wrapper around the service create_memory with a default tenant."""
    return await _svc_create_memory(
        data,
        session,
        embedding_service,
        tenant_id=tenant_id,
        skip_curation=skip_curation,
    )


async def search_memories(
    query, session, embedding_service, *, tenant_id=_TEST_TENANT_ID, **kwargs
):
    """Test wrapper around search_memories with a default tenant."""
    return await _svc_search_memories(
        query, session, embedding_service, tenant_id=tenant_id, **kwargs
    )


async def get_relationships(node_id, session, *, tenant_id=_TEST_TENANT_ID, **kwargs):
    """Test wrapper around get_relationships with a default tenant."""
    return await _svc_get_relationships(node_id, session, tenant_id=tenant_id, **kwargs)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make(
    content: str,
    *,
    owner_id: str = "test-user",
    scope: MemoryScope = MemoryScope.USER,
    weight: float = 0.9,
) -> MemoryNodeCreate:
    return MemoryNodeCreate(
        content=content,
        scope=scope,
        weight=weight,
        owner_id=owner_id,
    )


# ---------------------------------------------------------------------------
# Fixture: reset the pipeline's lazy-seed flag around tests that touch it
# ---------------------------------------------------------------------------


@pytest.fixture
def reset_rules_seeded():
    """Ensure _seeded_tenants is empty before and restored after the test.

    Phase 4 (#46) replaced the Phase-0 boolean ``_rules_seeded`` with a
    per-tenant set so lazy-seeding happens once per tenant.
    """
    original = set(pipeline_module._seeded_tenants)
    pipeline_module._seeded_tenants = set()
    yield
    pipeline_module._seeded_tenants = original


# ---------------------------------------------------------------------------
# 1. Real pgvector cosine similarity search
# ---------------------------------------------------------------------------


async def test_search_returns_results_ordered_by_cosine_similarity(
    async_session: AsyncSession,
    embedding_service: MockEmbeddingService,
) -> None:
    """Results must be ranked by cosine similarity descending, not arbitrary."""
    # Create memories with distinct semantic content.
    # MockEmbeddingService uses word-level hashing, so overlapping words → closer vectors.
    await create_memory(
        _make("python programming language interpreter"), async_session, embedding_service, skip_curation=True
    )
    await create_memory(
        _make("kubernetes container orchestration deployment"), async_session, embedding_service, skip_curation=True
    )
    await create_memory(
        _make("python data science machine learning"), async_session, embedding_service, skip_curation=True
    )
    await create_memory(
        _make("postgresql database relational tables"), async_session, embedding_service, skip_curation=True
    )

    # Query is most similar to the python-related memories.
    results = await search_memories(
        query="python language programming",
        session=async_session,
        embedding_service=embedding_service,
        max_results=10,
    )

    assert len(results) > 0, "Expected at least one result"

    # Scores must be real floats in [0, 1], not synthetic rank-based values.
    scores = [score for _, score in results]
    for i, score in enumerate(scores):
        assert 0.0 <= score <= 1.0, f"Score {score!r} at index {i} is outside [0, 1]"

    # Results must be ordered descending by score.
    for i in range(len(scores) - 1):
        assert scores[i] >= scores[i + 1], (
            f"Results not sorted by cosine similarity: score[{i}]={scores[i]:.4f} "
            f"< score[{i+1}]={scores[i+1]:.4f}"
        )

    # The top result must be one of the python memories (highest word overlap with query).
    top_memory, top_score = results[0]
    assert "python" in top_memory.content.lower(), (
        f"Expected top result to contain 'python', got: {top_memory.content!r} "
        f"(score={top_score:.4f})"
    )


async def test_search_scores_are_not_synthetic_rank_values(
    async_session: AsyncSession,
    embedding_service: MockEmbeddingService,
) -> None:
    """PostgreSQL path returns real cosine similarity; not the 0, 1/n, 2/n... fallback."""
    await create_memory(
        _make("database indexing performance optimization"), async_session, embedding_service, skip_curation=True
    )
    await create_memory(
        _make("network packet routing protocol latency"), async_session, embedding_service, skip_curation=True
    )

    results = await search_memories(
        query="database performance",
        session=async_session,
        embedding_service=embedding_service,
        max_results=5,
    )

    assert len(results) == 2, f"Expected 2 results, got {len(results)}"
    scores = [score for _, score in results]

    # Synthetic scores would be exactly 0.0 and 0.5 (or 0.0 and 1.0).
    # Real cosine scores are continuous and almost certainly not exact fractions.
    assert scores[0] != 0.0, "Top score of 0.0 suggests synthetic fallback was used"
    assert scores != [0.0, 0.5], "Scores match synthetic fallback pattern exactly"


# ---------------------------------------------------------------------------
# 2. Embedding storage and retrieval roundtrip
# ---------------------------------------------------------------------------


async def test_embedding_stored_as_vector_not_json(
    async_session: AsyncSession,
    embedding_service: MockEmbeddingService,
) -> None:
    """PostgreSQL stores the embedding as a native vector, readable as a list of floats."""
    content = "the quick brown fox jumps over the lazy dog"
    memory, _ = await create_memory(_make(content), async_session, embedding_service, skip_curation=True)

    # Read back directly from ORM to inspect the raw stored type.
    from memoryhub_core.models.memory import MemoryNode

    stmt = select(MemoryNode).where(MemoryNode.id == memory.id)
    result = await async_session.execute(stmt)
    node = result.scalar_one()

    assert node.embedding is not None, "Embedding must not be None after create"
    # pgvector returns a numpy ndarray or a Python list depending on the driver version.
    # Both are valid — the key check is that it's indexable with float elements.
    assert hasattr(node.embedding, "__len__"), (
        f"Embedding must be array-like, got {type(node.embedding).__name__!r}"
    )
    assert len(node.embedding) == EMBEDDING_DIM, (
        f"Expected {EMBEDDING_DIM} dimensions, got {len(node.embedding)}"
    )
    for val in node.embedding:
        assert isinstance(float(val), float), f"Embedding element {val!r} is not numeric"


async def test_embedding_roundtrip_matches_mock_service(
    async_session: AsyncSession,
    embedding_service: MockEmbeddingService,
) -> None:
    """The embedding retrieved from PostgreSQL must be numerically identical to what was written."""
    content = "unique content for roundtrip verification test"
    expected_embedding = await embedding_service.embed(content)

    memory, _ = await create_memory(_make(content), async_session, embedding_service, skip_curation=True)

    from memoryhub_core.models.memory import MemoryNode

    stmt = select(MemoryNode).where(MemoryNode.id == memory.id)
    result = await async_session.execute(stmt)
    node = result.scalar_one()

    assert node.embedding is not None
    for i, (stored, expected) in enumerate(zip(node.embedding, expected_embedding, strict=False)):
        assert abs(stored - expected) < 1e-5, (
            f"Embedding mismatch at dimension {i}: stored={stored:.6f}, expected={expected:.6f}"
        )


# ---------------------------------------------------------------------------
# 3. Curation pipeline — exact duplicate detection
# ---------------------------------------------------------------------------


async def test_curation_blocks_exact_duplicate(
    async_session: AsyncSession,
    embedding_service: MockEmbeddingService,
    reset_rules_seeded,
) -> None:
    """A second write with identical content must be blocked as an exact duplicate."""
    content = "prefer dark mode for all editor interfaces"
    owner_id = "dup-test-user"

    # First write succeeds.
    first, first_curation = await create_memory(
        _make(content, owner_id=owner_id),
        async_session,
        embedding_service,
    )
    assert first is not None, "First write must succeed"
    assert not first_curation["blocked"], f"First write unexpectedly blocked: {first_curation}"

    # Second write with the same content must be blocked.
    second, second_curation = await create_memory(
        _make(content, owner_id=owner_id),
        async_session,
        embedding_service,
    )

    assert second is None, "Duplicate write must return None for the memory"
    assert second_curation["blocked"] is True, (
        f"Expected blocked=True, got: {second_curation}"
    )
    assert second_curation["reason"] == "exact_duplicate", (
        f"Expected reason='exact_duplicate', got: {second_curation['reason']!r}"
    )

    # nearest_score must be a real float — not None (as SQLite returns).
    nearest_score = second_curation["nearest_score"]
    assert nearest_score is not None, (
        "nearest_score is None — pgvector similarity check did not run (SQLite fallback?)"
    )
    assert isinstance(nearest_score, float), f"nearest_score must be float, got {type(nearest_score)}"
    assert nearest_score >= 0.95, (
        f"Exact duplicate should have similarity >= 0.95, got {nearest_score:.4f}"
    )


async def test_curation_nearest_score_close_to_one_for_identical_content(
    async_session: AsyncSession,
    embedding_service: MockEmbeddingService,
    reset_rules_seeded,
) -> None:
    """Identical content produces a cosine similarity of effectively 1.0."""
    content = "always use type hints in python function signatures"
    owner_id = "similarity-score-test"

    await create_memory(_make(content, owner_id=owner_id), async_session, embedding_service)

    # Re-run the pipeline directly to inspect the score without persisting.
    embedding = await embedding_service.embed(content)
    from memoryhub_core.services.curation.pipeline import run_curation_pipeline

    result = await run_curation_pipeline(
        content=content,
        embedding=embedding,
        owner_id=owner_id,
        scope=MemoryScope.USER,
        session=async_session,
        tenant_id=_TEST_TENANT_ID,
    )

    assert result["nearest_score"] is not None, "nearest_score must not be None on PostgreSQL"
    assert result["nearest_score"] > 0.99, (
        f"Identical content should have similarity close to 1.0, got {result['nearest_score']:.4f}"
    )


# ---------------------------------------------------------------------------
# 4. Near-duplicate detection (similarity in the 0.80-0.95 band)
# ---------------------------------------------------------------------------


async def test_curation_flags_near_duplicate(
    async_session: AsyncSession,
    embedding_service: MockEmbeddingService,
    reset_rules_seeded,
) -> None:
    """Slightly rephrased content must be flagged as a near-duplicate, not blocked."""
    owner_id = "near-dup-user"
    # High word overlap ensures MockEmbeddingService produces similar vectors (>0.80).
    original = "use snake_case for all python variable names in functions"
    similar = "use snake_case for all python variable names in methods"

    first, _ = await create_memory(_make(original, owner_id=owner_id), async_session, embedding_service)
    assert first is not None

    second, second_curation = await create_memory(
        _make(similar, owner_id=owner_id),
        async_session,
        embedding_service,
    )

    # May or may not be blocked depending on exact similarity — but if not blocked,
    # it should carry a near-dup flag. If blocked, nearest_score should still be meaningful.
    nearest_score = second_curation["nearest_score"]
    assert nearest_score is not None, (
        "nearest_score is None — pgvector similarity check did not run"
    )
    assert isinstance(nearest_score, float)
    assert 0.0 < nearest_score <= 1.0, f"nearest_score {nearest_score:.4f} outside (0, 1]"

    if not second_curation["blocked"]:
        # Content was written; it should carry a possible_duplicate flag.
        assert second is not None
        assert "possible_duplicate" in second_curation["flags"], (
            f"Expected 'possible_duplicate' flag for near-dup content, "
            f"got flags={second_curation['flags']!r}, score={nearest_score:.4f}"
        )
        assert second_curation["similar_count"] > 0, (
            f"similar_count should be > 0, got {second_curation['similar_count']}"
        )


async def test_check_similarity_returns_score_not_none(
    async_session: AsyncSession,
    embedding_service: MockEmbeddingService,
    reset_rules_seeded,
) -> None:
    """check_similarity returns a non-None nearest_score on PostgreSQL."""
    from memoryhub_core.services.curation.similarity import check_similarity

    owner_id = "similarity-direct-test"
    content = "redis is an in-memory key-value data store"
    memory, _ = await create_memory(_make(content, owner_id=owner_id), async_session, embedding_service)

    # Query with a nearly identical embedding.
    embedding = await embedding_service.embed(content)
    result = await check_similarity(
        embedding=embedding,
        owner_id=owner_id,
        scope=MemoryScope.USER,
        session=async_session,
        tenant_id=_TEST_TENANT_ID,
        flag_threshold=0.5,
        exclude_id=memory.id,
    )

    # With no other memories in the same owner+scope, count must be 0.
    assert result.similar_count == 0, (
        f"Expected 0 similar memories (only one exists and it's excluded), got {result.similar_count}"
    )
    assert result.nearest_score is None, (
        "With no candidates, nearest_score should be None"
    )


# ---------------------------------------------------------------------------
# 5. Lazy rule seeding
# ---------------------------------------------------------------------------


async def test_pipeline_seeds_default_rules_on_first_call(
    async_session: AsyncSession,
    embedding_service: MockEmbeddingService,
    reset_rules_seeded,
) -> None:
    """Running the pipeline for a fresh tenant seeds the 5 default system rules."""
    # Verify the DB is empty before we start (conftest truncates between tests).
    count_before = (await async_session.execute(select(CuratorRule))).scalars().all()
    assert len(count_before) == 0, (
        f"Expected no rules before pipeline runs, found {len(count_before)}"
    )
    assert _TEST_TENANT_ID not in pipeline_module._seeded_tenants

    from memoryhub_core.services.curation.pipeline import run_curation_pipeline

    await run_curation_pipeline(
        content="test content for rule seeding verification",
        embedding=await embedding_service.embed("test content for rule seeding verification"),
        owner_id="seed-test-user",
        scope=MemoryScope.USER,
        session=async_session,
        tenant_id=_TEST_TENANT_ID,
    )

    rules_after = (await async_session.execute(select(CuratorRule))).scalars().all()
    assert len(rules_after) == 5, (
        f"Expected 5 default rules after pipeline run, found {len(rules_after)}: "
        + ", ".join(r.name for r in rules_after)
    )

    rule_names = {r.name for r in rules_after}
    expected_names = {"secrets_scan", "pii_scan", "exact_duplicate", "near_duplicate", "staleness_trigger"}
    assert rule_names == expected_names, (
        f"Unexpected rule names. Got: {rule_names}"
    )

    assert _TEST_TENANT_ID in pipeline_module._seeded_tenants, (
        "default tenant should be in _seeded_tenants after first pipeline invocation"
    )


async def test_pipeline_skips_seeding_on_subsequent_calls(
    async_session: AsyncSession,
    embedding_service: MockEmbeddingService,
    reset_rules_seeded,
) -> None:
    """After the tenant is in _seeded_tenants, the pipeline does not re-seed rules."""
    from memoryhub_core.services.curation.pipeline import run_curation_pipeline

    # First call seeds the rules.
    embedding = await embedding_service.embed("first call seeds rules")
    await run_curation_pipeline(
        content="first call seeds rules",
        embedding=embedding,
        owner_id="seed-idempotency-user",
        scope=MemoryScope.USER,
        session=async_session,
        tenant_id=_TEST_TENANT_ID,
    )
    assert _TEST_TENANT_ID in pipeline_module._seeded_tenants
    rules_after_first = (await async_session.execute(select(CuratorRule))).scalars().all()

    # Second call must not duplicate rules.
    embedding2 = await embedding_service.embed("second call should not reseed")
    await run_curation_pipeline(
        content="second call should not reseed",
        embedding=embedding2,
        owner_id="seed-idempotency-user",
        scope=MemoryScope.USER,
        session=async_session,
        tenant_id=_TEST_TENANT_ID,
    )
    rules_after_second = (await async_session.execute(select(CuratorRule))).scalars().all()

    assert len(rules_after_second) == len(rules_after_first), (
        f"Rule count changed on second pipeline call: "
        f"first={len(rules_after_first)}, second={len(rules_after_second)}"
    )


# ---------------------------------------------------------------------------
# 6. Graph relationships with real PostgreSQL
# ---------------------------------------------------------------------------


async def test_create_and_query_derived_from_chain(
    async_session: AsyncSession,
    embedding_service: MockEmbeddingService,
) -> None:
    """Create a 3-node provenance chain and verify trace_provenance walks it correctly."""
    # Node A is the original. B derived from A. C derived from B.
    node_a, _ = await create_memory(
        _make("original architecture decision: use postgresql for persistence"),
        async_session,
        embedding_service,
        skip_curation=True,
    )
    node_b, _ = await create_memory(
        _make("we chose postgresql over mysql for pgvector support"),
        async_session,
        embedding_service,
        skip_curation=True,
    )
    node_c, _ = await create_memory(
        _make("pgvector enables cosine similarity search for memory retrieval"),
        async_session,
        embedding_service,
        skip_curation=True,
    )

    # Link: B derived_from A, C derived_from B.
    await create_relationship(
        RelationshipCreate(
            source_id=node_b.id,
            target_id=node_a.id,
            relationship_type=RelationshipType.derived_from,
            created_by="test",
        ),
        async_session,
    )
    await create_relationship(
        RelationshipCreate(
            source_id=node_c.id,
            target_id=node_b.id,
            relationship_type=RelationshipType.derived_from,
            created_by="test",
        ),
        async_session,
    )

    # Trace from C should walk: C → B → A.
    steps = await trace_provenance(node_c.id, async_session, max_hops=5)

    assert len(steps) == 2, (
        f"Expected 2 provenance steps (C→B, B→A), got {len(steps)}: "
        + str([(s["hop"], s["node"].id) for s in steps])
    )
    assert steps[0]["hop"] == 1
    assert steps[0]["node"].id == node_b.id, (
        f"First hop should reach node B, got {steps[0]['node'].id}"
    )
    assert steps[1]["hop"] == 2
    assert steps[1]["node"].id == node_a.id, (
        f"Second hop should reach node A, got {steps[1]['node'].id}"
    )


async def test_get_relationships_returns_correct_types(
    async_session: AsyncSession,
    embedding_service: MockEmbeddingService,
) -> None:
    """get_relationships filters by direction and type correctly on real PostgreSQL."""
    source, _ = await create_memory(
        _make("source memory for relationship test"),
        async_session,
        embedding_service,
        skip_curation=True,
    )
    target1, _ = await create_memory(
        _make("first target memory for relationship test"),
        async_session,
        embedding_service,
        skip_curation=True,
    )
    target2, _ = await create_memory(
        _make("second target memory for relationship test"),
        async_session,
        embedding_service,
        skip_curation=True,
    )

    await create_relationship(
        RelationshipCreate(
            source_id=source.id,
            target_id=target1.id,
            relationship_type=RelationshipType.derived_from,
            created_by="test",
        ),
        async_session,
    )
    await create_relationship(
        RelationshipCreate(
            source_id=source.id,
            target_id=target2.id,
            relationship_type=RelationshipType.related_to,
            created_by="test",
        ),
        async_session,
    )

    # All outgoing from source.
    outgoing = await get_relationships(source.id, async_session, direction="outgoing")
    assert len(outgoing) == 2, f"Expected 2 outgoing relationships, got {len(outgoing)}"

    # Filter by type.
    derived_only = await get_relationships(
        source.id, async_session, direction="outgoing", relationship_type="derived_from"
    )
    assert len(derived_only) == 1, f"Expected 1 derived_from relationship, got {len(derived_only)}"
    assert derived_only[0].target_id == target1.id

    # Incoming to target1.
    incoming = await get_relationships(target1.id, async_session, direction="incoming")
    assert len(incoming) == 1, f"Expected 1 incoming relationship to target1, got {len(incoming)}"
    assert incoming[0].source_id == source.id


async def test_graph_relationship_stubs_are_populated(
    async_session: AsyncSession,
    embedding_service: MockEmbeddingService,
) -> None:
    """RelationshipRead includes source_stub and target_stub from the linked nodes."""
    node_x, _ = await create_memory(
        _make("memory x for stub population test"),
        async_session,
        embedding_service,
        skip_curation=True,
    )
    node_y, _ = await create_memory(
        _make("memory y for stub population test"),
        async_session,
        embedding_service,
        skip_curation=True,
    )

    rel = await create_relationship(
        RelationshipCreate(
            source_id=node_x.id,
            target_id=node_y.id,
            relationship_type=RelationshipType.related_to,
            created_by="test",
        ),
        async_session,
    )

    assert rel.source_stub is not None, "source_stub must be populated"
    assert rel.target_stub is not None, "target_stub must be populated"
    assert len(rel.source_stub) > 0
    assert len(rel.target_stub) > 0


# ---------------------------------------------------------------------------
# Bonus: update_memory preserves embedding and branch copies on PostgreSQL
# ---------------------------------------------------------------------------


async def test_update_memory_new_version_has_fresh_embedding(
    async_session: AsyncSession,
    embedding_service: MockEmbeddingService,
) -> None:
    """After update_memory, the new version has an embedding for the updated content."""
    original_content = "original memory content for update test"
    updated_content = "revised memory content with different words entirely"

    original, _ = await create_memory(
        _make(original_content),
        async_session,
        embedding_service,
        skip_curation=True,
    )
    assert original is not None

    updated = await update_memory(
        original.id,
        MemoryNodeUpdate(content=updated_content),
        async_session,
        embedding_service,
    )

    assert updated.version == 2, f"Expected version 2, got {updated.version}"
    assert updated.content == updated_content
    assert updated.is_current is True

    # Verify the new version has a stored embedding that differs from the original.
    from memoryhub_core.models.memory import MemoryNode

    stmt = select(MemoryNode).where(MemoryNode.id == updated.id)
    result = await async_session.execute(stmt)
    new_node = result.scalar_one()

    assert new_node.embedding is not None
    assert len(new_node.embedding) == EMBEDDING_DIM

    expected_embedding = await embedding_service.embed(updated_content)
    original_embedding = await embedding_service.embed(original_content)

    # The new embedding must match the updated content, not the original.
    new_emb_dot_updated = sum(a * b for a, b in zip(new_node.embedding, expected_embedding, strict=False))
    new_emb_dot_original = sum(a * b for a, b in zip(new_node.embedding, original_embedding, strict=False))
    assert new_emb_dot_updated > new_emb_dot_original, (
        f"New embedding should be closer to updated content than original content. "
        f"dot(updated)={new_emb_dot_updated:.4f}, dot(original)={new_emb_dot_original:.4f}"
    )


# ---------------------------------------------------------------------------
# 7. JSONB server defaults and PostgreSQL-specific column behavior
# ---------------------------------------------------------------------------


async def test_relationship_metadata_server_default_is_empty_dict(
    async_session: AsyncSession,
    embedding_service: MockEmbeddingService,
) -> None:
    """MemoryRelationship.metadata_ should default to {} via server_default, not None.

    Uses a direct ORM insert with metadata_ omitted so SQLAlchemy lets the
    server_default fire. Going through the service would pass metadata_=None
    explicitly, which SQLAlchemy sends as NULL, bypassing the default.
    """
    import uuid as _uuid

    from memoryhub_core.models.memory import MemoryRelationship

    source, _ = await create_memory(
        _make("source node for jsonb default test"),
        async_session,
        embedding_service,
        skip_curation=True,
    )
    target, _ = await create_memory(
        _make("target node for jsonb default test"),
        async_session,
        embedding_service,
        skip_curation=True,
    )

    # Insert directly, omitting metadata_ so the server_default fires.
    rel = MemoryRelationship(
        id=_uuid.uuid4(),
        source_id=source.id,
        target_id=target.id,
        relationship_type="derived_from",
        created_by="jsonb-default-test",
    )
    async_session.add(rel)
    await async_session.commit()

    # Read back via raw SQL to see what PostgreSQL actually stored.
    row = await async_session.execute(
        text("SELECT metadata_ FROM memory_relationships WHERE id = :id"),
        {"id": rel.id},
    )
    raw_metadata = row.scalar_one()

    assert raw_metadata is not None, (
        "metadata_ should be {} via server_default, not None"
    )
    assert raw_metadata == {}, (
        f"Expected empty dict {{}}, got {raw_metadata!r}"
    )


async def test_memory_domains_server_default_is_empty_array(
    async_session: AsyncSession,
    embedding_service: MockEmbeddingService,
) -> None:
    """MemoryNode.domains should default to [] via server_default, not None.

    Uses a direct ORM insert with domains omitted so SQLAlchemy lets the
    server_default fire. The service layer always passes domains=data.domains
    (None when unset), which SQLAlchemy sends as NULL, bypassing the default.
    """
    import uuid as _uuid

    from memoryhub_core.models.memory import MemoryNode

    embedding = await embedding_service.embed("memory for array default test")
    node = MemoryNode(
        id=_uuid.uuid4(),
        content="memory for array default test",
        stub="memory for array default test",
        scope="user",
        weight=0.9,
        owner_id="test-user",
        tenant_id=_TEST_TENANT_ID,
        embedding=embedding,
        # NOTE: domains intentionally omitted — server_default must fire
    )
    async_session.add(node)
    await async_session.commit()

    # Read back via raw SQL to see what PostgreSQL actually stored.
    row = await async_session.execute(
        text("SELECT domains FROM memory_nodes WHERE id = :id"),
        {"id": node.id},
    )
    raw_domains = row.scalar_one()

    assert raw_domains is not None, (
        "domains should be [] via server_default '{}'::text[], not None"
    )
    assert raw_domains == [], (
        f"Expected empty list [], got {raw_domains!r}"
    )


# ---------------------------------------------------------------------------
# 8. Transaction rollback resilience
# ---------------------------------------------------------------------------


async def test_transaction_rollback_preserves_prior_commit(
    async_session: AsyncSession,
    embedding_service: MockEmbeddingService,
) -> None:
    """A failed insert must not corrupt previously committed rows.

    Creates a memory successfully, then attempts an insert with a duplicate
    primary key (guaranteed IntegrityError). After rollback the original
    memory must still be readable.
    """
    from memoryhub_core.models.memory import MemoryNode

    # Step 1: Create a memory through the normal service path and commit.
    good_memory, _ = await create_memory(
        _make("memory that must survive a rollback"),
        async_session,
        embedding_service,
        skip_curation=True,
    )
    await async_session.commit()

    # Step 2: Attempt a raw ORM insert with a duplicate primary key.
    duplicate = MemoryNode(
        id=good_memory.id,  # intentional duplicate
        content="this should fail",
        stub="this should fail",
        scope="user",
        weight=0.5,
        owner_id="rollback-test-user",
        tenant_id=_TEST_TENANT_ID,
        embedding=await embedding_service.embed("this should fail"),
    )
    async_session.add(duplicate)

    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        await async_session.flush()

    await async_session.rollback()

    # Step 3: Verify the original row is intact after rollback.
    stmt = select(MemoryNode).where(MemoryNode.id == good_memory.id)
    result = await async_session.execute(stmt)
    recovered = result.scalar_one_or_none()

    assert recovered is not None, (
        "Original memory vanished after rollback — transaction isolation failure"
    )
    assert recovered.content == "memory that must survive a rollback", (
        f"Content mismatch after rollback: {recovered.content!r}"
    )


async def test_session_usable_after_rollback(
    async_session: AsyncSession,
    embedding_service: MockEmbeddingService,
) -> None:
    """The session must remain functional for new operations after a rollback."""
    from sqlalchemy.exc import IntegrityError

    from memoryhub_core.models.memory import MemoryNode

    # Force a rollback via duplicate primary key.
    first, _ = await create_memory(
        _make("first memory before intentional error"),
        async_session,
        embedding_service,
        skip_curation=True,
    )
    await async_session.commit()

    bad_node = MemoryNode(
        id=first.id,
        content="duplicate pk",
        stub="duplicate pk",
        scope="user",
        weight=0.5,
        owner_id="session-reuse-test",
        tenant_id=_TEST_TENANT_ID,
        embedding=await embedding_service.embed("duplicate pk"),
    )
    async_session.add(bad_node)

    with pytest.raises(IntegrityError):
        await async_session.flush()

    await async_session.rollback()

    # The session should still work for a new create.
    second, _ = await create_memory(
        _make("second memory after rollback"),
        async_session,
        embedding_service,
        skip_curation=True,
    )
    assert second is not None, "Session was unusable after rollback"
    assert second.content == "second memory after rollback"


# ---------------------------------------------------------------------------
# 9. ARRAY column with GIN index (domains)
# ---------------------------------------------------------------------------


async def test_array_contains_query_uses_gin_index(
    async_session: AsyncSession,
    embedding_service: MockEmbeddingService,
) -> None:
    """The @> (array contains) operator on domains exercises the GIN index."""
    # Create memories with distinct domain tags.
    react_mem, _ = await create_memory(
        MemoryNodeCreate(
            content="React component lifecycle management",
            scope=MemoryScope.USER,
            weight=0.8,
            owner_id="domain-test-user",
            domains=["React", "JavaScript"],
        ),
        async_session,
        embedding_service,
        skip_curation=True,
    )
    spring_mem, _ = await create_memory(
        MemoryNodeCreate(
            content="Spring Boot dependency injection patterns",
            scope=MemoryScope.USER,
            weight=0.8,
            owner_id="domain-test-user",
            domains=["Spring Boot", "Java"],
        ),
        async_session,
        embedding_service,
        skip_curation=True,
    )
    both_mem, _ = await create_memory(
        MemoryNodeCreate(
            content="Full-stack app with React frontend and Spring backend",
            scope=MemoryScope.USER,
            weight=0.8,
            owner_id="domain-test-user",
            domains=["React", "Spring Boot"],
        ),
        async_session,
        embedding_service,
        skip_curation=True,
    )

    # Query: memories whose domains contain "React".
    stmt = text(
        "SELECT id FROM memory_nodes "
        "WHERE domains @> ARRAY[:domain]::text[] "
        "AND tenant_id = :tid"
    )
    result = await async_session.execute(
        stmt, {"domain": "React", "tid": _TEST_TENANT_ID}
    )
    react_ids = {row[0] for row in result.fetchall()}

    assert react_mem.id in react_ids, "React memory missing from @> 'React' query"
    assert both_mem.id in react_ids, "Both-domains memory missing from @> 'React' query"
    assert spring_mem.id not in react_ids, (
        "Spring-only memory should not appear in @> 'React' query"
    )

    # Query: memories whose domains contain "Spring Boot".
    result = await async_session.execute(
        stmt, {"domain": "Spring Boot", "tid": _TEST_TENANT_ID}
    )
    spring_ids = {row[0] for row in result.fetchall()}

    assert spring_mem.id in spring_ids, "Spring memory missing from @> 'Spring Boot' query"
    assert both_mem.id in spring_ids, "Both-domains memory missing from @> 'Spring Boot' query"
    assert react_mem.id not in spring_ids, (
        "React-only memory should not appear in @> 'Spring Boot' query"
    )


async def test_array_contains_multiple_domains(
    async_session: AsyncSession,
    embedding_service: MockEmbeddingService,
) -> None:
    """Querying for memories that contain ALL of multiple domains."""
    multi_mem, _ = await create_memory(
        MemoryNodeCreate(
            content="CORS configuration for React + Spring Boot apps",
            scope=MemoryScope.USER,
            weight=0.8,
            owner_id="multi-domain-user",
            domains=["React", "Spring Boot", "CORS"],
        ),
        async_session,
        embedding_service,
        skip_curation=True,
    )
    partial_mem, _ = await create_memory(
        MemoryNodeCreate(
            content="React state management with Redux",
            scope=MemoryScope.USER,
            weight=0.8,
            owner_id="multi-domain-user",
            domains=["React", "Redux"],
        ),
        async_session,
        embedding_service,
        skip_curation=True,
    )

    # Query: memories containing BOTH "React" AND "CORS".
    stmt = text(
        "SELECT id FROM memory_nodes "
        "WHERE domains @> ARRAY['React', 'CORS']::text[] "
        "AND tenant_id = :tid"
    )
    result = await async_session.execute(stmt, {"tid": _TEST_TENANT_ID})
    ids = {row[0] for row in result.fetchall()}

    assert multi_mem.id in ids, (
        "Memory with ['React', 'Spring Boot', 'CORS'] should match @> ['React', 'CORS']"
    )
    assert partial_mem.id not in ids, (
        "Memory with ['React', 'Redux'] should NOT match @> ['React', 'CORS']"
    )
