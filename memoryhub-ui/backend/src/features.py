"""What has content for this viewer, so the navigation only shows tabs that do.

Knowledge, Documents, Context packs, Retrieval checks and Operations appear in
the menu once there is something in them; until then they are reached from
the page where their first item is made (Search playground, Memory browser).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.access import ViewerDep
from src.config import Settings, get_settings
from src.database import get_db

router = APIRouter()

DbDep = Annotated[AsyncSession, Depends(get_db)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


async def _count(db: AsyncSession, sql: str, params: dict) -> int:
    try:
        return int((await db.execute(text(sql), params)).scalar() or 0)
    except Exception:  # the table is created on first use
        await db.rollback()
        return 0


@router.get("/api/nav-features")
async def nav_features(db: DbDep, settings: SettingsDep, viewer: ViewerDep):
    from memoryhub_core.models.memory import MemoryNode
    from sqlalchemy import func, select

    from src.access import access_for
    from src.knowledge import _base, _projects, _subject_filters

    t = settings.ui_tenant_id
    mine = {"t": t, "o": viewer.username}
    out: dict[str, int] = {}
    if viewer.redacts_content:
        out["search_runs"] = await _count(
            db, "SELECT count(*) FROM memoryhub_ui_search_runs WHERE tenant_id = :t", {"t": t}
        )
        out["jobs"] = await _count(db, "SELECT count(*) FROM memoryhub_ui_jobs WHERE tenant_id = :t", {"t": t})
        return _without_labs(settings, out)

    acc = await access_for(db, settings, viewer)
    knowledge = 0
    for kind, sid in [("me", viewer.username)] + [("project", p) for p in await _projects(db, settings, acc)]:
        filters = _base(settings, acc) + _subject_filters(acc, viewer, kind, sid)
        knowledge += int((await db.execute(select(func.count()).select_from(MemoryNode).where(*filters))).scalar_one())
        if knowledge:
            break
    projects = sorted(acc.grants.projects) if acc.grants is not None else None
    shared = "(owner = :o OR project = ANY(:p))" if projects is not None else "(owner = :o OR project IS NOT NULL)"
    params = {**mine, "p": projects or []}
    out["knowledge"] = knowledge
    out["documents"] = await _count(
        db, f"SELECT count(*) FROM memoryhub_ui_documents WHERE tenant_id = :t AND {shared}", params
    )
    pack_shared = (
        "(owner = :o OR (visibility = 'project' AND project = ANY(:p)))"
        if projects is not None
        else "(owner = :o OR visibility = 'project')"
    )
    out["packs"] = await _count(
        db, f"SELECT count(*) FROM memoryhub_ui_context_packs WHERE tenant_id = :t AND {pack_shared}", params
    )
    out["checks"] = await _count(
        db,
        "SELECT count(*) FROM memoryhub_ui_saved_queries WHERE tenant_id = :t AND owner = :o",
        mine,
    )
    out["check_runs"] = await _count(
        db, "SELECT count(*) FROM memoryhub_ui_eval_runs WHERE tenant_id = :t AND owner = :o", mine
    )
    out["search_runs"] = await _count(
        db, "SELECT count(*) FROM memoryhub_ui_search_runs WHERE tenant_id = :t AND viewer = :o", mine
    )
    out["jobs"] = await _count(db, "SELECT count(*) FROM memoryhub_ui_jobs WHERE tenant_id = :t AND owner = :o", mine)
    return _without_labs(settings, out)


LABS_FEATURES = ("knowledge", "documents", "packs", "checks", "check_runs", "search_runs")


def _without_labs(settings: Settings, out: dict) -> dict:
    """While MemoryHub Labs is off, Labs tabs never appear in the menu."""
    if not settings.ui_labs:
        out.update({k: 0 for k in LABS_FEATURES if k in out})
    return {**out, "labs": int(settings.ui_labs)}
