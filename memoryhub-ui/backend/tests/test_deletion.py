"""Delete capability snapshots must match full-set mutation authorization."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from src.authorization import Access, Principal
from src.deletion import delete_capabilities


def node(owner="alice", actor=None):
    return SimpleNamespace(id=uuid.uuid4(), tenant_id="tenant-a", scope="project", scope_id="p",
                           owner_id=owner, actor_id=actor or owner, status="active", deleted_at=None)


async def test_batch_delete_capabilities_do_not_share_grants_between_roots():
    viewer = Access(Principal("alice", "user", "tenant-a"), human_projects={"p"})
    revised = node(owner="bob", actor="alice")
    historical = node(owner="bob")
    own = node()
    denied = node(owner="carol")
    result = MagicMock()
    result.all.return_value = [(revised.id, revised), (revised.id, historical), (own.id, own)]
    db = AsyncMock()
    db.execute.return_value = result
    allowed = await delete_capabilities(db, viewer, [revised, own, denied])
    assert allowed == {revised.id: False, own.id: True, denied.id: False}
    db.execute.assert_awaited_once()
    assert "FOR UPDATE" not in str(db.execute.await_args.args[0])
    db.commit.assert_not_awaited()


async def test_deleted_or_unauthorized_roots_need_no_closure_query():
    viewer = Access(Principal("alice", "user", "tenant-a"), human_projects={"p"})
    deleted, denied = node(), node(owner="bob")
    deleted.deleted_at = "deleted"
    db = AsyncMock()
    assert await delete_capabilities(db, viewer, [deleted, denied]) == {deleted.id: False, denied.id: False}
    db.execute.assert_not_awaited()
