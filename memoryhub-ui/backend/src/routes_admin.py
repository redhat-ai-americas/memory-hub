"""Dashboard endpoints for governance and access screens: projects and
campaigns, identities, credentials, curation rule testing, the review queue,
audit and forensics, tenant settings and the development login.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from collections import Counter, defaultdict
from datetime import UTC, date, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from memoryhub_core.models.audit import AuditLog
from memoryhub_core.models.campaign import Campaign, CampaignMembership
from memoryhub_core.models.contradiction import ContradictionReport
from memoryhub_core.models.curation import CuratorRule
from memoryhub_core.models.memory import MemoryNode, MemoryRelationship
from memoryhub_core.models.project import Project, ProjectMembership
from memoryhub_core.models.role import RoleAssignment
from pydantic import BaseModel, Field
from sqlalchemy import and_, false, func, literal_column, or_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.access import ViewerDep, access_for, admin_viewer
from src.config import Settings, get_settings
from src.database import get_db
from src.routes_dashboard import _auth_clients, _event_row, _load_memory, _review_counts, tool_name
from src.ui_common import (
    DEFAULT_TENANT_SETTINGS,
    SCOPES,
    SESSION_COOKIE,
    VIEW_AS_COOKIE,
    audit,
    auth_enabled,
    clean_stub,
    cosine,
    embed,
    live_filters,
    load_tenant_settings,
    make_session_cookie,
    make_view_as_cookie,
    now_utc,
    parse_uuid,
    real_viewer,
    save_tenant_settings,
    viewer_from_request,
)

logger = logging.getLogger(__name__)
router = APIRouter()

DbDep = Annotated[AsyncSession, Depends(get_db)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


# ---------------------------------------------------------------------------
# Auth (screen 13)
# ---------------------------------------------------------------------------


class LoginRequest(BaseModel):
    # Local account sign-in
    login: str | None = Field(default=None, max_length=320)
    password: str | None = Field(default=None, max_length=256)
    # Development API-key sign-in
    api_key: str | None = Field(default=None, max_length=1024)
    username: str | None = Field(default=None, max_length=255)
    role: str = Field(default="admin", pattern="^(admin|user)$")


@router.get("/api/auth/status")
async def auth_status(request: Request, db: DbDep, settings: SettingsDep):
    viewer = viewer_from_request(request, settings)
    if viewer.source == "oauth-proxy":
        mode = "oauth-proxy"
    elif settings.ui_local_accounts:
        mode = "accounts"
    elif settings.ui_dev_api_key:
        mode = "api-key"
    else:
        mode = "open"
    body = {
        "mode": mode,
        "authenticated": mode in ("open", "oauth-proxy") or viewer.source in ("api-key", "account"),
        "api_key_login": bool(settings.ui_dev_api_key),
        "local_accounts": settings.ui_local_accounts,
        "user": viewer.username if viewer.source != "anonymous" else None,
        "role": viewer.role,
        "cluster_domain": settings.cluster_domain or None,
        "setup_required": False,
        "test_mode": settings.ui_test_mode,
    }
    if settings.ui_local_accounts and viewer.source != "oauth-proxy":
        from src.accounts import accounts_status

        body.update(await accounts_status(db, settings))
    return body


@router.post("/api/auth/login")
async def login(body: LoginRequest, response: Response, db: DbDep, settings: SettingsDep):
    import hmac

    if body.password is not None:
        if not settings.ui_local_accounts:
            raise HTTPException(status_code=404, detail="Password sign-in is disabled on this deployment")
        from src.accounts import password_login

        return await password_login(db, settings, response, body.login or body.username or "", body.password)
    if not settings.ui_dev_api_key:
        raise HTTPException(status_code=404, detail="API-key login is disabled on this deployment")
    if not hmac.compare_digest(body.api_key or "", settings.ui_dev_api_key):
        raise HTTPException(status_code=401, detail="That API key is not valid for this dashboard")
    username = (body.username or "dev-operator").strip() or "dev-operator"
    response.set_cookie(
        SESSION_COOKIE,
        make_session_cookie(username, settings, role=body.role, source="api-key"),
        httponly=True,
        samesite="lax",
        max_age=12 * 3600,
    )
    return {"ok": True, "user": username, "role": body.role}


OAUTH_PROXY_COOKIE = "_oauth_proxy"


def _openshift_logout_url(request: Request, settings: Settings) -> str | None:
    """OpenShift OAuth server logout, so the next visit asks for credentials again."""
    if settings.ui_oauth_logout_url:
        return settings.ui_oauth_logout_url
    host = (request.headers.get("x-forwarded-host") or request.headers.get("host") or "").split(",")[0].strip()
    marker = host.find(".apps.")
    if marker < 0:
        return None
    return f"https://oauth-openshift{host[marker:]}/logout"


@router.post("/api/auth/logout")
async def logout(request: Request, response: Response, settings: SettingsDep):
    """End the dashboard session completely and say where the browser goes next.

    Clears the dashboard session cookie and the OAuth proxy cookie. Behind the
    OpenShift OAuth proxy the browser is then sent to the OpenShift OAuth
    server's logout, otherwise to the dashboard's sign-in page.
    """
    viewer = real_viewer(request, settings)
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(OAUTH_PROXY_COOKIE, path="/")
    response.delete_cookie(VIEW_AS_COOKIE, path="/")
    body: dict = {"ok": True, "redirect": "/#/login?signed_out=1", "method": "GET", "fields": {}}
    if viewer.source == "oauth-proxy":
        host = (request.headers.get("x-forwarded-host") or request.headers.get("host") or "").split(",")[0].strip()
        back = f"https://{host}/" if host else "/"
        logout_url = _openshift_logout_url(request, settings)
        if logout_url:
            # The OpenShift OAuth server only accepts POST on /logout (a GET
            # answers "Method Not Allowed"); the browser submits a form.
            body.update(redirect=logout_url, method="POST", fields={"then": back})
        else:
            body.update(redirect="/oauth/sign_in")
    return body


# ---------------------------------------------------------------------------
# Test-mode account switcher
# ---------------------------------------------------------------------------


class SwitchRequest(BaseModel):
    username: str | None = Field(default=None, max_length=255)
    role: str | None = Field(default=None, pattern="^(admin|superuser|user|operator)$")


def _switch_allowed(request: Request, settings: Settings):
    if not settings.ui_test_mode:
        raise HTTPException(status_code=404, detail="The account switcher is only available in test mode")
    real = real_viewer(request, settings)
    if real.source == "anonymous" and auth_enabled(settings):
        raise HTTPException(status_code=401, detail="Log in to the dashboard first")
    return real


ROLE_NAMES = {"admin": "platform admin", "superuser": "super-user", "user": "user", "operator": "open mode"}


@router.get("/api/auth/switch")
async def switch_targets(request: Request, db: DbDep, settings: SettingsDep):
    """Identities the signed-in tester can view the dashboard as."""
    if not settings.ui_test_mode:
        return {"enabled": False, "targets": []}
    real = _switch_allowed(request, settings)
    current = viewer_from_request(request, settings)
    targets: list[dict] = []

    def add(username: str, role: str, label: str, note: str | None = None) -> None:
        if any(t["username"] == username and t["role"] == role for t in targets):
            return
        targets.append({"username": username, "role": role, "label": label, "note": note})

    add(real.username, "user", f"{real.username} · user", "your own identity")
    add(real.username, "admin", f"{real.username} · platform admin", "your own identity")
    add(real.username, "superuser", f"{real.username} · super-user", "admin + incident access to user memories")
    if real.source == "anonymous":
        add(real.username, "operator", "Open mode operator", "sees everything (development)")
    try:
        owners = (
            await db.execute(
                select(MemoryNode.owner_id, func.count())
                .where(*live_filters(settings.ui_tenant_id), MemoryNode.scope == "user", MemoryNode.parent_id.is_(None))
                .group_by(MemoryNode.owner_id)
                .order_by(func.count().desc())
                .limit(8)
            )
        ).all()
        for owner, count in owners:
            add(owner, "user", f"{owner} · user", f"{count} user memories")
        if settings.ui_local_accounts:
            from src.accounts import ACCOUNTS, ensure_tables

            await ensure_tables(db)
            rows = (
                await db.execute(
                    text(
                        f"SELECT username, role FROM {ACCOUNTS} WHERE tenant_id = :t AND status = 'active' "
                        "ORDER BY role, username LIMIT 20"
                    ),
                    {"t": settings.ui_tenant_id},
                )
            ).all()
            for username, role in rows:
                add(
                    username,
                    role,
                    f"{username} · {ROLE_NAMES.get(role, role)}",
                    "dashboard account",
                )
    except Exception as exc:  # pragma: no cover - needs a database
        logger.warning("Switch targets unavailable: %s", exc)
        await db.rollback()
    return {
        "enabled": True,
        "real": {"username": real.username, "role": real.role},
        "current": {"username": current.username, "role": current.role},
        "targets": targets,
    }


@router.post("/api/auth/switch")
async def switch_account(body: SwitchRequest, request: Request, response: Response, settings: SettingsDep):
    real = _switch_allowed(request, settings)
    if not body.username or not body.role:
        response.delete_cookie(VIEW_AS_COOKIE, path="/")
        return {"ok": True, "username": real.username, "role": real.role}
    response.set_cookie(
        VIEW_AS_COOKIE,
        make_view_as_cookie(body.username.strip(), body.role, settings),
        httponly=True,
        samesite="lax",
        max_age=12 * 3600,
        path="/",
    )
    logger.info("Test mode: %s now views the dashboard as %s (%s)", real.username, body.username, body.role)
    return {"ok": True, "username": body.username.strip(), "role": body.role}


# ---------------------------------------------------------------------------
# Projects & campaigns (screen 06)
# ---------------------------------------------------------------------------


class ProjectRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    description: str | None = None
    invite_only: bool = False


class ProjectUpdate(BaseModel):
    description: str | None = None
    invite_only: bool | None = None


class MemberRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=255)
    role: str = Field(default="member", pattern="^(member|admin)$")


class CampaignRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    default_ttl_days: int | None = Field(default=None, ge=1, le=3650)
    projects: list[str] = []


class CampaignUpdate(BaseModel):
    description: str | None = None
    status: str | None = Field(default=None, pattern="^(active|completed|archived)$")
    default_ttl_days: int | None = Field(default=None, ge=1, le=3650)


class EnrollRequest(BaseModel):
    project_id: str = Field(min_length=1)


async def _project_stats(db: AsyncSession, tenant_id: str, names: list[str]) -> dict[str, dict]:
    stats: dict[str, dict] = {n: {"memories": 0, "last_write": None, "members": 0, "campaigns": []} for n in names}
    if not names:
        return stats
    for name, count, last in (
        await db.execute(
            select(MemoryNode.scope_id, func.count(), func.max(MemoryNode.updated_at))
            .where(*live_filters(tenant_id), MemoryNode.scope == "project", MemoryNode.scope_id.in_(names))
            .group_by(MemoryNode.scope_id)
        )
    ).all():
        stats[name]["memories"], stats[name]["last_write"] = count, last
    for name, count in (
        await db.execute(
            select(ProjectMembership.project_id, func.count())
            .where(ProjectMembership.project_id.in_(names))
            .group_by(ProjectMembership.project_id)
        )
    ).all():
        stats[name]["members"] = count
    for project_id, cid, cname, cstatus in (
        await db.execute(
            select(CampaignMembership.project_id, Campaign.id, Campaign.name, Campaign.status)
            .join(Campaign, Campaign.id == CampaignMembership.campaign_id)
            .where(CampaignMembership.project_id.in_(names), Campaign.tenant_id == tenant_id)
        )
    ).all():
        stats[project_id]["campaigns"].append({"id": str(cid), "name": cname, "status": cstatus})
    return stats


@router.get("/api/projects")
async def list_projects(request: Request, db: DbDep, settings: SettingsDep, mine: bool = Query(default=False)):
    tenant_id = settings.ui_tenant_id
    viewer = viewer_from_request(request, settings)
    stmt = select(Project).where(Project.tenant_id == tenant_id).order_by(Project.name)
    if mine:
        stmt = stmt.where(
            Project.name.in_(select(ProjectMembership.project_id).where(ProjectMembership.user_id == viewer.username))
        )
    projects = (await db.execute(stmt)).scalars().all()
    stats = await _project_stats(db, tenant_id, [p.name for p in projects])
    total = (
        await db.execute(select(func.count()).select_from(Project).where(Project.tenant_id == tenant_id))
    ).scalar_one()
    campaigns = (
        await db.execute(select(func.count()).select_from(Campaign).where(Campaign.tenant_id == tenant_id))
    ).scalar_one()
    rows = [
        {
            "name": p.name,
            "description": p.description,
            "invite_only": p.invite_only,
            "created_at": p.created_at,
            "created_by": p.created_by,
            **stats[p.name],
        }
        for p in projects
    ]
    rows.sort(key=lambda r: r["last_write"] or r["created_at"], reverse=True)
    return {"items": rows, "total": total, "campaign_total": campaigns, "viewer": viewer.username}


async def _project_teams(db: AsyncSession, tenant_id: str, name: str) -> list[dict]:
    from src.teams import teams_for_project

    try:
        return await teams_for_project(db, tenant_id, name)
    except Exception as exc:  # pragma: no cover - needs a database
        logger.info("Teams unavailable: %s", exc)
        await db.rollback()
        return []


@router.get("/api/projects/{name}")
async def project_detail(name: str, db: DbDep, settings: SettingsDep):
    tenant_id = settings.ui_tenant_id
    project = (
        await db.execute(select(Project).where(Project.name == name, Project.tenant_id == tenant_id))
    ).scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=404, detail=f"Project {name!r} not found")
    stats = (await _project_stats(db, tenant_id, [name]))[name]
    members = (
        (
            await db.execute(
                select(ProjectMembership)
                .where(ProjectMembership.project_id == name)
                .order_by(ProjectMembership.joined_at)
            )
        )
        .scalars()
        .all()
    )
    today = now_utc().replace(hour=0, minute=0, second=0, microsecond=0)
    agents_today = (
        await db.execute(
            select(func.count(func.distinct(AuditLog.actor_id))).where(
                AuditLog.tenant_id == tenant_id,
                AuditLog.timestamp >= today,
                or_(AuditLog.owner_id == name, AuditLog.event_metadata["project_id"].astext == name),
            )
        )
    ).scalar_one()

    focus = None
    tenant_settings = await load_tenant_settings(db, tenant_id)
    if settings.valkey_url:
        try:
            from memoryhub_core.config import ValkeySettings
            from memoryhub_core.services.valkey_client import ValkeyClient

            client = ValkeyClient(ValkeySettings(url=settings.valkey_url))
            end = date.today()
            entries = await client.read_focus_history(name, end - timedelta(days=29), end)
            counts = Counter((e.get("focus") or "").strip() for e in entries if e.get("focus"))
            focus = [{"focus": f, "count": c} for f, c in counts.most_common(8)]
        except Exception as exc:
            logger.info("Focus history unavailable for %s: %s", name, exc)
            focus = None

    retrieval = tenant_settings["retrieval"]
    policy = (
        "memory_loading:\n"
        "  pattern: session_start\n"
        "  focus_source: git_branch\n"
        "retrieval_defaults:\n"
        f"  max_results: {retrieval['max_results']}\n"
        f"  session_focus_weight: {retrieval['session_focus_weight']}\n"
        "  mode: full"
    )
    return {
        "name": project.name,
        "description": project.description,
        "invite_only": project.invite_only,
        "created_at": project.created_at,
        "created_by": project.created_by,
        **stats,
        "agents_today": agents_today,
        "members_list": [
            {
                "user_id": m.user_id,
                "role": m.role,
                "joined_at": m.joined_at,
                "joined_by": m.joined_by,
                "via_team": (m.joined_by or "")[5:] if (m.joined_by or "").startswith("team:") else None,
            }
            for m in members
        ],
        "teams": await _project_teams(db, tenant_id, name),
        "focus_history": focus,
        "focus_available": focus is not None,
        "loading_policy": policy,
    }


@router.post("/api/projects", status_code=201)
async def create_project(body: ProjectRequest, request: Request, db: DbDep, settings: SettingsDep):
    viewer = viewer_from_request(request, settings)
    exists_ = (await db.execute(select(Project).where(Project.name == body.name))).scalar_one_or_none()
    if exists_ is not None:
        raise HTTPException(status_code=409, detail=f"Project {body.name!r} already exists")
    db.add(
        Project(
            name=body.name,
            description=body.description,
            invite_only=body.invite_only,
            tenant_id=settings.ui_tenant_id,
            created_by=viewer.username,
        )
    )
    await db.flush()
    db.add(ProjectMembership(project_id=body.name, user_id=viewer.username, role="admin", joined_by=viewer.username))
    await audit(
        db,
        tenant_id=settings.ui_tenant_id,
        viewer=viewer,
        event_type="project.create",
        scope="project",
        owner_id=body.name,
        memory_id=None,
        metadata={"invite_only": body.invite_only},
    )
    await db.commit()
    return {"name": body.name}


@router.patch("/api/projects/{name}")
async def update_project(name: str, body: ProjectUpdate, request: Request, db: DbDep, settings: SettingsDep):
    viewer = viewer_from_request(request, settings)
    project = (
        await db.execute(select(Project).where(Project.name == name, Project.tenant_id == settings.ui_tenant_id))
    ).scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=404, detail=f"Project {name!r} not found")
    changes = body.model_dump(exclude_unset=True)
    for key, value in changes.items():
        setattr(project, key, value)
    await audit(
        db,
        tenant_id=settings.ui_tenant_id,
        viewer=viewer,
        event_type="project.update",
        scope="project",
        owner_id=name,
        memory_id=None,
        metadata=changes,
    )
    await db.commit()
    return {"name": name}


@router.post("/api/projects/{name}/members", status_code=201)
async def add_member(name: str, body: MemberRequest, request: Request, db: DbDep, settings: SettingsDep):
    viewer = viewer_from_request(request, settings)
    project = (
        await db.execute(select(Project).where(Project.name == name, Project.tenant_id == settings.ui_tenant_id))
    ).scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=404, detail=f"Project {name!r} not found")
    db.add(ProjectMembership(project_id=name, user_id=body.user_id, role=body.role, joined_by=viewer.username))
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail=f"{body.user_id} is already a member") from None
    await audit(
        db,
        tenant_id=settings.ui_tenant_id,
        viewer=viewer,
        event_type="project.member_added",
        scope="project",
        owner_id=name,
        memory_id=None,
        metadata={"user_id": body.user_id, "role": body.role},
    )
    await db.commit()
    return {"ok": True}


@router.delete("/api/projects/{name}/members/{user_id}", status_code=204)
async def remove_member(name: str, user_id: str, request: Request, db: DbDep, settings: SettingsDep):
    viewer = viewer_from_request(request, settings)
    membership = (
        await db.execute(
            select(ProjectMembership)
            .join(Project, Project.name == ProjectMembership.project_id)
            .where(
                ProjectMembership.project_id == name,
                ProjectMembership.user_id == user_id,
                Project.tenant_id == settings.ui_tenant_id,
            )
        )
    ).scalar_one_or_none()
    if membership is None:
        raise HTTPException(status_code=404, detail="Membership not found")
    await db.delete(membership)
    await audit(
        db,
        tenant_id=settings.ui_tenant_id,
        viewer=viewer,
        event_type="project.member_removed",
        scope="project",
        owner_id=name,
        memory_id=None,
        metadata={"user_id": user_id},
    )
    await db.commit()


def _campaign_row(c: Campaign, projects: list[str], memories: int) -> dict:
    return {
        "id": str(c.id),
        "name": c.name,
        "description": c.description,
        "status": c.status,
        "default_ttl_days": c.default_ttl.days if c.default_ttl else None,
        "projects": projects,
        "memories": memories,
        "created_at": c.created_at,
        "updated_at": c.updated_at,
    }


@router.get("/api/campaigns")
async def list_campaigns(db: DbDep, settings: SettingsDep):
    tenant_id = settings.ui_tenant_id
    campaigns = (
        (await db.execute(select(Campaign).where(Campaign.tenant_id == tenant_id).order_by(Campaign.created_at.desc())))
        .scalars()
        .all()
    )
    ids = [c.id for c in campaigns]
    projects: dict[uuid.UUID, list[str]] = defaultdict(list)
    if ids:
        for cid, pid in (
            await db.execute(
                select(CampaignMembership.campaign_id, CampaignMembership.project_id).where(
                    CampaignMembership.campaign_id.in_(ids)
                )
            )
        ).all():
            projects[cid].append(pid)
    keys = [str(c.id) for c in campaigns] + [c.name for c in campaigns]
    mem_counts: dict[str, int] = {}
    if keys:
        mem_counts = {
            row[0]: row[1]
            for row in (
                await db.execute(
                    select(MemoryNode.scope_id, func.count())
                    .where(*live_filters(tenant_id), MemoryNode.scope == "campaign", MemoryNode.scope_id.in_(keys))
                    .group_by(MemoryNode.scope_id)
                )
            ).all()
        }
    return {
        "items": [
            _campaign_row(c, projects.get(c.id, []), mem_counts.get(str(c.id), 0) + mem_counts.get(c.name, 0))
            for c in campaigns
        ]
    }


@router.post("/api/campaigns", status_code=201, dependencies=[Depends(admin_viewer)])
async def create_campaign(body: CampaignRequest, request: Request, db: DbDep, settings: SettingsDep):
    viewer = viewer_from_request(request, settings)
    campaign = Campaign(
        name=body.name,
        description=body.description,
        status="active",
        tenant_id=settings.ui_tenant_id,
        default_ttl=timedelta(days=body.default_ttl_days) if body.default_ttl_days else None,
    )
    db.add(campaign)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail=f"Campaign {body.name!r} already exists") from None
    for project_id in body.projects:
        db.add(CampaignMembership(campaign_id=campaign.id, project_id=project_id, enrolled_by=viewer.username))
    await audit(
        db,
        tenant_id=settings.ui_tenant_id,
        viewer=viewer,
        event_type="campaign.create",
        scope="campaign",
        owner_id=str(campaign.id),
        memory_id=None,
        metadata={"name": body.name},
    )
    await db.commit()
    return {"id": str(campaign.id)}


@router.patch("/api/campaigns/{campaign_id}", dependencies=[Depends(admin_viewer)])
async def update_campaign(campaign_id: str, body: CampaignUpdate, request: Request, db: DbDep, settings: SettingsDep):
    viewer = viewer_from_request(request, settings)
    campaign = (
        await db.execute(
            select(Campaign).where(Campaign.id == parse_uuid(campaign_id), Campaign.tenant_id == settings.ui_tenant_id)
        )
    ).scalar_one_or_none()
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    changes = body.model_dump(exclude_unset=True)
    if "default_ttl_days" in changes:
        days = changes.pop("default_ttl_days")
        campaign.default_ttl = timedelta(days=days) if days else None
    for key, value in changes.items():
        setattr(campaign, key, value)
    await audit(
        db,
        tenant_id=settings.ui_tenant_id,
        viewer=viewer,
        event_type="campaign.update",
        scope="campaign",
        owner_id=campaign_id,
        memory_id=None,
        metadata=body.model_dump(exclude_unset=True),
    )
    await db.commit()
    return {"id": campaign_id}


@router.post("/api/campaigns/{campaign_id}/projects", status_code=201, dependencies=[Depends(admin_viewer)])
async def enroll_project(campaign_id: str, body: EnrollRequest, request: Request, db: DbDep, settings: SettingsDep):
    viewer = viewer_from_request(request, settings)
    campaign = (
        await db.execute(
            select(Campaign).where(Campaign.id == parse_uuid(campaign_id), Campaign.tenant_id == settings.ui_tenant_id)
        )
    ).scalar_one_or_none()
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    db.add(CampaignMembership(campaign_id=campaign.id, project_id=body.project_id, enrolled_by=viewer.username))
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Project already enrolled") from None
    await audit(
        db,
        tenant_id=settings.ui_tenant_id,
        viewer=viewer,
        event_type="campaign.enroll",
        scope="campaign",
        owner_id=campaign_id,
        memory_id=None,
        metadata={"project_id": body.project_id},
    )
    await db.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Users & agents (screen 07)
# ---------------------------------------------------------------------------

TIER_KEYS = {"organizational": "organizational", "enterprise": "enterprise"}


def _scope_matrix(scopes: list[str]) -> list[dict]:
    s = set(scopes)
    admin = "memory:admin" in s
    rows = []
    for tier in SCOPES:
        read = admin or "memory:read" in s or f"memory:read:{tier}" in s
        write = admin or "memory:write" in s or f"memory:write:{tier}" in s
        approve = admin or "memory:approve:enterprise" in s
        if tier == "enterprise" and write and not approve:
            write_label = "via approval"
        else:
            write_label = "yes" if write else "no"
        rows.append({"tier": tier, "read": read, "write": write_label})
    return rows


async def _identity_rows(db: AsyncSession, settings: Settings) -> tuple[list[dict], bool]:
    tenant_id = settings.ui_tenant_id
    now = now_utc()
    clients = await _auth_clients(settings)
    owners = {
        row[0]: row[1]
        for row in (
            await db.execute(
                select(MemoryNode.owner_id, func.count())
                .where(*live_filters(tenant_id), MemoryNode.parent_id.is_(None), MemoryNode.scope == "user")
                .group_by(MemoryNode.owner_id)
            )
        ).all()
    }
    writers = {
        row[0]: row[1]
        for row in (
            await db.execute(
                select(MemoryNode.actor_id, func.count())
                .where(*live_filters(tenant_id), MemoryNode.actor_id.is_not(None), MemoryNode.parent_id.is_(None))
                .group_by(MemoryNode.actor_id)
            )
        ).all()
    }
    # Agent → human binding: the driver an actor most often acts for.
    bindings: dict[str, str] = {}
    for actor, driver, _ in (
        await db.execute(
            select(AuditLog.actor_id, AuditLog.driver_id, func.count())
            .where(AuditLog.tenant_id == tenant_id, AuditLog.driver_id != AuditLog.actor_id)
            .group_by(AuditLog.actor_id, AuditLog.driver_id)
            .order_by(func.count())
        )
    ).all():
        bindings[actor] = driver
    for actor, driver in (
        await db.execute(
            select(MemoryNode.actor_id, MemoryNode.driver_id)
            .where(
                MemoryNode.tenant_id == tenant_id,
                MemoryNode.actor_id.is_not(None),
                MemoryNode.driver_id.is_not(None),
                MemoryNode.actor_id != MemoryNode.driver_id,
            )
            .distinct()
        )
    ).all():
        bindings.setdefault(actor, driver)
    last_seen = {
        row[0]: row[1]
        for row in (
            await db.execute(
                select(AuditLog.actor_id, func.max(AuditLog.timestamp))
                .where(AuditLog.tenant_id == tenant_id)
                .group_by(AuditLog.actor_id)
            )
        ).all()
    }
    last_write = {
        row[0]: row[1]
        for row in (
            await db.execute(
                select(func.coalesce(MemoryNode.actor_id, MemoryNode.owner_id), func.max(MemoryNode.updated_at))
                .where(MemoryNode.tenant_id == tenant_id)
                .group_by(func.coalesce(MemoryNode.actor_id, MemoryNode.owner_id))
            )
        ).all()
    }
    roles: dict[str, list[str]] = defaultdict(list)
    for user_id, role in (
        await db.execute(
            select(RoleAssignment.user_id, RoleAssignment.role_name).where(RoleAssignment.tenant_id == tenant_id)
        )
    ).all():
        roles[user_id].append(role)

    ids: dict[str, dict] = {}

    def add(identity_id: str, **values):
        row = ids.setdefault(
            identity_id,
            {
                "id": identity_id,
                "name": identity_id,
                "type": "user",
                "scopes": [],
                "client": False,
                "active": True,
                "public": False,
                "created_at": None,
            },
        )
        row.update({k: v for k, v in values.items() if v is not None})

    for c in clients or []:
        cid = c["client_id"]
        bound = bindings.get(cid)
        kind = (
            "service" if c.get("identity_type") == "service" else ("user agent" if bound and bound != cid else "user")
        )
        add(
            cid,
            name=c.get("client_name") or cid,
            type=kind,
            scopes=c.get("default_scopes") or [],
            client=True,
            active=c.get("active", True),
            public=c.get("public", False),
            created_at=c.get("created_at"),
        )
    for identity_id in set(owners) | set(writers) | set(bindings.values()) | set(roles):
        if identity_id in ids:
            continue
        bound = bindings.get(identity_id)
        add(identity_id, type="user agent" if bound and bound != identity_id else "user")
    from src.ownership import explicit_owners

    owners_by_client = await explicit_owners(db, tenant_id)
    rows = []
    for row in ids.values():
        identity_id = row["id"]
        seen = max(
            [d for d in (last_seen.get(identity_id), last_write.get(identity_id)) if d is not None], default=None
        )
        rows.append(
            {
                **row,
                "bound_to": bindings.get(identity_id) if row["type"] == "user agent" else None,
                "owner": owners_by_client.get(identity_id)
                or (bindings.get(identity_id) if row["type"] == "user agent" else None),
                "roles": sorted(roles.get(identity_id, [])),
                "memory_count": max(owners.get(identity_id, 0), writers.get(identity_id, 0)),
                "last_active": seen,
                "active_now": bool(
                    last_seen.get(identity_id) and last_seen[identity_id] >= now - timedelta(minutes=15)
                ),
            }
        )
    rows.sort(key=lambda r: (r["last_active"] is None, -(r["last_active"].timestamp() if r["last_active"] else 0)))
    return rows, clients is not None


async def _my_identities(db: AsyncSession, settings: Settings, request: Request) -> set[str] | None:
    """None for admins (everything); otherwise the viewer and their agents."""
    viewer = viewer_from_request(request, settings)
    if not viewer.restricted:
        return None
    acc = await access_for(db, settings, viewer)
    return acc.grants.identities if acc.grants else {viewer.username}


@router.get("/api/identities")
async def list_identities(request: Request, db: DbDep, settings: SettingsDep):
    rows, auth_ok = await _identity_rows(db, settings)
    mine = await _my_identities(db, settings, request)
    if mine is not None:
        viewer = viewer_from_request(request, settings)
        rows = [r for r in rows if r["id"] in mine]
        if not any(r["id"] == viewer.username for r in rows):
            rows.insert(
                0,
                {
                    "id": viewer.username,
                    "name": viewer.name,
                    "type": "user",
                    "scopes": [],
                    "client": False,
                    "active": True,
                    "public": False,
                    "created_at": None,
                    "bound_to": None,
                    "owner": None,
                    "roles": [],
                    "memory_count": 0,
                    "last_active": None,
                    "active_now": True,
                },
            )
        for r in rows:
            if r["id"] != viewer.username and r["type"] == "user":
                r["type"] = "user agent"
                r["bound_to"] = r.get("bound_to") or viewer.username
    role_filter = [RoleAssignment.user_id.in_(list(mine))] if mine is not None else []
    role_rows = (
        await db.execute(
            select(RoleAssignment.role_name, func.count())
            .where(RoleAssignment.tenant_id == settings.ui_tenant_id, *role_filter)
            .group_by(RoleAssignment.role_name)
            .order_by(RoleAssignment.role_name)
        )
    ).all()
    counts = Counter(r["type"] for r in rows)
    return {
        "items": rows,
        "auth_available": auth_ok,
        "roles": [{"name": r[0], "members": r[1]} for r in role_rows],
        "counts": {
            "all": len(rows),
            "users": counts.get("user", 0),
            "user_agents": counts.get("user agent", 0),
            "service_agents": counts.get("service", 0),
            "roles": len(role_rows),
        },
    }


@router.get("/api/identities/{identity_id}")
async def identity_detail(identity_id: str, request: Request, db: DbDep, settings: SettingsDep):
    mine = await _my_identities(db, settings, request)
    if mine is not None and identity_id not in mine:
        raise HTTPException(status_code=404, detail=f"Identity {identity_id!r} not found")
    rows, _ = await _identity_rows(db, settings)
    row = next((r for r in rows if r["id"] == identity_id), None)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Identity {identity_id!r} not found")
    since = now_utc() - timedelta(hours=24)
    stats = (
        await db.execute(
            select(
                func.count().filter(AuditLog.event_type == "memory.search"),
                func.count().filter(AuditLog.event_type.in_(("memory.write", "memory.update"))),
                func.count().filter(AuditLog.decision == "denied"),
                func.count(),
            ).where(
                AuditLog.tenant_id == settings.ui_tenant_id,
                AuditLog.actor_id == identity_id,
                AuditLog.timestamp >= since,
            )
        )
    ).one()
    hour_col = func.date_trunc(literal_column("'hour'"), AuditLog.timestamp).label("hour")
    hourly = (
        await db.execute(
            select(hour_col, func.count())
            .where(
                AuditLog.tenant_id == settings.ui_tenant_id,
                AuditLog.actor_id == identity_id,
                AuditLog.timestamp >= since,
            )
            .group_by(literal_column("hour"))
        )
    ).all()
    agents = [r for r in rows if r.get("bound_to") == identity_id]
    grant = "auth code + PKCE" if row.get("public") else ("client_credentials" if row.get("client") else None)
    return {
        **row,
        "grant": grant,
        "scope_matrix": _scope_matrix(row["scopes"]) if row["scopes"] else None,
        "activity_24h": {"searches": stats[0], "writes": stats[1], "denied": stats[2], "total": stats[3]},
        "hourly": [{"hour": h, "count": c} for h, c in hourly],
        "agents": [{"id": a["id"], "name": a["name"]} for a in agents],
    }


class LinkAgentRequest(BaseModel):
    client_id: str = Field(min_length=1, max_length=255)
    client_secret: str = Field(min_length=1, max_length=1024)


@router.post("/api/identities/link", status_code=201)
async def link_agent(body: LinkAgentRequest, request: Request, db: DbDep, settings: SettingsDep):
    """A user links an existing agent by proving they hold its client secret."""
    from src.ownership import explicit_owners, set_owner, verify_client_secret

    viewer = viewer_from_request(request, settings)
    if viewer.source == "anonymous":
        raise HTTPException(status_code=403, detail="Sign in to link an agent")
    current = (await explicit_owners(db, settings.ui_tenant_id)).get(body.client_id)
    if current and current != viewer.username:
        raise HTTPException(status_code=409, detail="That agent already belongs to someone else. Ask a platform admin.")
    if not await verify_client_secret(settings, body.client_id, body.client_secret):
        raise HTTPException(status_code=403, detail="The auth service did not accept that client ID and secret")
    await set_owner(db, settings.ui_tenant_id, body.client_id, viewer.username, viewer.username, "secret")
    await audit(
        db,
        tenant_id=settings.ui_tenant_id,
        viewer=viewer,
        event_type="agent.link",
        scope="session",
        owner_id=viewer.username,
        memory_id=None,
        metadata={"client_id": body.client_id},
    )
    await db.commit()
    return {"ok": True, "client_id": body.client_id, "owner": viewer.username}


class OwnerRequest(BaseModel):
    owner: str | None = Field(default=None, max_length=255)


@router.put("/api/identities/{identity_id}/owner", dependencies=[Depends(admin_viewer)])
async def assign_owner(identity_id: str, body: OwnerRequest, request: Request, db: DbDep, settings: SettingsDep):
    """Admin assigns (or clears) the person an agent belongs to."""
    from src.ownership import set_owner

    viewer = viewer_from_request(request, settings)
    owner = (body.owner or "").strip() or None
    await set_owner(db, settings.ui_tenant_id, identity_id, owner, viewer.username, "admin")
    await audit(
        db,
        tenant_id=settings.ui_tenant_id,
        viewer=viewer,
        event_type="agent.owner",
        scope="session",
        owner_id=owner or identity_id,
        memory_id=None,
        metadata={"client_id": identity_id, "owner": owner},
    )
    await db.commit()
    return {"ok": True, "client_id": identity_id, "owner": owner}


class RoleRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=255)
    role_name: str = Field(min_length=1, max_length=100)


@router.post("/api/roles", status_code=201, dependencies=[Depends(admin_viewer)])
async def assign_role(body: RoleRequest, request: Request, db: DbDep, settings: SettingsDep):
    viewer = viewer_from_request(request, settings)
    db.add(
        RoleAssignment(
            user_id=body.user_id, role_name=body.role_name, tenant_id=settings.ui_tenant_id, assigned_by=viewer.username
        )
    )
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Role already assigned") from None
    await audit(
        db,
        tenant_id=settings.ui_tenant_id,
        viewer=viewer,
        event_type="role.assign",
        scope="role",
        owner_id=body.role_name,
        memory_id=None,
        metadata={"user_id": body.user_id},
    )
    await db.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# OAuth clients & keys (screen 08)
# ---------------------------------------------------------------------------


@router.get("/api/credentials")
async def credentials(request: Request, db: DbDep, settings: SettingsDep):
    from src.routes import _admin_request

    tenant_id = settings.ui_tenant_id
    now = now_utc()
    clients = await _auth_clients(settings)
    last_used = {
        row[0]: row[1]
        for row in (
            await db.execute(
                select(AuditLog.actor_id, func.max(AuditLog.timestamp))
                .where(AuditLog.tenant_id == tenant_id)
                .group_by(AuditLog.actor_id)
            )
        ).all()
    }
    mine = await _my_identities(db, settings, request)
    if mine is not None and clients is not None:
        clients = [c for c in clients if c["client_id"] in mine]
    items = []
    for c in clients or []:
        used = last_used.get(c["client_id"])
        created = c.get("created_at")
        created_dt = datetime.fromisoformat(created.replace("Z", "+00:00")) if isinstance(created, str) else created
        if not c.get("active", True):
            status = "revoked"
        elif used is None and created_dt and created_dt >= now - timedelta(days=1):
            status = "new"
        elif used is not None and used < now - timedelta(days=30):
            status = "stale"
        else:
            status = "active"
        items.append(
            {
                **c,
                "grant": "auth code + PKCE" if c.get("public") else "client_credentials",
                "last_used": used,
                "status": status,
            }
        )
    items.sort(
        key=lambda c: (
            c["status"] != "new",
            c["status"] == "revoked",
            -(c["last_used"].timestamp() if c["last_used"] else 0),
        )
    )

    issuers = []
    metadata = None
    if settings.auth_service_url:
        try:
            resp = await _admin_request(settings, "GET", "/.well-known/oauth-authorization-server")
            metadata = resp.json()
        except Exception:
            metadata = None
    if metadata and "urn:ietf:params:oauth:grant-type:token-exchange" in metadata.get("grant_types_supported", []):
        issuers.append(
            {
                "name": "local-cluster",
                "kind": "Kubernetes",
                "description": ("Kubernetes · tenant from namespace annotation memoryhub.redhat.com/tenant-id"),
                "status": "active",
            }
        )
    if settings.trusted_issuers:
        try:
            extra = json.loads(settings.trusted_issuers)
            issuers.extend(i for i in extra if isinstance(i, dict) and i.get("name"))
        except json.JSONDecodeError:
            logger.warning("MEMORYHUB_TRUSTED_ISSUERS is not valid JSON")

    return {
        "auth_available": clients is not None,
        "issuer": metadata.get("issuer") if metadata else None,
        "clients": items,
        "api_keys": [c for c in items if not c.get("public")],
        "issuers": issuers,
    }


# ---------------------------------------------------------------------------
# Curation rules (screen 09)
# ---------------------------------------------------------------------------


class RuleTestRequest(BaseModel):
    tier: str = Field(pattern="^(regex|embedding|policy)$")
    sample: str = Field(min_length=1, max_length=20_000)
    pattern: str | None = None
    pattern_set: str | None = None
    reference: str | None = None
    threshold: float | None = Field(default=None, ge=0, le=1)
    action: str = "flag"


@router.post("/api/rules/test")
async def test_rule(body: RuleTestRequest, settings: SettingsDep):
    if body.tier == "regex":
        if body.pattern_set in ("secrets", "pii"):
            from memoryhub_core.services.curation.scanner import scan_content

            results = scan_content(body.sample, pattern_set=body.pattern_set)
            return {
                "matched": bool(results),
                "action": body.action,
                "matches": [{"name": r.pattern_name, "detail": r.detail} for r in results],
            }
        if not body.pattern:
            raise HTTPException(status_code=422, detail="pattern is required for a regex rule")
        try:
            compiled = re.compile(body.pattern)
        except re.error as exc:
            raise HTTPException(status_code=422, detail=f"Invalid regex: {exc}") from None
        matches = []
        for m in compiled.finditer(body.sample):
            line_start = body.sample.rfind("\n", 0, m.start()) + 1
            matches.append(
                {
                    "text": m.group(0),
                    "start": m.start(),
                    "col": m.start() - line_start,
                    "line": body.sample.count("\n", 0, m.start()) + 1,
                }
            )
            if len(matches) >= 20:
                break
        return {"matched": bool(matches), "action": body.action, "matches": matches}
    if body.tier == "embedding":
        if not body.reference:
            raise HTTPException(status_code=422, detail="reference text is required for an embedding rule")
        a = await embed(body.sample, settings.embedding_url)
        b = await embed(body.reference, settings.embedding_url)
        if a is None or b is None:
            raise HTTPException(
                status_code=503, detail="The embedding service is unavailable, so embedding rules cannot be tested"
            )
        score = cosine(a, b)
        threshold = body.threshold if body.threshold is not None else 0.92
        return {"matched": score >= threshold, "action": body.action, "score": round(score, 4), "threshold": threshold}
    raise HTTPException(status_code=422, detail="Policy rules are evaluated by the server and cannot be tested here")


@router.get("/api/rules/matches", dependencies=[Depends(admin_viewer)])
async def rule_matches(db: DbDep, settings: SettingsDep, days: int = Query(default=7, ge=1, le=90)):
    """Per-rule match counts over the last ``days`` days from the audit log.

    Counted from audit events whose metadata names the rule (``rule`` or
    ``rule_name``). Returns ``available: false`` when the MCP server does not
    record rule names yet, so the UI shows a dash instead of a false zero.
    """
    since = now_utc() - timedelta(days=days)
    rule_key = func.coalesce(AuditLog.event_metadata["rule"].astext, AuditLog.event_metadata["rule_name"].astext)
    rows = (
        await db.execute(
            select(rule_key, func.count())
            .where(AuditLog.tenant_id == settings.ui_tenant_id, AuditLog.timestamp >= since, rule_key.is_not(None))
            .group_by(rule_key)
        )
    ).all()
    return {"days": days, "available": bool(rows), "counts": {r[0]: r[1] for r in rows}}


@router.post("/api/rules/scan", dependencies=[Depends(admin_viewer)])
async def batch_scan(request: Request, db: DbDep, settings: SettingsDep):
    """Run enabled regex rules over current memories and flag matches.

    The curator agent runs the full scan (including embedding tiers); this
    dashboard trigger evaluates regex rules inline and records one audit
    event per match so the results show up in rule match counts.
    """
    from memoryhub_core.services.curation.scanner import scan_content, scan_with_custom_patterns

    viewer = viewer_from_request(request, settings)
    tenant_id = settings.ui_tenant_id
    rules = (
        (
            await db.execute(
                select(CuratorRule)
                .where(
                    CuratorRule.tenant_id == tenant_id,
                    CuratorRule.is_current.is_(True),
                    CuratorRule.enabled.is_(True),
                    CuratorRule.tier == "regex",
                )
                .order_by(CuratorRule.priority)
            )
        )
        .scalars()
        .all()
    )
    nodes = (
        (
            await db.execute(
                select(MemoryNode).where(*live_filters(tenant_id)).order_by(MemoryNode.updated_at.desc()).limit(5000)
            )
        )
        .scalars()
        .all()
    )
    hits = Counter()
    for node in nodes:
        for rule in rules:
            if rule.scope_filter and rule.scope_filter != node.scope:
                continue
            config = rule.config or {}
            if config.get("pattern_set") in ("secrets", "pii"):
                found = scan_content(node.content, pattern_set=config["pattern_set"])
            elif config.get("pattern"):
                found = scan_with_custom_patterns(node.content, {rule.name: config["pattern"]})
            else:
                found = []
            if found:
                hits[rule.name] += 1
                await audit(
                    db,
                    tenant_id=tenant_id,
                    viewer=viewer,
                    event_type="curation.scan_match",
                    scope=node.scope,
                    owner_id=node.owner_id,
                    memory_id=node.id,
                    metadata={"rule": rule.name, "action": rule.action},
                )
    await audit(
        db,
        tenant_id=tenant_id,
        viewer=viewer,
        event_type="curation.batch_scan",
        scope="session",
        owner_id=tenant_id,
        memory_id=None,
        metadata={"scanned": len(nodes), "matches": dict(hits)},
    )
    await db.commit()
    return {"scanned": len(nodes), "rules": len(rules), "matches": dict(hits)}


# ---------------------------------------------------------------------------
# Review queue (screen 10)
# ---------------------------------------------------------------------------


class ReviewDecision(BaseModel):
    decision: str = Field(pattern="^(approve|reject|request_changes|restore)$")
    comment: str | None = Field(default=None, max_length=4000)


class _BriefRow:
    def __init__(self, d: dict):
        self.scope, self.scope_id, self.owner_id = d.get("scope"), d.get("scope_id"), d.get("owner_id")


async def _review_item(
    db: AsyncSession, tenant_id: str, node: MemoryNode, kind: str, threshold: int, full_threshold: float
) -> dict:
    branches = (
        (
            await db.execute(
                select(MemoryNode)
                .where(MemoryNode.parent_id == node.id, MemoryNode.deleted_at.is_(None))
                .order_by(MemoryNode.created_at)
            )
        )
        .scalars()
        .all()
    )
    sources = (
        (
            await db.execute(
                select(MemoryNode)
                .join(MemoryRelationship, MemoryRelationship.target_id == MemoryNode.id)
                .where(
                    MemoryRelationship.source_id == node.id,
                    MemoryRelationship.relationship_type == "derived_from",
                    MemoryNode.tenant_id == tenant_id,
                )
            )
        )
        .scalars()
        .all()
    )
    similar = None
    if node.embedding is not None:
        distance = MemoryNode.embedding.cosine_distance(node.embedding)
        row = (
            await db.execute(
                select(MemoryNode, (1 - distance))
                .where(
                    *live_filters(tenant_id),
                    MemoryNode.id != node.id,
                    MemoryNode.parent_id.is_(None),
                    MemoryNode.status == "active",
                    MemoryNode.embedding.is_not(None),
                    MemoryNode.id.not_in([s.id for s in sources] or [uuid.uuid4()]),
                )
                .order_by(distance)
                .limit(1)
            )
        ).first()
        if row and row[1] >= 0.75:
            similar = {"id": str(row[0].id), "stub": clean_stub(row[0].stub), "score": round(float(row[1]), 3)}
    from memoryhub_core.services.curation.scanner import scan_content

    scan = scan_content(node.content, pattern_set="all")
    requested = (
        (
            await db.execute(
                select(AuditLog)
                .where(AuditLog.tenant_id == tenant_id, AuditLog.memory_id == node.id)
                .order_by(AuditLog.timestamp)
                .limit(1)
            )
        )
        .scalars()
        .first()
    )
    history = (
        (
            await db.execute(
                select(AuditLog)
                .where(
                    AuditLog.tenant_id == tenant_id, AuditLog.memory_id == node.id, AuditLog.event_type.like("review.%")
                )
                .order_by(AuditLog.timestamp.desc())
            )
        )
        .scalars()
        .all()
    )
    month_start = now_utc().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    enterprise_this_month = (
        await db.execute(
            select(func.count())
            .select_from(MemoryNode)
            .where(
                MemoryNode.tenant_id == tenant_id,
                MemoryNode.scope == "enterprise",
                MemoryNode.created_at >= month_start,
                MemoryNode.parent_id.is_(None),
            )
        )
    ).scalar_one()
    contradictions = []
    if kind == "contradiction":
        contradictions = [
            {
                "id": str(c.id),
                "observed_behavior": c.observed_behavior,
                "confidence": c.confidence,
                "reporter": c.reporter,
                "created_at": c.created_at,
            }
            for c in (
                await db.execute(
                    select(ContradictionReport)
                    .where(ContradictionReport.memory_id == node.id, ContradictionReport.resolved.is_(False))
                    .order_by(ContradictionReport.created_at.desc())
                )
            )
            .scalars()
            .all()
        ]
    requester = (requested.actor_id if requested else None) or node.actor_id or node.owner_id
    return {
        "kind": kind,
        "id": str(node.id),
        "content": node.content,
        "stub": clean_stub(node.stub),
        "scope": node.scope,
        "scope_id": node.scope_id,
        "owner_id": node.owner_id,
        "status": node.status,
        "weight": node.weight,
        "version": node.version,
        "requested_by": requester,
        "requested_at": requested.timestamp if requested else node.created_at,
        "reason": (node.metadata_ or {}).get("reason") or (node.metadata_ or {}).get("quarantine_reason"),
        "injection": "full" if node.weight >= full_threshold else "stub",
        "branches": [{"id": str(b.id), "branch_type": b.branch_type, "content": b.content} for b in branches],
        "sources": [
            {"id": str(s.id), "stub": clean_stub(s.stub), "scope": s.scope, "owner_id": s.owner_id} for s in sources
        ],
        "checks": {
            "scan_clean": not scan,
            "scan_findings": [r.pattern_name for r in scan],
            "similar": similar,
            "enterprise_this_month": enterprise_this_month,
            "has_provenance": bool(branches or sources),
        },
        "contradictions": contradictions,
        "contradiction_threshold": threshold,
        "history": [
            {
                "event_type": h.event_type,
                "actor_id": h.actor_id,
                "timestamp": h.timestamp,
                "comment": (h.event_metadata or {}).get("comment"),
            }
            for h in history
        ],
    }


@router.get("/api/review")
async def review_queue(
    request: Request,
    db: DbDep,
    settings: SettingsDep,
    tab: str = Query(default="approvals", pattern="^(approvals|promotions|contradictions|quarantine|history)$"),
):
    tenant_id = settings.ui_tenant_id
    tenant_settings = await load_tenant_settings(db, tenant_id)
    threshold = int(tenant_settings["governance"]["contradiction_threshold"])
    counts = await _review_counts(db, tenant_id, threshold)
    approvers_needed = int(tenant_settings["governance"]["enterprise_approvers"])
    viewer = viewer_from_request(request, settings)
    items: list[dict] = []

    def summary(node: MemoryNode, kind: str, **extra) -> dict:
        return {
            "kind": kind,
            "id": str(node.id),
            "stub": clean_stub(node.stub),
            "content": node.content,
            "scope": node.scope,
            "scope_id": node.scope_id,
            "owner_id": node.owner_id,
            "actor_id": node.actor_id,
            "created_at": node.created_at,
            "updated_at": node.updated_at,
            "metadata": node.metadata_ or {},
            **extra,
        }

    if tab in ("approvals", "promotions"):
        scope_clause = MemoryNode.scope == "enterprise" if tab == "approvals" else MemoryNode.scope != "enterprise"
        nodes = (
            (
                await db.execute(
                    select(MemoryNode)
                    .where(*live_filters(tenant_id), MemoryNode.status == "pending", scope_clause)
                    .order_by(MemoryNode.created_at.desc())
                )
            )
            .scalars()
            .all()
        )
        source_counts = {}
        if nodes:
            source_counts = {
                row[0]: row[1]
                for row in (
                    await db.execute(
                        select(MemoryRelationship.source_id, func.count())
                        .where(
                            MemoryRelationship.source_id.in_([n.id for n in nodes]),
                            MemoryRelationship.relationship_type == "derived_from",
                        )
                        .group_by(MemoryRelationship.source_id)
                    )
                ).all()
            }
        items = [
            summary(n, "approval" if tab == "approvals" else "promotion", sources=source_counts.get(n.id, 0))
            for n in nodes
        ]
    elif tab == "contradictions":
        rows = (
            await db.execute(
                select(MemoryNode, func.count(ContradictionReport.id))
                .join(ContradictionReport, ContradictionReport.memory_id == MemoryNode.id)
                .where(*live_filters(tenant_id, current=False), ContradictionReport.resolved.is_(False))
                .group_by(MemoryNode.id)
                .having(func.count(ContradictionReport.id) >= threshold)
                .order_by(func.count(ContradictionReport.id).desc())
            )
        ).all()
        items = [summary(n, "contradiction", reports=c) for n, c in rows]
    elif tab == "quarantine":
        nodes = (
            (
                await db.execute(
                    select(MemoryNode)
                    .where(
                        MemoryNode.tenant_id == tenant_id,
                        MemoryNode.deleted_at.is_(None),
                        MemoryNode.status == "quarantined",
                    )
                    .order_by(MemoryNode.updated_at.desc())
                )
            )
            .scalars()
            .all()
        )
        items = [summary(n, "quarantine") for n in nodes]
    else:
        events = (
            await db.execute(
                select(AuditLog, MemoryNode)
                .outerjoin(MemoryNode, MemoryNode.id == AuditLog.memory_id)
                .where(AuditLog.tenant_id == tenant_id, AuditLog.event_type.like("review.%"))
                .order_by(AuditLog.timestamp.desc())
                .limit(100)
            )
        ).all()
        items = [{"kind": "history", **_event_row(e, m, {})} for e, m in events]

    acc = await access_for(db, settings, viewer)
    if acc.grants is not None:
        items = [i for i in items if i.get("kind") == "history" or acc.can_read_row(_BriefRow(i))]
    items = acc.redact_tree(items)

    # "Also waiting": the first item of every other queue.
    also = []
    if tab == "approvals":
        for other_tab, kind in (("promotions", "promotion"), ("contradictions", "contradiction")):
            if counts[other_tab]:
                sub = await review_queue(request, db, settings, tab=other_tab)
                also.extend(sub["items"][:1])
    return {
        "tab": tab,
        "counts": counts,
        "items": items,
        "also_waiting": also,
        "approvers_required": approvers_needed,
        "viewer": viewer.username,
    }


@router.get("/api/review/{memory_id}")
async def review_item(
    memory_id: str, request: Request, db: DbDep, settings: SettingsDep, kind: str = Query(default="approval")
):
    tenant_id = settings.ui_tenant_id
    tenant_settings = await load_tenant_settings(db, tenant_id)
    node = await _load_memory(db, tenant_id, memory_id)
    acc = await access_for(db, settings, viewer_from_request(request, settings))
    acc.ensure_readable(node)
    item = await _review_item(
        db,
        tenant_id,
        node,
        kind,
        int(tenant_settings["governance"]["contradiction_threshold"]),
        float(tenant_settings["retrieval"]["full_content_threshold"]),
    )
    agents = (
        await db.execute(
            select(func.count(func.distinct(AuditLog.actor_id))).where(
                AuditLog.tenant_id == tenant_id, AuditLog.timestamp >= now_utc() - timedelta(days=30)
            )
        )
    ).scalar_one()
    item["reach_agents"] = agents
    item["approvers_required"] = int(tenant_settings["governance"]["enterprise_approvers"])
    return acc.redact_tree(item, node.scope)


@router.post("/api/review/{memory_id}/decision")
async def review_decision(memory_id: str, body: ReviewDecision, request: Request, db: DbDep, settings: SettingsDep):
    tenant_id = settings.ui_tenant_id
    viewer = viewer_from_request(request, settings)
    node = await _load_memory(db, tenant_id, memory_id)
    tenant_settings = await load_tenant_settings(db, tenant_id)
    if viewer.redacts_content and node.status == "quarantined":
        # #667: quarantined user memories are moderated by super-users under an incident grant.
        (await access_for(db, settings, viewer)).ensure_moderatable(node)

    if body.decision in ("approve", "reject", "request_changes") and node.status not in ("pending", "quarantined"):
        # Contradiction reviews resolve the reports instead.
        if body.decision in ("approve", "reject"):
            reports = (
                (
                    await db.execute(
                        select(ContradictionReport).where(
                            ContradictionReport.memory_id == node.id, ContradictionReport.resolved.is_(False)
                        )
                    )
                )
                .scalars()
                .all()
            )
            if not reports:
                raise HTTPException(status_code=409, detail="Nothing is waiting for review on this memory")
            for report in reports:
                report.resolved = True
                report.resolved_at = now_utc()
                if hasattr(report, "resolution_action"):
                    report.resolution_action = "accept_new" if body.decision == "approve" else "keep_old"
                if hasattr(report, "resolved_by"):
                    report.resolved_by = viewer.username
        else:
            raise HTTPException(status_code=409, detail="Nothing is waiting for review on this memory")
    elif body.decision == "approve":
        requester = node.actor_id or node.owner_id
        if node.scope == "enterprise" and requester == viewer.username:
            raise HTTPException(status_code=403, detail="Requesters can never approve their own proposal")
        required = int(tenant_settings["governance"]["enterprise_approvers"]) if node.scope == "enterprise" else 1
        prior = (
            await db.execute(
                select(func.count(func.distinct(AuditLog.actor_id))).where(
                    AuditLog.tenant_id == tenant_id,
                    AuditLog.memory_id == node.id,
                    AuditLog.event_type == "review.approve",
                    AuditLog.actor_id != viewer.username,
                )
            )
        ).scalar_one()
        if prior + 1 >= required:
            node.status = "active"
            from memoryhub_core.models.schemas import MemoryNodeCreate  # noqa: F401  (schema parity)

            approval_id = uuid.uuid4()
            db.add(
                MemoryNode(
                    id=approval_id,
                    logical_id=approval_id,
                    parent_id=node.id,
                    branch_type="approval",
                    content=f"Approved by {viewer.username}" + (f": {body.comment}" if body.comment else ""),
                    stub=f"Approved by {viewer.username}",
                    storage_type="inline",
                    weight=node.weight,
                    scope=node.scope,
                    scope_id=node.scope_id,
                    owner_id=node.owner_id,
                    actor_id=viewer.username,
                    driver_id=viewer.username,
                    tenant_id=tenant_id,
                    content_type="knowledge",
                    status="active",
                    source="import",
                    is_current=True,
                    version=1,
                )
            )
    elif body.decision == "reject":
        node.status = "rejected" if node.status == "pending" else node.status
        node.deleted_at = now_utc()
        node.is_current = False
    elif body.decision == "restore":
        if node.status != "quarantined":
            raise HTTPException(status_code=409, detail="Only quarantined memories can be restored")
        node.status = "active"

    await audit(
        db,
        tenant_id=tenant_id,
        viewer=viewer,
        event_type=f"review.{body.decision}",
        scope=node.scope,
        owner_id=node.owner_id,
        memory_id=node.id,
        metadata={"comment": body.comment, "status": node.status},
    )
    await db.commit()
    return {"id": str(node.id), "status": node.status}


# ---------------------------------------------------------------------------
# Audit & forensics (screen 11)
# ---------------------------------------------------------------------------


@router.get("/api/audit", dependencies=[Depends(admin_viewer)])
async def audit_log(
    request: Request,
    db: DbDep,
    settings: SettingsDep,
    viewer: ViewerDep,
    operation: list[str] | None = Query(default=None),
    decision: str | None = Query(default=None, pattern="^(allowed|denied)$"),
    actor: str | None = Query(default=None, max_length=255),
    hours: int | None = Query(default=24, ge=1, le=24 * 400),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=25, ge=1, le=200),
):
    tenant_id = settings.ui_tenant_id
    where = [AuditLog.tenant_id == tenant_id]
    acc = await access_for(db, settings, viewer)
    mine = acc.grants.identities if acc.grants is not None else None
    if mine is not None:
        where.append(or_(AuditLog.actor_id.in_(mine), AuditLog.driver_id.in_(mine)))
    # #667: admins audit everything except operations on user memories; super-users see all.
    hides_user_ops = viewer.redacts_content and not viewer.is_superuser
    if operation:
        where.append(AuditLog.event_type.in_(operation))
    if decision:
        where.append(AuditLog.decision == decision)
    if actor:
        if mine is not None and actor not in mine:
            where.append(false())
        else:
            where.append(or_(AuditLog.actor_id == actor, AuditLog.driver_id == actor))
    if hours:
        where.append(AuditLog.timestamp >= now_utc() - timedelta(hours=hours))
    hidden_user_ops = 0
    if hides_user_ops:
        user_ops = and_(AuditLog.scope == "user", AuditLog.memory_id.is_not(None))
        hidden_user_ops = (
            await db.execute(select(func.count()).select_from(AuditLog).where(*where, user_ops))
        ).scalar_one()
        where.append(~user_ops)
    total = (await db.execute(select(func.count()).select_from(AuditLog).where(*where))).scalar_one()
    rows = (
        await db.execute(
            select(AuditLog, MemoryNode)
            .outerjoin(MemoryNode, and_(MemoryNode.id == AuditLog.memory_id, MemoryNode.tenant_id == tenant_id))
            .where(*where)
            .order_by(AuditLog.timestamp.desc(), AuditLog.id.desc())
            .offset((page - 1) * per_page)
            .limit(per_page)
        )
    ).all()
    items = []
    for event, memory in rows:
        if memory is not None and not acc.can_read_row(memory):
            memory = None
        item = _event_row(event, memory, {})
        if event.event_type == "memory.update" and memory is not None and memory.previous_version_id:
            prev = (
                await db.execute(
                    select(MemoryNode).where(
                        MemoryNode.id == memory.previous_version_id,
                        MemoryNode.tenant_id == tenant_id,
                    )
                )
            ).scalar_one_or_none()
            if prev is not None and acc.can_read_row(prev):
                item["change"] = {
                    "before": {"version": prev.version, "content": prev.content, "weight": prev.weight},
                    "after": {"version": memory.version, "content": memory.content, "weight": memory.weight},
                }
        items.append(item)
    types = (await db.execute(select(AuditLog.event_type).where(*where).distinct())).scalars().all()
    denied_total = (
        await db.execute(select(func.count()).select_from(AuditLog).where(*where, AuditLog.decision == "denied"))
    ).scalar_one()
    tenant_settings = await load_tenant_settings(db, tenant_id)
    return {
        "items": acc.redact_tree(items),
        "total": total,
        "page": page,
        "per_page": per_page,
        "event_types": sorted(types),
        "operations": {t: tool_name(t) for t in types},
        "denied_total": denied_total,
        "retention_days": tenant_settings["audit"]["full_retention_days"],
        "hidden_user_operations": hidden_user_ops,
    }


@router.get("/api/audit/sessions", dependencies=[Depends(admin_viewer)])
async def audit_sessions(db: DbDep, settings: SettingsDep, actor: str = Query(min_length=1)):
    """Session registrations for an actor, used to pick a session to reconstruct."""
    rows = (
        (
            await db.execute(
                select(AuditLog)
                .where(
                    AuditLog.tenant_id == settings.ui_tenant_id,
                    AuditLog.actor_id == actor,
                    AuditLog.event_type == "session.registered",
                )
                .order_by(AuditLog.timestamp.desc())
                .limit(50)
            )
        )
        .scalars()
        .all()
    )
    return [{"session_id": (r.event_metadata or {}).get("session_id"), "timestamp": r.timestamp} for r in rows]


@router.get("/api/audit/forensics", dependencies=[Depends(admin_viewer)])
async def forensics(
    request: Request,
    db: DbDep,
    settings: SettingsDep,
    actor: str = Query(min_length=1, max_length=255),
    at: datetime = Query(...),
    session_id: str | None = Query(default=None, max_length=255),
    window_minutes: int = Query(default=60, ge=1, le=24 * 60),
):
    """Reconstruct which memories (and which versions) an agent had read or
    been served at time ``at``, and which have changed since."""
    tenant_id = settings.ui_tenant_id
    if at.tzinfo is None:
        at = at.replace(tzinfo=UTC)
    since = at - timedelta(minutes=window_minutes)
    where = [
        AuditLog.tenant_id == tenant_id,
        or_(AuditLog.actor_id == actor, AuditLog.driver_id == actor),
        AuditLog.timestamp <= at,
        AuditLog.timestamp >= since,
    ]
    if session_id:
        where.append(AuditLog.event_metadata["session_id"].astext == session_id)
    events = (await db.execute(select(AuditLog).where(*where).order_by(AuditLog.timestamp))).scalars().all()

    served: dict[uuid.UUID, datetime] = {}
    last_search = None
    for e in events:
        meta = e.event_metadata or {}
        ids = []
        if e.memory_id and e.event_type in ("memory.read", "memory.search", "memory.write", "memory.update"):
            ids.append(e.memory_id)
        for key in ("result_ids", "memory_ids", "served_ids"):
            for raw in meta.get(key, []) or []:
                try:
                    ids.append(uuid.UUID(str(raw)))
                except ValueError:
                    continue
        if e.event_type == "memory.search":
            last_search = e.timestamp
        for mid in ids:
            served[mid] = e.timestamp

    context = []
    changed_after: list[dict] = []
    for mid, ts in served.items():
        node = (
            await db.execute(select(MemoryNode).where(MemoryNode.id == mid, MemoryNode.tenant_id == tenant_id))
        ).scalar_one_or_none()
        if node is None:
            continue
        logical = getattr(node, "logical_id", None) or node.id
        chain = (
            await db.execute(
                select(MemoryNode)
                .where(
                    MemoryNode.tenant_id == tenant_id, MemoryNode.logical_id == logical, MemoryNode.parent_id.is_(None)
                )
                .order_by(MemoryNode.version)
            )
        ).scalars().all() or [node]
        at_time = [v for v in chain if v.created_at <= at] or [chain[0]]
        then = at_time[-1]
        latest = chain[-1]
        changed_by = None
        if latest.version != then.version:
            changed_by = latest.actor_id or latest.owner_id
        entry = {
            "id": str(then.id),
            "current_id": str(latest.id),
            "stub": clean_stub(then.stub),
            "content": then.content,
            "scope": then.scope,
            "version_then": then.version,
            "version_now": latest.version,
            "changed_after": latest.version != then.version,
            "changed_at": latest.created_at if latest.version != then.version else None,
            "changed_by": changed_by,
            "deleted": latest.deleted_at is not None,
            "served_at": ts,
            "delivery": "stub" if then.weight < 0.8 else "full",
            "tokens": max(1, len(then.content or "") // 4),
        }
        context.append(entry)
        if entry["changed_after"]:
            exposed = (
                await db.execute(
                    select(func.count(func.distinct(AuditLog.actor_id))).where(
                        AuditLog.tenant_id == tenant_id,
                        AuditLog.memory_id == then.id,
                        AuditLog.actor_id != actor,
                        AuditLog.timestamp <= (entry["changed_at"] or at),
                    )
                )
            ).scalar_one()
            changed_after.append({**entry, "other_actors_exposed": exposed})
    context.sort(key=lambda c: c["served_at"])
    acc = await access_for(db, settings, viewer_from_request(request, settings))
    context = acc.redact_tree(context)
    changed_after = acc.redact_tree(changed_after)
    return {
        "actor": actor,
        "at": at,
        "window_minutes": window_minutes,
        "events": len(events),
        "last_search_at": last_search,
        "context": context,
        "tokens": sum(c["tokens"] for c in context),
        "findings": changed_after,
    }


# ---------------------------------------------------------------------------
# Settings (screen 12)
# ---------------------------------------------------------------------------


class SettingsUpdate(BaseModel):
    retrieval: dict | None = None
    governance: dict | None = None
    audit: dict | None = None
    organization: dict | None = None
    signup: dict | None = None
    privacy: dict | None = None
    security: dict | None = None


def _validate_settings(values: dict) -> dict:
    r, g, a = values["retrieval"], values["governance"], values["audit"]
    errors = []
    if not (1 <= int(r["max_results"]) <= 50):
        errors.append("Max results must be between 1 and 50")
    if not (100 <= int(r["max_response_tokens"]) <= 100_000):
        errors.append("Max response tokens must be between 100 and 100,000")
    for key, label in (
        ("session_focus_weight", "Session focus weight"),
        ("full_content_threshold", "Full-content weight threshold"),
    ):
        if not (0 <= float(r[key]) <= 1):
            errors.append(f"{label} must be between 0 and 1")
    if not (1 <= int(g["contradiction_threshold"]) <= 100):
        errors.append("Contradiction threshold must be between 1 and 100")
    if not (1 <= int(g["enterprise_approvers"]) <= 10):
        errors.append("Enterprise approvers must be between 1 and 10")
    if a["read_detail"] not in ("full", "summary", "sample"):
        errors.append("Read detail must be full, summary or sample")
    if not (1 <= int(a["full_retention_days"]) <= 3650):
        errors.append("Retention must be between 1 and 3650 days")
    if a["mcp_profile"] not in ("compact", "full"):
        errors.append("MCP profile must be compact or full")
    if "signup" in values:
        from src.accounts import validate_access_settings

        errors.extend(validate_access_settings(values))
    if errors:
        raise HTTPException(status_code=422, detail="; ".join(errors))
    return values


@router.get("/api/settings", dependencies=[Depends(admin_viewer)])
async def get_tenant_settings(db: DbDep, settings: SettingsDep):
    from src.ui_common import probe_components

    values = await load_tenant_settings(db, settings.ui_tenant_id)
    health = {p["key"]: p for p in await probe_components(db, settings)}
    return {
        "values": {k: values[k] for k in DEFAULT_TENANT_SETTINGS},
        "meta": values["_meta"],
        "models": {
            "embedding": {"url": settings.embedding_url or None, **health.get("embedding", {})},
            "reranker": {"url": settings.reranker_url or None, **health.get("reranker", {})},
        },
        "mcp": {
            "public_url": settings.public_mcp_url,
            "internal_url": settings.mcp_server_url,
            **health.get("mcp", {}),
        },
        "tenant": {
            "tenant_id": settings.ui_tenant_id,
            "auth_url": settings.public_auth_url,
            "cluster_domain": settings.cluster_domain or None,
        },
    }


@router.put("/api/settings", dependencies=[Depends(admin_viewer)])
async def put_tenant_settings(body: SettingsUpdate, request: Request, db: DbDep, settings: SettingsDep):
    viewer = viewer_from_request(request, settings)
    current = await load_tenant_settings(db, settings.ui_tenant_id)
    merged = {k: {**current[k], **(getattr(body, k) or {})} for k in DEFAULT_TENANT_SETTINGS}
    _validate_settings(merged)
    changed = {
        f"{section}.{key}": value
        for section in DEFAULT_TENANT_SETTINGS
        for key, value in merged[section].items()
        if current[section].get(key) != value
    }
    await save_tenant_settings(db, settings.ui_tenant_id, merged, viewer.username)
    await audit(
        db,
        tenant_id=settings.ui_tenant_id,
        viewer=viewer,
        event_type="settings.update",
        scope="session",
        owner_id=settings.ui_tenant_id,
        memory_id=None,
        metadata={"changed": changed},
    )
    await db.commit()
    return await get_tenant_settings(db, settings)
