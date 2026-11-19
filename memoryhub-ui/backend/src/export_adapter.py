"""Role-specific exports of the existing human browse projection."""

from __future__ import annotations

import csv
import io
import json
import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from memoryhub_core.models.memory import MemoryNode
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.authorization import AccessDep
from src.browse_filters import BrowseQueryDep, OptionalEmbeddingDep, plan_search
from src.database import get_db
from src.human_adapters import Sort, _human_can_see_content, browse_page

router = APIRouter()
DbDep = Annotated[AsyncSession, Depends(get_db)]
EXPORT_PAGE_SIZE = 100


def _csv_safe(value: object) -> object:
    """Avoid spreadsheet formula execution in user-controlled metadata."""
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


@router.get("/api/memories/export")
async def export_memories(
    db: DbDep, access: AccessDep, query: BrowseQueryDep, embedding: OptionalEmbeddingDep,
    sort: Sort = "updated",
    order: Literal["asc", "desc"] = "desc",
    mine: bool = False,
):
    if mine and access.principal.role != "user":
        raise HTTPException(status_code=403, detail="Personal export forbidden")
    # Embed once: every page of the export ranks against the same query vector.
    plan = await plan_search(query, embedding)
    first = await browse_page(db, access, query, plan, sort=sort, order=order,
                              page=1, per_page=EXPORT_PAGE_SIZE, summary=False)

    async def selected_pages():
        yield first["items"]
        page = 2
        while (page - 1) * EXPORT_PAGE_SIZE < first["total"]:
            browsed = await browse_page(db, access, query, plan, sort=sort, order=order,
                                        page=page, per_page=EXPORT_PAGE_SIZE, summary=False)
            yield browsed["items"]
            page += 1

    if access.principal.role == "admin":
        # The Admin browser/export contract is metadata-only even when this
        # administrator may read some shared content elsewhere.
        columns = ("id", "scope", "scope_id", "owner_id", "actor_id", "driver_id",
                   "weight", "version", "is_current", "status", "content_type",
                   "created_at", "updated_at", "deleted_at", "redacted")
        async def csv_rows():
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(columns)
            yield output.getvalue()
            async for items in selected_pages():
                for item in items:
                    output.seek(0)
                    output.truncate(0)
                    writer.writerow([_csv_safe(item.get(column)) for column in columns])
                    yield output.getvalue()
        return StreamingResponse(csv_rows(), media_type="text/csv; charset=utf-8",
                                 headers={"Content-Disposition": 'attachment; filename="memoryhub-metadata.csv"',
                                          "Cache-Control": "no-store"})

    tenant = access.principal.tenant_id
    async def jsonl_rows():
        async for items in selected_pages():
            ids = [uuid.UUID(item["id"]) for item in items]
            rows = (await db.execute(select(MemoryNode).where(
                MemoryNode.id.in_(ids), MemoryNode.tenant_id == tenant,
                MemoryNode.deleted_at.is_(None), access.content_clause(),
            ))).scalars().all() if ids else []
            by_id = {node.id: node for node in rows if _human_can_see_content(access, node)}
            for item in items:
                node = by_id.get(uuid.UUID(item["id"]))
                if node is None or (mine and node.owner_id not in access.identities):
                    continue
                record = {
                    "id": str(node.id), "logical_id": str(node.logical_id),
                    "scope": node.scope, "scope_id": node.scope_id,
                    "owner_id": node.owner_id, "content": node.content, "stub": node.stub,
                    "weight": node.weight, "version": node.version,
                    "is_current": node.is_current, "domains": node.domains or [],
                    "metadata": node.metadata_, "created_at": node.created_at.isoformat(),
                    "updated_at": node.updated_at.isoformat(),
                }
                yield json.dumps(record, ensure_ascii=False) + "\n"
    return StreamingResponse(jsonl_rows(), media_type="application/x-ndjson; charset=utf-8",
                             headers={"Content-Disposition": 'attachment; filename="memoryhub-memories.jsonl"',
                                      "Cache-Control": "no-store"})
