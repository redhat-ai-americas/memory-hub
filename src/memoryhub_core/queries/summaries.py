"""Authorized summary and legacy graph queries over Core models."""

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from memoryhub_core.authorization.human import Access
from memoryhub_core.models.contradiction import ContradictionReport
from memoryhub_core.models.memory import MemoryNode


async def navigation_counts(db: AsyncSession, access: Access):
    tenant = access.principal.tenant_id
    memories = (
        await db.execute(
            select(func.count())
            .select_from(MemoryNode)
            .where(
                MemoryNode.tenant_id == tenant,
                MemoryNode.is_current.is_(True),
                MemoryNode.deleted_at.is_(None),
                access.clause(),
            )
        )
    ).scalar_one()
    review_queue = 0
    if access.principal.role == "admin" and access.human_project_admins and "project" in access.moderation_scopes:
        review_queue = (
            await db.execute(
                select(func.count())
                .select_from(ContradictionReport)
                .join(
                    MemoryNode,
                    ContradictionReport.memory_id == MemoryNode.id,
                )
                .where(
                    ContradictionReport.tenant_id == tenant,
                    ContradictionReport.resolved.is_(False),
                    MemoryNode.tenant_id == tenant,
                    MemoryNode.deleted_at.is_(None),
                    MemoryNode.scope == "project",
                    MemoryNode.scope_id.in_(access.human_project_admins),
                    ~ContradictionReport.reporter.in_(access.identities),
                    ~MemoryNode.owner_id.in_(access.identities),
                    or_(MemoryNode.actor_id.is_(None), ~MemoryNode.actor_id.in_(access.identities)),
                    or_(MemoryNode.driver_id.is_(None), ~MemoryNode.driver_id.in_(access.identities)),
                )
            )
        ).scalar_one()
    return memories, review_queue


async def current_memories(db: AsyncSession, access: Access, *, scope=None, owner_id=None):
    stmt = select(MemoryNode).where(
        MemoryNode.tenant_id == access.principal.tenant_id,
        MemoryNode.is_current.is_(True),
        MemoryNode.deleted_at.is_(None),
        access.clause(),
    )
    if scope:
        stmt = stmt.where(MemoryNode.scope == scope)
    if owner_id:
        stmt = stmt.where(MemoryNode.owner_id == owner_id)

    result = await db.execute(stmt)
    nodes = [n for n in result.scalars().all() if access.can_read(n)]

    return nodes


async def semantic_graph_matches(db: AsyncSession, access: Access, embedding):
    tenant_id = access.principal.tenant_id
    distance = MemoryNode.embedding.cosine_distance(embedding)
    stmt = (
        select(MemoryNode.id, (1 - distance).label("score"))
        .where(
            MemoryNode.tenant_id == tenant_id,
            MemoryNode.is_current.is_(True),
            MemoryNode.deleted_at.is_(None),
            access.content_clause(),
        )
        .order_by(distance)
        .limit(20)
    )
    result = await db.execute(stmt)
    rows = result.fetchall()
    return rows


async def text_graph_matches(db: AsyncSession, access: Access, q):
    tenant_id = access.principal.tenant_id
    # Text fallback
    pattern = f"%{q}%"
    stmt = (
        select(MemoryNode)
        .where(
            MemoryNode.tenant_id == tenant_id,
            MemoryNode.is_current.is_(True),
            MemoryNode.deleted_at.is_(None),
            access.content_clause(),
            (MemoryNode.content.ilike(pattern) | MemoryNode.stub.ilike(pattern)),
        )
        .limit(20)
    )
    result = await db.execute(stmt)
    nodes = [n for n in result.scalars().all() if access.can_read(n)]
    return nodes


async def memory_statistics(db: AsyncSession, access: Access):
    tenant_id = access.principal.tenant_id
    # Total current memories
    total_result = await db.execute(
        select(func.count())
        .select_from(MemoryNode)
        .where(
            MemoryNode.tenant_id == tenant_id,
            MemoryNode.is_current.is_(True),
            MemoryNode.deleted_at.is_(None),
            access.clause(),
        )
    )
    total = total_result.scalar_one()

    # Count by scope
    scope_result = await db.execute(
        select(MemoryNode.scope, func.count().label("cnt"))
        .where(
            MemoryNode.tenant_id == tenant_id,
            MemoryNode.is_current.is_(True),
            MemoryNode.deleted_at.is_(None),
            access.clause(),
        )
        .group_by(MemoryNode.scope)
    )
    scope_counts = scope_result.fetchall()

    # 10 most recently touched nodes
    recent_result = await db.execute(
        select(MemoryNode)
        .where(
            MemoryNode.tenant_id == tenant_id,
            MemoryNode.is_current.is_(True),
            MemoryNode.deleted_at.is_(None),
            access.clause(),
        )
        .order_by(MemoryNode.updated_at.desc())
        .limit(10)
    )
    recent_nodes = recent_result.scalars().all()
    return total, scope_counts, recent_nodes


async def individual_activity(db: AsyncSession, access: Access):
    if not access.sees_individual_activity:
        return {}
    tenant_id = access.principal.tenant_id
    # Get memory stats per owner from DB
    stats_query = (
        select(
            MemoryNode.owner_id,
            func.count().label("memory_count"),
            func.max(MemoryNode.updated_at).label("last_active"),
        )
        .where(
            MemoryNode.tenant_id == tenant_id,
            MemoryNode.is_current.is_(True),
            MemoryNode.deleted_at.is_(None),
            access.clause(),
        )
        .group_by(MemoryNode.owner_id)
    )
    if access.principal.role == "user":
        stats_query = stats_query.where(MemoryNode.owner_id.in_(access.identities))
    result = await db.execute(stats_query)
    return {row[0]: {"memory_count": row[1], "last_active": row[2]} for row in result.fetchall()}
