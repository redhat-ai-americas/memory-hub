"""Real-SQL integration tests for cross-tenant isolation (issue #46, Phase 5).

These tests exercise the service-layer functions directly against a real
PostgreSQL + pgvector database so the tenant filter is proven at the
actual SQL level, not through mock boundaries. They complement the
tool-level tests in ``memory-hub-mcp/tests/test_tenant_isolation.py``
(which go through the tools + authz stack but mock the service layer).

Together they form the acceptance coverage for issue #46:
  - Tool-level: real claims flow + real authz + real tool wiring,
    fake DB (proves the tool → service contract).
  - SQL-level (this file): real DB + real service layer, no claims
    (proves the tenant filter holds at the actual storage layer).

Run with the compose stack active:
    podman-compose -f tests/integration/compose.yaml up -d
    pytest tests/integration/test_tenant_isolation.py
"""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import memoryhub_core.services.curation.pipeline as pipeline_module
from memoryhub_core.models.curation import CuratorRule
from memoryhub_core.models.schemas import (
    CuratorRuleCreate,
    MemoryNodeCreate,
    MemoryNodeUpdate,
    MemoryScope,
    RelationshipCreate,
    RelationshipType,
    RuleAction,
    RuleLayer,
    RuleTier,
    RuleTrigger,
)
from memoryhub_core.services.curation.rules import create_rule, load_rules
from memoryhub_core.services.curation.similarity import (
    check_similarity,
    get_similar_memories,
)
from memoryhub_core.services.embeddings import MockEmbeddingService
from memoryhub_core.services.exceptions import MemoryNotFoundError
from memoryhub_core.services.graph import (
    create_relationship,
    get_relationships,
)
from memoryhub_core.services.memory import (
    count_search_matches,
    create_memory,
    get_memory_history,
    read_memory,
    report_contradiction,
    search_memories,
    update_memory,
)

pytestmark = pytest.mark.integration

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


TENANT_A = "tenant_a"
TENANT_B = "tenant_b"


def _make(
    content: str,
    *,
    owner_id: str = "user-a",
    scope: MemoryScope = MemoryScope.USER,
    weight: float = 0.9,
) -> MemoryNodeCreate:
    return MemoryNodeCreate(
        content=content,
        scope=scope,
        weight=weight,
        owner_id=owner_id,
    )


@pytest.fixture
def reset_rules_seeded():
    """Ensure _seeded_tenants is clean before and restored after.

    Phase 4 (#46) replaced the Phase-0 boolean ``_rules_seeded`` with a
    per-tenant set. Cross-tenant tests touch multiple tenants and must
    start with a clean seed state so lazy seeding runs for each.
    """
    original = set(pipeline_module._seeded_tenants)
    pipeline_module._seeded_tenants = set()
    yield
    pipeline_module._seeded_tenants = original


# ---------------------------------------------------------------------------
# 1. memory_nodes — write A, read/search B cross-tenant
# ---------------------------------------------------------------------------


async def test_memory_read_isolation_across_tenants(
    async_session: AsyncSession,
    embedding_service: MockEmbeddingService,
    reset_rules_seeded,
) -> None:
    """Two memories in two tenants. Same-tenant reads succeed;
    cross-tenant reads raise MemoryNotFoundError — indistinguishable
    from a nonexistent row."""
    memory_a, _ = await create_memory(
        _make("tenant A secret data", owner_id="user-a"),
        async_session,
        embedding_service,
        tenant_id=TENANT_A,
    )
    memory_b, _ = await create_memory(
        _make("tenant B secret data", owner_id="user-b"),
        async_session,
        embedding_service,
        tenant_id=TENANT_B,
    )

    # Same-tenant reads succeed.
    result_a = await read_memory(memory_a.id, async_session, tenant_id=TENANT_A)
    assert result_a.id == memory_a.id
    assert result_a.content == "tenant A secret data"

    result_b = await read_memory(memory_b.id, async_session, tenant_id=TENANT_B)
    assert result_b.id == memory_b.id

    # Cross-tenant reads fail with MemoryNotFoundError.
    with pytest.raises(MemoryNotFoundError) as exc_a:
        await read_memory(memory_a.id, async_session, tenant_id=TENANT_B)
    assert exc_a.value.memory_id == memory_a.id

    with pytest.raises(MemoryNotFoundError) as exc_b:
        await read_memory(memory_b.id, async_session, tenant_id=TENANT_A)
    assert exc_b.value.memory_id == memory_b.id


async def test_memory_search_isolation_across_tenants(
    async_session: AsyncSession,
    embedding_service: MockEmbeddingService,
    reset_rules_seeded,
) -> None:
    """A search in tenant A must not return tenant B memories even when
    the content is identical."""
    # Identical content in two tenants, same owner_id to rule out the
    # owner filter as the thing that saves us.
    await create_memory(
        _make("python programming preference", owner_id="shared-user"),
        async_session,
        embedding_service,
        tenant_id=TENANT_A,
    )
    await create_memory(
        _make("python programming preference", owner_id="shared-user"),
        async_session,
        embedding_service,
        tenant_id=TENANT_B,
    )

    results_a = await search_memories(
        "python programming",
        async_session,
        embedding_service,
        tenant_id=TENANT_A,
        owner_id="shared-user",
    )
    assert len(results_a) == 1
    assert results_a[0][0].tenant_id == TENANT_A

    results_b = await search_memories(
        "python programming",
        async_session,
        embedding_service,
        tenant_id=TENANT_B,
        owner_id="shared-user",
    )
    assert len(results_b) == 1
    assert results_b[0][0].tenant_id == TENANT_B

    # Count queries are used by the tool layer for has_more pagination —
    # they must also respect tenant.
    count_a = await count_search_matches(
        async_session, tenant_id=TENANT_A, owner_id="shared-user"
    )
    count_b = await count_search_matches(
        async_session, tenant_id=TENANT_B, owner_id="shared-user"
    )
    assert count_a == 1
    assert count_b == 1


# ---------------------------------------------------------------------------
# 2. memory_relationships — create edge A, query as B
# ---------------------------------------------------------------------------


async def test_relationship_isolation_across_tenants(
    async_session: AsyncSession,
    embedding_service: MockEmbeddingService,
    reset_rules_seeded,
) -> None:
    """A relationship created in tenant A is invisible to tenant B.
    Querying the source node as tenant B raises MemoryNotFoundError
    at the _fetch_current_node step — the edge itself never gets
    returned."""
    source_a, _ = await create_memory(
        _make("source node A", owner_id="user-a"),
        async_session,
        embedding_service,
        tenant_id=TENANT_A,
    )
    target_a, _ = await create_memory(
        _make("target node A", owner_id="user-a"),
        async_session,
        embedding_service,
        tenant_id=TENANT_A,
    )

    await create_relationship(
        RelationshipCreate(
            source_id=source_a.id,
            target_id=target_a.id,
            relationship_type=RelationshipType.related_to,
            created_by="user-a",
        ),
        async_session,
    )

    # Tenant A query returns the edge.
    rels_a = await get_relationships(
        source_a.id, async_session, tenant_id=TENANT_A
    )
    assert len(rels_a) == 1
    assert rels_a[0].source_id == source_a.id

    # Tenant B query raises MemoryNotFoundError at the source lookup.
    with pytest.raises(MemoryNotFoundError):
        await get_relationships(source_a.id, async_session, tenant_id=TENANT_B)


async def test_cross_tenant_relationship_create_is_rejected(
    async_session: AsyncSession,
    embedding_service: MockEmbeddingService,
    reset_rules_seeded,
) -> None:
    """create_relationship must reject a source-target pair from
    different tenants with CrossTenantRelationshipError. This is the
    defense-in-depth service-layer check from Phase 3."""
    from memoryhub_core.services.exceptions import CrossTenantRelationshipError

    source_a, _ = await create_memory(
        _make("A source", owner_id="user-a"),
        async_session,
        embedding_service,
        tenant_id=TENANT_A,
    )
    target_b, _ = await create_memory(
        _make("B target", owner_id="user-b"),
        async_session,
        embedding_service,
        tenant_id=TENANT_B,
    )

    with pytest.raises(CrossTenantRelationshipError):
        await create_relationship(
            RelationshipCreate(
                source_id=source_a.id,
                target_id=target_b.id,
                relationship_type=RelationshipType.related_to,
                created_by="attacker",
            ),
            async_session,
        )


# ---------------------------------------------------------------------------
# 3. contradiction_reports — report against A memory from B fails
# ---------------------------------------------------------------------------


async def test_contradiction_report_respects_memory_tenant(
    async_session: AsyncSession,
    embedding_service: MockEmbeddingService,
    reset_rules_seeded,
) -> None:
    """A contradiction report inherits the memory's tenant. Since the
    tool layer calls read_memory with the caller's tenant_id before
    report_contradiction, cross-tenant reports are blocked at the tool
    layer. At the service layer, the report correctly stamps the
    memory's own tenant.
    """
    from memoryhub_core.models.contradiction import ContradictionReport

    memory_a, _ = await create_memory(
        _make("tenant A preference", owner_id="user-a"),
        async_session,
        embedding_service,
        tenant_id=TENANT_A,
    )

    # A same-tenant read + report path works and tags the report with
    # the memory's tenant.
    await report_contradiction(
        memory_id=memory_a.id,
        observed_behavior="contradicting observation",
        confidence=0.8,
        reporter="user-a",
        session=async_session,
    )

    stmt = select(ContradictionReport).where(
        ContradictionReport.memory_id == memory_a.id
    )
    report = (await async_session.execute(stmt)).scalar_one()
    assert report.tenant_id == TENANT_A

    # A tenant B read_memory call (the tool layer's auth precheck)
    # would raise MemoryNotFoundError, so the report call below is the
    # real-service equivalent of "the attacker cannot even look up the
    # memory to contradict it". Assert the read path fails.
    with pytest.raises(MemoryNotFoundError):
        await read_memory(memory_a.id, async_session, tenant_id=TENANT_B)


# ---------------------------------------------------------------------------
# 4. curator_rules — each tenant gets its own copy
# ---------------------------------------------------------------------------


async def test_curator_rule_isolation_across_tenants(
    async_session: AsyncSession,
    embedding_service: MockEmbeddingService,
    reset_rules_seeded,
) -> None:
    """A user-layer rule named "foo" can be created in tenant A and in
    tenant B without collision. load_rules in tenant A sees only A's
    rule; load_rules in tenant B sees only B's."""
    rule_data_a = CuratorRuleCreate(
        name="foo",
        trigger=RuleTrigger.ON_WRITE,
        tier=RuleTier.EMBEDDING,
        action=RuleAction.FLAG,
        config={"threshold": 0.95},
        layer=RuleLayer.USER,
        owner_id="user-a",
        override=False,
        enabled=True,
        priority=10,
    )
    rule_data_b = CuratorRuleCreate(
        name="foo",
        trigger=RuleTrigger.ON_WRITE,
        tier=RuleTier.EMBEDDING,
        action=RuleAction.FLAG,
        config={"threshold": 0.90},
        layer=RuleLayer.USER,
        owner_id="user-b",
        override=False,
        enabled=True,
        priority=10,
    )

    rule_a = await create_rule(rule_data_a, async_session, tenant_id=TENANT_A)
    rule_b = await create_rule(rule_data_b, async_session, tenant_id=TENANT_B)

    assert rule_a.id != rule_b.id
    assert rule_a.tenant_id == TENANT_A
    assert rule_b.tenant_id == TENANT_B

    # load_rules in tenant A sees only the A rule (note: load_rules
    # also returns system rules for the tenant, which this tenant has
    # none of since reset_rules_seeded cleared seeding and we did not
    # trigger the lazy-seed path).
    rules_a = await load_rules(
        trigger="on_write",
        owner_id="user-a",
        scope=None,
        session=async_session,
        tenant_id=TENANT_A,
    )
    user_rules_a = [r for r in rules_a if r.layer == "user"]
    assert len(user_rules_a) == 1
    assert user_rules_a[0].id == rule_a.id

    rules_b = await load_rules(
        trigger="on_write",
        owner_id="user-b",
        scope=None,
        session=async_session,
        tenant_id=TENANT_B,
    )
    user_rules_b = [r for r in rules_b if r.layer == "user"]
    assert len(user_rules_b) == 1
    assert user_rules_b[0].id == rule_b.id

    # And tenant C (no rules created) sees no user rules at all.
    rules_c = await load_rules(
        trigger="on_write",
        owner_id="user-a",
        scope=None,
        session=async_session,
        tenant_id="tenant_c",
    )
    assert [r for r in rules_c if r.layer == "user"] == []


async def test_default_rules_seeded_per_tenant(
    async_session: AsyncSession,
    embedding_service: MockEmbeddingService,
    reset_rules_seeded,
) -> None:
    """The lazy-seed path must run once per tenant, so each tenant
    gets its own copy of the system rules."""
    # Write in tenant A → triggers default rule seeding for A.
    await create_memory(
        _make("first write in tenant A", owner_id="user-a"),
        async_session,
        embedding_service,
        tenant_id=TENANT_A,
    )
    assert TENANT_A in pipeline_module._seeded_tenants
    assert TENANT_B not in pipeline_module._seeded_tenants

    stmt_a = select(CuratorRule).where(
        CuratorRule.layer == "system", CuratorRule.tenant_id == TENANT_A
    )
    system_a = (await async_session.execute(stmt_a)).scalars().all()
    assert len(system_a) == 5, (
        f"Expected 5 default rules seeded for {TENANT_A}, got {len(system_a)}"
    )

    # Write in tenant B → triggers seeding for B independently.
    await create_memory(
        _make("first write in tenant B", owner_id="user-b"),
        async_session,
        embedding_service,
        tenant_id=TENANT_B,
    )
    assert TENANT_B in pipeline_module._seeded_tenants

    stmt_b = select(CuratorRule).where(
        CuratorRule.layer == "system", CuratorRule.tenant_id == TENANT_B
    )
    system_b = (await async_session.execute(stmt_b)).scalars().all()
    assert len(system_b) == 5

    # The two sets are disjoint — each tenant has its own copies.
    ids_a = {r.id for r in system_a}
    ids_b = {r.id for r in system_b}
    assert ids_a.isdisjoint(ids_b)


# ---------------------------------------------------------------------------
# 5. curation similarity (pipeline cross-tenant)
# ---------------------------------------------------------------------------


async def test_curation_similarity_is_tenant_scoped(
    async_session: AsyncSession,
    embedding_service: MockEmbeddingService,
    reset_rules_seeded,
) -> None:
    """A write in tenant B with content identical to an existing
    tenant A memory must NOT match the tenant A memory in the
    similarity pool — otherwise write_memory would leak row existence
    via curation.similar_count.
    """
    # Create a memory in tenant A.
    content = "always use type hints in python function signatures"
    memory_a, curation_a = await create_memory(
        _make(content, owner_id="shared-user"),
        async_session,
        embedding_service,
        tenant_id=TENANT_A,
    )
    assert memory_a is not None
    assert curation_a["blocked"] is False

    # Now write an IDENTICAL memory in tenant B (same owner_id).
    # In a tenant-leaky world, curation would see the A memory as an
    # exact duplicate and block the B write. With tenant scoping, B's
    # curation pool excludes A entirely and the write succeeds.
    memory_b, curation_b = await create_memory(
        _make(content, owner_id="shared-user"),
        async_session,
        embedding_service,
        tenant_id=TENANT_B,
    )
    assert memory_b is not None, (
        f"Tenant B write was blocked by curation — tenant leak! curation={curation_b}"
    )
    assert curation_b["blocked"] is False
    # And no similar candidates should have been flagged.
    assert curation_b["similar_count"] == 0, (
        f"curation.similar_count leaked cross-tenant: {curation_b}"
    )


async def test_check_similarity_scoped_by_tenant(
    async_session: AsyncSession,
    embedding_service: MockEmbeddingService,
    reset_rules_seeded,
) -> None:
    """The raw check_similarity service call must ignore cross-tenant
    rows even when owner_id and scope match."""
    content = "shared owner content across tenants"
    owner_id = "shared-user"

    # Memory in tenant A.
    await create_memory(
        _make(content, owner_id=owner_id),
        async_session,
        embedding_service,
        tenant_id=TENANT_A,
    )

    # Query similarity from tenant B's perspective, same owner and scope.
    embedding = await embedding_service.embed(content)
    result_b = await check_similarity(
        embedding=embedding,
        owner_id=owner_id,
        scope=MemoryScope.USER,
        session=async_session,
        tenant_id=TENANT_B,
        flag_threshold=0.5,
    )
    assert result_b.similar_count == 0, (
        f"check_similarity saw cross-tenant row: {result_b}"
    )
    assert result_b.nearest_id is None
    assert result_b.nearest_score is None

    # Same query from tenant A must see exactly one match (itself).
    result_a = await check_similarity(
        embedding=embedding,
        owner_id=owner_id,
        scope=MemoryScope.USER,
        session=async_session,
        tenant_id=TENANT_A,
        flag_threshold=0.5,
    )
    assert result_a.similar_count == 1


async def test_get_similar_memories_scoped_by_tenant(
    async_session: AsyncSession,
    embedding_service: MockEmbeddingService,
    reset_rules_seeded,
) -> None:
    """get_similar_memories must refuse cross-tenant source lookups
    with MemoryNotFoundError, and must exclude cross-tenant candidates
    from the returned results even for same-tenant sources."""
    # A pair of similar memories in tenant A.
    a1, _ = await create_memory(
        _make("prefers dark mode in editor", owner_id="user-a"),
        async_session,
        embedding_service,
        tenant_id=TENANT_A,
    )
    await create_memory(
        _make("prefers dark mode in terminal", owner_id="user-a"),
        async_session,
        embedding_service,
        tenant_id=TENANT_A,
    )
    # A "noise" memory in tenant B with identical content.
    await create_memory(
        _make("prefers dark mode in editor", owner_id="user-a"),
        async_session,
        embedding_service,
        tenant_id=TENANT_B,
    )

    # Tenant A: sees one similar (the other A memory), not the B noise.
    result_a = await get_similar_memories(
        a1.id,
        async_session,
        tenant_id=TENANT_A,
        threshold=0.5,
    )
    assert result_a["total"] == 1

    # Tenant B: cannot even load the A memory as a source.
    with pytest.raises(MemoryNotFoundError):
        await get_similar_memories(
            a1.id,
            async_session,
            tenant_id=TENANT_B,
            threshold=0.5,
        )


# ---------------------------------------------------------------------------
# 6. Version history — cross-tenant walk fails
# ---------------------------------------------------------------------------


async def test_get_memory_history_cross_tenant_fails(
    async_session: AsyncSession,
    embedding_service: MockEmbeddingService,
    reset_rules_seeded,
) -> None:
    """Update a memory in tenant A, then try to walk the history as
    tenant B — must raise MemoryNotFoundError at the entry-point lookup.
    """
    memory_a, _ = await create_memory(
        _make("v1 content", owner_id="user-a"),
        async_session,
        embedding_service,
        tenant_id=TENANT_A,
    )
    await update_memory(
        memory_a.id,
        MemoryNodeUpdate(content="v2 content"),
        async_session,
        embedding_service,
    )

    # Same-tenant walk returns both versions.
    history_a = await get_memory_history(
        memory_a.id, async_session, tenant_id=TENANT_A
    )
    assert history_a["total_versions"] == 2

    # Cross-tenant walk: not found.
    with pytest.raises(MemoryNotFoundError):
        await get_memory_history(memory_a.id, async_session, tenant_id=TENANT_B)


async def test_nonexistent_memory_indistinguishable_from_cross_tenant(
    async_session: AsyncSession,
    embedding_service: MockEmbeddingService,
    reset_rules_seeded,
) -> None:
    """A random UUID that exists in tenant A but not in tenant B raises
    the same exception type (MemoryNotFoundError) as a UUID that does
    not exist anywhere — callers cannot distinguish the two cases."""
    memory_a, _ = await create_memory(
        _make("tenant A only", owner_id="user-a"),
        async_session,
        embedding_service,
        tenant_id=TENANT_A,
    )

    # Case 1: ID exists in A, accessed from B → MemoryNotFoundError.
    with pytest.raises(MemoryNotFoundError) as exc_cross:
        await read_memory(memory_a.id, async_session, tenant_id=TENANT_B)

    # Case 2: ID does not exist at all → MemoryNotFoundError.
    random_id = uuid.uuid4()
    with pytest.raises(MemoryNotFoundError) as exc_nonexistent:
        await read_memory(random_id, async_session, tenant_id=TENANT_B)

    # Same exception type, same "not found" semantics — no leak.
    assert type(exc_cross.value) is type(exc_nonexistent.value)
