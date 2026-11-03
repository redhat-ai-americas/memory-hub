"""A new version deep-copies its branches; the copies must stay the same branch."""

import uuid

from sqlalchemy import select

from memoryhub_core.models.memory import MemoryNode
from memoryhub_core.models.schemas import MemoryNodeUpdate
from memoryhub_core.services.memory import update_memory


async def test_copied_branch_keeps_its_project_and_author(async_session, embedding_service):
    common = {"tenant_id": "default", "storage_type": "inline", "is_current": True}
    root = MemoryNode(
        id=uuid.uuid4(), content="Root", stub="Root", scope="project", scope_id="team-x",
        owner_id="team-x", actor_id="alice", driver_id="alice", weight=0.7, version=1, **common,
    )
    root.logical_id = root.id
    async_session.add(root)
    await async_session.flush()
    child = MemoryNode(
        id=uuid.uuid4(), content="Why", stub="Why", scope="project", scope_id="team-x",
        owner_id="team-x", actor_id="bob", driver_id="bob", weight=0.5, version=1,
        parent_id=root.id, branch_type="rationale", **common,
    )
    child.logical_id = child.id
    async_session.add(child)
    await async_session.commit()

    new_root = await update_memory(
        root.id, MemoryNodeUpdate(content="Root, revised"), async_session,
        embedding_service, actor_id="alice", driver_id="alice",
    )
    await async_session.commit()

    copied = (
        await async_session.execute(select(MemoryNode).where(MemoryNode.parent_id == new_root.id))
    ).scalar_one()
    # Without scope_id the branch leaves the project: nobody can read it, and the
    # project's memory count and quota stop seeing it.
    assert copied.scope_id == "team-x"
    # Authorship decides who may edit or delete a branch, so the copy keeps it.
    assert copied.actor_id == "bob"
    assert copied.driver_id == "bob"
    assert copied.branch_type == "rationale"
