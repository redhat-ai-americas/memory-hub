"""Context packs: a named, reusable piece of context for an agent or project.

A pack is pinned memories (always included, in order) plus searches whose
results fill the rest, within a token budget. Rendering happens under the
*viewer's* access every time, so a shared pack never shows anyone more than
they may read, and it always reflects the current memories.

Packs can be private or shared with a project, read-only for others, and
attached to the owner's agents. MemoryHub's MCP server does not deliver packs
to agents yet (there is no ``get_context_pack`` tool), so attaching records
the intent and the pack can be copied or downloaded as Markdown meanwhile.
"""

from __future__ import annotations

import json
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from memoryhub_core.models.memory import MemoryNode
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.access import ContentDep, LabsDep, access_for
from src.config import Settings, get_settings
from src.database import get_db
from src.ui_common import Viewer, audit, clean_stub, now_utc

router = APIRouter(dependencies=[LabsDep])

DbDep = Annotated[AsyncSession, Depends(get_db)]
SettingsDep = Annotated[Settings, Depends(get_settings)]

TABLE = "memoryhub_ui_context_packs"


async def ensure_table(db: AsyncSession) -> None:
    from src.schema import require

    await require(db)


def _load(v: Any) -> Any:
    return json.loads(v) if isinstance(v, str) else v


_COLS = (
    "id, owner, name, description, pinned, queries, token_budget, visibility, project, read_only, agents, "
    "created_at, updated_at, last_render"
)


def _row(r: Any, viewer: Viewer) -> dict:
    mine = r[1] == viewer.username
    return {
        "id": str(r[0]),
        "owner": r[1],
        "name": r[2],
        "description": r[3],
        "pinned": _load(r[4]) or [],
        "queries": _load(r[5]) or [],
        "token_budget": r[6],
        "visibility": r[7],
        "project": r[8],
        "read_only": r[9],
        "agents": _load(r[10]) or [],
        "created_at": r[11],
        "updated_at": r[12],
        "last_render": _load(r[13]),
        "mine": mine,
        "can_edit": mine or not r[9],
    }


async def visible_packs(db: AsyncSession, settings: Settings, viewer: Viewer) -> list[dict]:
    await ensure_table(db)
    acc = await access_for(db, settings, viewer)
    projects = acc.grants.projects if acc.grants is not None else None
    rows = (
        await db.execute(
            text(f"SELECT {_COLS} FROM {TABLE} WHERE tenant_id = :t ORDER BY updated_at DESC"),
            {"t": settings.ui_tenant_id},
        )
    ).all()
    return [
        _row(r, viewer)
        for r in rows
        if r[1] == viewer.username or (r[7] == "project" and r[8] and (projects is None or r[8] in projects))
    ]


async def _pack(db, settings, viewer, pack_id: str) -> dict:
    try:
        parsed = uuid.UUID(pack_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Invalid pack ID") from exc
    for p in await visible_packs(db, settings, viewer):
        if p["id"] == str(parsed):
            return p
    raise HTTPException(status_code=404, detail="Context pack not found")


class PackQuery(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    max_results: int = Field(default=5, ge=1, le=20)
    weight_threshold: float = Field(default=0.0, ge=0, le=1)
    project: str | None = Field(default=None, max_length=255)


class PackIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    pinned: list[str] = Field(default_factory=list, max_length=100)
    queries: list[PackQuery] = Field(default_factory=list, max_length=10)
    token_budget: int = Field(default=2000, ge=200, le=50_000)
    visibility: str = Field(default="private", pattern="^(private|project)$")
    project: str | None = Field(default=None, max_length=255)
    read_only: bool = True


class PackPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    pinned: list[str] | None = Field(default=None, max_length=100)
    queries: list[PackQuery] | None = Field(default=None, max_length=10)
    token_budget: int | None = Field(default=None, ge=200, le=50_000)
    visibility: str | None = Field(default=None, pattern="^(private|project)$")
    project: str | None = Field(default=None, max_length=255)
    read_only: bool | None = None
    agents: list[str] | None = Field(default=None, max_length=50)


async def render(db: AsyncSession, settings: Settings, viewer: Viewer, pack: dict) -> dict:
    """Assemble the pack for this viewer: pinned first, then each search, within the budget."""
    from src.retrieval import run_search
    from src.routes_dashboard import SearchRequest

    acc = await access_for(db, settings, viewer)
    budget = int(pack["token_budget"])
    used = 0
    items: list[dict] = []
    seen: set[str] = set()
    hidden = 0
    over: list[dict] = []

    def add(node_id: str, stub: str, scope: str, body: str, source: str, weight: float) -> None:
        nonlocal used
        tokens = max(1, len(body) // 4)
        if used + tokens > budget:
            over.append({"id": node_id, "stub": stub, "source": source, "tokens": tokens})
            return
        used += tokens
        items.append(
            {
                "id": node_id,
                "stub": stub,
                "scope": scope,
                "text": body,
                "source": source,
                "tokens": tokens,
                "weight": weight,
            }
        )

    pinned_ids = []
    for raw in pack["pinned"]:
        try:
            pinned_ids.append(uuid.UUID(raw))
        except ValueError:
            continue
    nodes = {
        n.id: n
        for n in (
            await db.execute(
                select(MemoryNode).where(
                    MemoryNode.tenant_id == settings.ui_tenant_id,
                    MemoryNode.id.in_(pinned_ids or [uuid.uuid4()]),
                    MemoryNode.deleted_at.is_(None),
                )
            )
        ).scalars()
    }
    missing = 0
    for pid in pinned_ids:
        n = nodes.get(pid)
        if n is None:
            missing += 1
            continue
        if not acc.can_read_row(n):
            hidden += 1
            continue
        seen.add(str(n.id))
        add(str(n.id), clean_stub(n.stub), n.scope, n.content, "pinned", n.weight)

    for i, q in enumerate(pack["queries"]):
        body = SearchRequest(
            query=q["query"],
            max_results=q.get("max_results", 5),
            weight_threshold=q.get("weight_threshold", 0.0),
            project=q.get("project"),
            mode="full",
            max_response_tokens=max(200, budget),
        )
        out = await run_search(db, settings, viewer, body, source="pack")
        for r in out["results"]:
            if r["id"] in seen:
                continue
            seen.add(r["id"])
            add(r["id"], r["stub"], r["scope"], r["content"] or r["stub"], f"query:{i}", r["weight"])

    markdown = "\n".join(
        [f"# {pack['name']}", "", pack.get("description") or "", ""]
        + [f"- [{it['scope']}] {it['text']}" for it in items]
    ).strip()
    return {
        "items": items,
        "tokens": used,
        "budget": budget,
        "over_budget": over,
        "hidden": hidden,
        "missing": missing,
        "markdown": markdown + "\n",
        "rendered_at": now_utc(),
        "as": viewer.username,
    }


@router.get("/api/context-packs")
async def list_packs(db: DbDep, settings: SettingsDep, viewer: ContentDep):
    return {"items": await visible_packs(db, settings, viewer)}


@router.post("/api/context-packs", status_code=201)
async def create_pack(body: PackIn, db: DbDep, settings: SettingsDep, viewer: ContentDep):
    from src.quality import _check_share

    await ensure_table(db)
    await _check_share(db, settings, viewer, body.visibility, body.project)
    pid = uuid.uuid4()
    await db.execute(
        text(
            f"INSERT INTO {TABLE} (id, tenant_id, owner, name, description, pinned, queries, token_budget, visibility, project, "  # noqa: E501
            "read_only) VALUES (:id, :t, :o, :n, :d, CAST(:p AS JSONB), CAST(:q AS JSONB), :b, :v, :pr, :ro)"
        ),
        {
            "id": pid,
            "t": settings.ui_tenant_id,
            "o": viewer.username,
            "n": body.name.strip(),
            "d": body.description,
            "p": json.dumps(list(dict.fromkeys(body.pinned))),
            "q": json.dumps([q.model_dump() for q in body.queries]),
            "b": body.token_budget,
            "v": body.visibility,
            "pr": body.project if body.visibility == "project" else None,
            "ro": body.read_only,
        },
    )
    await audit(
        db,
        tenant_id=settings.ui_tenant_id,
        viewer=viewer,
        event_type="pack.create",
        scope="user",
        owner_id=viewer.username,
        memory_id=None,
        metadata={"pack": str(pid)},
    )
    await db.commit()
    return {"id": str(pid)}


@router.get("/api/context-packs/{pack_id}")
async def get_pack(pack_id: str, db: DbDep, settings: SettingsDep, viewer: ContentDep):
    pack = await _pack(db, settings, viewer, pack_id)
    rendered = await render(db, settings, viewer, pack)
    if pack["mine"]:
        await db.execute(
            text(f"UPDATE {TABLE} SET last_render = CAST(:r AS JSONB) WHERE id = :id"),
            {
                "id": uuid.UUID(pack["id"]),
                "r": json.dumps(
                    {"at": now_utc().isoformat(), "tokens": rendered["tokens"], "items": len(rendered["items"])}
                ),
            },
        )
        await db.commit()
    acc = await access_for(db, settings, viewer)
    return {**pack, "render": rendered, "my_agents": sorted(acc.grants.agents) if acc.grants else []}


@router.get("/api/context-packs/{pack_id}/markdown", response_class=PlainTextResponse)
async def pack_markdown(pack_id: str, db: DbDep, settings: SettingsDep, viewer: ContentDep):
    pack = await _pack(db, settings, viewer, pack_id)
    return PlainTextResponse(
        (await render(db, settings, viewer, pack))["markdown"],
        headers={"Content-Disposition": f'attachment; filename="context-pack-{pack["id"][:8]}.md"'},
    )


@router.patch("/api/context-packs/{pack_id}")
async def update_pack(pack_id: str, body: PackPatch, db: DbDep, settings: SettingsDep, viewer: ContentDep):
    from src.quality import _check_share

    pack = await _pack(db, settings, viewer, pack_id)
    if not pack["can_edit"]:
        raise HTTPException(status_code=403, detail="This pack is read-only; only its owner can change it")
    owner_only = {"visibility", "project", "read_only", "agents"}
    changes = body.model_dump(exclude_none=True)
    if not pack["mine"] and owner_only & changes.keys():
        raise HTTPException(status_code=403, detail="Only the owner can change sharing or agents")
    if "agents" in changes:
        acc = await access_for(db, settings, viewer)
        mine = acc.grants.agents if acc.grants is not None else set(changes["agents"])
        foreign = [a for a in changes["agents"] if a not in mine]
        if foreign:
            raise HTTPException(status_code=403, detail=f"Not your agent: {', '.join(foreign)}")
    merged = {**pack, **changes}
    await _check_share(db, settings, viewer, merged["visibility"], merged["project"])
    await db.execute(
        text(
            f"UPDATE {TABLE} SET name = :n, description = :d, pinned = CAST(:p AS JSONB), queries = CAST(:q AS JSONB), "
            "token_budget = :b, visibility = :v, project = :pr, read_only = :ro, agents = CAST(:a AS JSONB), updated_at = now() "  # noqa: E501
            "WHERE id = :id"
        ),
        {
            "id": uuid.UUID(pack["id"]),
            "n": merged["name"].strip(),
            "d": merged["description"],
            "p": json.dumps(list(dict.fromkeys(merged["pinned"]))),
            "q": json.dumps([PackQuery(**q).model_dump() if isinstance(q, dict) else q for q in merged["queries"]]),
            "b": merged["token_budget"],
            "v": merged["visibility"],
            "pr": merged["project"] if merged["visibility"] == "project" else None,
            "ro": merged["read_only"],
            "a": json.dumps(sorted(set(merged["agents"]))),
        },
    )
    await audit(
        db,
        tenant_id=settings.ui_tenant_id,
        viewer=viewer,
        event_type="pack.update",
        scope="user",
        owner_id=pack["owner"],
        memory_id=None,
        metadata={"pack": pack["id"], "fields": sorted(changes)},
    )
    await db.commit()
    return {"ok": True}


@router.delete("/api/context-packs/{pack_id}", status_code=204)
async def delete_pack(pack_id: str, db: DbDep, settings: SettingsDep, viewer: ContentDep):
    pack = await _pack(db, settings, viewer, pack_id)
    if not pack["mine"]:
        raise HTTPException(status_code=403, detail="Only the owner can delete a pack")
    await db.execute(text(f"DELETE FROM {TABLE} WHERE id = :id"), {"id": uuid.UUID(pack["id"])})
    await db.commit()
