"""Unit tests for the graph relationship service layer.

Uses the same async in-memory SQLite setup as test_memory_service.py.
The pgvector Vector column and the PostgreSQL-specific metadata_ server_default
are patched out so that SQLite can create the schema.
"""

import uuid

import pytest

from memoryhub_core.models.schemas import (
    MemoryNodeCreate,
    MemoryScope,
    RelationshipCreate,
    RelationshipRead,
    RelationshipType,
)
from memoryhub_core.services.exceptions import MemoryNotFoundError, RelationshipNotFoundError
from memoryhub_core.services.graph import (
    create_relationship,
    delete_relationship,
    find_related,
    get_relationships,
    get_subtree,
    trace_provenance,
)
from memoryhub_core.services.memory import create_memory


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


async def _create_node(session, embedding_service, **overrides):
    """Create a memory node and return it."""
    data = _make_create_data(**overrides)
    node, _ = await create_memory(data, session, embedding_service)
    return node


def _make_relationship_data(**overrides) -> RelationshipCreate:
    """Build a RelationshipCreate with sensible defaults."""
    defaults = {
        "source_id": uuid.uuid4(),
        "target_id": uuid.uuid4(),
        "relationship_type": RelationshipType.related_to,
        "created_by": "agent-test",
    }
    defaults.update(overrides)
    return RelationshipCreate(**defaults)


# -- create_relationship --


@pytest.mark.asyncio
async def test_create_relationship(async_session, embedding_service):
    source = await _create_node(async_session, embedding_service, content="source node")
    target = await _create_node(async_session, embedding_service, content="target node")

    data = _make_relationship_data(
        source_id=source.id,
        target_id=target.id,
        relationship_type=RelationshipType.related_to,
        created_by="agent-test",
    )
    result = await create_relationship(data, async_session)

    assert isinstance(result, RelationshipRead)
    assert result.source_id == source.id
    assert result.target_id == target.id
    assert result.relationship_type == RelationshipType.related_to
    assert result.created_by == "agent-test"
    assert result.id is not None
    assert result.created_at is not None


@pytest.mark.asyncio
async def test_create_relationship_source_not_found(async_session, embedding_service):
    target = await _create_node(async_session, embedding_service, content="target node")
    fake_source_id = uuid.uuid4()

    data = _make_relationship_data(source_id=fake_source_id, target_id=target.id)
    with pytest.raises(MemoryNotFoundError) as exc_info:
        await create_relationship(data, async_session)
    assert exc_info.value.memory_id == fake_source_id


@pytest.mark.asyncio
async def test_create_relationship_target_not_found(async_session, embedding_service):
    source = await _create_node(async_session, embedding_service, content="source node")
    fake_target_id = uuid.uuid4()

    data = _make_relationship_data(source_id=source.id, target_id=fake_target_id)
    with pytest.raises(MemoryNotFoundError) as exc_info:
        await create_relationship(data, async_session)
    assert exc_info.value.memory_id == fake_target_id


@pytest.mark.asyncio
async def test_create_relationship_duplicate_raises(async_session, embedding_service):
    source = await _create_node(async_session, embedding_service, content="source node")
    target = await _create_node(async_session, embedding_service, content="target node")

    data = _make_relationship_data(source_id=source.id, target_id=target.id)
    await create_relationship(data, async_session)

    # Creating the same edge again should raise ValueError
    with pytest.raises(ValueError, match=str(source.id)):
        await create_relationship(data, async_session)


# -- delete_relationship --


@pytest.mark.asyncio
async def test_delete_relationship(async_session, embedding_service):
    source = await _create_node(async_session, embedding_service, content="source node")
    target = await _create_node(async_session, embedding_service, content="target node")

    data = _make_relationship_data(source_id=source.id, target_id=target.id)
    rel = await create_relationship(data, async_session)

    await delete_relationship(rel.id, async_session)

    # After deletion, the relationship should no longer be returned
    remaining = await get_relationships(source.id, async_session)
    assert all(r.id != rel.id for r in remaining)


@pytest.mark.asyncio
async def test_delete_relationship_not_found(async_session):
    fake_id = uuid.uuid4()
    with pytest.raises(RelationshipNotFoundError) as exc_info:
        await delete_relationship(fake_id, async_session)
    assert exc_info.value.relationship_id == fake_id


# -- get_relationships --


@pytest.mark.asyncio
async def test_get_relationships_both_directions(async_session, embedding_service):
    node_a = await _create_node(async_session, embedding_service, content="node A")
    node_b = await _create_node(async_session, embedding_service, content="node B")
    node_c = await _create_node(async_session, embedding_service, content="node C")

    # A -> B (outgoing from A)
    await create_relationship(
        _make_relationship_data(source_id=node_a.id, target_id=node_b.id), async_session
    )
    # C -> A (incoming to A)
    await create_relationship(
        _make_relationship_data(source_id=node_c.id, target_id=node_a.id), async_session
    )

    results = await get_relationships(node_a.id, async_session, direction="both")

    assert len(results) == 2
    rel_ids = {(r.source_id, r.target_id) for r in results}
    assert (node_a.id, node_b.id) in rel_ids
    assert (node_c.id, node_a.id) in rel_ids


@pytest.mark.asyncio
async def test_get_relationships_outgoing_only(async_session, embedding_service):
    node_a = await _create_node(async_session, embedding_service, content="node A")
    node_b = await _create_node(async_session, embedding_service, content="node B")
    node_c = await _create_node(async_session, embedding_service, content="node C")

    await create_relationship(
        _make_relationship_data(source_id=node_a.id, target_id=node_b.id), async_session
    )
    await create_relationship(
        _make_relationship_data(source_id=node_c.id, target_id=node_a.id), async_session
    )

    results = await get_relationships(node_a.id, async_session, direction="outgoing")

    assert len(results) == 1
    assert results[0].source_id == node_a.id
    assert results[0].target_id == node_b.id


@pytest.mark.asyncio
async def test_get_relationships_incoming_only(async_session, embedding_service):
    node_a = await _create_node(async_session, embedding_service, content="node A")
    node_b = await _create_node(async_session, embedding_service, content="node B")
    node_c = await _create_node(async_session, embedding_service, content="node C")

    await create_relationship(
        _make_relationship_data(source_id=node_a.id, target_id=node_b.id), async_session
    )
    await create_relationship(
        _make_relationship_data(source_id=node_c.id, target_id=node_a.id), async_session
    )

    results = await get_relationships(node_a.id, async_session, direction="incoming")

    assert len(results) == 1
    assert results[0].source_id == node_c.id
    assert results[0].target_id == node_a.id


@pytest.mark.asyncio
async def test_get_relationships_filter_by_type(async_session, embedding_service):
    node_a = await _create_node(async_session, embedding_service, content="node A")
    node_b = await _create_node(async_session, embedding_service, content="node B")
    node_c = await _create_node(async_session, embedding_service, content="node C")

    await create_relationship(
        _make_relationship_data(
            source_id=node_a.id,
            target_id=node_b.id,
            relationship_type=RelationshipType.related_to,
        ),
        async_session,
    )
    await create_relationship(
        _make_relationship_data(
            source_id=node_a.id,
            target_id=node_c.id,
            relationship_type=RelationshipType.derived_from,
        ),
        async_session,
    )

    results = await get_relationships(
        node_a.id, async_session, relationship_type="related_to"
    )

    assert len(results) == 1
    assert results[0].relationship_type == RelationshipType.related_to
    assert results[0].target_id == node_b.id


@pytest.mark.asyncio
async def test_get_relationships_nonexistent_node(async_session):
    fake_id = uuid.uuid4()
    with pytest.raises(MemoryNotFoundError) as exc_info:
        await get_relationships(fake_id, async_session)
    assert exc_info.value.memory_id == fake_id


# -- get_subtree --


@pytest.mark.asyncio
async def test_get_subtree_single_node(async_session, embedding_service):
    node = await _create_node(async_session, embedding_service, content="lone node")

    result = await get_subtree(node.id, async_session)

    assert result["node"].id == node.id
    assert result["children"] == []
    assert result["total_nodes"] == 1


@pytest.mark.asyncio
async def test_get_subtree_with_children(async_session, embedding_service):
    parent = await _create_node(async_session, embedding_service, content="parent node")
    child_a = await _create_node(
        async_session, embedding_service, content="child A", parent_id=parent.id, branch_type="description"
    )
    child_b = await _create_node(
        async_session, embedding_service, content="child B", parent_id=parent.id, branch_type="rationale"
    )

    result = await get_subtree(parent.id, async_session)

    assert result["node"].id == parent.id
    assert result["node"].has_children is True
    assert result["node"].has_rationale is True
    assert result["total_nodes"] == 3

    child_ids = {entry["node"].id for entry in result["children"]}
    assert child_a.id in child_ids
    assert child_b.id in child_ids


@pytest.mark.asyncio
async def test_get_subtree_depth_limit(async_session, embedding_service):
    root = await _create_node(async_session, embedding_service, content="root")
    level_1 = await _create_node(
        async_session, embedding_service, content="level 1", parent_id=root.id, branch_type="description"
    )
    await _create_node(
        async_session, embedding_service, content="level 2", parent_id=level_1.id, branch_type="description"
    )

    # Request only 1 level deep — should include root + level_1, not level_2
    result = await get_subtree(root.id, async_session, max_depth=1)

    assert result["node"].id == root.id
    assert len(result["children"]) == 1
    assert result["children"][0]["node"].id == level_1.id
    # Level 1's children list should be empty because max_depth=1 cuts it off
    assert result["children"][0]["children"] == []


# -- trace_provenance --


@pytest.mark.asyncio
async def test_trace_provenance_simple_chain(async_session, embedding_service):
    # A was derived from B, B was derived from C
    node_a = await _create_node(async_session, embedding_service, content="node A (derived)")
    node_b = await _create_node(async_session, embedding_service, content="node B (intermediate)")
    node_c = await _create_node(async_session, embedding_service, content="node C (origin)")

    # source=A, target=B means "A was derived from B"
    await create_relationship(
        _make_relationship_data(
            source_id=node_a.id,
            target_id=node_b.id,
            relationship_type=RelationshipType.derived_from,
        ),
        async_session,
    )
    # source=B, target=C means "B was derived from C"
    await create_relationship(
        _make_relationship_data(
            source_id=node_b.id,
            target_id=node_c.id,
            relationship_type=RelationshipType.derived_from,
        ),
        async_session,
    )

    steps = await trace_provenance(node_a.id, async_session)

    assert len(steps) == 2
    assert steps[0]["hop"] == 1
    assert steps[0]["node"].id == node_b.id
    assert steps[1]["hop"] == 2
    assert steps[1]["node"].id == node_c.id
    # Each step has a relationship
    assert isinstance(steps[0]["relationship"], RelationshipRead)
    assert steps[0]["relationship"].relationship_type == RelationshipType.derived_from


@pytest.mark.asyncio
async def test_trace_provenance_no_chain(async_session, embedding_service):
    node = await _create_node(async_session, embedding_service, content="standalone node")

    steps = await trace_provenance(node.id, async_session)

    assert steps == []


@pytest.mark.asyncio
async def test_trace_provenance_node_not_found(async_session):
    fake_id = uuid.uuid4()
    with pytest.raises(MemoryNotFoundError) as exc_info:
        await trace_provenance(fake_id, async_session)
    assert exc_info.value.memory_id == fake_id


# -- find_related --


@pytest.mark.asyncio
async def test_find_related_one_hop(async_session, embedding_service):
    node_a = await _create_node(async_session, embedding_service, content="node A")
    node_b = await _create_node(async_session, embedding_service, content="node B")

    await create_relationship(
        _make_relationship_data(source_id=node_a.id, target_id=node_b.id), async_session
    )

    results = await find_related(node_a.id, async_session, max_hops=1)

    assert len(results) == 1
    assert results[0]["node"].id == node_b.id
    assert results[0]["distance"] == 1
    assert len(results[0]["path"]) == 1


@pytest.mark.asyncio
async def test_find_related_two_hops(async_session, embedding_service):
    node_a = await _create_node(async_session, embedding_service, content="node A")
    node_b = await _create_node(async_session, embedding_service, content="node B")
    node_c = await _create_node(async_session, embedding_service, content="node C")

    await create_relationship(
        _make_relationship_data(source_id=node_a.id, target_id=node_b.id), async_session
    )
    await create_relationship(
        _make_relationship_data(source_id=node_b.id, target_id=node_c.id), async_session
    )

    results = await find_related(node_a.id, async_session, max_hops=2)

    found_ids = {r["node"].id for r in results}
    assert node_b.id in found_ids
    assert node_c.id in found_ids

    b_entry = next(r for r in results if r["node"].id == node_b.id)
    c_entry = next(r for r in results if r["node"].id == node_c.id)
    assert b_entry["distance"] == 1
    assert c_entry["distance"] == 2


@pytest.mark.asyncio
async def test_find_related_no_relationships(async_session, embedding_service):
    node = await _create_node(async_session, embedding_service, content="isolated node")

    results = await find_related(node.id, async_session)

    assert results == []
