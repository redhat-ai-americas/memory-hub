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
