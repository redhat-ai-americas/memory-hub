"""Core and BFF share the same complete delete closure."""

import uuid

import pytest
from sqlalchemy import select

from memoryhub_core.models.memory import MemoryNode
from memoryhub_core.services.exceptions import MemoryAccessDeniedError
from memoryhub_core.services.memory import collect_delete_nodes, delete_memory


def _node(owner: str, *, parent_id=None, previous_version_id=None):
    node_id = uuid.uuid4()
    return MemoryNode(
        id=node_id,
        logical_id=node_id,
        content="content",
        stub="stub",
        scope="user",
        owner_id=owner,
        tenant_id="tenant-a",
        weight=0.7,
        parent_id=parent_id,
        previous_version_id=previous_version_id,
        version=1,
        is_current=True,
    )


@pytest.mark.asyncio
async def test_delete_requires_exact_authorized_closure_and_reaches_nested_branch(async_session):
    root = _node("alice")
    newer = _node("alice", previous_version_id=root.id)
    child = _node("bob", parent_id=newer.id)
    grandchild = _node("carol", parent_id=child.id)
    async_session.add_all([root, newer, child, grandchild])
    await async_session.commit()

    affected = await collect_delete_nodes(root, async_session, "tenant-a")
    expected = {root.id, newer.id, child.id, grandchild.id}
    root_id = root.id
    grandchild_id = grandchild.id
    assert set(affected) == expected

    with pytest.raises(MemoryAccessDeniedError, match="closure changed"):
        await delete_memory(root_id, async_session, tenant_id="tenant-a", expected_ids={root_id})
    await async_session.rollback()
    assert (await async_session.get(MemoryNode, grandchild_id)).deleted_at is None

    result = await delete_memory(root_id, async_session, tenant_id="tenant-a", expected_ids=expected)
    assert result["total_deleted"] == 4
    assert result["versions_deleted"] == 2
    assert result["branches_deleted"] == 2
    async_session.expire_all()
    rows = (await async_session.execute(select(MemoryNode).where(MemoryNode.id.in_(expected)))).scalars().all()
    assert len(rows) == 4
    assert all(row.deleted_at is not None for row in rows)


@pytest.mark.asyncio
async def test_capability_and_mutation_share_cycles_deleted_bridges_and_tenant_boundary(async_session):
    from memoryhub_core.authorization.human import Access, Principal
    from memoryhub_core.queries.deletion import delete_capabilities

    root = _node("alice")
    bridge = _node("alice", parent_id=root.id)
    nested = _node("bob", parent_id=bridge.id)
    foreign = _node("alice", parent_id=root.id)
    foreign.tenant_id = "tenant-b"
    async_session.add_all([root, bridge, nested, foreign])
    await async_session.flush()
    # Corrupt version cycles must terminate, and a deleted intermediate branch
    # must not hide its live descendant from either permission or deletion.
    root.previous_version_id = nested.id
    nested.previous_version_id = root.id
    from datetime import UTC, datetime
    bridge.deleted_at = datetime.now(UTC)
    await async_session.commit()

    policy = Access(Principal("alice", "user", "tenant-a"))
    found = await collect_delete_nodes(root, async_session, "tenant-a")
    assert set(found) == {root.id, bridge.id, nested.id}
    capabilities = await delete_capabilities(async_session, policy, [root, foreign])
    assert capabilities == {root.id: False, foreign.id: False}
    assert capabilities[root.id] == all(policy.can_delete(row) for row in found.values() if row.deleted_at is None)


@pytest.mark.asyncio
@pytest.mark.parametrize("changed", ["added", "removed"])
async def test_locked_closure_rechecks_rows_that_change_while_waiting(changed):
    from unittest.mock import AsyncMock, MagicMock

    root = _node("alice")
    child = _node("alice", parent_id=root.id)
    grandchild = _node("alice", parent_id=child.id)

    def rows(nodes):
        result = MagicMock()
        result.scalars.return_value.all.return_value = nodes
        return result

    initial = [root, child]
    # A recursive SELECT has one snapshot. Once all discovered rows have been
    # locked, the next snapshot must include a committed child or drop a row
    # moved away before its lock was acquired. A growing-only union is unsafe.
    final = [root, child, grandchild] if changed == "added" else [root]
    session = AsyncMock()
    session.execute.side_effect = [rows(initial), rows(final), rows(final)]
    found = await collect_delete_nodes(root, session, "tenant-a", seed_locked=True)
    assert set(found) == {row.id for row in final}
    assert session.execute.await_count == 3
    session.commit.assert_not_awaited()
