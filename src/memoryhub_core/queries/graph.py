"""Authorized graph selection and traversal over the shared memory filters."""

from sqlalchemy import func, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from memoryhub_core.authorization.human import Access
from memoryhub_core.exceptions import MemoryNotFoundError
from memoryhub_core.models.memory import MemoryNode, MemoryRelationship
from memoryhub_core.queries.filters import MemoryFilters, QueryValidationError, memory_conditions
from memoryhub_core.queries.memories import relationships_touching


async def graph_page(db: AsyncSession, access: Access, query: MemoryFilters, *, max_nodes=300, prefer="connected"):
    tenant = access.principal.tenant_id
    where = memory_conditions(access, query)
    total = (await db.execute(select(func.count()).select_from(MemoryNode).where(*where))).scalar_one()
    stmt = select(MemoryNode).where(*where)
    if prefer == "connected":
        visible = select(MemoryNode.id).where(*where).subquery("graph_visible")
        a, b = visible.alias("a"), visible.alias("b")
        child = aliased(MemoryNode)
        c, p = visible.alias("c"), visible.alias("p")
        rel = MemoryRelationship
        connected_ids = union_all(
            select(rel.source_id.label("id"))
            .join(a, rel.source_id == a.c.id)
            .join(b, rel.target_id == b.c.id)
            .where(rel.tenant_id == tenant, rel.valid_until.is_(None)),
            select(rel.target_id.label("id"))
            .join(a, rel.source_id == a.c.id)
            .join(b, rel.target_id == b.c.id)
            .where(rel.tenant_id == tenant, rel.valid_until.is_(None)),
            select(child.id.label("id")).join(c, child.id == c.c.id).join(p, child.parent_id == p.c.id),
            select(child.parent_id.label("id")).join(c, child.id == c.c.id).join(p, child.parent_id == p.c.id),
        ).subquery()
        degrees = select(connected_ids.c.id, func.count().label("degree")).group_by(connected_ids.c.id).subquery()
        stmt = stmt.outerjoin(degrees, degrees.c.id == MemoryNode.id).order_by(
            func.coalesce(degrees.c.degree, 0).desc(), MemoryNode.updated_at.desc(), MemoryNode.id
        )
    elif prefer == "weight":
        stmt = stmt.order_by(MemoryNode.weight.desc(), MemoryNode.updated_at.desc(), MemoryNode.id)
    else:
        stmt = stmt.order_by(MemoryNode.updated_at.desc(), MemoryNode.id)
    selected = (await db.execute(stmt.limit(max_nodes))).scalars().all()
    nodes = {node.id: node for node in selected if node.tenant_id == tenant and access.can_read(node)}
    return total, nodes


async def neighbourhood(
    db: AsyncSession, access: Access, query: MemoryFilters, *, focus, depth=1, max_nodes=300, types=None
):
    if not 1 <= depth <= 3 or not 1 <= max_nodes <= 1500:
        raise QueryValidationError("Invalid graph traversal limit")
    tenant = access.principal.tenant_id
    where = memory_conditions(access, query)
    center = (await db.execute(select(MemoryNode).where(*where, MemoryNode.id == focus))).scalar_one_or_none()
    if center is None or center.tenant_id != tenant or not access.can_read(center):
        raise MemoryNotFoundError(focus)
    nodes = {center.id: center}
    depths = {center.id: 0}
    frontier = {center.id}
    cut_count = 0
    for step in range(1, depth + 1):
        rels = await relationships_touching(db, frontier, tenant, types=types)
        candidates = {rel.target_id if rel.source_id in frontier else rel.source_id for rel in rels}
        if types is None or "parent_child" in types:
            children = (
                (
                    await db.execute(
                        select(MemoryNode.id).where(
                            MemoryNode.parent_id.in_(frontier),
                            MemoryNode.tenant_id == tenant,
                        )
                    )
                )
                .scalars()
                .all()
            )
            parents = (
                (
                    await db.execute(
                        select(MemoryNode.parent_id).where(
                            MemoryNode.id.in_(frontier),
                            MemoryNode.tenant_id == tenant,
                            MemoryNode.parent_id.is_not(None),
                        )
                    )
                )
                .scalars()
                .all()
            )
            candidates.update(children)
            candidates.update(parents)
        candidates -= nodes.keys()
        if not candidates:
            break
        visible = (
            (
                await db.execute(
                    select(MemoryNode)
                    .where(*where, MemoryNode.id.in_(candidates))
                    .order_by(MemoryNode.updated_at.desc(), MemoryNode.id)
                )
            )
            .scalars()
            .all()
        )
        visible = [node for node in visible if node.tenant_id == tenant and access.can_read(node)]
        available = max_nodes - len(nodes)
        cut_count += max(len(visible) - max(available, 0), 0)
        chosen = visible[: max(available, 0)]
        frontier = {node.id for node in chosen}
        for node in chosen:
            nodes[node.id] = node
            depths[node.id] = step
        if not frontier:
            break
    return center, nodes, depths, cut_count
