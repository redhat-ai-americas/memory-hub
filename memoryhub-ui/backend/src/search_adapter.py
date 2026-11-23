"""Human search playground adapter for existing Core retrieval."""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from memoryhub_core.models.memory import MemoryNode
from memoryhub_core.services.memory import search_memories, search_memories_with_focus
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.authorization import Access, AccessDep
from src.database import get_db
from src.human_adapters import EmbeddingDep, _human_can_see_content

router = APIRouter()
DbDep = Annotated[AsyncSession, Depends(get_db)]


class SearchBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=8000)
    focus: str | None = Field(default=None, max_length=8000)
    identity: str | None = Field(default=None, max_length=255)
    project: str | None = Field(default=None, max_length=255)
    mode: Literal["full", "index", "full_only"] = "full"
    max_results: int = Field(default=20, ge=1, le=100)
    session_focus_weight: float = Field(default=0.4, ge=0, le=1)
    weight_threshold: float = Field(default=0.8, ge=0, le=1)
    max_response_tokens: int = Field(default=4096, ge=1, le=100000)
    current_only: bool = True
    include_branches: bool = False
    rerank: bool = False
    temporal_status: Literal["current", "expired", "all"] | None = None
    explain: list[uuid.UUID] = Field(default_factory=list, max_length=100)


def _authorized_scopes(access: Access) -> tuple[dict, set[str], set[str], set[str]]:
    """Map direct human grants to Core filters, independent of MCP scopes."""
    scopes: dict = {}
    if access.principal.role == "user":
        scopes["user"] = sorted(access.identities)
        scopes["organizational"] = None
        scopes["enterprise"] = None
        projects = access.human_projects
        roles = access.human_roles
        campaigns = access.human_campaigns
    else:
        projects = access.human_projects if "project" in access.moderation_scopes else set()
        roles = access.human_roles if "role" in access.moderation_scopes else set()
        campaigns = access.human_campaigns if "campaign" in access.moderation_scopes else set()
        if "organizational" in access.moderation_scopes:
            scopes["organizational"] = None
    if projects:
        scopes["project"] = sorted(projects)
    if roles:
        scopes["role"] = None
    if campaigns:
        scopes["campaign"] = None
    return scopes, projects, roles, campaigns


def _token_estimate(value: str) -> int:
    # A display estimate only; Core's retrieval ranking is unchanged.
    return max(1, (len(value) + 3) // 4) if value else 0


@router.post("/api/search")
async def human_search(body: SearchBody, db: DbDep, access: AccessDep,
                       embedding: EmbeddingDep):
    """Search only human-readable nodes and reauthorize every returned hit."""
    scopes, projects, roles, campaigns = _authorized_scopes(access)
    if body.project:
        if body.project not in projects:
            raise HTTPException(status_code=404, detail="Project not found")
        projects = {body.project}
        scopes = {"project": [body.project]}
    access.forbid_person_filter(body.identity)
    if body.identity and access.principal.role == "user" and body.identity not in access.identities:
        raise HTTPException(status_code=404, detail="Identity not found")
    start = time.monotonic()
    if scopes:
        kwargs = dict(
            tenant_id=access.principal.tenant_id,
            owner_id=body.identity,
            weight_threshold=body.weight_threshold,
            max_results=min(100, body.max_results * 4),
            current_only=body.current_only,
            authorized_scopes=scopes,
            campaign_ids=campaigns,
            project_ids=projects,
            role_names=roles,
            temporal_status=body.temporal_status,
        )
        if body.focus and body.session_focus_weight > 0:
            focused = await search_memories_with_focus(
                body.query, db, embedding, focus_string=body.focus,
                session_focus_weight=body.session_focus_weight, **kwargs,
            )
            hits = focused.results
        else:
            hits = await search_memories(body.query, db, embedding, **kwargs)
    else:
        hits = []
    elapsed_ms = round((time.monotonic() - start) * 1000, 2)
    ids = [item.id for item, _score in hits]
    rows = (await db.execute(select(MemoryNode).where(
        MemoryNode.id.in_(ids),
        MemoryNode.tenant_id == access.principal.tenant_id,
        MemoryNode.deleted_at.is_(None),
        access.content_clause(),
    ))).scalars().all() if ids else []
    allowed = {node.id: node for node in rows if _human_can_see_content(access, node)}
    now = datetime.now(UTC)
    results = []
    context = []
    used_tokens = 0
    for hit, score in hits:
        node = allowed.get(hit.id)
        if node is None or (body.project and (node.scope != "project" or node.scope_id != body.project)):
            continue
        if body.identity and node.owner_id != body.identity:
            continue
        if not body.include_branches and node.parent_id is not None:
            continue
        if body.mode == "full_only" and node.weight < body.weight_threshold:
            continue
        full = body.mode != "index" and node.weight >= body.weight_threshold
        content = node.content if full else None
        delivered = content if full else node.stub
        tokens = _token_estimate(delivered)
        if used_tokens + tokens > body.max_response_tokens:
            continue
        used_tokens += tokens
        context.append(delivered)
        temporal = "expired" if node.relevant_until and node.relevant_until <= now else "current"
        results.append({
            "rank": len(results) + 1, "id": str(node.id), "scope": node.scope,
            "scope_id": node.scope_id, "owner_id": node.owner_id, "stub": node.stub,
            "content": content, "delivery": "full" if full else "stub",
            "weight": node.weight, "version": node.version,
            "relevant_until": node.relevant_until, "temporal_status": temporal,
            "historical": not node.is_current,
            "scores": {"vector": None, "text": None, "focus": None,
                       "rrf": float(score), "rerank": None, "weight": node.weight},
            "tokens": tokens,
        })
        if len(results) >= body.max_results:
            break
    by_id = {result["id"]: result for result in results}
    explain = [{
        "id": str(uid), "found": str(uid) in by_id,
        "stage": "returned" if str(uid) in by_id else "missing",
        "detail": "Returned in this authorized result set" if str(uid) in by_id
                  else "Not returned in this authorized result set",
        **({"stub": by_id[str(uid)]["stub"], "scope": by_id[str(uid)]["scope"],
            "weight": by_id[str(uid)]["weight"], "rank": by_id[str(uid)]["rank"]}
           if str(uid) in by_id else {}),
    } for uid in body.explain]
    full_count = sum(item["delivery"] == "full" for item in results)
    return {
        "run_as": access.principal.username,
        "retrieval": "vector", "rerank": "not_configured",
        "stages": [{"name": "Core search", "ms": elapsed_ms,
                    "detail": "Human scope applied before retrieval and verified per result"}],
        "total_ms": elapsed_ms,
        # Core does not expose its internal candidate/funnel trace. These
        # counts describe only the authorized delivered set.
        "candidates": len(results), "omitted_count": 0, "weight_filtered": 0,
        "returned": len(results), "full_count": full_count,
        "stub_count": len(results) - full_count, "tokens": used_tokens,
        "results": results, "assembled_context": "\n\n".join(context),
        "explain": explain,
    }
