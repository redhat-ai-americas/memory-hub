"""Shared paginated human memory selection and aggregate queries."""

import uuid
from collections import Counter

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from memoryhub_core.authorization.human import Access
from memoryhub_core.models.contradiction import ContradictionReport
from memoryhub_core.models.memory import MemoryNode, MemoryRelationship
from memoryhub_core.queries.filters import (
    MemoryFilters,
    base_conditions,
    has_children,
    has_contradictions,
    memory_conditions,
)


async def browse_page(
    db: AsyncSession, access: Access, query: MemoryFilters, *, sort="updated", order="desc", page=1, per_page=20
):
    tenant = access.principal.tenant_id
    filters = memory_conditions(access, query)
    search_mode = "none" if not query.q else "metadata" if query.mode == "metadata" else "text"
    total = (await db.execute(select(func.count()).select_from(MemoryNode).where(*filters))).scalar_one()
    sort_col = {
        "updated": MemoryNode.updated_at,
        "created": MemoryNode.created_at,
        "weight": MemoryNode.weight,
        "relevance": MemoryNode.updated_at,
    }[sort]
    ordered = sort_col.asc() if order == "asc" else sort_col.desc()
    memories = (
        (
            await db.execute(
                select(MemoryNode)
                .where(*filters)
                .order_by(ordered, MemoryNode.id)
                .offset((page - 1) * per_page)
                .limit(per_page)
            )
        )
        .scalars()
        .all()
    )
    memories = [
        memory
        for memory in memories
        if memory.tenant_id == tenant
        and (access.can_read(memory) if access.principal.role == "admin" else access.can_see_content(memory))
    ]
    ids = [memory.id for memory in memories]
    branch_counts: dict[uuid.UUID, Counter] = {}
    report_counts: dict[uuid.UUID, int] = {}
    entities_by_memory: dict[uuid.UUID, list[dict]] = {}
    if ids:
        children = (
            await db.execute(
                select(MemoryNode.parent_id, MemoryNode.branch_type).where(
                    MemoryNode.parent_id.in_(ids),
                    MemoryNode.tenant_id == tenant,
                    MemoryNode.deleted_at.is_(None),
                    MemoryNode.is_current.is_(True),
                    access.clause(),
                )
            )
        ).all()
        for parent_id, branch in children:
            branch_counts.setdefault(parent_id, Counter())[branch or "other"] += 1
        reports = (
            await db.execute(
                select(ContradictionReport.memory_id, func.count())
                .where(
                    ContradictionReport.memory_id.in_(ids),
                    ContradictionReport.tenant_id == tenant,
                    ContradictionReport.resolved.is_(False),
                )
                .group_by(ContradictionReport.memory_id)
            )
        ).all()
        report_counts = dict(reports)
        # Entity names are content. The selected source memory is already
        # authorized, and a redacted Admin row gets no linked entity names.
        content_ids = [memory.id for memory in memories if access.can_see_content(memory)]
        if content_ids:
            entity_node = aliased(MemoryNode)
            entity_rows = (
                await db.execute(
                    select(
                        MemoryRelationship.source_id,
                        entity_node.id,
                        entity_node.content,
                        entity_node.branch_type,
                    )
                    .join(entity_node, entity_node.id == MemoryRelationship.target_id)
                    .where(
                        MemoryRelationship.source_id.in_(content_ids),
                        MemoryRelationship.tenant_id == tenant,
                        MemoryRelationship.relationship_type == "mentions",
                        MemoryRelationship.valid_until.is_(None),
                        entity_node.tenant_id == tenant,
                        entity_node.scope == "entity",
                        entity_node.status == "active",
                        entity_node.is_current.is_(True),
                        entity_node.deleted_at.is_(None),
                    )
                )
            ).all()
            for source_id, entity_id, name, kind in entity_rows:
                entities_by_memory.setdefault(source_id, []).append(
                    {
                        "id": str(entity_id),
                        "name": name,
                        "type": (kind or "").removeprefix("entity:"),
                    }
                )
    return total, memories, branch_counts, report_counts, entities_by_memory, search_mode


async def browse_facets(db: AsyncSession, access: Access):
    tenant = access.principal.tenant_id
    base = base_conditions(access)
    tabs = {}
    for name, condition in (
        ("current", (MemoryNode.deleted_at.is_(None), MemoryNode.is_current.is_(True), MemoryNode.status == "active")),
        ("all", (MemoryNode.deleted_at.is_(None),)),
        ("quarantined", (MemoryNode.deleted_at.is_(None), MemoryNode.status == "quarantined")),
        ("deleted", (MemoryNode.deleted_at.is_not(None),)),
    ):
        if access.principal.role == "user" and name in ("quarantined", "deleted"):
            tabs[name] = 0
        else:
            stmt = select(func.count()).select_from(MemoryNode).where(*base, *condition)
            tabs[name] = (await db.execute(stmt)).scalar_one()
    facets = {"writers": []}
    for name, column, extra in (
        ("scopes", MemoryNode.scope, ()),
        # Memories per person is individual activity: not an admin facet (#667).
        *((("writers", MemoryNode.owner_id, ()),) if access.sees_individual_activity else ()),
        ("projects", MemoryNode.scope_id, (MemoryNode.scope == "project",)),
    ):
        rows = (
            await db.execute(
                select(column, func.count())
                .select_from(MemoryNode)
                .where(
                    *base,
                    MemoryNode.deleted_at.is_(None),
                    *extra,
                )
                .group_by(column)
            )
        ).all()
        facets[name] = [{"value": value, "count": count} for value, count in rows if value is not None]
    facets["domains"] = []
    # These counts describe only authorized memories. Domain values are
    # content metadata and must exclude Admin's redacted personal rows.
    domain_rows = (
        select(func.unnest(MemoryNode.domains).label("value"))
        .where(
            *base,
            MemoryNode.deleted_at.is_(None),
            access.live_content_clause(),
        )
        .subquery()
    )
    domains = (
        await db.execute(
            select(domain_rows.c.value, func.count()).select_from(domain_rows).group_by(domain_rows.c.value)
        )
    ).all()
    facets["domains"] = [{"value": value, "count": count} for value, count in domains if value]
    contradicted = (
        await db.execute(
            select(func.count())
            .select_from(MemoryNode)
            .where(
                *base,
                MemoryNode.deleted_at.is_(None),
                has_contradictions(tenant),
            )
        )
    ).scalar_one()
    has_branches = (
        await db.execute(
            select(func.count())
            .select_from(MemoryNode)
            .where(
                *base,
                MemoryNode.deleted_at.is_(None),
                has_children(access),
            )
        )
    ).scalar_one()
    facets["flags"] = {"contradicted": contradicted, "has_branches": has_branches, "near_duplicate": None}
    return tabs, facets
