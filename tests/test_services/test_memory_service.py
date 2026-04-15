"""Unit tests for the core memory service layer.

Uses async in-memory SQLite. The pgvector Vector column is replaced with a
plain JSON-like column via a listener so that the schema can be created
without the pgvector extension.
"""

import uuid

import pytest

from memoryhub_core.models.schemas import (
    MemoryNodeCreate,
    MemoryNodeRead,
    MemoryNodeStub,
    MemoryNodeUpdate,
    MemoryScope,
)
from memoryhub_core.services.exceptions import ContradictionNotFoundError, MemoryNotCurrentError, MemoryNotFoundError
from memoryhub_core.services.memory import (
    DEFAULT_PIVOT_THRESHOLD,
    count_search_matches as _svc_count_search_matches,
    create_memory as _svc_create_memory,
    delete_memory as _svc_delete_memory,
    get_memory_history as _svc_get_memory_history,
    read_memory as _svc_read_memory,
    report_contradiction,
    resolve_contradiction,
    search_memories as _svc_search_memories,
    search_memories_with_focus as _svc_search_memories_with_focus,
    update_memory as _svc_update_memory,
)
from memoryhub_core.services.rerank import NoopRerankerService, RerankerService


# Default tenant used by tests that don't care which tenant writes occur in.
# Phase 3 made tenant_id a required kwarg on create_memory; Phase 4 adds
# tenant_id kwargs to every read path. These wrappers keep existing
# happy-path tests terse by defaulting tenant_id to "default". Tests that
# exercise cross-tenant behavior call the underlying _svc_* functions
# directly with explicit tenant_id.
_TEST_TENANT_ID = "default"


async def create_memory(data, session, embedding_service, skip_curation=False, *, tenant_id=_TEST_TENANT_ID, s3_adapter=None):
    """Test wrapper around the service create_memory with a default tenant."""
    return await _svc_create_memory(
        data,
        session,
        embedding_service,
        tenant_id=tenant_id,
        skip_curation=skip_curation,
        s3_adapter=s3_adapter,
    )


async def read_memory(memory_id, session, *, tenant_id=_TEST_TENANT_ID):
    """Test wrapper around read_memory with a default tenant."""
    return await _svc_read_memory(memory_id, session, tenant_id=tenant_id)


async def update_memory(memory_id, data, session, embedding_service, s3_adapter=None):
    """Test wrapper around update_memory (tenant inherited from existing row)."""
    return await _svc_update_memory(memory_id, data, session, embedding_service, s3_adapter=s3_adapter)


async def get_memory_history(memory_id, session, *, tenant_id=_TEST_TENANT_ID, **kwargs):
    """Test wrapper around get_memory_history with a default tenant."""
    return await _svc_get_memory_history(memory_id, session, tenant_id=tenant_id, **kwargs)


async def search_memories(
    query, session, embedding_service, *, tenant_id=_TEST_TENANT_ID, **kwargs
):
    """Test wrapper around search_memories with a default tenant."""
    return await _svc_search_memories(
        query, session, embedding_service, tenant_id=tenant_id, **kwargs
    )


async def count_search_matches(session, *, tenant_id=_TEST_TENANT_ID, **kwargs):
    """Test wrapper around count_search_matches with a default tenant."""
    return await _svc_count_search_matches(session, tenant_id=tenant_id, **kwargs)


async def search_memories_with_focus(
    query,
    session,
    embedding_service,
    *,
    tenant_id=_TEST_TENANT_ID,
    **kwargs,
):
    """Test wrapper around search_memories_with_focus with a default tenant."""
    return await _svc_search_memories_with_focus(
        query,
        session,
        embedding_service,
        tenant_id=tenant_id,
        **kwargs,
    )


def _make_create_data(**overrides) -> MemoryNodeCreate:
    """Build a MemoryNodeCreate with sensible defaults."""
    defaults = {
        "content": "prefers Podman over Docker",
        "scope": MemoryScope.USER,
        "weight": 0.9,
        "owner_id": "user-123",
    }
    defaults.update(overrides)
    return MemoryNodeCreate(**defaults)


# -- create_memory --


async def test_create_memory(async_session, embedding_service):
    data = _make_create_data()
    result, curation = await create_memory(data, async_session, embedding_service)

    assert curation["blocked"] is False
    assert isinstance(result, MemoryNodeRead)
    assert result.content == "prefers Podman over Docker"
    assert result.scope == MemoryScope.USER
    assert result.weight == 0.9
    assert result.owner_id == "user-123"
    assert result.is_current is True
    assert result.version == 1
    assert result.previous_version_id is None
    assert "prefers Podman over Docker" in result.stub


async def test_create_memory_with_parent(async_session, embedding_service):
    parent_data = _make_create_data(content="I use Red Hat UBI images")
    parent, _ = await create_memory(parent_data, async_session, embedding_service)

    child_data = _make_create_data(
        content="Because UBI images are FIPS-compliant",
        parent_id=parent.id,
        branch_type="rationale",
    )
    child, curation = await create_memory(child_data, async_session, embedding_service)

    assert curation["blocked"] is False
    assert child.parent_id == parent.id
    assert child.branch_type == "rationale"


async def test_create_memory_with_metadata(async_session, embedding_service):
    data = _make_create_data(metadata={"source": "user-stated", "confidence": 0.95})
    result, curation = await create_memory(data, async_session, embedding_service)

    assert curation["blocked"] is False
    assert result.metadata is not None
    assert result.metadata["source"] == "user-stated"


# -- read_memory --


async def test_read_memory(async_session, embedding_service):
    data = _make_create_data()
    created, _ = await create_memory(data, async_session, embedding_service)

    result = await read_memory(created.id, async_session)

    assert result.id == created.id
    assert result.content == created.content
    assert result.has_children is False
    assert result.has_rationale is False


async def test_read_memory_preserves_scope_id_and_domains(async_session, embedding_service):
    """Regression: node_to_read must propagate scope_id and domains.

    Without these fields, authorize_read/authorize_write always receive None
    for scope_id, breaking all project-scope and role-scope authorization.
    """
    data = _make_create_data(
        content="project-scoped with domains",
        scope=MemoryScope.PROJECT,
        scope_id="my-project",
        domains=["React", "FastAPI"],
    )
    created, _ = await create_memory(data, async_session, embedding_service)

    result = await read_memory(created.id, async_session)

    assert result.scope_id == "my-project", (
        f"scope_id lost in node_to_read: expected 'my-project', got {result.scope_id!r}"
    )
    assert result.domains == ["React", "FastAPI"], (
        f"domains lost in node_to_read: expected ['React', 'FastAPI'], got {result.domains!r}"
    )


async def test_read_memory_with_children(async_session, embedding_service):
    parent, _ = await create_memory(_make_create_data(content="Parent node"), async_session, embedding_service)
    await create_memory(
        _make_create_data(content="Child 1", parent_id=parent.id, branch_type="description"),
        async_session,
        embedding_service,
    )
    await create_memory(
        _make_create_data(content="Rationale child", parent_id=parent.id, branch_type="rationale"),
        async_session,
        embedding_service,
    )

    result = await read_memory(parent.id, async_session)

    assert result.has_children is True
    assert result.has_rationale is True
    assert result.branch_count == 2


async def test_read_memory_not_found(async_session):
    fake_id = uuid.uuid4()
    with pytest.raises(MemoryNotFoundError) as exc_info:
        await read_memory(fake_id, async_session)
    assert exc_info.value.memory_id == fake_id


# -- update_memory --


async def test_update_memory(async_session, embedding_service):
    original, _ = await create_memory(_make_create_data(), async_session, embedding_service)

    update_data = MemoryNodeUpdate(content="prefers Podman over Docker for all container work")
    updated = await update_memory(original.id, update_data, async_session, embedding_service)

    assert updated.version == 2
    assert updated.is_current is True
    assert updated.previous_version_id == original.id
    assert "all container work" in updated.content

    # Original should no longer be current and should have expires_at set
    old = await read_memory(original.id, async_session)
    assert old.is_current is False
    assert old.expires_at is not None


async def test_update_memory_preserves_unchanged_fields(async_session, embedding_service):
    original, _ = await create_memory(
        _make_create_data(weight=0.85, metadata={"source": "observed"}),
        async_session,
        embedding_service,
    )

    update_data = MemoryNodeUpdate(content="updated content only")
    updated = await update_memory(original.id, update_data, async_session, embedding_service)

    assert updated.weight == 0.85
    assert updated.metadata["source"] == "observed"
    assert updated.scope == original.scope
    assert updated.owner_id == original.owner_id


async def test_update_memory_not_found(async_session, embedding_service):
    fake_id = uuid.uuid4()
    with pytest.raises(MemoryNotFoundError):
        await update_memory(fake_id, MemoryNodeUpdate(content="nope"), async_session, embedding_service)


async def test_update_non_current_memory_raises(async_session, embedding_service):
    original, _ = await create_memory(_make_create_data(), async_session, embedding_service)
    await update_memory(original.id, MemoryNodeUpdate(content="v2"), async_session, embedding_service)

    # Trying to update the old (non-current) version should fail
    with pytest.raises(MemoryNotCurrentError) as exc_info:
        await update_memory(original.id, MemoryNodeUpdate(content="v3"), async_session, embedding_service)
    assert exc_info.value.memory_id == original.id


async def test_update_memory_deep_copies_branches(async_session, embedding_service):
    """When a memory is updated, its child branches are deep-copied to the new version."""
    parent, _ = await create_memory(_make_create_data(content="I use Red Hat UBI"), async_session, embedding_service)

    # Add a rationale branch and a description branch to the original
    rationale_data = _make_create_data(
        content="Because UBI images are FIPS-compliant",
        parent_id=parent.id,
        branch_type="rationale",
    )
    rationale, _ = await create_memory(rationale_data, async_session, embedding_service)

    desc_data = _make_create_data(
        content="Red Hat Universal Base Image",
        parent_id=parent.id,
        branch_type="description",
    )
    await create_memory(desc_data, async_session, embedding_service)

    # Update the parent memory
    updated = await update_memory(
        parent.id, MemoryNodeUpdate(content="I use Red Hat UBI 9"), async_session, embedding_service
    )

    # The new version should report having children
    assert updated.has_children is True
    assert updated.has_rationale is True

    # Read the new version and verify branch_count reflects the deep copy.
    # read_memory no longer expands branches inline, so query the new version's
    # children directly via SQL to confirm the deep-copy behavior.
    from sqlalchemy import select as _select

    from memoryhub_core.models.memory import MemoryNode as _MemoryNode

    new_version = await read_memory(updated.id, async_session)
    assert new_version.branch_count == 2
    assert new_version.has_children is True
    assert new_version.has_rationale is True

    children_stmt = _select(_MemoryNode).where(
        _MemoryNode.parent_id == updated.id,
        _MemoryNode.deleted_at.is_(None),
    )
    children = (await async_session.execute(children_stmt)).scalars().all()
    assert len(children) == 2

    # The copied branches should have different IDs than the originals
    copied_ids = {c.id for c in children}
    assert rationale.id not in copied_ids

    # But the rationale branch_type should still be present
    copied_rationale = [c for c in children if c.branch_type == "rationale"]
    assert len(copied_rationale) == 1


async def test_update_memory_sets_expires_at(async_session, embedding_service):
    """Old version gets an expires_at timestamp when superseded."""
    from datetime import timedelta

    original, _ = await create_memory(_make_create_data(), async_session, embedding_service)
    assert original.expires_at is None  # current version has no TTL

    updated = await update_memory(original.id, MemoryNodeUpdate(content="v2"), async_session, embedding_service)
    assert updated.expires_at is None  # new current version has no TTL

    old = await read_memory(original.id, async_session)
    assert old.expires_at is not None
    # The expires_at should be roughly 90 days from now (default retention)
    assert old.expires_at > old.updated_at
    # Check it's approximately 90 days out (within 1 day tolerance)
    expected_delta = timedelta(days=90)
    actual_delta = old.expires_at - old.created_at
    assert abs(actual_delta - expected_delta) < timedelta(days=1)


# -- get_memory_history --


async def test_get_memory_history(async_session, embedding_service):
    v1, _ = await create_memory(_make_create_data(content="version 1"), async_session, embedding_service)
    v2 = await update_memory(v1.id, MemoryNodeUpdate(content="version 2"), async_session, embedding_service)
    v3 = await update_memory(v2.id, MemoryNodeUpdate(content="version 3"), async_session, embedding_service)

    # Get history starting from the latest version
    result = await get_memory_history(v3.id, async_session)
    history = result["versions"]

    assert result["total_versions"] == 3
    assert result["has_more"] is False
    assert result["offset"] == 0
    assert len(history) == 3
    # Newest first
    assert history[0].version == 3
    assert history[1].version == 2
    assert history[2].version == 1
    assert history[0].is_current is True
    assert history[1].is_current is False
    assert history[2].is_current is False
    # Content field should be populated
    assert history[0].content == "version 3"
    assert history[2].content == "version 1"


async def test_get_memory_history_single_version(async_session, embedding_service):
    node, _ = await create_memory(_make_create_data(), async_session, embedding_service)
    result = await get_memory_history(node.id, async_session)
    history = result["versions"]

    assert len(history) == 1
    assert history[0].version == 1
    assert history[0].is_current is True
    assert history[0].content == "prefers Podman over Docker"


async def test_get_memory_history_pagination(async_session, embedding_service):
    """Pagination returns the correct window and has_more flag."""
    v1, _ = await create_memory(_make_create_data(content="v1"), async_session, embedding_service)
    v2 = await update_memory(v1.id, MemoryNodeUpdate(content="v2"), async_session, embedding_service)
    v3 = await update_memory(v2.id, MemoryNodeUpdate(content="v3"), async_session, embedding_service)
    v4 = await update_memory(v3.id, MemoryNodeUpdate(content="v4"), async_session, embedding_service)
    v5 = await update_memory(v4.id, MemoryNodeUpdate(content="v5"), async_session, embedding_service)

    # Page 1: first 2 versions (newest first: v5, v4)
    result = await get_memory_history(v5.id, async_session, max_versions=2, offset=0)
    assert len(result["versions"]) == 2
    assert result["versions"][0].version == 5
    assert result["versions"][1].version == 4
    assert result["total_versions"] == 5
    assert result["has_more"] is True

    # Page 2: next 2 (v3, v2)
    result = await get_memory_history(v5.id, async_session, max_versions=2, offset=2)
    assert len(result["versions"]) == 2
    assert result["versions"][0].version == 3
    assert result["has_more"] is True

    # Page 3: last 1 (v1)
    result = await get_memory_history(v5.id, async_session, max_versions=2, offset=4)
    assert len(result["versions"]) == 1
    assert result["versions"][0].version == 1
    assert result["has_more"] is False


async def test_get_memory_history_not_found(async_session):
    with pytest.raises(MemoryNotFoundError):
        await get_memory_history(uuid.uuid4(), async_session)


async def test_read_memory_historical_version_surfaces_current_pointer(
    async_session, embedding_service
):
    """Regression for #51: historical reads include a pointer to the current version.

    Reading a superseded version should populate current_version_id so the
    caller can pivot in one round-trip. Reading the current version should
    leave the field as None.
    """
    v1, _ = await create_memory(
        _make_create_data(content="v1"), async_session, embedding_service
    )
    v2 = await update_memory(
        v1.id, MemoryNodeUpdate(content="v2"), async_session, embedding_service
    )
    v3 = await update_memory(
        v2.id, MemoryNodeUpdate(content="v3"), async_session, embedding_service
    )

    # Reading the oldest version surfaces a pointer to v3
    result_v1 = await read_memory(v1.id, async_session)
    assert result_v1.is_current is False
    assert result_v1.current_version_id == v3.id

    # Reading the middle version surfaces the same pointer
    result_v2 = await read_memory(v2.id, async_session)
    assert result_v2.is_current is False
    assert result_v2.current_version_id == v3.id

    # Reading the current version leaves current_version_id None
    result_v3 = await read_memory(v3.id, async_session)
    assert result_v3.is_current is True
    assert result_v3.current_version_id is None


async def test_get_memory_history_walks_chain_bidirectionally(
    async_session, embedding_service
):
    """Regression for #49: history walks both directions from any version ID.

    Pre-#49 the walker only followed previous_version_id backward, so
    passing the oldest version ID returned just that one node and
    total_versions=1. Verify all three call sites (oldest, middle, current)
    return the full chain.
    """
    v1, _ = await create_memory(
        _make_create_data(content="v1"), async_session, embedding_service
    )
    v2 = await update_memory(
        v1.id, MemoryNodeUpdate(content="v2"), async_session, embedding_service
    )
    v3 = await update_memory(
        v2.id, MemoryNodeUpdate(content="v3"), async_session, embedding_service
    )

    expected_versions = {1, 2, 3}

    for label, version_id in [
        ("oldest", v1.id),
        ("middle", v2.id),
        ("current", v3.id),
    ]:
        result = await get_memory_history(version_id, async_session)
        assert result["total_versions"] == 3, (
            f"calling with the {label} version ID should return all 3 versions"
        )
        assert {v.version for v in result["versions"]} == expected_versions, (
            f"calling with the {label} version ID should yield versions {expected_versions}"
        )
        # Newest-first ordering must hold regardless of which ID was passed
        versions_in_order = [v.version for v in result["versions"]]
        assert versions_in_order == sorted(versions_in_order, reverse=True), (
            f"calling with the {label} version ID must return newest-first"
        )


# -- report_contradiction --


async def test_report_contradiction(async_session, embedding_service):
    from sqlalchemy import select
    from memoryhub_core.models.contradiction import ContradictionReport

    node, _ = await create_memory(_make_create_data(), async_session, embedding_service)

    count = await report_contradiction(
        node.id,
        observed_behavior="user actually used Docker in last session",
        confidence=0.8,
        reporter="test-agent",
        session=async_session,
    )
    assert count == 1

    count = await report_contradiction(
        node.id,
        observed_behavior="user ran docker-compose up",
        confidence=0.6,
        reporter="test-agent",
        session=async_session,
    )
    assert count == 2

    # Verify stored in contradiction_reports table
    result = await async_session.execute(
        select(ContradictionReport).where(ContradictionReport.memory_id == node.id)
    )
    reports = result.scalars().all()
    assert len(reports) == 2
    assert reports[0].confidence == 0.8


async def test_report_contradiction_not_found(async_session):
    with pytest.raises(MemoryNotFoundError):
        await report_contradiction(uuid.uuid4(), "doesn't matter", 0.5, "test-agent", async_session)


async def test_report_contradiction_preserves_existing_metadata(async_session, embedding_service):
    node, _ = await create_memory(
        _make_create_data(metadata={"source": "user-stated"}),
        async_session,
        embedding_service,
    )

    await report_contradiction(node.id, "contradicting behavior", 0.7, "test-agent", session=async_session)

    refreshed = await read_memory(node.id, async_session)
    assert refreshed.metadata["source"] == "user-stated"
    assert "contradictions" not in refreshed.metadata


async def test_report_contradiction_resolved_not_counted(async_session, embedding_service):
    from sqlalchemy import select
    from memoryhub_core.models.contradiction import ContradictionReport

    node, _ = await create_memory(_make_create_data(), async_session, embedding_service)

    await report_contradiction(
        node.id,
        observed_behavior="user used Docker once",
        confidence=0.7,
        reporter="test-agent",
        session=async_session,
    )

    # Mark the first report resolved
    result = await async_session.execute(
        select(ContradictionReport).where(ContradictionReport.memory_id == node.id)
    )
    report = result.scalars().first()
    report.resolved = True
    await async_session.commit()

    count = await report_contradiction(
        node.id,
        observed_behavior="user ran docker-compose up again",
        confidence=0.6,
        reporter="test-agent",
        session=async_session,
    )
    assert count == 1


# -- resolve_contradiction --


async def test_resolve_contradiction(async_session, embedding_service):
    node, _ = await create_memory(_make_create_data(), async_session, embedding_service)

    await report_contradiction(
        node.id, "user ran docker build", 0.8, "test-agent", async_session,
    )

    from sqlalchemy import select
    from memoryhub_core.models.contradiction import ContradictionReport

    result = await async_session.execute(
        select(ContradictionReport).where(ContradictionReport.memory_id == node.id)
    )
    report = result.scalars().first()
    assert report.resolved is False

    resolved = await resolve_contradiction(report.id, async_session)
    assert resolved.resolved is True
    assert resolved.resolved_at is not None


async def test_resolve_contradiction_not_found(async_session):
    with pytest.raises(ContradictionNotFoundError):
        await resolve_contradiction(uuid.uuid4(), async_session)


async def test_resolve_contradiction_already_resolved(async_session, embedding_service):
    node, _ = await create_memory(_make_create_data(), async_session, embedding_service)

    await report_contradiction(
        node.id, "user ran docker build", 0.8, "test-agent", async_session,
    )

    from sqlalchemy import select
    from memoryhub_core.models.contradiction import ContradictionReport

    result = await async_session.execute(
        select(ContradictionReport).where(ContradictionReport.memory_id == node.id)
    )
    report = result.scalars().first()

    await resolve_contradiction(report.id, async_session)

    with pytest.raises(ValueError, match="already resolved"):
        await resolve_contradiction(report.id, async_session)


# -- search_memories --


async def test_search_memories_returns_results(async_session, embedding_service):
    """Search returns (node, relevance_score) tuples filtered by owner and scope."""
    await create_memory(  # result intentionally discarded
        _make_create_data(content="prefers Podman over Docker", weight=0.9),
        async_session,
        embedding_service,
    )
    await create_memory(  # result intentionally discarded
        _make_create_data(content="uses FastAPI for web services", weight=0.5),
        async_session,
        embedding_service,
    )

    results = await search_memories(
        "container runtime preference",
        async_session,
        embedding_service,
        owner_id="user-123",
    )

    assert len(results) == 2
    # Each result is a (node, score) tuple
    for item, score in results:
        assert isinstance(score, float)
        assert isinstance(item, (MemoryNodeRead, MemoryNodeStub))
    # High weight -> MemoryNodeRead, low weight -> MemoryNodeStub
    types = {type(item) for item, _ in results}
    assert MemoryNodeRead in types
    assert MemoryNodeStub in types


async def test_search_memories_filters_scope(async_session, embedding_service):
    await create_memory(  # result intentionally discarded
        _make_create_data(content="user preference", scope=MemoryScope.USER),
        async_session,
        embedding_service,
    )
    await create_memory(  # result intentionally discarded
        _make_create_data(content="project standard", scope=MemoryScope.PROJECT),
        async_session,
        embedding_service,
    )

    results = await search_memories(
        "preference",
        async_session,
        embedding_service,
        scope="user",
    )

    assert len(results) == 1
    item, score = results[0]
    assert item.scope == MemoryScope.USER
    assert isinstance(score, float)


async def test_search_memories_current_only(async_session, embedding_service):
    v1, _ = await create_memory(_make_create_data(content="old"), async_session, embedding_service)
    await update_memory(v1.id, MemoryNodeUpdate(content="new"), async_session, embedding_service)

    results = await search_memories("old", async_session, embedding_service, current_only=True)

    # Only the current version should be returned
    assert all((r.is_current if isinstance(r, MemoryNodeRead) else True) for r, _ in results)


# -- search_memories_with_focus (#58) --


class _StubReranker(RerankerService):
    """Reranker that reverses input order, with a usage counter.

    Reversing makes the cross-encoder reordering observable in tests
    without requiring a real model -- if the test sees the reversed
    order in the output, the rerank stage ran. The counter lets tests
    verify the rerank was called the expected number of times.
    """

    is_configured = True

    def __init__(self) -> None:
        self.calls = 0

    async def rerank(self, query, texts):
        self.calls += 1
        return list(range(len(texts) - 1, -1, -1))


async def test_search_with_focus_no_focus_short_circuits(
    async_session, embedding_service
):
    """Empty/zero-weight focus should match plain search_memories output."""
    await create_memory(
        _make_create_data(content="podman build --platform linux/amd64", weight=0.9),
        async_session,
        embedding_service,
    )
    await create_memory(
        _make_create_data(content="OAuth client credentials grant", weight=0.9),
        async_session,
        embedding_service,
    )

    bundle = await search_memories_with_focus(
        query="podman",
        session=async_session,
        embedding_service=embedding_service,
        focus_string="",  # empty focus should short-circuit
        owner_id="user-123",
    )

    # Short-circuit means no pivot signal is computed and no rerank
    # call is needed. Results match the cosine baseline.
    assert bundle.pivot_suggested is False
    assert bundle.pivot_distance is None
    assert bundle.used_reranker is False
    assert bundle.fallback_reason is None
    assert len(bundle.results) >= 1


async def test_search_with_focus_zero_weight_short_circuits(
    async_session, embedding_service
):
    """session_focus_weight=0.0 should also bypass the focus path."""
    await create_memory(
        _make_create_data(content="OpenShift route TLS termination", weight=0.9),
        async_session,
        embedding_service,
    )
    bundle = await search_memories_with_focus(
        query="route TLS",
        session=async_session,
        embedding_service=embedding_service,
        focus_string="OpenShift",
        session_focus_weight=0.0,
        owner_id="user-123",
    )
    assert bundle.used_reranker is False
    assert bundle.pivot_suggested is False
    assert bundle.pivot_distance is None


async def test_search_with_focus_runs_reranker_when_configured(
    async_session, embedding_service
):
    """When focus is set and reranker is configured, the rerank runs once."""
    for content in (
        "podman build --platform linux/amd64",
        "OpenShift BuildConfig binary source type",
        "container image registry pull policy",
    ):
        await create_memory(
            _make_create_data(content=content, weight=0.9),
            async_session,
            embedding_service,
        )

    stub_reranker = _StubReranker()
    bundle = await search_memories_with_focus(
        query="container deployment",
        session=async_session,
        embedding_service=embedding_service,
        focus_string="OpenShift container build",
        session_focus_weight=0.4,
        reranker=stub_reranker,
        owner_id="user-123",
        max_results=5,
    )

    assert stub_reranker.calls == 1
    assert bundle.used_reranker is True
    assert bundle.fallback_reason is None
    assert len(bundle.results) >= 1


async def test_search_with_focus_falls_back_when_reranker_fails(
    async_session, embedding_service
):
    """Reranker exceptions are caught; the bundle reports the fallback reason."""
    await create_memory(
        _make_create_data(content="podman containerfile patterns", weight=0.9),
        async_session,
        embedding_service,
    )

    class _ExplodingReranker(RerankerService):
        is_configured = True

        async def rerank(self, query, texts):
            raise RuntimeError("simulated reranker outage")

    bundle = await search_memories_with_focus(
        query="container",
        session=async_session,
        embedding_service=embedding_service,
        focus_string="OpenShift",
        session_focus_weight=0.4,
        reranker=_ExplodingReranker(),
        owner_id="user-123",
    )
    assert bundle.used_reranker is False
    assert bundle.fallback_reason is not None
    # The fallback reason records the exception type (not the message,
    # which may contain sensitive data). The actual message still
    # appears in the warning log for operator debugging.
    assert "RuntimeError" in bundle.fallback_reason
    assert "falling back" in bundle.fallback_reason
    # Results still come back from the cosine fallback path.
    assert len(bundle.results) >= 1


async def test_search_with_focus_skips_rerank_when_noop(
    async_session, embedding_service
):
    """NoopRerankerService.is_configured=False causes the rerank stage to skip."""
    await create_memory(
        _make_create_data(content="podman build linux amd64", weight=0.9),
        async_session,
        embedding_service,
    )
    bundle = await search_memories_with_focus(
        query="podman build",
        session=async_session,
        embedding_service=embedding_service,
        focus_string="OpenShift container build",
        session_focus_weight=0.4,
        reranker=NoopRerankerService(),
        owner_id="user-123",
    )
    assert bundle.used_reranker is False
    assert bundle.fallback_reason is not None
    assert "not configured" in bundle.fallback_reason


async def test_search_with_focus_emits_pivot_signal_for_distant_query(
    async_session, embedding_service
):
    """A query string that diverges from the focus should set pivot_suggested.

    The mock embedding service produces embeddings via word-hash sums,
    so two strings with no shared words map to nearly orthogonal
    vectors -- cosine distance >= ~1.0, well above the 0.55 threshold.
    """
    await create_memory(
        _make_create_data(content="random unrelated content", weight=0.9),
        async_session,
        embedding_service,
    )
    bundle = await search_memories_with_focus(
        query="alpha bravo charlie delta",
        session=async_session,
        embedding_service=embedding_service,
        focus_string="kilo lima mike november",
        session_focus_weight=0.4,
        owner_id="user-123",
        pivot_threshold=DEFAULT_PIVOT_THRESHOLD,
    )
    assert bundle.pivot_suggested is True
    assert bundle.pivot_distance is not None
    assert bundle.pivot_distance > DEFAULT_PIVOT_THRESHOLD
    assert bundle.pivot_reason is not None
    assert "threshold" in bundle.pivot_reason


async def test_search_with_focus_no_pivot_when_query_aligned_with_focus(
    async_session, embedding_service
):
    """Same-words query and focus should sit close enough to clear the threshold."""
    await create_memory(
        _make_create_data(content="podman openshift build", weight=0.9),
        async_session,
        embedding_service,
    )
    bundle = await search_memories_with_focus(
        query="podman openshift build",
        session=async_session,
        embedding_service=embedding_service,
        focus_string="podman openshift build",
        session_focus_weight=0.4,
        owner_id="user-123",
    )
    # Identical strings should have distance ~ 0, far below threshold.
    assert bundle.pivot_suggested is False
    assert bundle.pivot_distance is not None
    assert bundle.pivot_distance < DEFAULT_PIVOT_THRESHOLD


async def test_search_with_focus_returns_empty_when_no_authorized_scopes(
    async_session, embedding_service
):
    """Empty authorized_scopes short-circuits to no results, with pivot still computed."""
    bundle = await search_memories_with_focus(
        query="anything",
        session=async_session,
        embedding_service=embedding_service,
        focus_string="something",
        session_focus_weight=0.4,
        authorized_scopes={},  # explicitly empty
    )
    assert bundle.results == []
    # Pivot computation is independent of the DB filter, so it still
    # ran and the bundle reports the distance + threshold.
    assert bundle.pivot_distance is not None
    assert bundle.pivot_threshold == DEFAULT_PIVOT_THRESHOLD


def test_cosine_distance_returns_python_float_for_numpy_inputs():
    """Regression for the focus-path serialization bug.

    pgvector returns embeddings as numpy arrays in production. Without
    an explicit float() cast, _cosine_distance propagates numpy.float32
    out, which breaks pydantic_core.to_jsonable_python and causes
    FastMCP to drop structured output (manifesting as the confusing
    "outputSchema defined but no structured output returned" error).
    The mock embedding service used by the rest of this suite returns
    Python lists, so this regression would not have been caught
    without an explicit numpy test.
    """
    import pydantic_core
    try:
        import numpy as np
    except ImportError:
        pytest.skip("numpy not installed")

    from memoryhub_core.services.memory import _cosine_distance

    # Build a numpy embedding the way pgvector would.
    np_embedding = np.array([0.1] * 384, dtype=np.float32)
    list_form = list(np_embedding)
    assert type(list_form[0]).__name__ == "float32"

    distance = _cosine_distance(list_form, list_form)
    assert isinstance(distance, float)
    assert type(distance).__name__ == "float"  # not numpy.float32

    # Round-trip through pydantic_core to confirm the response shape
    # the production code emits is fully jsonable. This is the exact
    # call that FastMCP's convert_result makes; if it raises, the
    # tool result loses its structured_content and the MCP layer
    # fires the outputSchema error.
    payload = {
        "results": [],
        "total_matching": 0,
        "has_more": False,
        "pivot_suggested": False,
        "pivot_reason": None,
        "relevance_score": max(0.0, 1.0 - distance),
    }
    pydantic_core.to_jsonable_python(payload)  # must not raise


# -- Phase 3 (#46) tenant plumbing tests --


async def test_create_memory_populates_tenant_from_param(async_session, embedding_service):
    """create_memory must stamp the passed tenant_id onto the persisted row."""
    from sqlalchemy import select
    from memoryhub_core.models.memory import MemoryNode

    data = _make_create_data(content="tenant-a content")
    created, curation = await _svc_create_memory(
        data, async_session, embedding_service, tenant_id="tenant_a"
    )
    assert curation["blocked"] is False
    assert created.tenant_id == "tenant_a"

    # And the ORM row must also carry tenant_a, not the column server default.
    stmt = select(MemoryNode).where(MemoryNode.id == created.id)
    row = (await async_session.execute(stmt)).scalar_one()
    assert row.tenant_id == "tenant_a"


async def test_create_memory_tenant_id_is_keyword_only(async_session, embedding_service):
    """tenant_id must be a required keyword arg — positional calls should not
    accidentally reach the old signature and silently fall back to 'default'."""
    import inspect

    sig = inspect.signature(_svc_create_memory)
    tenant_param = sig.parameters["tenant_id"]
    assert tenant_param.kind == inspect.Parameter.KEYWORD_ONLY
    assert tenant_param.default is inspect.Parameter.empty


async def test_update_memory_inherits_tenant_from_existing(async_session, embedding_service):
    """The new version must inherit tenant_id from the existing row, not
    from claims or a parameter. Tenant is a property of the memory."""
    from sqlalchemy import select
    from memoryhub_core.models.memory import MemoryNode

    original, _ = await _svc_create_memory(
        _make_create_data(content="original"),
        async_session,
        embedding_service,
        tenant_id="tenant_a",
    )
    assert original.tenant_id == "tenant_a"

    updated = await update_memory(
        original.id,
        MemoryNodeUpdate(content="updated"),
        async_session,
        embedding_service,
    )
    assert updated.tenant_id == "tenant_a"

    # The retired old version must also still carry its tenant (for
    # get_memory_history integrity -- historical versions are
    # tenant-bound).
    old_stmt = select(MemoryNode).where(MemoryNode.id == original.id)
    old_row = (await async_session.execute(old_stmt)).scalar_one()
    assert old_row.tenant_id == "tenant_a"


async def test_update_memory_deep_copied_children_inherit_tenant(async_session, embedding_service):
    """Deep-copied child branches from update_memory must inherit the
    parent's tenant so the whole subtree stays tenant-consistent."""
    from sqlalchemy import select
    from memoryhub_core.models.memory import MemoryNode

    parent, _ = await _svc_create_memory(
        _make_create_data(content="parent"),
        async_session,
        embedding_service,
        tenant_id="tenant_a",
    )
    await _svc_create_memory(
        _make_create_data(
            content="child rationale",
            parent_id=parent.id,
            branch_type="rationale",
        ),
        async_session,
        embedding_service,
        tenant_id="tenant_a",
    )

    new_parent = await update_memory(
        parent.id,
        MemoryNodeUpdate(content="parent v2"),
        async_session,
        embedding_service,
    )

    stmt = select(MemoryNode).where(MemoryNode.parent_id == new_parent.id)
    copied_children = (await async_session.execute(stmt)).scalars().all()
    assert len(copied_children) == 1
    assert copied_children[0].tenant_id == "tenant_a"


async def test_report_contradiction_inherits_tenant_from_memory(async_session, embedding_service):
    """The contradiction report row must carry the contradicted memory's
    tenant_id, inherited from the loaded memory — callers don't pass it."""
    from sqlalchemy import select
    from memoryhub_core.models.contradiction import ContradictionReport

    node, _ = await _svc_create_memory(
        _make_create_data(),
        async_session,
        embedding_service,
        tenant_id="tenant_a",
    )

    await report_contradiction(
        node.id,
        observed_behavior="observed contradicting thing",
        confidence=0.8,
        reporter="test-agent",
        session=async_session,
    )

    stmt = select(ContradictionReport).where(ContradictionReport.memory_id == node.id)
    report = (await async_session.execute(stmt)).scalar_one()
    assert report.tenant_id == "tenant_a"


# -- Phase 4 (#46) read-path tenant isolation tests --


async def test_read_memory_returns_not_found_for_cross_tenant(
    async_session, embedding_service
):
    """A read_memory call from tenant B targeting a tenant-A row must raise
    MemoryNotFoundError -- the same exception type as a nonexistent row,
    so the caller can never distinguish "does not exist" from "exists in
    another tenant."
    """
    created, _ = await _svc_create_memory(
        _make_create_data(content="tenant A secret"),
        async_session,
        embedding_service,
        tenant_id="tenant_a",
    )

    # Same-tenant read works.
    same_tenant = await _svc_read_memory(
        created.id, async_session, tenant_id="tenant_a"
    )
    assert same_tenant.id == created.id

    # Cross-tenant read raises MemoryNotFoundError (indistinguishable from
    # a nonexistent row).
    with pytest.raises(MemoryNotFoundError) as exc_info:
        await _svc_read_memory(created.id, async_session, tenant_id="tenant_b")
    assert exc_info.value.memory_id == created.id


async def test_search_memories_excludes_cross_tenant_results(
    async_session, embedding_service
):
    """search_memories must only surface memories from the caller's tenant.
    A search that would match a tenant-B memory from tenant A simply
    returns fewer results; the cross-tenant row is invisible at the SQL
    level, not merely dropped by a post-filter."""
    # Two memories with identical content in two tenants.
    await _svc_create_memory(
        _make_create_data(content="python preference in tenant A", weight=0.9),
        async_session,
        embedding_service,
        tenant_id="tenant_a",
    )
    await _svc_create_memory(
        _make_create_data(content="python preference in tenant B", weight=0.9),
        async_session,
        embedding_service,
        tenant_id="tenant_b",
    )

    # Tenant A search sees only its own memory.
    tenant_a_results = await _svc_search_memories(
        "python preference",
        async_session,
        embedding_service,
        tenant_id="tenant_a",
        owner_id="user-123",
    )
    assert len(tenant_a_results) == 1
    item_a, _ = tenant_a_results[0]
    assert item_a.tenant_id == "tenant_a"
    assert "tenant A" in item_a.content

    # Tenant B sees only its own.
    tenant_b_results = await _svc_search_memories(
        "python preference",
        async_session,
        embedding_service,
        tenant_id="tenant_b",
        owner_id="user-123",
    )
    assert len(tenant_b_results) == 1
    item_b, _ = tenant_b_results[0]
    assert item_b.tenant_id == "tenant_b"

    # A tenant that has no memories gets zero results, not a leak.
    none_results = await _svc_search_memories(
        "python preference",
        async_session,
        embedding_service,
        tenant_id="tenant_c",
        owner_id="user-123",
    )
    assert none_results == []


async def test_count_search_matches_excludes_cross_tenant_rows(
    async_session, embedding_service
):
    """count_search_matches contributes to has_more; cross-tenant rows
    must not inflate the count."""
    # Tenant A gets 2 memories; tenant B gets 3.
    for i in range(2):
        await _svc_create_memory(
            _make_create_data(content=f"tenant A memory {i}", weight=0.9),
            async_session,
            embedding_service,
            tenant_id="tenant_a",
        )
    for i in range(3):
        await _svc_create_memory(
            _make_create_data(content=f"tenant B memory {i}", weight=0.9),
            async_session,
            embedding_service,
            tenant_id="tenant_b",
        )

    count_a = await _svc_count_search_matches(
        async_session, tenant_id="tenant_a", owner_id="user-123"
    )
    count_b = await _svc_count_search_matches(
        async_session, tenant_id="tenant_b", owner_id="user-123"
    )
    assert count_a == 2
    assert count_b == 3


async def test_search_memories_with_focus_excludes_cross_tenant_results(
    async_session, embedding_service
):
    """Two-vector retrieval (focused search) must also honor tenant filter."""
    await _svc_create_memory(
        _make_create_data(content="OpenShift deployment in tenant A", weight=0.9),
        async_session,
        embedding_service,
        tenant_id="tenant_a",
    )
    await _svc_create_memory(
        _make_create_data(content="OpenShift deployment in tenant B", weight=0.9),
        async_session,
        embedding_service,
        tenant_id="tenant_b",
    )

    # Tenant A focused search sees only its own.
    bundle_a = await _svc_search_memories_with_focus(
        query="OpenShift deployment",
        session=async_session,
        embedding_service=embedding_service,
        tenant_id="tenant_a",
        focus_string="OpenShift",
        session_focus_weight=0.4,
        owner_id="user-123",
    )
    assert len(bundle_a.results) == 1
    assert bundle_a.results[0][0].tenant_id == "tenant_a"

    # Tenant B sees only its own.
    bundle_b = await _svc_search_memories_with_focus(
        query="OpenShift deployment",
        session=async_session,
        embedding_service=embedding_service,
        tenant_id="tenant_b",
        focus_string="OpenShift",
        session_focus_weight=0.4,
        owner_id="user-123",
    )
    assert len(bundle_b.results) == 1
    assert bundle_b.results[0][0].tenant_id == "tenant_b"


async def test_search_memories_with_focus_no_focus_path_honors_tenant(
    async_session, embedding_service
):
    """The short-circuit "no focus" path delegates to search_memories and
    must forward tenant_id, not fall through to the default."""
    await _svc_create_memory(
        _make_create_data(content="tenant A fallback content", weight=0.9),
        async_session,
        embedding_service,
        tenant_id="tenant_a",
    )
    await _svc_create_memory(
        _make_create_data(content="tenant B fallback content", weight=0.9),
        async_session,
        embedding_service,
        tenant_id="tenant_b",
    )

    # Empty focus forces the no-focus short-circuit.
    bundle = await _svc_search_memories_with_focus(
        query="fallback content",
        session=async_session,
        embedding_service=embedding_service,
        tenant_id="tenant_a",
        focus_string="",
        owner_id="user-123",
    )
    assert len(bundle.results) == 1
    assert bundle.results[0][0].tenant_id == "tenant_a"


async def test_get_memory_history_returns_not_found_for_cross_tenant(
    async_session, embedding_service
):
    """get_memory_history must refuse cross-tenant history walks.
    The version chain is tenant-bound by create/update, but the
    entry-point lookup also filters by tenant so an attacker cannot
    discover a chain they should not see."""
    v1, _ = await _svc_create_memory(
        _make_create_data(content="tenant A v1"),
        async_session,
        embedding_service,
        tenant_id="tenant_a",
    )
    await _svc_update_memory(
        v1.id,
        MemoryNodeUpdate(content="tenant A v2"),
        async_session,
        embedding_service,
    )

    # Same-tenant history works.
    history = await _svc_get_memory_history(
        v1.id, async_session, tenant_id="tenant_a"
    )
    assert history["total_versions"] == 2

    # Cross-tenant history raises MemoryNotFoundError.
    with pytest.raises(MemoryNotFoundError):
        await _svc_get_memory_history(v1.id, async_session, tenant_id="tenant_b")


async def test_read_memory_tenant_id_is_keyword_only():
    """tenant_id must be a required keyword arg on read_memory so any
    caller that forgets to thread it gets a loud TypeError rather than
    silently falling back to the default tenant."""
    import inspect

    sig = inspect.signature(_svc_read_memory)
    tenant_param = sig.parameters["tenant_id"]
    assert tenant_param.kind == inspect.Parameter.KEYWORD_ONLY
    assert tenant_param.default is inspect.Parameter.empty


async def test_search_memories_tenant_id_is_keyword_only():
    """Same invariant for search_memories: tenant_id is keyword-only and required."""
    import inspect

    sig = inspect.signature(_svc_search_memories)
    tenant_param = sig.parameters["tenant_id"]
    assert tenant_param.kind == inspect.Parameter.KEYWORD_ONLY
    assert tenant_param.default is inspect.Parameter.empty


async def test_get_memory_history_tenant_id_is_keyword_only():
    """Same invariant for get_memory_history: tenant_id is keyword-only and required."""
    import inspect

    sig = inspect.signature(_svc_get_memory_history)
    tenant_param = sig.parameters["tenant_id"]
    assert tenant_param.kind == inspect.Parameter.KEYWORD_ONLY
    assert tenant_param.default is inspect.Parameter.empty


# ---------------------------------------------------------------------------
# Two-tier storage (S3 + semantic chunking)
# ---------------------------------------------------------------------------


class MockS3Adapter:
    """In-memory S3 adapter for testing two-tier storage."""

    def __init__(self):
        self.store: dict[str, str] = {}
        self.deleted: list[str] = []

    async def put_content(self, tenant_id, memory_id, version_id, content):
        key = f"{tenant_id}/{memory_id}/{version_id}"
        self.store[key] = content
        return key

    async def get_content(self, content_ref):
        return self.store[content_ref]

    async def delete_content(self, content_ref):
        self.store.pop(content_ref, None)
        self.deleted.append(content_ref)

    async def delete_contents(self, refs):
        for ref in refs:
            self.store.pop(ref, None)
            self.deleted.append(ref)


def _make_oversized_content() -> str:
    """Return content exceeding the configured S3 threshold (default 1024 bytes).

    Uses distinct paragraphs separated by double-newlines so that the
    semantic chunker produces multiple chunks (it splits on paragraph
    boundaries first).
    """
    paragraphs = [
        f"Paragraph {i}: " + "x" * 400
        for i in range(15)
    ]
    return "\n\n".join(paragraphs)


# -- create_memory: two-tier storage --


async def test_create_memory_inline_when_under_threshold(async_session, embedding_service):
    """Content under 4096 bytes stays inline even with an S3 adapter present."""
    s3 = MockS3Adapter()
    data = _make_create_data(content="Short content that fits inline")
    result, curation = await create_memory(data, async_session, embedding_service, s3_adapter=s3)

    assert curation["blocked"] is False
    assert result.storage_type == "inline"
    assert result.content_ref is None
    assert len(s3.store) == 0, "nothing should be written to S3"


async def test_create_memory_s3_when_over_threshold(async_session, embedding_service):
    """Content over 4096 bytes is uploaded to S3 when an adapter is provided."""
    s3 = MockS3Adapter()
    big_content = _make_oversized_content()
    assert len(big_content.encode("utf-8")) > 4096

    data = _make_create_data(content=big_content)
    result, curation = await create_memory(data, async_session, embedding_service, s3_adapter=s3)

    assert curation["blocked"] is False
    assert result.storage_type == "s3"
    assert result.content_ref is not None
    assert result.content_ref in s3.store, "content_ref should be a valid S3 key"
    assert s3.store[result.content_ref] == big_content


async def test_create_memory_s3_creates_chunks(async_session, embedding_service):
    """Oversized S3 content produces chunk children with branch_type='chunk'."""
    from sqlalchemy import select as sa_select
    from memoryhub_core.models.memory import MemoryNode as MN

    s3 = MockS3Adapter()
    data = _make_create_data(content=_make_oversized_content())
    result, _ = await create_memory(data, async_session, embedding_service, s3_adapter=s3)

    chunks_stmt = sa_select(MN).where(
        MN.parent_id == result.id,
        MN.branch_type == "chunk",
        MN.deleted_at.is_(None),
    )
    chunks = (await async_session.execute(chunks_stmt)).scalars().all()

    assert len(chunks) >= 2, f"expected multiple chunks, got {len(chunks)}"
    for chunk in chunks:
        assert chunk.branch_type == "chunk"
        assert chunk.weight == 0.0
        assert chunk.is_current is True


async def test_create_memory_s3_chunks_have_embeddings(async_session, embedding_service):
    """Each semantic chunk gets its own embedding vector."""
    from sqlalchemy import select as sa_select
    from memoryhub_core.models.memory import MemoryNode as MN

    s3 = MockS3Adapter()
    data = _make_create_data(content=_make_oversized_content())
    result, _ = await create_memory(data, async_session, embedding_service, s3_adapter=s3)

    chunks_stmt = sa_select(MN).where(
        MN.parent_id == result.id,
        MN.branch_type == "chunk",
    )
    chunks = (await async_session.execute(chunks_stmt)).scalars().all()

    assert len(chunks) >= 2
    for chunk in chunks:
        assert chunk.embedding is not None, "chunk should have a non-None embedding"
        assert len(chunk.embedding) > 0, "embedding should not be empty"


async def test_create_memory_s3_no_adapter_inline_fallback(async_session, embedding_service):
    """Oversized content without an S3 adapter falls back to inline storage."""
    big_content = _make_oversized_content()
    assert len(big_content.encode("utf-8")) > 4096

    data = _make_create_data(content=big_content)
    result, curation = await create_memory(data, async_session, embedding_service, s3_adapter=None)

    assert curation["blocked"] is False
    assert result.storage_type == "inline"
    assert result.content_ref is None


async def test_create_memory_oversized_no_s3_truncates_embed_text(async_session, embedding_service):
    """Oversized content without S3 still truncates embed text to prevent 413."""
    from unittest.mock import AsyncMock
    from memoryhub_core.config import AppSettings

    big_content = _make_oversized_content()
    captured_texts = []
    original_embed = embedding_service.embed

    async def capturing_embed(text):
        captured_texts.append(text)
        return await original_embed(text)

    embedding_service.embed = capturing_embed
    try:
        data = _make_create_data(content=big_content)
        result, _ = await create_memory(data, async_session, embedding_service, s3_adapter=None)
    finally:
        embedding_service.embed = original_embed

    settings = AppSettings()
    # The first embed call is for the parent node
    assert len(captured_texts) >= 1
    assert len(captured_texts[0]) == settings.s3_prefix_chars, (
        f"embed text should be truncated to {settings.s3_prefix_chars} chars, "
        f"got {len(captured_texts[0])}"
    )


async def test_create_memory_oversized_no_s3_creates_chunks(async_session, embedding_service):
    """Oversized content without S3 still creates chunk children."""
    from sqlalchemy import select as sa_select
    from memoryhub_core.models.memory import MemoryNode as MN

    data = _make_create_data(content=_make_oversized_content())
    result, _ = await create_memory(data, async_session, embedding_service, s3_adapter=None)

    chunks_stmt = sa_select(MN).where(
        MN.parent_id == result.id,
        MN.branch_type == "chunk",
        MN.deleted_at.is_(None),
    )
    chunks = (await async_session.execute(chunks_stmt)).scalars().all()

    assert len(chunks) >= 2, f"expected multiple chunks, got {len(chunks)}"
    for chunk in chunks:
        assert chunk.weight == 0.0
        assert chunk.is_current is True
        assert chunk.storage_type == "inline"
    assert result.storage_type == "inline"
    assert result.content_ref is None


async def test_create_memory_oversized_no_s3_stores_full_content_inline(async_session, embedding_service):
    """Without S3, full oversized content is stored inline in the database."""
    big_content = _make_oversized_content()
    data = _make_create_data(content=big_content)
    result, _ = await create_memory(data, async_session, embedding_service, s3_adapter=None)

    assert result.content == big_content, "full content should be stored inline"
    assert result.storage_type == "inline"
    assert result.content_ref is None


# -- update_memory: two-tier storage --


async def test_update_memory_s3_content_changed_rechunks(async_session, embedding_service):
    """Updating S3 content retires old chunks and creates new ones."""
    from sqlalchemy import select as sa_select
    from memoryhub_core.models.memory import MemoryNode as MN

    s3 = MockS3Adapter()
    original_content = _make_oversized_content()
    data = _make_create_data(content=original_content)
    original, _ = await create_memory(data, async_session, embedding_service, s3_adapter=s3)

    # Verify original chunks exist
    old_chunks_stmt = sa_select(MN).where(
        MN.parent_id == original.id,
        MN.branch_type == "chunk",
    )
    old_chunks = (await async_session.execute(old_chunks_stmt)).scalars().all()
    assert len(old_chunks) >= 2

    # Update with new oversized content
    new_content = "\n\n".join(
        [f"Updated paragraph {i}: " + "y" * 400 for i in range(15)]
    )
    updated = await update_memory(
        original.id,
        MemoryNodeUpdate(content=new_content),
        async_session,
        embedding_service,
        s3_adapter=s3,
    )

    assert updated.storage_type == "s3"

    # Old chunks should be retired (is_current=False)
    async_session.expire_all()
    old_chunks = (await async_session.execute(old_chunks_stmt)).scalars().all()
    for chunk in old_chunks:
        assert chunk.is_current is False, "old chunks must be retired"

    # New chunks should exist under the updated version
    new_chunks_stmt = sa_select(MN).where(
        MN.parent_id == updated.id,
        MN.branch_type == "chunk",
        MN.is_current.is_(True),
    )
    new_chunks = (await async_session.execute(new_chunks_stmt)).scalars().all()
    assert len(new_chunks) >= 2, "new chunks should be created after rechunking"


async def test_update_memory_s3_content_unchanged_preserves_storage(async_session, embedding_service):
    """Updating only weight on an S3 memory preserves storage_type and content_ref."""
    s3 = MockS3Adapter()
    data = _make_create_data(content=_make_oversized_content(), weight=0.8)
    original, _ = await create_memory(data, async_session, embedding_service, s3_adapter=s3)

    assert original.storage_type == "s3"
    original_ref = original.content_ref

    updated = await update_memory(
        original.id,
        MemoryNodeUpdate(weight=0.5),
        async_session,
        embedding_service,
        s3_adapter=s3,
    )

    assert updated.storage_type == "s3"
    assert updated.content_ref == original_ref, "content_ref should be inherited when content is unchanged"


async def test_update_memory_non_chunk_branches_still_copied(async_session, embedding_service):
    """On content update, rationale branches are deep-copied but chunk branches are retired."""
    from sqlalchemy import select as sa_select
    from memoryhub_core.models.memory import MemoryNode as MN

    s3 = MockS3Adapter()
    parent_data = _make_create_data(content=_make_oversized_content())
    parent, _ = await create_memory(parent_data, async_session, embedding_service, s3_adapter=s3)

    # Add a rationale branch manually
    rationale_data = _make_create_data(
        content="Rationale: oversized content is stored in S3 for efficiency",
        parent_id=parent.id,
        branch_type="rationale",
    )
    await create_memory(rationale_data, async_session, embedding_service)

    # Verify starting state: chunks + 1 rationale
    children_stmt = sa_select(MN).where(MN.parent_id == parent.id, MN.deleted_at.is_(None))
    old_children = (await async_session.execute(children_stmt)).scalars().all()
    old_chunk_count = sum(1 for c in old_children if c.branch_type == "chunk")
    old_rationale_count = sum(1 for c in old_children if c.branch_type == "rationale")
    assert old_chunk_count >= 2
    assert old_rationale_count == 1

    # Update content (triggers rechunk + deep-copy of non-chunk branches)
    new_content = "\n\n".join(
        [f"Revised paragraph {i}: " + "z" * 400 for i in range(15)]
    )
    updated = await update_memory(
        parent.id,
        MemoryNodeUpdate(content=new_content),
        async_session,
        embedding_service,
        s3_adapter=s3,
    )

    # New version should have deep-copied rationale + new chunks
    new_children_stmt = sa_select(MN).where(
        MN.parent_id == updated.id,
        MN.deleted_at.is_(None),
    )
    new_children = (await async_session.execute(new_children_stmt)).scalars().all()

    new_rationale = [c for c in new_children if c.branch_type == "rationale"]
    new_chunks = [c for c in new_children if c.branch_type == "chunk"]

    assert len(new_rationale) == 1, "rationale branch should be deep-copied"
    assert len(new_chunks) >= 2, "new chunks should be created"
    # The copied rationale should have a new ID (deep copy, not move)
    old_rationale_ids = {c.id for c in old_children if c.branch_type == "rationale"}
    assert new_rationale[0].id not in old_rationale_ids, "deep-copied rationale should have a new ID"


async def test_update_memory_oversized_no_s3_creates_chunks(async_session, embedding_service):
    """Updating with oversized content and no S3 creates chunk children."""
    from sqlalchemy import select as sa_select
    from memoryhub_core.models.memory import MemoryNode as MN

    # Create a normal (small) inline memory
    data = _make_create_data(content="Short initial content")
    original, _ = await create_memory(data, async_session, embedding_service, s3_adapter=None)

    # Update with oversized content, still no S3
    new_content = _make_oversized_content()
    updated = await update_memory(
        original.id,
        MemoryNodeUpdate(content=new_content),
        async_session,
        embedding_service,
        s3_adapter=None,
    )

    assert updated.storage_type == "inline"
    assert updated.content_ref is None

    chunks_stmt = sa_select(MN).where(
        MN.parent_id == updated.id,
        MN.branch_type == "chunk",
        MN.is_current.is_(True),
    )
    chunks = (await async_session.execute(chunks_stmt)).scalars().all()
    assert len(chunks) >= 2, f"expected chunks after oversized update, got {len(chunks)}"


async def test_update_memory_oversized_no_s3_retires_old_chunks(async_session, embedding_service):
    """Updating oversized inline memory retires old chunks and creates new ones."""
    from sqlalchemy import select as sa_select
    from memoryhub_core.models.memory import MemoryNode as MN

    # Create oversized memory without S3 (now creates chunks)
    data = _make_create_data(content=_make_oversized_content())
    original, _ = await create_memory(data, async_session, embedding_service, s3_adapter=None)

    old_chunks_stmt = sa_select(MN).where(
        MN.parent_id == original.id,
        MN.branch_type == "chunk",
    )
    old_chunks = (await async_session.execute(old_chunks_stmt)).scalars().all()
    assert len(old_chunks) >= 2
    old_chunk_ids = {c.id for c in old_chunks}

    # Update with different oversized content
    new_content = "\n\n".join(
        [f"Updated paragraph {i}: " + "z" * 400 for i in range(15)]
    )
    updated = await update_memory(
        original.id,
        MemoryNodeUpdate(content=new_content),
        async_session,
        embedding_service,
        s3_adapter=None,
    )

    # Old chunks should be retired
    async_session.expire_all()
    old_chunks = (await async_session.execute(old_chunks_stmt)).scalars().all()
    for chunk in old_chunks:
        assert chunk.is_current is False, "old chunks must be retired"

    # New chunks should exist under updated version
    new_chunks_stmt = sa_select(MN).where(
        MN.parent_id == updated.id,
        MN.branch_type == "chunk",
        MN.is_current.is_(True),
    )
    new_chunks = (await async_session.execute(new_chunks_stmt)).scalars().all()
    assert len(new_chunks) >= 2, "new chunks should be created"
    new_chunk_ids = {c.id for c in new_chunks}
    assert old_chunk_ids.isdisjoint(new_chunk_ids), "new chunks should have different IDs"


# -- delete_memory: two-tier storage --


async def test_delete_memory_s3_removes_objects(async_session, embedding_service):
    """Deleting an S3-backed memory cleans up the S3 objects."""
    s3 = MockS3Adapter()
    data = _make_create_data(content=_make_oversized_content())
    result, _ = await create_memory(data, async_session, embedding_service, s3_adapter=s3)

    assert result.storage_type == "s3"
    content_ref = result.content_ref
    assert content_ref in s3.store

    await _svc_delete_memory(result.id, async_session, s3_adapter=s3)

    assert content_ref in s3.deleted, "S3 object should be deleted"
    assert content_ref not in s3.store, "S3 object should be removed from store"


async def test_delete_memory_inline_no_s3_cleanup(async_session, embedding_service):
    """Deleting an inline memory does not attempt S3 cleanup, even with an adapter."""
    s3 = MockS3Adapter()
    data = _make_create_data(content="Short inline content")
    result, _ = await create_memory(data, async_session, embedding_service, s3_adapter=s3)

    assert result.storage_type == "inline"

    await _svc_delete_memory(result.id, async_session, s3_adapter=s3)

    assert len(s3.deleted) == 0, "no S3 cleanup should be attempted for inline memories"


# -- force flag passthrough --


async def test_create_memory_passes_force(async_session, embedding_service, monkeypatch):
    """force=True is forwarded to run_curation_pipeline so gated writes can proceed."""
    from unittest.mock import AsyncMock, call
    import memoryhub_core.services.memory as _memory_module

    captured_kwargs: dict = {}

    original_pipeline = _memory_module.run_curation_pipeline

    async def _capturing_pipeline(*args, **kwargs):
        captured_kwargs.update(kwargs)
        # Delegate to the real pipeline so the test exercises no magic path.
        return await original_pipeline(*args, **kwargs)

    monkeypatch.setattr(_memory_module, "run_curation_pipeline", _capturing_pipeline)

    data = _make_create_data(content="prefers Podman for containers")
    await _svc_create_memory(
        data,
        async_session,
        embedding_service,
        tenant_id=_TEST_TENANT_ID,
        force=True,
    )

    assert "force" in captured_kwargs, "force kwarg was not forwarded to run_curation_pipeline"
    assert captured_kwargs["force"] is True, (
        f"Expected force=True forwarded, got force={captured_kwargs.get('force')!r}"
    )
