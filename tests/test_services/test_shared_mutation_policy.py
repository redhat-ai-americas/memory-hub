"""Write invariants apply to every caller of the shared Core services."""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from memoryhub_core.models.curation import CuratorRule
from memoryhub_core.models.memory import MemoryNode, MemoryRelationship
from memoryhub_core.models.schemas import MemoryNodeCreate, MemoryNodeUpdate
from memoryhub_core.queries.mutations import RelationshipBoundaryError
from memoryhub_core.services.exceptions import CurationBlockedError, MemoryAccessDeniedError
from memoryhub_core.services.memory import (
    create_memory,
    delete_memory,
    prepare_memory_delete,
    stage_memory_delete,
    update_memory,
)


async def seed(session, embedding, content="Allowed content", *, parent=None, owner="alice"):
    node, _ = await create_memory(
        MemoryNodeCreate(content=content, scope="user", owner_id=owner,
                         parent_id=parent, branch_type="evidence" if parent else None),
        session, embedding, tenant_id="tenant-a", skip_curation=True,
    )
    return node.id


@pytest.mark.parametrize("action", ["block", "quarantine", "reject_with_pointer"])
async def test_core_update_vetoes_content_without_retiring_current_version(async_session, embedding_service, action):
    db = async_session
    memory_id = await seed(db, embedding_service)
    db.add(CuratorRule(
        id=uuid.uuid4(), tenant_id="tenant-a", name="protected-content", layer="organizational",
        owner_id=None, trigger="on_write", tier="regex", config={"pattern": "FORBIDDEN_CONTENT"},
        action=action, enabled=True, override=True, priority=0,
    ))
    await db.commit()
    with pytest.raises(CurationBlockedError):
        await update_memory(memory_id, MemoryNodeUpdate(content="FORBIDDEN_CONTENT"), db, embedding_service)
    await db.rollback()
    rows = (await db.execute(select(MemoryNode))).scalars().all()
    assert len(rows) == 1 and rows[0].id == memory_id and rows[0].is_current
    assert rows[0].content == "Allowed content"


async def test_weight_only_update_does_not_reapply_content_rules(async_session, embedding_service):
    db = async_session
    memory_id = await seed(db, embedding_service, "FORBIDDEN_CONTENT")
    db.add(CuratorRule(
        id=uuid.uuid4(), tenant_id="tenant-a", name="protected-content", layer="organizational",
        owner_id=None, trigger="on_write", tier="regex", config={"pattern": "FORBIDDEN_CONTENT"},
        action="block", enabled=True, override=True, priority=0,
    ))
    await db.commit()
    changed = await update_memory(memory_id, MemoryNodeUpdate(weight=0.4), db, embedding_service)
    assert changed.weight == 0.4 and changed.content == "FORBIDDEN_CONTENT"


@pytest.mark.parametrize("bulk", [False, True])
async def test_delete_preserves_deleted_bridges_and_only_changes_live_rows(async_session, embedding_service, bulk):
    db = async_session
    root = await seed(db, embedding_service)
    bridge = await seed(db, embedding_service, parent=root, owner="bob")
    leaf = await seed(db, embedding_service, parent=bridge)
    old = datetime(2020, 1, 1, tzinfo=UTC)
    retired = await db.get(MemoryNode, bridge)
    retired.deleted_at, retired.is_current = old, False
    await db.commit()
    if bulk:
        plan = await prepare_memory_delete([root], db, "tenant-a", can_delete=lambda node: node.owner_id == "alice")
        assert set(plan.nodes) == {root, leaf}
        await stage_memory_delete(plan, db)
        await db.commit()
    else:
        result = await delete_memory(root, db, tenant_id="tenant-a")
        assert result["total_deleted"] == 2 and result["branches_deleted"] == 1
    stored = (await db.execute(select(MemoryNode.deleted_at).where(MemoryNode.id == bridge))).scalar_one()
    assert stored.replace(tzinfo=None) == old.replace(tzinfo=None)


async def test_delete_authorizes_every_live_row_before_any_update(async_session, embedding_service):
    root = await seed(async_session, embedding_service)
    child = await seed(async_session, embedding_service, parent=root, owner="bob")
    with pytest.raises(MemoryAccessDeniedError):
        await prepare_memory_delete([root], async_session, "tenant-a", can_delete=lambda node: node.owner_id == "alice")
    assert (await async_session.get(MemoryNode, root)).deleted_at is None
    assert (await async_session.get(MemoryNode, child)).deleted_at is None


@pytest.mark.parametrize("bulk", [False, True])
async def test_delete_rejects_cross_tenant_edges_before_changes(async_session, embedding_service, bulk):
    db = async_session
    root, target = await seed(db, embedding_service), await seed(db, embedding_service)
    db.add(MemoryRelationship(
        id=uuid.uuid4(), source_id=root, target_id=target,
        relationship_type="related_to", tenant_id="tenant-b", created_by="bob",
    ))
    await db.commit()
    with pytest.raises(RelationshipBoundaryError):
        if bulk:
            await prepare_memory_delete([root], db, "tenant-a")
        else:
            await delete_memory(root, db, tenant_id="tenant-a")
    assert (await db.get(MemoryNode, root)).deleted_at is None


async def test_staged_delete_rolls_back_with_its_transaction(async_session, embedding_service):
    memory_id = await seed(async_session, embedding_service)
    plan = await prepare_memory_delete([memory_id], async_session, "tenant-a")
    await stage_memory_delete(plan, async_session)
    await async_session.rollback()
    assert (await async_session.get(MemoryNode, memory_id)).deleted_at is None
