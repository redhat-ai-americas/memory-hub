"""Human graph projections over the existing memory and relationship graph."""

from __future__ import annotations

import uuid
from collections import Counter
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from memoryhub_core.models.memory import MemoryNode, MemoryRelationship
from memoryhub_core.queries import graph as graph_queries
from memoryhub_core.queries.filters import MemoryFilters
from memoryhub_core.queries.memories import relationships_between
from memoryhub_core.services.exceptions import MemoryNotFoundError
from sqlalchemy.ext.asyncio import AsyncSession

from src.authorization import AccessDep
from src.database import get_db
from src.human_adapters import _human_can_see_content
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
    rels = await relationships_between(db, ids, tenant, types)
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
    query = MemoryFilters(tab=tab, q=q, mode=mode, scope=scope, actor=actor,
        project=project, domain=domain, min_weight=min_weight, max_weight=max_weight,
        created_from=created_from, created_to=created_to, branch_type=branch_type, flag=flag, entity=entity)
    total, nodes = await graph_queries.graph_page(db, access, query, max_nodes=max_nodes, prefer=prefer)
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
    query = MemoryFilters(tab=tab, q=q, mode=mode, scope=scope, actor=actor,
        project=project, domain=domain, min_weight=min_weight, max_weight=max_weight,
        created_from=created_from, created_to=created_to, branch_type=branch_type, flag=flag, entity=entity)
    try:
        center, nodes, depths, cut_count = await graph_queries.neighbourhood(
            db, access, query, focus=focus, depth=depth, max_nodes=max_nodes, types=types,
        )
    except MemoryNotFoundError:
        raise HTTPException(status_code=404, detail="Memory not found") from None
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
