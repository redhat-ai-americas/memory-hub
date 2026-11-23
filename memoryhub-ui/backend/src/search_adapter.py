"""Search playground (#714): run a search the way an agent's ``search_memory`` does.

The BFF calls the same Core retrieval functions with the same routing as the
MCP tool: a session focus selects ``search_memories_with_focus`` (where domain
and graph boosts apply); without one, ``search_memories``. The reranker is the
one MCP uses (``MEMORYHUB_RERANKER_URL``). On top of that the BFF:

- applies the person's own read grants before retrieval and re-checks every hit;
- reports a funnel (matched → filters → access → weight → limit → budget) and
  which memories each stage dropped, without details of memories the person
  cannot read;
- explains each result (vector, focus and keyword similarity, Core's fused
  score, whether it was delivered in full) and, on request, why a given memory
  did not come back;
- falls back to text search when the embedding service is down, and says so.

``GET /api/search/health`` reports embedding and reranker availability.
"""

from __future__ import annotations

import math
import re
import time
import uuid
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from memoryhub_core.models.memory import MemoryNode
from memoryhub_core.services.memory import search_memories, search_memories_with_focus
from memoryhub_core.services.rerank import HttpRerankerService, NoopRerankerService, RerankerService
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.authorization import Access, AccessDep
from src.config import Settings, get_settings
from src.database import get_db
from src.human_adapters import EmbeddingDep, _human_can_see_content

router = APIRouter()
DbDep = Annotated[AsyncSession, Depends(get_db)]
SettingsDep = Annotated[Settings, Depends(get_settings)]

Scope = Literal["user", "project", "campaign", "role", "organizational", "enterprise"]
Signal = Literal["reranker", "focus", "keyword", "domain", "graph"]
WINDOW_MIN, WINDOW_MAX = 30, 200


class SearchBody(BaseModel):
    """The options of MCP ``search_memory`` a person may use, with the same names and defaults."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=8000)
    # Filters
    scope: Scope | None = None
    project: str | None = Field(default=None, max_length=255)
    identity: str | None = Field(default=None, max_length=255)
    domains: list[str] = Field(default_factory=list, max_length=20)
    entities: list[str] = Field(default_factory=list, max_length=20)
    content_type: Literal["experiential", "knowledge", "behavioral", "procedural"] | None = None
    current_only: bool = True
    weight_threshold: float = Field(default=0.8, ge=0, le=1)
    temporal_status: Literal["current", "expired", "all"] | None = None
    # Ranking
    focus: str | None = Field(default=None, max_length=8000)
    session_focus_weight: float = Field(default=0.4, ge=0, le=1)
    rerank: bool = True
    domain_boost_weight: float = Field(default=0.3, ge=0, le=1)
    graph_depth: int = Field(default=0, ge=0, le=3)
    graph_relationship_types: list[str] = Field(default_factory=list, max_length=10)
    graph_boost_weight: float = Field(default=0.2, ge=0, le=1)
    disabled_signals: list[Signal] = Field(default_factory=list)
    # Response
    mode: Literal["full", "index", "full_only"] = "full"
    max_results: int = Field(default=10, ge=1, le=100)
    max_response_tokens: int = Field(default=4000, ge=1, le=100000)
    include_branches: bool = False
    # Ask why given memories did (not) come back
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


def _token_estimate(value: str | None) -> int:
    # A display estimate only; Core's retrieval ranking is unchanged.
    return max(1, (len(value) + 3) // 4) if value else 0


def _reranker(settings: Settings) -> RerankerService:
    return HttpRerankerService(settings.reranker_url) if settings.reranker_url else NoopRerankerService()


def _cosine(a, b) -> float | None:
    if a is None or b is None:
        return None
    a, b = list(a), list(b)
    if not a or len(a) != len(b):
        return None
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
    return round(dot / (na * nb), 4) if na and nb else None


def _terms(text: str) -> set[str]:
    return set(re.findall(r"[\w-]{3,}", text.lower()))


def _keyword(query_terms: set[str], node: MemoryNode) -> float | None:
    if not query_terms:
        return None
    return round(len(_terms(node.content or "") & query_terms) / len(query_terms), 2)


def mcp_call(body: SearchBody, scopes: dict, projects: set[str], roles: set[str], campaigns: set[str],
             tenant: str, window: int, reranker: RerankerService) -> tuple[str, dict]:
    """Which Core function ``search_memory`` would call for these options, and with which arguments.

    Kept separate so a test can compare it with the MCP tool's call for the same options.
    """
    disabled = set(body.disabled_signals) | (set() if body.rerank else {"reranker"})
    common = dict(
        tenant_id=tenant, scope=body.scope, owner_id=body.identity,
        weight_threshold=0.0 if body.mode == "full_only" else body.weight_threshold,
        max_results=window, current_only=body.current_only, authorized_scopes=scopes,
        campaign_ids=campaigns, project_ids=projects, role_names=roles,
        entity_names=body.entities or None, content_type=body.content_type,
        temporal_status=body.temporal_status, disabled_signals=disabled or None, reranker=reranker,
    )
    if body.focus and body.focus.strip():
        return "search_memories_with_focus", dict(
            common, focus_string=body.focus.strip(), session_focus_weight=body.session_focus_weight,
            domains=body.domains or None, domain_boost_weight=body.domain_boost_weight,
            graph_depth=body.graph_depth, graph_relationship_types=body.graph_relationship_types or None,
            graph_boost_weight=body.graph_boost_weight,
        )
    return "search_memories", common


async def _text_fallback(db: AsyncSession, access: Access, body: SearchBody, window: int) -> list[tuple]:
    """Text match over memories the person may read, when the embedding service is down."""
    terms = sorted(_terms(body.query))[:8] or [body.query.strip().lower()]
    where = [MemoryNode.tenant_id == access.principal.tenant_id, MemoryNode.deleted_at.is_(None),
             access.content_clause(), or_(*[MemoryNode.content.ilike(f"%{t}%") for t in terms])]
    if body.current_only:
        where.append(MemoryNode.is_current.is_(True))
    if body.scope:
        where.append(MemoryNode.scope == body.scope)
    if body.content_type:
        where.append(MemoryNode.content_type == body.content_type)
    rows = (await db.execute(select(MemoryNode).where(and_(*where)).order_by(
        MemoryNode.weight.desc(), MemoryNode.updated_at.desc()).limit(window))).scalars().all()
    wanted = set(terms)

    def matched(n: MemoryNode) -> int:
        return len(_terms(n.content or "") & wanted)

    ranked = sorted(rows, key=lambda n: -(matched(n) + n.weight / 10))
    return [(n, round(matched(n) / len(wanted), 4)) for n in ranked]


FUNNEL = [("matched", "Matched by retrieval"), ("filters", "Passed your filters"),
          ("rbac", "You may read"), ("weight", "Passed the weight rule"),
          ("limit", "Within max results"), ("budget", "Within the token budget")]


async def _retrieve(db: AsyncSession, access: Access, body: SearchBody, embedding, reranker: RerankerService,
                    scopes: dict, projects: set[str], roles: set[str], campaigns: set[str], window: int) -> dict:
    """Run Core retrieval as search_memory would; fall back to text when vectors are unavailable."""
    out = {"hits": [], "retrieval": "vector", "fallback_reason": None, "used_reranker": False,
           "graph_added": 0, "pivot": None, "stages": []}
    if not scopes:
        return out
    name, kwargs = mcp_call(body, scopes, projects, roles, campaigns, access.principal.tenant_id, window, reranker)
    t0 = time.monotonic()
    try:
        if name == "search_memories_with_focus":
            bundle = await search_memories_with_focus(body.query, db, embedding, **kwargs)
            out.update(hits=bundle.results, used_reranker=bundle.used_reranker,
                       graph_added=bundle.graph_neighbors_added, fallback_reason=bundle.fallback_reason,
                       pivot={"suggested": bundle.pivot_suggested, "distance": bundle.pivot_distance,
                              "reason": bundle.pivot_reason})
        else:
            out["hits"] = await search_memories(body.query, db, embedding, **kwargs)
            out["used_reranker"] = bool(reranker.is_configured and "reranker" not in (kwargs["disabled_signals"] or ()))
        out["stages"].append({"name": "Core search", "ms": round((time.monotonic() - t0) * 1000, 2),
                              "detail": f"{name}, same routing and arguments as search_memory"})
    except Exception as exc:  # noqa: BLE001 - an unreachable embedding service lands here
        await db.rollback()
        t0 = time.monotonic()
        out.update(retrieval="text", hits=await _text_fallback(db, access, body, window),
                   fallback_reason=f"Vector search failed ({type(exc).__name__}); text match used")
        out["stages"].append({"name": "full-text", "ms": round((time.monotonic() - t0) * 1000, 2),
                              "detail": "Fallback: the embedding service did not answer"})
    return out


@router.post("/api/search")
async def human_search(body: SearchBody, db: DbDep, access: AccessDep, settings: SettingsDep,
                       embedding: EmbeddingDep):
    """Run a search as the signed-in person, the way their agent's ``search_memory`` would."""
    scopes, projects, roles, campaigns = _authorized_scopes(access)
    if body.project:
        if body.project not in projects:
            raise HTTPException(status_code=404, detail="Project not found")
        projects = {body.project}
        scopes = {"project": [body.project]}
    if body.scope:
        scopes = {body.scope: scopes[body.scope]} if body.scope in scopes else {}
    if body.identity and access.principal.role == "user" and body.identity not in access.identities:
        raise HTTPException(status_code=404, detail="Identity not found")
    window = min(WINDOW_MAX, max(WINDOW_MIN, body.max_results * 3))
    reranker = _reranker(settings)
    notes: list[str] = []
    if not (body.focus and body.focus.strip()) and (body.domains or body.graph_depth):
        notes.append("Domain and graph boosts apply only with a session focus, as in search_memory.")

    got = await _retrieve(db, access, body, embedding, reranker, scopes, projects, roles, campaigns, window)
    hits, stages = got["hits"], got["stages"]
    query_vec = focus_vec = None
    if got["retrieval"] == "vector" and hits:
        t1 = time.monotonic()
        try:
            query_vec = await embedding.embed(body.query)
            if body.focus and body.focus.strip():
                focus_vec = await embedding.embed(body.focus.strip())
        except Exception:  # noqa: BLE001 - explain is best effort; ranking already happened
            query_vec = focus_vec = None
        stages.append({"name": "explain", "ms": round((time.monotonic() - t1) * 1000, 2),
                       "detail": "Similarities recomputed for the explanation"})

    t2 = time.monotonic()
    ids = [item.id for item, _score in hits]
    nodes = {n.id: n for n in (await db.execute(select(MemoryNode).where(
        MemoryNode.id.in_(ids), MemoryNode.tenant_id == access.principal.tenant_id,
    ))).scalars().all()} if ids else {}
    query_terms = _terms(body.query)
    now = datetime.now(UTC)
    dropped, results, context = [], [], []
    hidden: dict[str, int] = {}
    passed = dict.fromkeys(("filters", "weight", "limit"), 0)
    downgraded = used_tokens = 0

    def drop(node: MemoryNode, stage: str, reason: str, detail: str, score: float, rank: int) -> None:
        dropped.append({"id": str(node.id), "stub": node.stub, "scope": node.scope, "scope_id": node.scope_id,
                        "owner_id": node.owner_id, "weight": node.weight, "version": node.version,
                        "stage": stage, "reason": reason, "detail": detail, "score": float(score), "rank": rank})

    for rank, (hit, score) in enumerate(hits, start=1):
        node = nodes.get(hit.id)
        if node is None or node.deleted_at is not None or not _human_can_see_content(access, node):
            # Never describe what the person cannot read: counted only.
            hidden["rbac"] = hidden.get("rbac", 0) + 1
            continue
        if body.project and (node.scope != "project" or node.scope_id != body.project):
            drop(node, "filters", "Other project", f"In {node.scope} scope, not project {body.project}", score, rank)
            continue
        if body.identity and node.owner_id != body.identity:
            drop(node, "filters", "Other owner", f"Owned by {node.owner_id}", score, rank)
            continue
        if not body.include_branches and node.parent_id is not None:
            drop(node, "filters", "Branch", "Branches are excluded unless include_branches is set", score, rank)
            continue
        passed["filters"] += 1
        if body.mode == "full_only" and node.weight < body.weight_threshold:
            drop(node, "weight", "Below weight threshold",
                 f"Weight {node.weight:.2f} < {body.weight_threshold:.2f}; full_only returns no stubs", score, rank)
            continue
        passed["weight"] += 1
        if len(results) >= body.max_results:
            drop(node, "limit", "Beyond max results", f"Ranked {rank}; max_results is {body.max_results}", score, rank)
            continue
        passed["limit"] += 1
        full = body.mode != "index" and node.weight >= body.weight_threshold
        delivered = node.content if full else node.stub
        tokens = _token_estimate(delivered)
        if used_tokens + tokens > body.max_response_tokens:
            left = body.max_response_tokens - used_tokens
            drop(node, "budget", "Over the token budget",
                 f"Needs {tokens} tokens; {left} left of {body.max_response_tokens}", score, rank)
            continue
        used_tokens += tokens
        downgraded += 0 if full or body.mode == "index" else 1
        context.append(delivered)
        results.append({
            "rank": len(results) + 1, "core_rank": rank, "id": str(node.id), "scope": node.scope,
            "scope_id": node.scope_id, "owner_id": node.owner_id, "stub": node.stub,
            "content": node.content if full else None, "delivery": "full" if full else "stub",
            "downgraded": not full and body.mode != "index",
            "weight": node.weight, "version": node.version, "domains": list(node.domains or []),
            "relevant_until": node.relevant_until,
            "temporal_status": "expired" if node.relevant_until and node.relevant_until <= now else "current",
            "historical": not node.is_current,
            "scores": {"vector": _cosine(node.embedding, query_vec), "text": _keyword(query_terms, node),
                       "focus": _cosine(node.embedding, focus_vec), "rrf": float(score),
                       "rerank": None, "weight": node.weight},
            "why": _why(node, full, body, query_terms, score),
            "tokens": tokens,
        })
    counts = {"matched": len(hits), "filters": passed["filters"] + hidden.get("rbac", 0),
              "rbac": passed["filters"], "weight": passed["weight"], "limit": passed["limit"],
              "budget": len(results)}
    funnel = [{"key": k, "label": label, "count": counts[k],
               **({"dropped": sum(d["stage"] == k for d in dropped)} if k != "matched" else {}),
               **({"downgraded": downgraded} if k == "weight" else {})} for k, label in FUNNEL]
    stages.append({"name": "assemble", "ms": round((time.monotonic() - t2) * 1000, 2),
                   "detail": "Access re-checked per result; filters, weight rule, limit and token budget applied"})

    explain = await _explain(db, access, body, results, dropped, query_vec)
    full_count = sum(r["delivery"] == "full" for r in results)
    rerank_state = ("off" if not body.rerank or "reranker" in body.disabled_signals
                    else "not_configured" if not reranker.is_configured
                    else "on" if got["used_reranker"] else "unavailable")
    return {
        "run_as": access.principal.username, "retrieval": got["retrieval"], "rerank": rerank_state,
        "fallback_reason": got["fallback_reason"], "notes": notes, "pivot": got["pivot"],
        "graph_neighbors_added": got["graph_added"],
        "stages": stages, "total_ms": round(sum(s["ms"] for s in stages), 2),
        # omitted_count: hits withheld because the person may not read them (shown as "filtered by access").
        "candidates": len(hits), "omitted_count": sum(hidden.values()),
        "weight_filtered": sum(d["stage"] == "weight" for d in dropped),
        "returned": len(results), "full_count": full_count, "stub_count": len(results) - full_count,
        "tokens": used_tokens, "results": results, "assembled_context": "\n\n".join(context),
        "funnel": funnel, "dropped": dropped, "hidden_dropped": hidden, "explain": explain,
    }


def _why(node: MemoryNode, full: bool, body: SearchBody, query_terms: set[str], score: float) -> list[str]:
    """Plain reasons for a result: what matched and how it was delivered."""
    reasons = [f"Core fused score {float(score):.3f}"]
    matched = sorted(_terms(node.content or "") & query_terms)
    if matched:
        reasons.append(f"Shares the words {', '.join(matched[:5])}")
    if body.focus and body.focus.strip():
        reasons.append(f"Session focus blended at {body.session_focus_weight:.2f}")
    boosted = sorted(set(node.domains or []) & set(body.domains))
    if boosted and body.focus and body.focus.strip():
        reasons.append(f"Domain boost: {', '.join(boosted)}")
    if full:
        reasons.append(f"Full text: weight {node.weight:.2f} ≥ {body.weight_threshold:.2f}")
    else:
        reasons.append("Stub only: " + ("index mode" if body.mode == "index"
                                        else f"weight {node.weight:.2f} < {body.weight_threshold:.2f}"))
    return reasons


async def _explain(db: AsyncSession, access: Access, body: SearchBody, results: list[dict], dropped: list[dict],
                   query_vec) -> list[dict]:
    if not body.explain:
        return []
    returned = {r["id"]: r for r in results}
    lost = {d["id"]: d for d in dropped}
    rows = {n.id: n for n in (await db.execute(select(MemoryNode).where(
        MemoryNode.id.in_(body.explain), MemoryNode.tenant_id == access.principal.tenant_id,
    ))).scalars().all()}
    out = []
    for uid in body.explain:
        key, node = str(uid), rows.get(uid)
        if key in returned:
            r = returned[key]
            out.append({"id": key, "found": True, "stage": "returned", "detail": f"Returned at rank {r['rank']}",
                        "stub": r["stub"], "scope": r["scope"], "weight": r["weight"], "rank": r["rank"],
                        "similarity": r["scores"]["vector"]})
            continue
        if key in lost:
            d = lost[key]
            out.append({"id": key, "found": True, "stage": d["stage"], "detail": f"{d['reason']}: {d['detail']}",
                        "stub": d["stub"], "scope": d["scope"], "weight": d["weight"], "rank": d["rank"]})
            continue
        if node is None:
            out.append({"id": key, "found": False, "stage": "missing", "detail": "No memory you can read has this ID"})
            continue
        if node.deleted_at is not None:
            out.append({"id": key, "found": False, "stage": "deleted", "detail": "This memory is deleted"})
            continue
        if not _human_can_see_content(access, node):
            out.append({"id": key, "found": False, "stage": "missing", "detail": "No memory you can read has this ID"})
            continue
        reasons = []
        if body.current_only and not node.is_current:
            reasons.append("it is an old version and current_only is set")
        if body.content_type and node.content_type != body.content_type:
            reasons.append(f"its content type is {node.content_type}")
        if body.scope and node.scope != body.scope:
            reasons.append(f"it is in {node.scope} scope")
        sim = _cosine(node.embedding, query_vec)
        if reasons:
            detail = "Not retrieved: " + "; ".join(reasons)
        else:
            detail = "Ranked below the candidates retrieval returned"
            detail += f" (similarity {sim:.2f})" if sim is not None else ""
        out.append({"id": key, "found": True, "stage": "filters" if reasons else "matched", "detail": detail,
                    "stub": node.stub, "scope": node.scope, "weight": node.weight, "similarity": sim})
    return out


@router.get("/api/search/health")
async def search_health(settings: SettingsDep, embedding: EmbeddingDep, _access: AccessDep):
    """Is semantic search available right now, and is a reranker configured and answering?"""
    t = time.monotonic()
    try:
        vector = await embedding.embed("search health check")
        emb = {"status": "ok", "dimensions": len(vector), "ms": round((time.monotonic() - t) * 1000, 1)}
    except Exception as exc:  # noqa: BLE001
        emb = {"status": "down", "error": type(exc).__name__, "ms": round((time.monotonic() - t) * 1000, 1)}
    reranker = _reranker(settings)
    if not reranker.is_configured:
        rr = {"status": "not_configured"}
    else:
        t = time.monotonic()
        try:
            order = await reranker.rerank("health", ["health check", "unrelated"])
            rr = {"status": "ok" if order else "down", "ms": round((time.monotonic() - t) * 1000, 1)}
        except Exception as exc:  # noqa: BLE001
            rr = {"status": "down", "error": type(exc).__name__}
    return {
        "embedding": emb, "reranker": rr,
        "search_mode": "vector" if emb["status"] == "ok" else "text",
        "fallback": (None if emb["status"] == "ok"
                     else "Searches use text matching until the embedding service answers."),
    }
