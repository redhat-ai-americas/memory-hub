"""Human graph projections over the existing memory and relationship graph."""

from __future__ import annotations

import uuid
from collections import Counter
from datetime import date, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from memoryhub_core.models.contradiction import ContradictionReport
from memoryhub_core.models.memory import MemoryNode, MemoryRelationship
from sqlalchemy import String, and_, cast, func, or_, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from src.authorization import Access, AccessDep
from src.database import get_db
from src.human_adapters import _human_can_see_content
from src.memory_context import _brief

router = APIRouter()
DbDep = Annotated[AsyncSession, Depends(get_db)]
MAX_GRAPH_NODES = 1500


def _conditions(
    access: Access,
    *,
    tab: str, q: str | None, mode: str, scope: list[str] | None,
    actor: list[str] | None, project: str | None, domain: list[str] | None,
    min_weight: float | None, max_weight: float | None,
    created_from: date | None, created_to: date | None,
    branch_type: str | None, flag: list[str] | None, entity: uuid.UUID | None,
) -> list:
    """Apply browser filters after human visibility; filters only narrow scope."""
    tenant = access.principal.tenant_id
    if min_weight is not None and max_weight is not None and min_weight > max_weight:
        raise HTTPException(status_code=422, detail="Invalid weight range")
    if flag and any(value not in {"contradicted", "has_branches"} for value in flag):
        raise HTTPException(status_code=422, detail="Unsupported graph flag")
    if access.principal.role == "user" and tab in {"quarantined", "deleted"}:
        raise HTTPException(status_code=403, detail="Memory state forbidden")
    access.forbid_person_filter(actor)
    where = [MemoryNode.tenant_id == tenant, access.clause()]
    if tab == "current":
        where += [MemoryNode.deleted_at.is_(None), MemoryNode.status == "active",
                  MemoryNode.is_current.is_(True)]
    elif tab == "all":
        where.append(MemoryNode.deleted_at.is_(None))
    elif tab == "quarantined":
        where += [MemoryNode.deleted_at.is_(None), MemoryNode.status == "quarantined"]
    elif tab == "deleted":
        where.append(MemoryNode.deleted_at.is_not(None))
    else:
        raise HTTPException(status_code=422, detail="Invalid graph tab")
    if scope:
        where.append(MemoryNode.scope.in_(scope))
    if actor:
        where.append(MemoryNode.actor_id.in_(actor))
    if project:
        where += [MemoryNode.scope == "project", MemoryNode.scope_id == project]
    if domain:
        # A domain filter must never test hidden content metadata.
        where += [access.content_clause(), MemoryNode.domains.overlap(domain)]
    if min_weight is not None:
        where.append(MemoryNode.weight >= min_weight)
    if max_weight is not None:
        where.append(MemoryNode.weight <= max_weight)
    if created_from:
        where.append(MemoryNode.created_at >= created_from)
    if created_to:
        where.append(MemoryNode.created_at < created_to + timedelta(days=1))
    if branch_type:
        child = aliased(MemoryNode)
        where.append(select(child.id).where(
            child.parent_id == MemoryNode.id, child.tenant_id == tenant,
            child.deleted_at.is_(None), child.branch_type == branch_type,
            child.is_current.is_(True),
            access.clause(child),
        ).exists())
    if flag:
        if "contradicted" in flag:
            where.append(select(ContradictionReport.id).where(
                ContradictionReport.memory_id == MemoryNode.id,
                ContradictionReport.tenant_id == tenant,
                ContradictionReport.resolved.is_(False),
                access.content_clause(),
            ).exists())
        if "has_branches" in flag:
            child = aliased(MemoryNode)
            where.append(select(child.id).where(
                child.parent_id == MemoryNode.id, child.tenant_id == tenant,
                child.deleted_at.is_(None), child.is_current.is_(True), access.clause(child),
            ).exists())
    if entity:
        where.append(select(MemoryRelationship.id).where(
            MemoryRelationship.source_id == MemoryNode.id,
            MemoryRelationship.target_id == entity,
            MemoryRelationship.tenant_id == tenant,
            MemoryRelationship.relationship_type == "mentions",
            MemoryRelationship.valid_until.is_(None),
            access.content_clause(),
        ).exists())
    if q:
        pattern = f"%{q.strip()}%"
        metadata = (or_(cast(MemoryNode.id, String).ilike(pattern), MemoryNode.owner_id.ilike(pattern))
                    if access.sees_individual_activity else cast(MemoryNode.id, String).ilike(pattern))
        if mode == "metadata":
            where.append(metadata)
        elif mode in {"semantic", "text"}:
            where.append(or_(metadata, and_(access.content_clause(),
                or_(MemoryNode.content.ilike(pattern), MemoryNode.stub.ilike(pattern)))))
        else:
            raise HTTPException(status_code=422, detail="Invalid graph search mode")
    return where


def _edge(rel: MemoryRelationship) -> dict:
    return {"id": str(rel.id), "source": str(rel.source_id),
            "target": str(rel.target_id), "type": rel.relationship_type}


async def _edges(db: AsyncSession, tenant: str, nodes: dict[uuid.UUID, MemoryNode],
                 types: list[str] | None = None) -> list[dict]:
    """Only expose edges after both endpoints have passed node authorization."""
    ids = set(nodes)
    if not ids:
        return []
    edges = []
    if types is None or "parent_child" in types:
        edges += [{"id": f"pc-{node.parent_id}-{node.id}",
                   "source": str(node.parent_id), "target": str(node.id), "type": "parent_child"}
                  for node in nodes.values() if node.parent_id in ids]
    stmt = select(MemoryRelationship).where(
        MemoryRelationship.tenant_id == tenant,
        MemoryRelationship.valid_until.is_(None),
        MemoryRelationship.source_id.in_(ids), MemoryRelationship.target_id.in_(ids),
    )
    if types is not None:
        stmt = stmt.where(MemoryRelationship.relationship_type.in_(types))
    rels = (await db.execute(stmt)).scalars().all()
    edges += [_edge(rel) for rel in rels if rel.source_id in ids and rel.target_id in ids]
    return edges


def _degree(edges: list[dict]) -> Counter:
    degree: Counter = Counter()
    for edge in edges:
        degree[edge["source"]] += 1
        degree[edge["target"]] += 1
    return degree


@router.get("/api/graph/all")
async def graph_all(
    db: DbDep, access: AccessDep,
    tab: Literal["current", "all", "quarantined", "deleted"] = "current",
    q: str | None = None, mode: Literal["semantic", "text", "metadata"] = "semantic",
    scope: list[str] | None = Query(None), actor: list[str] | None = Query(None),
    project: str | None = None, domain: list[str] | None = Query(None),
    min_weight: float | None = Query(None, ge=0, le=1),
    max_weight: float | None = Query(None, ge=0, le=1),
    created_from: date | None = None, created_to: date | None = None,
    branch_type: str | None = None, flag: list[str] | None = Query(None),
    entity: uuid.UUID | None = None, types: list[str] | None = Query(None),
    max_nodes: int = Query(300, ge=1, le=MAX_GRAPH_NODES),
    prefer: Literal["connected", "recent", "weight"] = "connected",
):
    tenant = access.principal.tenant_id
    where = _conditions(access, tab=tab, q=q, mode=mode, scope=scope, actor=actor,
                        project=project, domain=domain, min_weight=min_weight,
                        max_weight=max_weight, created_from=created_from, created_to=created_to,
                        branch_type=branch_type, flag=flag, entity=entity)
    total = (await db.execute(select(func.count()).select_from(MemoryNode).where(*where))).scalar_one()
    stmt = select(MemoryNode).where(*where)
    if prefer == "connected":
        visible = select(MemoryNode.id).where(*where).subquery("graph_visible")
        a, b = visible.alias("a"), visible.alias("b")
        child = aliased(MemoryNode)
        c, p = visible.alias("c"), visible.alias("p")
        rel = MemoryRelationship
        connected_ids = union_all(
            select(rel.source_id.label("id")).join(a, rel.source_id == a.c.id)
                .join(b, rel.target_id == b.c.id).where(
                    rel.tenant_id == tenant, rel.valid_until.is_(None)),
            select(rel.target_id.label("id")).join(a, rel.source_id == a.c.id)
                .join(b, rel.target_id == b.c.id).where(
                    rel.tenant_id == tenant, rel.valid_until.is_(None)),
            select(child.id.label("id")).join(c, child.id == c.c.id)
                .join(p, child.parent_id == p.c.id),
            select(child.parent_id.label("id")).join(c, child.id == c.c.id)
                .join(p, child.parent_id == p.c.id),
        ).subquery()
        degrees = select(connected_ids.c.id, func.count().label("degree")).group_by(
            connected_ids.c.id).subquery()
        stmt = stmt.outerjoin(degrees, degrees.c.id == MemoryNode.id).order_by(
            func.coalesce(degrees.c.degree, 0).desc(), MemoryNode.updated_at.desc(), MemoryNode.id)
    elif prefer == "weight":
        stmt = stmt.order_by(MemoryNode.weight.desc(), MemoryNode.updated_at.desc(), MemoryNode.id)
    else:
        stmt = stmt.order_by(MemoryNode.updated_at.desc(), MemoryNode.id)
    selected = (await db.execute(stmt.limit(max_nodes))).scalars().all()
    nodes = {node.id: node for node in selected if node.tenant_id == tenant and access.can_read(node)}
    edges = await _edges(db, tenant, nodes, types)
    degree = _degree(edges)
    result_nodes = [{**_brief(node, access), "depth": 0, "degree": degree[str(node.id)]}
                    for node in nodes.values()]
    return {"nodes": result_nodes, "edges": edges, "total": total,
            "truncated": total > len(nodes), "left_out": max(total - len(nodes), 0),
            "max_nodes": max_nodes, "limit_ceiling": MAX_GRAPH_NODES, "prefer": prefer,
            "orphan_count": sum(1 for node in nodes.values() if degree[str(node.id)] == 0),
            "hidden_links": 0, "metadata_only": access.principal.role == "admin"}


@router.get("/api/graph/neighbourhood")
async def graph_neighbourhood(
    db: DbDep, access: AccessDep, focus: uuid.UUID,
    depth: int = Query(1, ge=1, le=3), max_nodes: int = Query(300, ge=1, le=MAX_GRAPH_NODES),
    types: list[str] | None = Query(None),
    tab: Literal["current", "all", "quarantined", "deleted"] = "current",
    q: str | None = None, mode: Literal["semantic", "text", "metadata"] = "semantic",
    scope: list[str] | None = Query(None), actor: list[str] | None = Query(None),
    project: str | None = None, domain: list[str] | None = Query(None),
    min_weight: float | None = Query(None, ge=0, le=1),
    max_weight: float | None = Query(None, ge=0, le=1),
    created_from: date | None = None, created_to: date | None = None,
    branch_type: str | None = None, flag: list[str] | None = Query(None),
    entity: uuid.UUID | None = None,
):
    tenant = access.principal.tenant_id
    where = _conditions(access, tab=tab, q=q, mode=mode, scope=scope, actor=actor,
                        project=project, domain=domain, min_weight=min_weight,
                        max_weight=max_weight, created_from=created_from, created_to=created_to,
                        branch_type=branch_type, flag=flag, entity=entity)
    center = (await db.execute(select(MemoryNode).where(*where, MemoryNode.id == focus))).scalar_one_or_none()
    if center is None or center.tenant_id != tenant or not access.can_read(center):
        raise HTTPException(status_code=404, detail="Memory not found")
    nodes = {center.id: center}
    depths = {center.id: 0}
    frontier = {center.id}
    cut_count = 0
    for step in range(1, depth + 1):
        rels = (await db.execute(select(MemoryRelationship).where(
            MemoryRelationship.tenant_id == tenant, MemoryRelationship.valid_until.is_(None),
            or_(MemoryRelationship.source_id.in_(frontier),
                MemoryRelationship.target_id.in_(frontier)),
            *([MemoryRelationship.relationship_type.in_(types)] if types is not None else []),
        ))).scalars().all()
        candidates = {rel.target_id if rel.source_id in frontier else rel.source_id for rel in rels}
        if types is None or "parent_child" in types:
            children = (await db.execute(select(MemoryNode.id).where(
                MemoryNode.parent_id.in_(frontier), MemoryNode.tenant_id == tenant,
            ))).scalars().all()
            parents = (await db.execute(select(MemoryNode.parent_id).where(
                MemoryNode.id.in_(frontier), MemoryNode.tenant_id == tenant,
                MemoryNode.parent_id.is_not(None),
            ))).scalars().all()
            candidates.update(children)
            candidates.update(parents)
        candidates -= nodes.keys()
        if not candidates:
            break
        visible = (await db.execute(select(MemoryNode).where(*where, MemoryNode.id.in_(candidates))
                    .order_by(MemoryNode.updated_at.desc(), MemoryNode.id))).scalars().all()
        visible = [node for node in visible if node.tenant_id == tenant and access.can_read(node)]
        available = max_nodes - len(nodes)
        cut_count += max(len(visible) - max(available, 0), 0)
        chosen = visible[:max(available, 0)]
        frontier = {node.id for node in chosen}
        for node in chosen:
            nodes[node.id] = node
            depths[node.id] = step
        if not frontier:
            break
    edges = await _edges(db, tenant, nodes, types)
    degree = _degree(edges)
    related = {uuid.UUID(edge["target"]): edge["type"] for edge in edges
               if edge["source"] == str(center.id)}
    related.update({uuid.UUID(edge["source"]): edge["type"] for edge in edges
                    if edge["target"] == str(center.id)})
    return {
        "focus": {**_brief(center, access),
                  "content": center.content if _human_can_see_content(access, center) else "",
                  "degree": degree[str(center.id)], "hidden_degree": 0},
        "nodes": [{**_brief(node, access), "depth": depths[node.id]} for node in nodes.values()],
        "edges": edges, "hidden_count": 0, "cut_count": cut_count,
        "max_nodes": max_nodes,
        "provenance": [_brief(nodes[uid], access) for uid, kind in related.items()
                       if kind in {"derived_from", "supersedes"} and uid in nodes],
        "conflicts": [_brief(nodes[uid], access) for uid, kind in related.items()
                      if kind == "conflicts_with" and uid in nodes],
    }
