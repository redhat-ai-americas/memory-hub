"""Phase 1 tests for procedural graph memory (#552).

Exit criteria from planning/procedural-graphs.md:
- ContentType + DB CHECK accept `procedural`
- RelationshipType accepts precedes/requires/alternative_to
- End-to-end procedure (root + steps + mixed edges including a cycle)
- get_subtree returns all steps
- find_related type-filter excludes unrelated edge types
- collect_graph_neighbors unfiltered SQL is unchanged (baseline for #553)
"""

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from memoryhub_core.models.memory import MemoryNode
from memoryhub_core.models.schemas import (
    ContentType,
    MemoryNodeCreate,
    MemoryScope,
    RelationshipCreate,
    RelationshipType,
)
from memoryhub_core.services.graph import (
    collect_graph_neighbors,
    create_relationship,
    find_related,
    get_subtree,
)
from memoryhub_core.services.memory import create_memory as _svc_create_memory
from memoryhub_core.services.memory import list_memories

_TEST_TENANT_ID = "default"
_PROCEDURAL_REL_TYPES = ["precedes", "requires", "alternative_to"]


async def _create_memory(data, session, embedding_service, **kwargs):
    return await _svc_create_memory(
        data,
        session,
        embedding_service,
        tenant_id=_TEST_TENANT_ID,
        skip_curation=True,
        **kwargs,
    )


def _make_node(**overrides) -> MemoryNodeCreate:
    defaults = {
        "content": "prefers Podman over Docker",
        "scope": MemoryScope.USER,
        "weight": 0.9,
        "owner_id": "user-123",
    }
    defaults.update(overrides)
    return MemoryNodeCreate(**defaults)


async def _create_node(session, embedding_service, **overrides):
    node, _ = await _create_memory(_make_node(**overrides), session, embedding_service)
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


def _raw_node(*, content_type: str, content: str = "raw insert") -> MemoryNode:
    now = datetime.now(UTC)
    node_id = uuid.uuid4()
    return MemoryNode(
        id=node_id,
        logical_id=node_id,
        content=content,
        stub=content[:80],
        scope="user",
        weight=0.9,
        owner_id="user-123",
        tenant_id=_TEST_TENANT_ID,
        is_current=True,
        version=1,
        storage_type="inline",
        content_type=content_type,
        created_at=now,
        updated_at=now,
    )


# ---------------------------------------------------------------------------
# Enum / CHECK constraint
# ---------------------------------------------------------------------------


def test_content_type_enum_accepts_procedural():
    assert ContentType("procedural") is ContentType.PROCEDURAL


def test_pydantic_create_accepts_procedural():
    node = _make_node(content_type="procedural")
    assert node.content_type == ContentType.PROCEDURAL


def test_pydantic_create_rejects_unknown_content_type():
    with pytest.raises(ValidationError):
        _make_node(content_type="not_a_type")


def test_relationship_type_enum_accepts_procedural_edges():
    assert RelationshipType("precedes") is RelationshipType.precedes
    assert RelationshipType("requires") is RelationshipType.requires
    assert RelationshipType("alternative_to") is RelationshipType.alternative_to


def test_pydantic_relationship_create_accepts_procedural_edges():
    src, tgt = uuid.uuid4(), uuid.uuid4()
    for rel_type in _PROCEDURAL_REL_TYPES:
        rel = _rel(src, tgt, rel_type)
        assert rel.relationship_type == rel_type


@pytest.mark.asyncio
async def test_db_check_accepts_procedural_insert(async_session):
    """ORM CHECK (mirroring Alembic 028) must allow content_type='procedural'."""
    async_session.add(_raw_node(content_type="procedural", content="deploy runbook"))
    await async_session.commit()

    stored = (
        await async_session.execute(select(MemoryNode).where(MemoryNode.content_type == "procedural"))
    ).scalars().first()
    assert stored is not None


@pytest.mark.asyncio
async def test_db_check_rejects_unknown_content_type(async_session):
    async_session.add(_raw_node(content_type="not_a_type"))
    with pytest.raises(IntegrityError):
        await async_session.commit()


# ---------------------------------------------------------------------------
# End-to-end procedural graph
# ---------------------------------------------------------------------------


@pytest.fixture
async def procedure_graph(async_session, embedding_service):
    """Root procedure + 3 steps, mixed edges, and a 3-node cycle."""
    root = await _create_node(
        async_session,
        embedding_service,
        content="Deploy to staging: smoke test, promote, verify health",
        content_type=ContentType.PROCEDURAL,
        metadata={"procedure": {"entry_step_id": None}},
    )
    smoke = await _create_node(
        async_session,
        embedding_service,
        content="Run the pre-deploy smoke test suite",
        content_type=ContentType.PROCEDURAL,
        parent_id=root.id,
        branch_type="procedure_step",
        metadata={
            "procedure": {
                "action": "Run the pre-deploy smoke test suite",
                "tool_ref": "run_tests.sh --suite=smoke",
                "preconditions": ["staging environment is healthy"],
                "postconditions": ["all smoke tests green"],
                "pitfalls": ["flaky test_cache_warmup fails ~5% of the time"],
                "guidance": "If this step fails twice, do not proceed to deploy.",
            }
        },
    )
    promote = await _create_node(
        async_session,
        embedding_service,
        content="Promote the image to staging",
        content_type=ContentType.PROCEDURAL,
        parent_id=root.id,
        branch_type="procedure_step",
        metadata={"procedure": {"action": "Promote the image to staging"}},
    )
    rollback = await _create_node(
        async_session,
        embedding_service,
        content="Roll back the last deploy",
        content_type=ContentType.PROCEDURAL,
        parent_id=root.id,
        branch_type="procedure_step",
        metadata={"procedure": {"action": "Roll back the last deploy"}},
    )
    # Topology: smoke -> promote -> rollback -> smoke (cycle) plus a requires edge.
    await create_relationship(
        _rel(
            smoke.id,
            promote.id,
            RelationshipType.precedes,
            metadata={"condition": "smoke tests passed"},
        ),
        async_session,
    )
    await create_relationship(
        _rel(promote.id, rollback.id, RelationshipType.precedes),
        async_session,
    )
    await create_relationship(
        _rel(
            rollback.id,
            smoke.id,
            RelationshipType.precedes,
            metadata={
                "condition": "health check failed after promote",
                "guidance": "Roll back, then re-run smoke tests.",
                "pitfalls": ["rollback script requires the previous image tag"],
            },
        ),
        async_session,
    )
    await create_relationship(
        _rel(promote.id, smoke.id, RelationshipType.requires),
        async_session,
    )
    await create_relationship(
        _rel(rollback.id, promote.id, RelationshipType.alternative_to),
        async_session,
    )
    return SimpleNamespace(root=root, smoke=smoke, promote=promote, rollback=rollback)


@pytest.mark.asyncio
async def test_procedural_graph_end_to_end(procedure_graph):
    root, smoke, promote, rollback = (
        procedure_graph.root,
        procedure_graph.smoke,
        procedure_graph.promote,
        procedure_graph.rollback,
    )
    assert root.content_type == "procedural"
    assert smoke.branch_type == "procedure_step"
    assert smoke.parent_id == root.id
    assert promote.parent_id == root.id
    assert rollback.parent_id == root.id
    assert smoke.metadata["procedure"]["tool_ref"] == "run_tests.sh --suite=smoke"


@pytest.mark.asyncio
async def test_get_subtree_returns_all_procedure_steps(async_session, procedure_graph):
    tree = await get_subtree(procedure_graph.root.id, async_session)
    child_ids = {child["node"].id for child in tree["children"]}
    assert tree["total_nodes"] == 4
    assert procedure_graph.smoke.id in child_ids
    assert procedure_graph.promote.id in child_ids
    assert procedure_graph.rollback.id in child_ids
    assert all(child["node"].branch_type == "procedure_step" for child in tree["children"])


@pytest.mark.asyncio
async def test_find_related_filters_to_procedural_edges(async_session, embedding_service, procedure_graph):
    outsider = await _create_node(
        async_session, embedding_service, content="unrelated note about cheese"
    )
    await create_relationship(
        _rel(procedure_graph.smoke.id, outsider.id, RelationshipType.related_to),
        async_session,
    )

    related = await find_related(
        procedure_graph.smoke.id,
        async_session,
        tenant_id=_TEST_TENANT_ID,
        relationship_types=_PROCEDURAL_REL_TYPES,
    )
    related_ids = {item["node"].id for item in related}
    assert outsider.id not in related_ids
    assert procedure_graph.promote.id in related_ids or procedure_graph.rollback.id in related_ids

    unfiltered = await find_related(
        procedure_graph.smoke.id, async_session, tenant_id=_TEST_TENANT_ID
    )
    unfiltered_ids = {item["node"].id for item in unfiltered}
    assert outsider.id in unfiltered_ids


@pytest.mark.asyncio
async def test_three_node_cycle_does_not_loop_forever(async_session, procedure_graph):
    """A precedes B, B precedes C, C precedes A is a valid graph (Decision 2)."""
    related = await find_related(
        procedure_graph.smoke.id,
        async_session,
        tenant_id=_TEST_TENANT_ID,
        max_hops=5,
        relationship_types=["precedes"],
    )
    related_ids = {item["node"].id for item in related}
    assert procedure_graph.promote.id in related_ids
    assert procedure_graph.rollback.id in related_ids
    # Starting node is excluded; each neighbor appears once.
    assert len(related) == len(related_ids)


@pytest.mark.asyncio
async def test_list_content_type_procedural_excludes_behavioral(
    async_session, embedding_service, procedure_graph
):
    await _create_node(
        async_session,
        embedding_service,
        content="When deploys fail, retry from smoke tests",
        content_type=ContentType.BEHAVIORAL,
    )
    hits, _cursor = await list_memories(
        async_session,
        tenant_id=_TEST_TENANT_ID,
        content_type="procedural",
    )
    types = {hit.content_type for hit in hits}
    assert types <= {"procedural"}
    assert any(hit.id == procedure_graph.root.id for hit in hits)
    assert all(hit.content_type != ContentType.BEHAVIORAL for hit in hits)


# ---------------------------------------------------------------------------
# collect_graph_neighbors — #553 baseline (mocked; CTE is PostgreSQL-only)
# ---------------------------------------------------------------------------


def _neighbor_session(rows=None):
    result = MagicMock()
    result.all.return_value = rows or []
    session = AsyncMock()
    session.execute = AsyncMock(return_value=result)
    return session


@pytest.mark.asyncio
async def test_collect_graph_neighbors_unfiltered_sql_has_no_type_clause():
    """#553 baseline: unfiltered neighbor collection does not exclude procedural edges."""
    session = _neighbor_session()
    seed = uuid.uuid4()
    await collect_graph_neighbors([seed], session, tenant_id="tenant-a")
    sql_obj = session.execute.call_args[0][0]
    assert "ANY(:rel_types)" not in str(sql_obj)


@pytest.mark.asyncio
async def test_collect_graph_neighbors_filtered_to_procedural_types():
    session = _neighbor_session()
    seed = uuid.uuid4()
    await collect_graph_neighbors(
        [seed],
        session,
        tenant_id="tenant-a",
        relationship_types=_PROCEDURAL_REL_TYPES,
    )
    _, call_kwargs = session.execute.call_args
    params = call_kwargs.get("parameters") or session.execute.call_args[0][1]
    assert params["rel_types"] == _PROCEDURAL_REL_TYPES
    sql_obj = session.execute.call_args[0][0]
    assert "ANY(:rel_types)" in str(sql_obj)
