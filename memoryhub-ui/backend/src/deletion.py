"""Read-only delete capabilities for the complete version/branch closure."""

import uuid

from memoryhub_core.models.memory import MemoryNode
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.authorization import Access


async def delete_capabilities(
    db: AsyncSession, access: Access, nodes: list[MemoryNode],
) -> dict[uuid.UUID, bool]:
    """Batch the same closure as Core deletion without acquiring write locks.

    A revision's author may not own earlier versions. Advertising permission
    on the selected row alone would offer a delete that the mutation rejects.
    Mutations still reauthorize every live row under lock before changing it.
    """
    allowed = {node.id: False for node in nodes}
    candidates = {node.id for node in nodes if node.deleted_at is None and access.can_delete(node)}
    if not candidates:
        return allowed

    tenant = access.principal.tenant_id
    closure = select(
        MemoryNode.id.label("root_id"), MemoryNode.id.label("node_id"), MemoryNode.previous_version_id,
    ).where(MemoryNode.tenant_id == tenant, MemoryNode.id.in_(candidates)).cte(
        "delete_capability_closure", recursive=True,
    )
    # UNION (not UNION ALL) bounds traversal even if a version chain cycles.
    closure = closure.union(select(
        closure.c.root_id, MemoryNode.id, MemoryNode.previous_version_id,
    ).select_from(MemoryNode).join(closure, or_(
        MemoryNode.id == closure.c.previous_version_id,
        MemoryNode.previous_version_id == closure.c.node_id,
        MemoryNode.parent_id == closure.c.node_id,
    )).where(MemoryNode.tenant_id == tenant))
    rows = (await db.execute(select(closure.c.root_id, MemoryNode).select_from(closure).join(
        MemoryNode, MemoryNode.id == closure.c.node_id,
    ))).all()
    seen = {root_id for root_id, node in rows if node.id == root_id}
    allowed.update({root_id: True for root_id in seen})
    for root_id, node in rows:
        if node.deleted_at is None and not access.can_delete(node):
            allowed[root_id] = False
    return allowed
