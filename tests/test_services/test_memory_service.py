"""Unit tests for the core memory service layer.

Uses async in-memory SQLite. The pgvector Vector column is replaced with a
plain JSON-like column via a listener so that the schema can be created
without the pgvector extension.
"""

import uuid

import pytest

from memoryhub.models.schemas import (
    MemoryNodeCreate,
    MemoryNodeRead,
    MemoryNodeStub,
    MemoryNodeUpdate,
    MemoryScope,
)
from memoryhub.services.exceptions import MemoryNotCurrentError, MemoryNotFoundError
from memoryhub.services.memory import (
    create_memory,
    get_memory_history,
    read_memory,
    report_contradiction,
    search_memories,
    update_memory,
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

    result = await read_memory(parent.id, async_session, depth=1)

    assert result.has_children is True
    assert result.has_rationale is True


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

    # Read the new version with depth=1 to see its branches
    new_with_branches = await read_memory(updated.id, async_session, depth=1)
    assert new_with_branches.branches is not None
    assert len(new_with_branches.branches) == 2

    # The copied branches should have different IDs than the originals
    copied_ids = {b.id for b in new_with_branches.branches}
    assert rationale.id not in copied_ids

    # But the content should match
    copied_rationale = [b for b in new_with_branches.branches if b.branch_type == "rationale"]
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


# -- report_contradiction --


async def test_report_contradiction(async_session, embedding_service):
    from sqlalchemy import select
    from memoryhub.models.contradiction import ContradictionReport

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
    from memoryhub.models.contradiction import ContradictionReport

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
