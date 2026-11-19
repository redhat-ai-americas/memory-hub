"""Human graph projections over the existing memory and relationship graph."""

from __future__ import annotations

import uuid
from collections import Counter
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from memoryhub_core.models.memory import MemoryNode, MemoryRelationship
from sqlalchemy import func, or_, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from src.authorization import AccessDep
from src.browse_filters import (
    BrowseQueryDep,
    OptionalEmbeddingDep,
    can_list,
    can_see_content,
    conditions,
    plan_search,
)
from src.database import get_db
from src.memory_context import _brief

router = APIRouter()
DbDep = Annotated[AsyncSession, Depends(get_db)]
MAX_GRAPH_NODES = 1500


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
    db: DbDep, access: AccessDep, query: BrowseQueryDep, embedding: OptionalEmbeddingDep,
    types: list[str] | None = Query(None),
    max_nodes: int = Query(300, ge=1, le=MAX_GRAPH_NODES),
    prefer: Literal["connected", "recent", "weight"] = "connected",
):
    """The browser's graph view: the same filters as the table, drawn as nodes and edges."""
    tenant = access.principal.tenant_id
    where = conditions(access, query, await plan_search(query, embedding))
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
    nodes = {node.id: node for node in selected if node.tenant_id == tenant and can_list(access, node)}
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
    db: DbDep, access: AccessDep, focus: uuid.UUID, query: BrowseQueryDep,
    embedding: OptionalEmbeddingDep,
    depth: int = Query(1, ge=1, le=3), max_nodes: int = Query(300, ge=1, le=MAX_GRAPH_NODES),
    types: list[str] | None = Query(None),
):
    tenant = access.principal.tenant_id
    where = conditions(access, query, await plan_search(query, embedding))
    center = (await db.execute(select(MemoryNode).where(*where, MemoryNode.id == focus))).scalar_one_or_none()
    if center is None or center.tenant_id != tenant or not can_list(access, center):
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
        visible = [node for node in visible if node.tenant_id == tenant and can_list(access, node)]
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
                  "content": center.content if can_see_content(access, center) else "",
                  "degree": degree[str(center.id)], "hidden_degree": 0},
        "nodes": [{**_brief(node, access), "depth": depths[node.id]} for node in nodes.values()],
        "edges": edges, "hidden_count": 0, "cut_count": cut_count,
        "max_nodes": max_nodes,
        "provenance": [_brief(nodes[uid], access) for uid, kind in related.items()
                       if kind in {"derived_from", "supersedes"} and uid in nodes],
        "conflicts": [_brief(nodes[uid], access) for uid, kind in related.items()
                      if kind == "conflicts_with" and uid in nodes],
    }
