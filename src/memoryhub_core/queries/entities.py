"""Entity queries and source authorization shared by preview and mutation."""

import uuid

from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from memoryhub_core.authorization.human import Access
from memoryhub_core.models.memory import MemoryNode, MemoryRelationship
from memoryhub_core.queries.projects import writable_by_human
from memoryhub_core.services.exceptions import MemoryAccessDeniedError


class EntityBoundaryError(ValueError):
    """An entity has an invalid or cross-tenant source relationship."""


def mention_statement(entity_id, tenant=None):
    stmt = select(MemoryRelationship).where(
        MemoryRelationship.target_id == entity_id,
        MemoryRelationship.relationship_type == "mentions",
        MemoryRelationship.valid_until.is_(None),
    )
    return stmt.where(MemoryRelationship.tenant_id == tenant) if tenant is not None else stmt


async def entity_row(db: AsyncSession, entity_id, tenant, *, lock=False):
    stmt = select(MemoryNode).where(
        MemoryNode.id == entity_id,
        MemoryNode.scope == "entity",
        MemoryNode.tenant_id == tenant,
        MemoryNode.deleted_at.is_(None),
        MemoryNode.is_current.is_(True),
        MemoryNode.status == "active",
    )
    if lock:
        stmt = stmt.with_for_update()
    return (await db.execute(stmt)).scalar_one_or_none()


async def mutation_sources(db: AsyncSession, access: Access, entity, *, lock=False):
    """One source set and row policy for both read-only capabilities and edits.

    The edit additionally rechecks live project membership under lock.
    Cross-tenant/corrupt edges are rejected, rather than silently omitted.
    """
    if not access.can_edit_entity(entity):
        raise MemoryAccessDeniedError("Entity not found")
    stmt = mention_statement(entity.id)
    if lock:
        stmt = stmt.with_for_update()
    rels = (await db.execute(stmt)).scalars().all()
    source_ids = {rel.source_id for rel in rels}
    if any(rel.tenant_id != access.principal.tenant_id for rel in rels):
        raise EntityBoundaryError("Entity relationship boundary invalid")
    sources = (
        (await db.execute(select(MemoryNode).where(MemoryNode.id.in_(source_ids)))).scalars().all()
        if source_ids
        else []
    )
    if len({source.id for source in sources}) != len(source_ids):
        raise EntityBoundaryError("Entity relationship boundary invalid")
    for source in sources:
        if not access.can_see_content(source) or not access.can_write(source):
            raise MemoryAccessDeniedError("Entity not found")
        if lock and not await writable_by_human(db, access, source):
            raise MemoryAccessDeniedError("Entity not found")
    return sources


async def readable_sources(db: AsyncSession, access: Access, entity_id):
    if access.principal.role != "user":
        raise MemoryAccessDeniedError("Entity access forbidden")
    rels = (await db.execute(mention_statement(entity_id, access.principal.tenant_id))).scalars().all()
    source_ids = {rel.source_id for rel in rels}
    if not source_ids:
        return []
    sources = (
        (
            await db.execute(
                select(MemoryNode).where(
                    MemoryNode.id.in_(source_ids),
                    access.live_content_clause(),
                )
            )
        )
        .scalars()
        .all()
    )
    visible = [
        source
        for source in sources
        if source.tenant_id == access.principal.tenant_id
        and source.deleted_at is None
        and source.is_current
        and access.can_see_content(source)
        and all(rel.tenant_id == access.principal.tenant_id for rel in rels if rel.source_id == source.id)
    ]
    return visible


async def entity_page(
    db: AsyncSession, access: Access, *, q=None, entity_type="all", project=None, page=1, per_page=20
):
    if access.principal.role != "user":
        raise MemoryAccessDeniedError("Entity access forbidden")
    source = aliased(MemoryNode)
    mention = MemoryRelationship
    visibility = (
        select(
            mention.target_id.label("entity_id"),
            func.count(func.distinct(source.id)).label("memory_count"),
            func.max(source.updated_at).label("last_seen"),
        )
        .join(source, source.id == mention.source_id)
        .where(
            mention.tenant_id == access.principal.tenant_id,
            mention.relationship_type == "mentions",
            mention.valid_until.is_(None),
            source.deleted_at.is_(None),
            source.is_current.is_(True),
            access.live_content_clause(source),
        )
    )
    if project:
        visibility = visibility.where(source.scope == "project", source.scope_id == project)
    visible = visibility.group_by(mention.target_id).subquery()
    conditions = [
        MemoryNode.scope == "entity",
        MemoryNode.tenant_id == access.principal.tenant_id,
        MemoryNode.deleted_at.is_(None),
        MemoryNode.is_current.is_(True),
        MemoryNode.status == "active",
    ]
    if q:
        pattern = f"%{q.strip()}%"
        conditions.append(or_(MemoryNode.content.ilike(pattern), cast(MemoryNode.metadata_, String).ilike(pattern)))
    visible_or_owned = (
        visible.c.entity_id.is_not(None)
        if project
        else or_(visible.c.entity_id.is_not(None), MemoryNode.owner_id == access.principal.username)
    )
    base = (
        select(MemoryNode.id)
        .outerjoin(visible, visible.c.entity_id == MemoryNode.id)
        .where(
            *conditions,
            visible_or_owned,
        )
    )
    counts_rows = (
        await db.execute(
            select(MemoryNode.branch_type, func.count())
            .outerjoin(
                visible,
                visible.c.entity_id == MemoryNode.id,
            )
            .where(*conditions, visible_or_owned)
            .group_by(MemoryNode.branch_type)
        )
    ).all()
    counts = {kind: 0 for kind in ("person", "organization", "location", "object", "event")}
    for branch_type, count in counts_rows:
        kind = (branch_type or "").removeprefix("entity:")
        if kind in counts:
            counts[kind] = count
    counts["all"] = sum(counts.values())
    if entity_type != "all":
        base = base.where(MemoryNode.branch_type == f"entity:{entity_type}")
    total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
    rows = (
        await db.execute(
            select(MemoryNode, visible.c.memory_count, visible.c.last_seen)
            .outerjoin(
                visible,
                visible.c.entity_id == MemoryNode.id,
            )
            .where(
                *conditions,
                visible_or_owned,
                *([MemoryNode.branch_type == f"entity:{entity_type}"] if entity_type != "all" else []),
            )
            .order_by(func.coalesce(visible.c.memory_count, 0).desc(), MemoryNode.content)
            .offset((page - 1) * per_page)
            .limit(per_page)
        )
    ).all()
    entity_ids = [entity.id for entity, _count, _last in rows]
    projects_by_entity: dict[uuid.UUID, set[str]] = {entity_id: set() for entity_id in entity_ids}
    if entity_ids:
        linked_source = aliased(MemoryNode)
        project_rows = (
            await db.execute(
                select(mention.target_id, linked_source.scope_id)
                .join(
                    linked_source,
                    linked_source.id == mention.source_id,
                )
                .where(
                    mention.target_id.in_(entity_ids),
                    mention.relationship_type == "mentions",
                    mention.valid_until.is_(None),
                    mention.tenant_id == access.principal.tenant_id,
                    linked_source.scope == "project",
                    linked_source.deleted_at.is_(None),
                    linked_source.is_current.is_(True),
                    access.live_content_clause(linked_source),
                )
            )
        ).all()
        for entity_id, project_name in project_rows:
            if project_name:
                projects_by_entity[entity_id].add(project_name)
    return rows, total, counts, projects_by_entity


async def co_mentions(db: AsyncSession, access: Access, entity, sources):
    other = aliased(MemoryNode)
    edge = aliased(MemoryRelationship)
    count = func.count(func.distinct(edge.source_id)).label("mentions_count")
    rows = (
        await db.execute(
            select(other, count)
            .join(edge, edge.target_id == other.id)
            .where(
                edge.source_id.in_([source.id for source in sources]),
                edge.target_id != entity.id,
                edge.relationship_type == "mentions",
                edge.tenant_id == access.principal.tenant_id,
                edge.valid_until.is_(None),
                other.tenant_id == access.principal.tenant_id,
                other.scope == "entity",
                other.deleted_at.is_(None),
                other.status == "active",
            )
            .group_by(other.id)
            .order_by(count.desc())
            .limit(20)
        )
    ).all()
    return rows
