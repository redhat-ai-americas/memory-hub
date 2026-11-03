"""Tenant-safe bounded traversal and procedure entry resolution (#553).

find_related had callers only in tests before this work. Those call sites
now pass tenant_id. The assertions here cover the contract added for
localized procedural retrieval: SQL tenant filters at every hop, directional
roles, deterministic BFS order, cycles, and the single-candidate entry fallback.
"""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import update

from memoryhub_core.models.memory import MemoryNode, MemoryRelationship
from memoryhub_core.models.schemas import (
    MemoryNodeCreate,
    MemoryScope,
    RelationshipCreate,
    RelationshipType,
)
from memoryhub_core.services.exceptions import EntryStepResolutionError, MemoryNotFoundError
from memoryhub_core.services.graph import (
    create_relationship,
    find_related,
    get_relationships,
    resolve_procedure_entry,
)
from memoryhub_core.services.memory import create_memory as _svc_create_memory

_TENANT_A = "tenant_a"
_TENANT_B = "tenant_b"

# Fixed ids so "pick the lowest UUID" cannot accidentally match the entry step.
# Hex letters are required: SQLite numeric affinity collapses all-digit
# UUID strings onto the same float and the unique constraint fires.
_ROOT = uuid.UUID("cccccccc-cccc-4ccc-8ccc-ccccccccccc0")
_STEP_A = uuid.UUID("cccccccc-cccc-4ccc-8ccc-ccccccccccca")
_STEP_B = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1")
_STEP_C = uuid.UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb2")


async def _create_node(session, embedding_service, *, tenant_id=_TENANT_A, **overrides):
    defaults = {
        "content": "procedural step",
        "scope": MemoryScope.USER,
        "weight": 0.9,
        "owner_id": "user-123",
    }
    defaults.update(overrides)
    node, _ = await _svc_create_memory(
        MemoryNodeCreate(**defaults),
        session,
        embedding_service,
        tenant_id=tenant_id,
        skip_curation=True,
    )
    return node


def _rel(source_id, target_id, rel_type, **overrides) -> RelationshipCreate:
    data = {
        "source_id": source_id,
        "target_id": target_id,
        "relationship_type": rel_type,
        "created_by": "agent-test",
    }
    data.update(overrides)
    return RelationshipCreate(**data)


async def _raw_edge(session, source_id, target_id, *, tenant_id, rel_type="precedes"):
    """Insert an edge without the same-tenant check in create_relationship."""
    now = datetime.now(UTC)
    rel = MemoryRelationship(
        id=uuid.uuid4(),
        source_id=source_id,
        target_id=target_id,
        relationship_type=rel_type,
        created_by="agent-test",
        tenant_id=tenant_id,
        metadata_={},
        valid_from=now,
        created_at=now,
    )
    session.add(rel)
    await session.commit()
    return rel


def _raw_node(
    node_id,
    *,
    content,
    tenant_id=_TENANT_A,
    parent_id=None,
    branch_type=None,
    metadata=None,
):
    now = datetime.now(UTC)
    return MemoryNode(
        id=node_id,
        logical_id=node_id,
        parent_id=parent_id,
        content=content,
        stub=content[:80],
        scope="user",
        weight=0.9,
        owner_id="user-123",
        tenant_id=tenant_id,
        is_current=True,
        version=1,
        storage_type="inline",
        content_type="procedural",
        branch_type=branch_type,
        metadata_=metadata,
        created_at=now,
        updated_at=now,
    )


async def _link(session, source_id, target_id, rel_type):
    return await create_relationship(_rel(source_id, target_id, rel_type), session)


# -- tenant isolation --


@pytest.mark.asyncio
async def test_find_related_other_tenant_start_is_not_found(async_session, embedding_service):
    start = await _create_node(async_session, embedding_service, content="start")
    neighbor = await _create_node(async_session, embedding_service, content="neighbor")
    await _link(async_session, start.id, neighbor.id, RelationshipType.precedes)

    with pytest.raises(MemoryNotFoundError) as exc_info:
        await find_related(start.id, async_session, tenant_id=_TENANT_B)

    assert exc_info.value.memory_id == start.id


@pytest.mark.asyncio
async def test_find_related_skips_other_tenant_edges_at_hop_1_and_2(async_session, embedding_service):
    """An edge owned by another tenant is invisible even when both nodes are ours."""
    start = await _create_node(async_session, embedding_service, content="start")
    near = await _create_node(async_session, embedding_service, content="near")
    secret = await _create_node(async_session, embedding_service, content="secret hop 1")
    far = await _create_node(async_session, embedding_service, content="far hop 2")
    await _link(async_session, start.id, near.id, RelationshipType.precedes)
    await _raw_edge(async_session, start.id, secret.id, tenant_id=_TENANT_B)
    await _raw_edge(async_session, near.id, far.id, tenant_id=_TENANT_B)

    results = await find_related(start.id, async_session, tenant_id=_TENANT_A, max_hops=2)

    found = {item["node"].id for item in results}
    assert found == {near.id}


@pytest.mark.asyncio
async def test_find_related_skips_other_tenant_nodes_at_hop_1_and_2(async_session, embedding_service):
    """A neighbor in another tenant is dropped even when the edge row says we own it."""
    start = await _create_node(async_session, embedding_service, content="start")
    near = await _create_node(async_session, embedding_service, content="near")
    foreign_hop1 = await _create_node(async_session, embedding_service, tenant_id=_TENANT_B, content="foreign hop 1")
    foreign_hop2 = await _create_node(async_session, embedding_service, tenant_id=_TENANT_B, content="foreign hop 2")
    await _link(async_session, start.id, near.id, RelationshipType.precedes)
    await _raw_edge(async_session, start.id, foreign_hop1.id, tenant_id=_TENANT_A)
    await _raw_edge(async_session, near.id, foreign_hop2.id, tenant_id=_TENANT_A)

    results = await find_related(start.id, async_session, tenant_id=_TENANT_A, max_hops=2)

    found = {item["node"].id for item in results}
    assert found == {near.id}
    assert all(item["node"].tenant_id == _TENANT_A for item in results)


@pytest.mark.asyncio
async def test_find_related_missing_start_raises(async_session):
    missing = uuid.uuid4()
    with pytest.raises(MemoryNotFoundError) as exc_info:
        await find_related(missing, async_session, tenant_id=_TENANT_A)
    assert exc_info.value.memory_id == missing


# -- bounds, filters, cycles, deletion --


@pytest.mark.asyncio
async def test_find_related_hop_cap_and_distance(async_session, embedding_service):
    nodes = []
    for index in range(7):
        nodes.append(await _create_node(async_session, embedding_service, content=f"step {index}"))
    for left, right in zip(nodes, nodes[1:], strict=False):
        await _link(async_session, left.id, right.id, RelationshipType.precedes)

    capped = await find_related(nodes[0].id, async_session, tenant_id=_TENANT_A, max_hops=9)
    assert [item["distance"] for item in capped] == [1, 2, 3, 4, 5]
    assert nodes[6].id not in {item["node"].id for item in capped}

    one_hop = await find_related(nodes[0].id, async_session, tenant_id=_TENANT_A, max_hops=1)
    assert [item["node"].id for item in one_hop] == [nodes[1].id]
    assert one_hop[0]["distance"] == 1

    none = await find_related(nodes[0].id, async_session, tenant_id=_TENANT_A, max_hops=0)
    assert none == []


@pytest.mark.asyncio
async def test_find_related_relationship_type_filter(async_session, embedding_service):
    start = await _create_node(async_session, embedding_service, content="start")
    successor = await _create_node(async_session, embedding_service, content="successor")
    aside = await _create_node(async_session, embedding_service, content="aside")
    await _link(async_session, start.id, successor.id, RelationshipType.precedes)
    await _link(async_session, start.id, aside.id, RelationshipType.related_to)

    filtered = await find_related(
        start.id,
        async_session,
        tenant_id=_TENANT_A,
        relationship_types=["precedes"],
    )
    assert {item["node"].id for item in filtered} == {successor.id}

    unfiltered = await find_related(start.id, async_session, tenant_id=_TENANT_A)
    assert {item["node"].id for item in unfiltered} == {successor.id, aside.id}
    aside_hit = next(item for item in unfiltered if item["node"].id == aside.id)
    assert aside_hit["path"][0]["role"] == "related_to"

    empty = await find_related(start.id, async_session, tenant_id=_TENANT_A, relationship_types=[])
    assert empty == []


@pytest.mark.asyncio
async def test_find_related_branching_graph(async_session, embedding_service):
    start = await _create_node(async_session, embedding_service, content="start")
    left = await _create_node(async_session, embedding_service, content="left")
    right = await _create_node(async_session, embedding_service, content="right")
    deeper = await _create_node(async_session, embedding_service, content="deeper")
    await _link(async_session, start.id, left.id, RelationshipType.precedes)
    await _link(async_session, start.id, right.id, RelationshipType.precedes)
    await _link(async_session, left.id, deeper.id, RelationshipType.precedes)

    results = await find_related(start.id, async_session, tenant_id=_TENANT_A, max_hops=2)
    by_id = {item["node"].id: item for item in results}
    assert set(by_id) == {left.id, right.id, deeper.id}
    assert by_id[left.id]["distance"] == 1
    assert by_id[right.id]["distance"] == 1
    assert by_id[deeper.id]["distance"] == 2
    assert by_id[deeper.id]["path"][0]["to_id"] == left.id
    assert start.id not in by_id


@pytest.mark.asyncio
async def test_find_related_three_node_cycle_terminates(async_session, embedding_service):
    first = await _create_node(async_session, embedding_service, content="first")
    second = await _create_node(async_session, embedding_service, content="second")
    third = await _create_node(async_session, embedding_service, content="third")
    await _link(async_session, first.id, second.id, RelationshipType.precedes)
    await _link(async_session, second.id, third.id, RelationshipType.precedes)
    await _link(async_session, third.id, first.id, RelationshipType.precedes)

    results = await find_related(
        first.id,
        async_session,
        tenant_id=_TENANT_A,
        max_hops=5,
        relationship_types=["precedes"],
    )
    found = [item["node"].id for item in results]
    assert found.count(second.id) == 1
    assert found.count(third.id) == 1
    assert first.id not in found
    assert len(found) == len(set(found)) == 2


@pytest.mark.asyncio
async def test_find_related_soft_deleted_node_ends_the_branch(async_session, embedding_service):
    start = await _create_node(async_session, embedding_service, content="start")
    middle = await _create_node(async_session, embedding_service, content="middle")
    tail = await _create_node(async_session, embedding_service, content="tail")
    await _link(async_session, start.id, middle.id, RelationshipType.precedes)
    await _link(async_session, middle.id, tail.id, RelationshipType.precedes)

    await async_session.execute(
        update(MemoryNode).where(MemoryNode.id == middle.id).values(deleted_at=datetime.now(UTC))
    )
    await async_session.commit()

    results = await find_related(start.id, async_session, tenant_id=_TENANT_A, max_hops=2)
    assert results == []


@pytest.mark.asyncio
async def test_find_related_soft_deleted_leaf_is_omitted(async_session, embedding_service):
    start = await _create_node(async_session, embedding_service, content="start")
    middle = await _create_node(async_session, embedding_service, content="middle")
    leaf = await _create_node(async_session, embedding_service, content="leaf")
    await _link(async_session, start.id, middle.id, RelationshipType.precedes)
    await _link(async_session, middle.id, leaf.id, RelationshipType.precedes)

    await async_session.execute(update(MemoryNode).where(MemoryNode.id == leaf.id).values(deleted_at=datetime.now(UTC)))
    await async_session.commit()

    results = await find_related(start.id, async_session, tenant_id=_TENANT_A, max_hops=2)
    assert [item["node"].id for item in results] == [middle.id]


@pytest.mark.asyncio
async def test_find_related_soft_deleted_start_raises(async_session, embedding_service):
    start = await _create_node(async_session, embedding_service, content="start")
    await async_session.execute(
        update(MemoryNode).where(MemoryNode.id == start.id).values(deleted_at=datetime.now(UTC))
    )
    await async_session.commit()

    with pytest.raises(MemoryNotFoundError):
        await find_related(start.id, async_session, tenant_id=_TENANT_A)


@pytest.mark.asyncio
async def test_find_related_inactive_edge_is_not_walked(async_session, embedding_service):
    start = await _create_node(async_session, embedding_service, content="start")
    closed = await _create_node(async_session, embedding_service, content="closed")
    open_node = await _create_node(async_session, embedding_service, content="open")
    closed_edge = await _link(async_session, start.id, closed.id, RelationshipType.precedes)
    await _link(async_session, start.id, open_node.id, RelationshipType.precedes)
    await async_session.execute(
        update(MemoryRelationship).where(MemoryRelationship.id == closed_edge.id).values(valid_until=datetime.now(UTC))
    )
    await async_session.commit()

    results = await find_related(start.id, async_session, tenant_id=_TENANT_A, max_hops=1)
    assert [item["node"].id for item in results] == [open_node.id]


@pytest.mark.asyncio
async def test_find_related_order_is_relationship_type_then_id(async_session, embedding_service):
    start = await _create_node(async_session, embedding_service, content="start")
    successor = await _create_node(async_session, embedding_service, content="successor")
    alternative = await _create_node(async_session, embedding_service, content="alternative")
    # Created first, but "precedes" sorts after "alternative_to".
    await _link(async_session, start.id, successor.id, RelationshipType.precedes)
    await _link(async_session, start.id, alternative.id, RelationshipType.alternative_to)

    results = await find_related(start.id, async_session, tenant_id=_TENANT_A, max_hops=1)
    assert [item["node"].id for item in results] == [alternative.id, successor.id]

    same_type_start = await _create_node(async_session, embedding_service, content="same-type start")
    left = await _create_node(async_session, embedding_service, content="left")
    right = await _create_node(async_session, embedding_service, content="right")
    await _link(async_session, same_type_start.id, left.id, RelationshipType.precedes)
    await _link(async_session, same_type_start.id, right.id, RelationshipType.precedes)
    same = await find_related(same_type_start.id, async_session, tenant_id=_TENANT_A, max_hops=1)
    same_edges = await get_relationships(same_type_start.id, async_session, tenant_id=_TENANT_A)
    expected = [
        edge.target_id for edge in sorted(same_edges, key=lambda edge: (str(edge.relationship_type), str(edge.id)))
    ]
    assert [item["node"].id for item in same] == expected


# -- directional roles --


@pytest.mark.asyncio
async def test_find_related_tags_four_distinct_roles(async_session, embedding_service):
    current = await _create_node(async_session, embedding_service, content="current")
    predecessor = await _create_node(async_session, embedding_service, content="predecessor")
    successor = await _create_node(async_session, embedding_service, content="successor")
    prerequisite = await _create_node(async_session, embedding_service, content="prerequisite")
    alternative = await _create_node(async_session, embedding_service, content="alternative")

    await _link(async_session, predecessor.id, current.id, RelationshipType.precedes)
    await _link(async_session, current.id, successor.id, RelationshipType.precedes)
    # Current requires the prerequisite: the neighbor is what must hold first.
    await _link(async_session, current.id, prerequisite.id, RelationshipType.requires)
    # alternative_to is symmetric; the alternative sits on the source end.
    await _link(async_session, alternative.id, current.id, RelationshipType.alternative_to)

    results = await find_related(
        current.id,
        async_session,
        tenant_id=_TENANT_A,
        max_hops=1,
        relationship_types=["precedes", "requires", "alternative_to"],
    )
    roles = {item["node"].id: item["path"][0] for item in results}
    assert set(roles) == {predecessor.id, successor.id, prerequisite.id, alternative.id}
    assert roles[predecessor.id]["role"] == "predecessor"
    assert roles[predecessor.id]["direction"] == "incoming"
    assert roles[successor.id]["role"] == "successor"
    assert roles[successor.id]["direction"] == "outgoing"
    assert roles[prerequisite.id]["role"] == "prerequisite"
    assert roles[prerequisite.id]["direction"] == "outgoing"
    assert roles[alternative.id]["role"] == "alternative"
    assert roles[alternative.id]["direction"] == "incoming"
    assert len({hop["role"] for hop in roles.values()}) == 4


@pytest.mark.asyncio
async def test_find_related_requires_target_is_dependent(async_session, embedding_service):
    current = await _create_node(async_session, embedding_service, content="current")
    dependent = await _create_node(async_session, embedding_service, content="dependent")
    await _link(async_session, dependent.id, current.id, RelationshipType.requires)

    results = await find_related(current.id, async_session, tenant_id=_TENANT_A, max_hops=1)
    hop = results[0]["path"][0]
    assert hop["role"] == "dependent"
    assert hop["direction"] == "incoming"


@pytest.mark.asyncio
async def test_find_related_two_hop_path_is_not_collapsed(async_session, embedding_service):
    current = await _create_node(async_session, embedding_service, content="current")
    mid = await _create_node(async_session, embedding_service, content="mid")
    needed = await _create_node(async_session, embedding_service, content="needed")
    other = await _create_node(async_session, embedding_service, content="other")
    await _link(async_session, current.id, mid.id, RelationshipType.precedes)
    await _link(async_session, mid.id, needed.id, RelationshipType.requires)
    await _link(async_session, other.id, mid.id, RelationshipType.precedes)

    results = await find_related(current.id, async_session, tenant_id=_TENANT_A, max_hops=2)
    by_id = {item["node"].id: item for item in results}

    assert by_id[mid.id]["distance"] == 1
    assert by_id[mid.id]["path"][0]["role"] == "successor"

    needed_path = by_id[needed.id]["path"]
    assert by_id[needed.id]["distance"] == 2
    assert len(needed_path) == 2
    assert needed_path[0]["role"] == "successor"
    assert needed_path[0]["direction"] == "outgoing"
    assert str(needed_path[0]["relationship"].relationship_type) == "precedes"
    assert needed_path[0]["from_id"] == current.id
    assert needed_path[0]["to_id"] == mid.id
    assert needed_path[1]["role"] == "prerequisite"
    assert needed_path[1]["direction"] == "outgoing"
    assert str(needed_path[1]["relationship"].relationship_type) == "requires"
    assert needed_path[1]["from_id"] == mid.id
    assert needed_path[1]["to_id"] == needed.id
    assert "role" not in by_id[needed.id]

    other_path = by_id[other.id]["path"]
    assert other_path[1]["role"] == "predecessor"
    assert other_path[1]["direction"] == "incoming"
    assert other_path[1]["from_id"] == mid.id
    assert other_path[1]["to_id"] == other.id


# -- entry step resolution --


async def _persist_procedure(session, root, *steps):
    session.add(root)
    session.add_all(steps)
    await session.commit()


@pytest.mark.asyncio
async def test_resolve_entry_single_candidate_ignores_uuid_order(async_session):
    """A → B → C. A is the only step with no incoming precedes, and its id sorts last."""
    root = _raw_node(_ROOT, content="deploy")
    step_a = _raw_node(_STEP_A, content="A", parent_id=_ROOT, branch_type="procedure_step")
    step_b = _raw_node(_STEP_B, content="B", parent_id=_ROOT, branch_type="procedure_step")
    step_c = _raw_node(_STEP_C, content="C", parent_id=_ROOT, branch_type="procedure_step")
    await _persist_procedure(async_session, root, step_a, step_b, step_c)
    await _link(async_session, _STEP_A, _STEP_B, RelationshipType.precedes)
    await _link(async_session, _STEP_B, _STEP_C, RelationshipType.precedes)

    resolved = await resolve_procedure_entry(_ROOT, async_session, tenant_id=_TENANT_A)
    assert resolved == _STEP_A
    assert str(_STEP_A) > str(_STEP_B)
    assert str(_STEP_A) > str(_STEP_C)


@pytest.mark.asyncio
async def test_resolve_entry_several_candidates_names_them(async_session):
    """A → C and B → C. A and B are both entries; neither is chosen."""
    root = _raw_node(_ROOT, content="deploy")
    step_a = _raw_node(_STEP_A, content="A", parent_id=_ROOT, branch_type="procedure_step")
    step_b = _raw_node(_STEP_B, content="B", parent_id=_ROOT, branch_type="procedure_step")
    step_c = _raw_node(_STEP_C, content="C", parent_id=_ROOT, branch_type="procedure_step")
    await _persist_procedure(async_session, root, step_a, step_b, step_c)
    await _link(async_session, _STEP_A, _STEP_C, RelationshipType.precedes)
    await _link(async_session, _STEP_B, _STEP_C, RelationshipType.precedes)

    with pytest.raises(EntryStepResolutionError) as exc_info:
        await resolve_procedure_entry(_ROOT, async_session, tenant_id=_TENANT_A)

    err = exc_info.value
    assert err.candidates == sorted([_STEP_A, _STEP_B], key=str)
    assert str(_STEP_A) in str(err)
    assert str(_STEP_B) in str(err)
    assert "current_step_id" in str(err)


@pytest.mark.asyncio
async def test_resolve_entry_cycle_has_no_candidate(async_session):
    root = _raw_node(_ROOT, content="retry loop")
    step_a = _raw_node(_STEP_A, content="A", parent_id=_ROOT, branch_type="procedure_step")
    step_b = _raw_node(_STEP_B, content="B", parent_id=_ROOT, branch_type="procedure_step")
    step_c = _raw_node(_STEP_C, content="C", parent_id=_ROOT, branch_type="procedure_step")
    await _persist_procedure(async_session, root, step_a, step_b, step_c)
    await _link(async_session, _STEP_A, _STEP_B, RelationshipType.precedes)
    await _link(async_session, _STEP_B, _STEP_C, RelationshipType.precedes)
    await _link(async_session, _STEP_C, _STEP_A, RelationshipType.precedes)

    with pytest.raises(EntryStepResolutionError) as exc_info:
        await resolve_procedure_entry(_ROOT, async_session, tenant_id=_TENANT_A)

    assert exc_info.value.candidates == []
    assert "current_step_id" in str(exc_info.value)


@pytest.mark.asyncio
async def test_resolve_entry_requires_edge_does_not_pick_a_start(async_session):
    root = _raw_node(_ROOT, content="deploy")
    step_a = _raw_node(_STEP_A, content="A", parent_id=_ROOT, branch_type="procedure_step")
    step_b = _raw_node(_STEP_B, content="B", parent_id=_ROOT, branch_type="procedure_step")
    await _persist_procedure(async_session, root, step_a, step_b)
    await _link(async_session, _STEP_B, _STEP_A, RelationshipType.requires)

    with pytest.raises(EntryStepResolutionError) as exc_info:
        await resolve_procedure_entry(_ROOT, async_session, tenant_id=_TENANT_A)

    assert set(exc_info.value.candidates) == {_STEP_A, _STEP_B}


@pytest.mark.asyncio
async def test_resolve_entry_uses_explicit_id_over_heuristic(async_session):
    root = _raw_node(
        _ROOT,
        content="deploy",
        metadata={"procedure": {"entry_step_id": str(_STEP_C)}},
    )
    step_a = _raw_node(_STEP_A, content="A", parent_id=_ROOT, branch_type="procedure_step")
    step_b = _raw_node(_STEP_B, content="B", parent_id=_ROOT, branch_type="procedure_step")
    step_c = _raw_node(_STEP_C, content="C", parent_id=_ROOT, branch_type="procedure_step")
    await _persist_procedure(async_session, root, step_a, step_b, step_c)
    await _link(async_session, _STEP_A, _STEP_B, RelationshipType.precedes)
    await _link(async_session, _STEP_B, _STEP_C, RelationshipType.precedes)

    resolved = await resolve_procedure_entry(_ROOT, async_session, tenant_id=_TENANT_A)
    assert resolved == _STEP_C


@pytest.mark.asyncio
async def test_resolve_entry_blank_field_uses_heuristic(async_session):
    root = _raw_node(
        _ROOT,
        content="deploy",
        metadata={"procedure": {"entry_step_id": "  "}},
    )
    step_a = _raw_node(_STEP_A, content="A", parent_id=_ROOT, branch_type="procedure_step")
    step_b = _raw_node(_STEP_B, content="B", parent_id=_ROOT, branch_type="procedure_step")
    await _persist_procedure(async_session, root, step_a, step_b)
    await _link(async_session, _STEP_A, _STEP_B, RelationshipType.precedes)

    resolved = await resolve_procedure_entry(_ROOT, async_session, tenant_id=_TENANT_A)
    assert resolved == _STEP_A


@pytest.mark.asyncio
async def test_resolve_entry_malformed_id_does_not_guess(async_session):
    root = _raw_node(
        _ROOT,
        content="deploy",
        metadata={"procedure": {"entry_step_id": "not-a-uuid"}},
    )
    step_a = _raw_node(_STEP_A, content="A", parent_id=_ROOT, branch_type="procedure_step")
    await _persist_procedure(async_session, root, step_a)

    with pytest.raises(EntryStepResolutionError) as exc_info:
        await resolve_procedure_entry(_ROOT, async_session, tenant_id=_TENANT_A)

    assert exc_info.value.candidates == []
    assert "not-a-uuid" in str(exc_info.value)
    assert "current_step_id" in str(exc_info.value)


@pytest.mark.asyncio
async def test_resolve_entry_dangling_id_is_not_found(async_session):
    missing = uuid.uuid4()
    root = _raw_node(
        _ROOT,
        content="deploy",
        metadata={"procedure": {"entry_step_id": str(missing)}},
    )
    step_a = _raw_node(_STEP_A, content="A", parent_id=_ROOT, branch_type="procedure_step")
    await _persist_procedure(async_session, root, step_a)

    with pytest.raises(MemoryNotFoundError) as exc_info:
        await resolve_procedure_entry(_ROOT, async_session, tenant_id=_TENANT_A)
    assert exc_info.value.memory_id == missing


@pytest.mark.asyncio
async def test_resolve_entry_other_tenant_target_is_not_found(async_session):
    foreign = _raw_node(_STEP_C, content="foreign step", tenant_id=_TENANT_B, branch_type="procedure_step")
    root = _raw_node(
        _ROOT,
        content="deploy",
        metadata={"procedure": {"entry_step_id": str(_STEP_C)}},
    )
    await _persist_procedure(async_session, root, foreign)

    with pytest.raises(MemoryNotFoundError) as exc_info:
        await resolve_procedure_entry(_ROOT, async_session, tenant_id=_TENANT_A)
    assert exc_info.value.memory_id == _STEP_C


@pytest.mark.asyncio
async def test_resolve_entry_deleted_explicit_step_is_not_found(async_session):
    root = _raw_node(
        _ROOT,
        content="deploy",
        metadata={"procedure": {"entry_step_id": str(_STEP_B)}},
    )
    step_a = _raw_node(_STEP_A, content="A", parent_id=_ROOT, branch_type="procedure_step")
    step_b = _raw_node(_STEP_B, content="B", parent_id=_ROOT, branch_type="procedure_step")
    await _persist_procedure(async_session, root, step_a, step_b)
    await _link(async_session, _STEP_A, _STEP_B, RelationshipType.precedes)
    await async_session.execute(update(MemoryNode).where(MemoryNode.id == _STEP_B).values(deleted_at=datetime.now(UTC)))
    await async_session.commit()

    with pytest.raises(MemoryNotFoundError):
        await resolve_procedure_entry(_ROOT, async_session, tenant_id=_TENANT_A)


@pytest.mark.asyncio
async def test_resolve_entry_unknown_procedure_raises(async_session):
    missing = uuid.uuid4()
    with pytest.raises(MemoryNotFoundError) as exc_info:
        await resolve_procedure_entry(missing, async_session, tenant_id=_TENANT_A)
    assert exc_info.value.memory_id == missing


@pytest.mark.asyncio
async def test_find_related_puts_each_stub_on_the_end_it_belongs_to(async_session, embedding_service):
    """Regression: the neighbor's stub went to the opposite end of the edge.

    ``RelationshipRead.source_stub`` is the stub of the node at
    ``source_id`` and ``target_stub`` the one at ``target_id``. The
    original implementation of this function inverted both. Nothing
    caught it because the function had no callers; #553 started
    returning these edges through the MCP and SDK responses, which made
    a dormant bug an incorrect API field.

    Checks both orientations: a neighbor reached as the edge's target
    (outgoing) and one reached as its source (incoming).
    """
    current = await _create_node(async_session, embedding_service, content="current step")
    successor = await _create_node(async_session, embedding_service, content="successor step")
    predecessor = await _create_node(async_session, embedding_service, content="predecessor step")
    await _link(async_session, current.id, successor.id, RelationshipType.precedes)
    await _link(async_session, predecessor.id, current.id, RelationshipType.precedes)

    results = await find_related(current.id, async_session, tenant_id=_TENANT_A, max_hops=1)
    by_id = {item["node"].id: item for item in results}
    assert set(by_id) == {successor.id, predecessor.id}

    # Neighbor is the target: its stub is the target_stub, and the source
    # end (the start node, which this walk does not hydrate) stays unset.
    out_edge = by_id[successor.id]["path"][0]["relationship"]
    assert out_edge.target_id == successor.id
    assert out_edge.target_stub == successor.stub
    assert out_edge.source_stub is None

    # Neighbor is the source: mirror image.
    in_edge = by_id[predecessor.id]["path"][0]["relationship"]
    assert in_edge.source_id == predecessor.id
    assert in_edge.source_stub == predecessor.stub
    assert in_edge.target_stub is None
