"""Core human entry points enforce entity policy independently of HTTP guards."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from memoryhub_core.authorization.human import Access, Principal
from memoryhub_core.queries.entities import entity_page, mutation_sources, readable_sources
from memoryhub_core.services.exceptions import MemoryAccessDeniedError


def entity(**values):
    return SimpleNamespace(id=uuid.uuid4(), tenant_id="tenant-a", scope="entity", status="active",
                           deleted_at=None, is_current=True, owner_id="alice", **values)


@pytest.mark.parametrize("operation", ["list", "sources", "mutation"])
async def test_admin_cannot_bypass_the_entity_boundary_by_calling_core(operation):
    access = Access(Principal("alice", "admin", "tenant-a"))
    db = AsyncMock()
    node = entity()
    with pytest.raises(MemoryAccessDeniedError):
        if operation == "list":
            await entity_page(db, access)
        elif operation == "sources":
            await readable_sources(db, access, node.id)
        else:
            await mutation_sources(db, access, node)
    db.execute.assert_not_awaited()


async def test_a_foreign_entity_cannot_pass_the_core_mutation_preflight():
    access = Access(Principal("alice", "user", "tenant-a"))
    db = AsyncMock()
    node = entity()
    node.tenant_id = "tenant-b"
    with pytest.raises(MemoryAccessDeniedError):
        await mutation_sources(db, access, node, lock=True)
    db.execute.assert_not_awaited()


async def test_missing_tenant_does_not_turn_a_required_core_read_into_an_unscoped_lookup(async_session):
    from memoryhub_core.models.memory import MemoryNode
    from memoryhub_core.queries.memories import get_memory_row
    from memoryhub_core.services.exceptions import MemoryNotFoundError
    from memoryhub_core.services.memory import read_memory

    node_id = uuid.uuid4()
    async_session.add(MemoryNode(id=node_id, logical_id=node_id, content="private", stub="private",
                                 scope="user", owner_id="alice", tenant_id="tenant-a", weight=0.8))
    await async_session.commit()
    assert await get_memory_row(async_session, node_id, None, live=True) is None
    with pytest.raises(MemoryNotFoundError):
        await read_memory(node_id, async_session, tenant_id=None)
