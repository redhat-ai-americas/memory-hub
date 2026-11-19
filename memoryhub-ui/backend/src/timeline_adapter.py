"""Timeline view of the Memory browser: when memories were written or changed."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from memoryhub_core.models.memory import MemoryNode
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

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

router = APIRouter()
DbDep = Annotated[AsyncSession, Depends(get_db)]
MAX_TIMELINE_ITEMS = 2000


@router.get("/api/memories/timeline")
async def memory_timeline(
    db: DbDep, access: AccessDep, query: BrowseQueryDep, embedding: OptionalEmbeddingDep,
    days: int = Query(0, ge=0, le=3650, description="Window ending now; 0 = all time"),
    by: Literal["created", "updated"] = "created",
    max_items: int = Query(1500, ge=1, le=MAX_TIMELINE_ITEMS),
):
    """Every memory the browser filters keep, placed in time.

    Returns the newest ``max_items`` in the window; ``total`` counts all of
    them and ``first`` is the earliest one, so the client can draw the axis.
    """
    tenant = access.principal.tenant_id
    at = MemoryNode.created_at if by == "created" else MemoryNode.updated_at
    now = datetime.now(UTC)
    where = conditions(access, query, await plan_search(query, embedding))
    if days:
        where.append(at >= now - timedelta(days=days))
    total, first = (await db.execute(select(func.count(), func.min(at)).select_from(MemoryNode).where(*where))).one()
    rows = (await db.execute(
        select(MemoryNode).where(*where).order_by(at.desc(), MemoryNode.id).limit(max_items)
    )).scalars().all()
    items = []
    for node in rows:
        if node.tenant_id != tenant or not can_list(access, node):
            continue
        hidden = not can_see_content(access, node)
        items.append({
            "id": str(node.id), "stub": "Content hidden" if hidden else node.stub,
            "scope": node.scope, "scope_id": node.scope_id, "owner_id": node.owner_id,
            "weight": node.weight, "version": node.version,
            "domains": [] if hidden else (node.domains or []),
            "created_at": node.created_at, "updated_at": node.updated_at,
            "at": node.created_at if by == "created" else node.updated_at,
            "redacted": hidden,
        })
    return {"items": items, "total": total, "truncated": total > len(items), "by": by,
            "days": days, "first": first, "now": now,
            "metadata_only": access.principal.role == "admin"}
