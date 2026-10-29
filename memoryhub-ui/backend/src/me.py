"""The signed-in user's own corner: preferences & privacy, and who read their memories."""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from memoryhub_core.models.audit import AuditLog
from memoryhub_core.models.memory import MemoryNode
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.access import ViewerDep, access_for
from src.config import Settings, get_settings
from src.database import get_db
from src.ui_common import SCOPES, audit, clean_stub, now_utc

logger = logging.getLogger(__name__)
router = APIRouter()

DbDep = Annotated[AsyncSession, Depends(get_db)]
SettingsDep = Annotated[Settings, Depends(get_settings)]

PREFS = "memoryhub_ui_user_prefs"
DEFAULT_PREFS = {
    "write": {"default_scope": "user", "default_weight": 0.7},
    "privacy": {"allow_promotion_by_others": False, "show_in_team_directory": True},
    "dreaming_fade_days": 60,
    "onboarding_dismissed": False,
    "behavior": None,  # filled from BEHAVIOR_TEMPLATES["balanced"] by _merge
    "behavior_history": [],
}

# Memory-behavior profile (R1-018/019): what agents should identify and store
# for this person. Stored and versioned here; agent hosts do not apply it yet,
# so the UI says so. Curation rules stay operator-owned guardrails (R1-021).
PROFILE_SCHEMA = "memoryhub.profile/v1"
BEHAVIOR_CATEGORIES = ("preferences", "project_decisions", "procedures", "facts")
BEHAVIOR_EXCLUDES = ("credentials", "personal_data", "health", "customer_data")
BEHAVIOR_TEMPLATES = {
    "balanced": {
        "include": ["preferences", "project_decisions", "procedures", "facts"],
        "exclude": ["credentials", "personal_data"],
        "confirmation": "sensitive",
        "cadence": "session_end",
        "update": "supersede",
    },
    "conservative": {
        "include": ["preferences", "project_decisions"],
        "exclude": ["credentials", "personal_data", "health", "customer_data"],
        "confirmation": "always",
        "cadence": "explicit",
        "update": "ask",
    },
    "proactive": {
        "include": ["preferences", "project_decisions", "procedures", "facts"],
        "exclude": ["credentials"],
        "confirmation": "never",
        "cadence": "every_turn",
        "update": "supersede",
    },
}
BEHAVIOR_CHOICES = {
    "confirmation": ("always", "sensitive", "never"),
    "cadence": ("every_turn", "session_end", "explicit"),
    "update": ("supersede", "branch", "ask"),
}


def behavior_from_template(name: str, revision: int = 1) -> dict:
    return {
        "schema": PROFILE_SCHEMA,
        "revision": revision,
        "template": name,
        **json.loads(json.dumps(BEHAVIOR_TEMPLATES[name])),
        "custom_exclude": [],
        "updated_at": None,
    }


async def _ensure(db: AsyncSession) -> None:
    from src.schema import require

    await require(db)


def _merge(stored: dict) -> dict:
    merged = json.loads(json.dumps(DEFAULT_PREFS))
    for key, value in (stored or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key].update({k: v for k, v in value.items() if k in merged[key]})
        elif key in merged:
            merged[key] = value
    if not isinstance(merged.get("behavior"), dict):
        merged["behavior"] = behavior_from_template("balanced")
    else:
        merged["behavior"] = {**behavior_from_template("balanced"), **merged["behavior"]}
    return merged


async def load_prefs(db: AsyncSession, tenant_id: str, username: str) -> dict:
    """Never raises: defaults when the table is unavailable."""
    try:
        await _ensure(db)
        row = (
            await db.execute(
                text(f"SELECT prefs FROM {PREFS} WHERE tenant_id = :t AND username = :u"),
                {"t": tenant_id, "u": username},
            )
        ).first()
    except Exception as exc:  # pragma: no cover - needs a database
        logger.info("User preferences unavailable: %s", exc)
        await db.rollback()
        return _merge({})
    stored = row[0] if row else {}
    return _merge(json.loads(stored) if isinstance(stored, str) else stored)


def _validate(p: dict) -> list[str]:
    errors = []
    if p["write"]["default_scope"] not in ("user", "project", "campaign", "role"):
        errors.append("Default scope must be user, project, campaign or role")
    if not (0 <= float(p["write"]["default_weight"]) <= 1):
        errors.append("Default weight must be between 0 and 1")
    if not (14 <= int(p["dreaming_fade_days"]) <= 365):
        errors.append("Fade after must be between 14 and 365 days")
    b = p["behavior"]
    if b.get("template") not in (*BEHAVIOR_TEMPLATES, "custom"):
        errors.append("Profile template must be balanced, conservative, proactive or custom")
    if not isinstance(b.get("include"), list) or any(c not in BEHAVIOR_CATEGORIES for c in b["include"]):
        errors.append(f"Profile categories must be among {', '.join(BEHAVIOR_CATEGORIES)}")
    if not isinstance(b.get("exclude"), list) or any(c not in BEHAVIOR_EXCLUDES for c in b["exclude"]):
        errors.append(f"Built-in exclusions must be among {', '.join(BEHAVIOR_EXCLUDES)}")
    custom = b.get("custom_exclude")
    if (
        not isinstance(custom, list)
        or len(custom) > 20
        or any(not isinstance(c, str) or not c.strip() or len(c) > 200 for c in custom)
    ):
        errors.append("Up to 20 custom exclusions of at most 200 characters")
    for field, allowed in BEHAVIOR_CHOICES.items():
        if b.get(field) not in allowed:
            errors.append(f"Profile {field} must be one of {', '.join(allowed)}")
    return errors


def _profile_body(b: dict) -> dict:
    return {k: v for k, v in b.items() if k not in ("revision", "updated_at", "schema")}


@router.get("/api/me/prefs")
async def get_prefs(db: DbDep, settings: SettingsDep, viewer: ViewerDep):
    acc = await access_for(db, settings, viewer)
    grants = acc.grants
    own = (
        await db.execute(
            select(func.count())
            .select_from(MemoryNode)
            .where(
                MemoryNode.tenant_id == settings.ui_tenant_id,
                MemoryNode.deleted_at.is_(None),
                MemoryNode.is_current.is_(True),
                MemoryNode.parent_id.is_(None),
                MemoryNode.scope == "user",
                MemoryNode.owner_id.in_(list(grants.identities) if grants else [viewer.username]),
            )
        )
    ).scalar_one()
    return {
        "prefs": await load_prefs(db, settings.ui_tenant_id, viewer.username),
        "profile": {
            "schema": PROFILE_SCHEMA,
            "templates": {k: behavior_from_template(k) for k in BEHAVIOR_TEMPLATES},
            "categories": list(BEHAVIOR_CATEGORIES),
            "excludes": list(BEHAVIOR_EXCLUDES),
            "choices": {k: list(v) for k, v in BEHAVIOR_CHOICES.items()},
            "applied_by": [],  # no host applies the profile yet (R1-018/019)
        },
        "account": {
            "username": viewer.username,
            "name": viewer.name,
            "email": viewer.email,
            "role": viewer.role,
            "source": viewer.source,
            "agents": sorted(grants.agents) if grants else [],
            "projects": sorted(grants.projects) if grants else [],
            "roles": sorted(grants.roles) if grants else [],
            "own_memories": own,
        },
    }


class PrefsUpdate(BaseModel):
    write: dict | None = None
    privacy: dict | None = None
    dreaming_fade_days: int | None = Field(default=None, ge=14, le=365)
    onboarding_dismissed: bool | None = None
    behavior: dict | None = None


@router.put("/api/me/prefs")
async def put_prefs(body: PrefsUpdate, db: DbDep, settings: SettingsDep, viewer: ViewerDep):
    if viewer.source == "anonymous" and viewer.role == "operator":
        raise HTTPException(status_code=403, detail="Sign in to save preferences")
    prefs = await load_prefs(db, settings.ui_tenant_id, viewer.username)
    before = json.loads(json.dumps(prefs["behavior"]))
    for key, value in body.model_dump(exclude_none=True).items():
        if isinstance(value, dict):
            prefs[key].update(
                {k: v for k, v in value.items() if k in prefs[key] and k not in ("schema", "revision", "updated_at")}
            )
        else:
            prefs[key] = value
    if body.behavior is not None and _profile_body(prefs["behavior"]) != _profile_body(before):
        prefs["behavior_history"] = ([before] + list(prefs.get("behavior_history") or []))[:5]
        prefs["behavior"]["revision"] = int(before.get("revision") or 1) + 1
        prefs["behavior"]["updated_at"] = now_utc().isoformat()
    errors = _validate(prefs)
    if errors:
        raise HTTPException(status_code=422, detail="; ".join(errors))
    await _ensure(db)
    await db.execute(
        text(
            f"""
            INSERT INTO {PREFS} (tenant_id, username, prefs) VALUES (:t, :u, CAST(:p AS JSONB))
            ON CONFLICT (tenant_id, username) DO UPDATE SET prefs = EXCLUDED.prefs, updated_at = now()
            """
        ),
        {"t": settings.ui_tenant_id, "u": viewer.username, "p": json.dumps(prefs)},
    )
    await audit(
        db,
        tenant_id=settings.ui_tenant_id,
        viewer=viewer,
        event_type="prefs.update",
        scope="user",
        owner_id=viewer.username,
        memory_id=None,
        metadata={
            "privacy": prefs["privacy"],
            "behavior_profile": {
                "schema": PROFILE_SCHEMA,
                "revision": prefs["behavior"]["revision"],
                "template": prefs["behavior"]["template"],
            },
        },
    )
    await db.commit()
    return {"prefs": prefs}


@router.get("/api/me/reads")
async def who_read_my_memories(
    db: DbDep,
    settings: SettingsDep,
    viewer: ViewerDep,
    days: int = Query(default=30, ge=1, le=400),
    who: str = Query(default="others", pattern="^(others|all)$"),
):
    """Who touched the memories you own (your user-scope memories and your agents')."""
    acc = await access_for(db, settings, viewer)
    mine = list(acc.grants.identities) if acc.grants else [viewer.username]
    since = now_utc() - timedelta(days=days)
    where = [
        AuditLog.tenant_id == settings.ui_tenant_id,
        AuditLog.timestamp >= since,
        MemoryNode.scope == "user",
        MemoryNode.owner_id.in_(mine),
    ]
    if who == "others":
        where.append(AuditLog.actor_id.not_in(mine))
    rows = (
        await db.execute(
            select(AuditLog, MemoryNode)
            .join(MemoryNode, and_(MemoryNode.id == AuditLog.memory_id, MemoryNode.tenant_id == settings.ui_tenant_id))
            .where(*where)
            .order_by(AuditLog.timestamp.desc())
            .limit(300)
        )
    ).all()
    readers: dict[str, dict] = {}
    memories: dict[str, dict] = defaultdict(lambda: {"count": 0})
    for event, memory in rows:
        r = readers.setdefault(
            event.actor_id,
            {
                "actor_id": event.actor_id,
                "driver_id": event.driver_id,
                "count": 0,
                "last": event.timestamp,
                "kinds": set(),
                "denied": 0,
                "yours": event.actor_id in mine,
                "via_dashboard": False,
            },
        )
        r["count"] += 1
        r["kinds"].add(event.event_type)
        r["denied"] += 1 if event.decision == "denied" else 0
        r["via_dashboard"] = r["via_dashboard"] or (event.event_metadata or {}).get("via") == "dashboard"
        m = memories[str(memory.id)]
        m.update(id=str(memory.id), stub=clean_stub(memory.stub), scope=memory.scope)
        m["count"] += 1
    events = [
        {
            "id": event.id,
            "timestamp": event.timestamp,
            "event_type": event.event_type,
            "actor_id": event.actor_id,
            "driver_id": event.driver_id,
            "decision": event.decision,
            "memory_id": str(memory.id),
            "memory_stub": clean_stub(memory.stub),
            "yours": event.actor_id in mine,
            "break_glass": bool((event.event_metadata or {}).get("break_glass")),
        }
        for event, memory in rows[:60]
    ]
    return {
        "days": days,
        "who": who,
        "identities": sorted(mine),
        "total": len(rows),
        "readers": sorted(
            ({**r, "kinds": sorted(r["kinds"])} for r in readers.values()), key=lambda r: (-r["count"], r["actor_id"])
        ),
        "top_memories": sorted(memories.values(), key=lambda m: -m["count"])[:8],
        "events": events,
        "scopes": SCOPES,
    }


@router.get("/api/me/onboarding")
async def onboarding(db: DbDep, settings: SettingsDep, viewer: ViewerDep):
    """Getting-started checklist for a user who is new to MemoryHub."""
    tenant_id = settings.ui_tenant_id
    acc = await access_for(db, settings, viewer)
    mine = list(acc.grants.identities) if acc.grants else [viewer.username]
    agents = sorted(acc.grants.agents) if acc.grants else []
    own = (
        await db.execute(
            select(func.count())
            .select_from(MemoryNode)
            .where(
                MemoryNode.tenant_id == tenant_id,
                MemoryNode.deleted_at.is_(None),
                MemoryNode.scope == "user",
                MemoryNode.owner_id.in_(mine),
            )
        )
    ).scalar_one()
    searched = (
        await db.execute(
            select(AuditLog.id)
            .where(AuditLog.tenant_id == tenant_id, AuditLog.event_type == "memory.search", AuditLog.actor_id.in_(mine))
            .limit(1)
        )
    ).first() is not None

    async def has_row(table: str, column: str) -> bool:
        try:
            row = (
                await db.execute(
                    text(f"SELECT 1 FROM {table} WHERE tenant_id = :t AND {column} = :u LIMIT 1"),
                    {"t": tenant_id, "u": viewer.username},
                )
            ).first()
            return row is not None
        except Exception:  # table not created yet
            await db.rollback()
            return False

    prefs = await load_prefs(db, tenant_id, viewer.username)
    steps = [
        {
            "id": "agent",
            "title": "Link an agent",
            "body": "Memories are written by agents. Link the agents you use so their memories count as yours.",
            "href": "/identities",
            "done": bool(agents) or not viewer.restricted,
        },
        {
            "id": "verify",
            "title": "Check the connection",
            "body": "Run the connection check: endpoint, sign-in, identity, project and a write-and-read round-trip.",
            "href": "/verify",
            "done": await has_row("memoryhub_ui_verify_results", "owner"),
        },
        {
            "id": "memory",
            "title": "Get your first memory",
            "body": "Let an agent call write_memory, or write one yourself in the Memory browser.",
            "href": "/memories",
            "done": own > 0,
        },
        {
            "id": "search",
            "title": "See what agents get back",
            "body": "Run a query in the Search playground to see exactly what an agent would receive.",
            "href": "/search",
            "done": searched,
        },
        {
            "id": "prefs",
            "title": "Set your defaults and privacy",
            "body": "Default scope and weight for new memories, and who may build on yours.",
            "href": "/preferences",
            "done": await has_row(PREFS, "username"),
        },
    ]
    if settings.ui_labs:
        steps += [
            {
                "id": "knowledge",
                "title": "Open your knowledge page",
                "body": "A summary of what memory knows about you, citing every memory it uses.",
                "href": "/knowledge",
                "done": await has_row("memoryhub_ui_knowledge", "owner"),
            },
            {
                "id": "dream",
                "title": "Run memory hygiene",
                "body": "Finds duplicates, missing links, stale memories and contradictions in what you can read.",
                "href": "/hygiene",
                "done": await has_row("memoryhub_ui_dreams", "owner"),
            },
        ]
    return {
        "steps": steps,
        "done": sum(1 for s in steps if s["done"]),
        "total": len(steps),
        "dismissed": bool(prefs.get("onboarding_dismissed")),
    }
