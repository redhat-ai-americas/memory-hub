"""Teams: groups of people that work across projects.

A project has members from several teams, and one team works on several
projects (many-to-many). Linking a team to a project gives every team member
project access: the BFF keeps ``project_memberships`` (the table the MCP read
RBAC uses) in sync, marking team-derived rows ``joined_by = "team:<name>"`` so
they are added and removed with the team while direct memberships are never
touched.

Tables, created on first use:

* ``memoryhub_ui_teams`` — id, name, description, creator.
* ``memoryhub_ui_team_members`` — team ↔ person (role ``lead`` | ``member``).
* ``memoryhub_ui_team_projects`` — team ↔ project.
"""

from __future__ import annotations

import logging
import uuid
from collections import defaultdict
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from memoryhub_core.models.project import Project, ProjectMembership
from pydantic import BaseModel, Field
from sqlalchemy import delete, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import Settings, get_settings
from src.database import get_db
from src.ui_common import Viewer, audit, viewer_from_request

logger = logging.getLogger(__name__)
router = APIRouter()

DbDep = Annotated[AsyncSession, Depends(get_db)]
SettingsDep = Annotated[Settings, Depends(get_settings)]

TEAMS = "memoryhub_ui_teams"
MEMBERS = "memoryhub_ui_team_members"
LINKS = "memoryhub_ui_team_projects"
TEAM_PREFIX = "team:"


async def ensure_tables(db: AsyncSession) -> None:
    from src.schema import require

    await require(db)


# ---------------------------------------------------------------------------
# Access sync
# ---------------------------------------------------------------------------


async def sync_project_access(db: AsyncSession, tenant_id: str) -> dict[str, int]:
    """Make team-derived project memberships match teams × projects."""
    await ensure_tables(db)
    rows = (
        await db.execute(
            text(
                f"""
                SELECT t.name, m.user_id, l.project_id
                FROM {TEAMS} t
                JOIN {MEMBERS} m ON m.team_id = t.id
                JOIN {LINKS} l ON l.team_id = t.id
                WHERE t.tenant_id = :t
                ORDER BY t.name
                """
            ),
            {"t": tenant_id},
        )
    ).all()
    desired: dict[tuple[str, str], str] = {}
    for team, user_id, project_id in rows:
        desired.setdefault((project_id, user_id), team)
    tenant_projects = set(
        (await db.execute(select(Project.name).where(Project.tenant_id == tenant_id))).scalars().all()
    )
    existing = (
        (await db.execute(select(ProjectMembership).where(ProjectMembership.project_id.in_(tenant_projects or {""}))))
        .scalars()
        .all()
    )
    have = {(m.project_id, m.user_id): m for m in existing}
    added = removed = 0
    for m in existing:
        if (m.joined_by or "").startswith(TEAM_PREFIX) and (m.project_id, m.user_id) not in desired:
            await db.delete(m)
            removed += 1
    for (project_id, user_id), team in desired.items():
        if project_id in tenant_projects and (project_id, user_id) not in have:
            db.add(
                ProjectMembership(
                    project_id=project_id, user_id=user_id, role="member", joined_by=f"{TEAM_PREFIX}{team}"
                )
            )
            added += 1
    await db.flush()
    return {"added": added, "removed": removed}


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


async def teams_overview(db: AsyncSession, tenant_id: str) -> list[dict]:
    await ensure_tables(db)
    teams = (
        await db.execute(
            text(
                f"SELECT id, name, description, created_by, created_at FROM {TEAMS} WHERE tenant_id = :t ORDER BY name"
            ),
            {"t": tenant_id},
        )
    ).all()
    members: dict[uuid.UUID, list[dict]] = defaultdict(list)
    for team_id, user_id, role, added_at in (
        await db.execute(
            text(
                f"SELECT m.team_id, m.user_id, m.role, m.added_at FROM {MEMBERS} m JOIN {TEAMS} t ON t.id = m.team_id "
                "WHERE t.tenant_id = :t ORDER BY m.role DESC, m.user_id"
            ),
            {"t": tenant_id},
        )
    ).all():
        members[team_id].append({"user_id": user_id, "role": role, "added_at": added_at})
    projects: dict[uuid.UUID, list[str]] = defaultdict(list)
    for team_id, project_id in (
        await db.execute(
            text(
                f"SELECT l.team_id, l.project_id FROM {LINKS} l JOIN {TEAMS} t ON t.id = l.team_id "
                "WHERE t.tenant_id = :t ORDER BY l.project_id"
            ),
            {"t": tenant_id},
        )
    ).all():
        projects[team_id].append(project_id)
    return [
        {
            "id": str(t[0]),
            "name": t[1],
            "description": t[2],
            "created_by": t[3],
            "created_at": t[4],
            "members": members.get(t[0], []),
            "projects": projects.get(t[0], []),
        }
        for t in teams
    ]


async def teams_for_project(db: AsyncSession, tenant_id: str, project: str) -> list[dict]:
    return [
        {"id": t["id"], "name": t["name"], "members": len(t["members"])}
        for t in await teams_overview(db, tenant_id)
        if project in t["projects"]
    ]


# ---------------------------------------------------------------------------
# Permissions
# ---------------------------------------------------------------------------


async def _team(db: AsyncSession, tenant_id: str, team_id: str) -> dict:
    await ensure_tables(db)
    try:
        parsed = uuid.UUID(team_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Invalid team ID") from exc
    row = (
        await db.execute(
            text(f"SELECT id, name FROM {TEAMS} WHERE id = :id AND tenant_id = :t"), {"id": parsed, "t": tenant_id}
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Team not found")
    return {"id": row[0], "name": row[1]}


async def _is_lead(db: AsyncSession, team_id: uuid.UUID, user: str) -> bool:
    return (
        await db.execute(
            text(f"SELECT 1 FROM {MEMBERS} WHERE team_id = :id AND user_id = :u AND role = 'lead'"),
            {"id": team_id, "u": user},
        )
    ).first() is not None


async def _can_manage(db: AsyncSession, viewer: Viewer, team_id: uuid.UUID) -> None:
    if viewer.can_admin or await _is_lead(db, team_id, viewer.username):
        return
    raise HTTPException(status_code=403, detail="Only the team lead or a platform admin can change this team")


async def _can_grant_project(db: AsyncSession, viewer: Viewer, tenant_id: str, project: str) -> None:
    """Linking a team gives project access: needs a project admin or platform admin."""
    exists = (
        await db.execute(select(Project.name).where(Project.name == project, Project.tenant_id == tenant_id))
    ).scalar_one_or_none()
    if exists is None:
        raise HTTPException(status_code=404, detail=f"Project {project!r} not found")
    if viewer.can_admin:
        return
    role = (
        await db.execute(
            select(ProjectMembership.role).where(
                ProjectMembership.project_id == project, ProjectMembership.user_id == viewer.username
            )
        )
    ).scalar_one_or_none()
    if role != "admin":
        raise HTTPException(status_code=403, detail=f"Only an admin of {project} can give a team access to it")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


class TeamRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    members: list[str] = Field(default_factory=list, max_length=200)
    projects: list[str] = Field(default_factory=list, max_length=100)


class TeamUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)


class TeamMemberRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=255)
    role: str = Field(default="member", pattern="^(member|lead)$")


class TeamProjectRequest(BaseModel):
    project: str = Field(min_length=1, max_length=255)


@router.get("/api/teams")
async def list_teams(db: DbDep, settings: SettingsDep):
    items = await teams_overview(db, settings.ui_tenant_id)
    people = {m["user_id"] for t in items for m in t["members"]}
    return {"items": items, "counts": {"teams": len(items), "people": len(people)}}


@router.post("/api/teams", status_code=201)
async def create_team(body: TeamRequest, request: Request, db: DbDep, settings: SettingsDep):
    viewer = viewer_from_request(request, settings)
    tenant_id = settings.ui_tenant_id
    await ensure_tables(db)
    for project in body.projects:
        await _can_grant_project(db, viewer, tenant_id, project)
    team_id = uuid.uuid4()
    try:
        await db.execute(
            text(f"INSERT INTO {TEAMS} (id, tenant_id, name, description, created_by) VALUES (:id, :t, :n, :d, :b)"),
            {"id": team_id, "t": tenant_id, "n": body.name.strip(), "d": body.description, "b": viewer.username},
        )
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail=f"A team called {body.name!r} already exists") from None
    people = {u.strip() for u in body.members if u.strip()}
    if viewer.source != "anonymous":
        people.add(viewer.username)
    for user_id in sorted(people):
        await db.execute(
            text(f"INSERT INTO {MEMBERS} (team_id, user_id, role, added_by) VALUES (:id, :u, :r, :b)"),
            {
                "id": team_id,
                "u": user_id,
                "r": "lead" if user_id == viewer.username else "member",
                "b": viewer.username,
            },
        )
    for project in sorted(set(body.projects)):
        await db.execute(
            text(f"INSERT INTO {LINKS} (team_id, project_id, added_by) VALUES (:id, :p, :b)"),
            {"id": team_id, "p": project, "b": viewer.username},
        )
    sync = await sync_project_access(db, tenant_id)
    await audit(
        db,
        tenant_id=tenant_id,
        viewer=viewer,
        event_type="team.create",
        scope="session",
        owner_id=body.name,
        memory_id=None,
        metadata={"members": len(people), "projects": body.projects, **sync},
    )
    await db.commit()
    return {"id": str(team_id), "name": body.name.strip(), **sync}


@router.patch("/api/teams/{team_id}")
async def update_team(team_id: str, body: TeamUpdate, request: Request, db: DbDep, settings: SettingsDep):
    viewer = viewer_from_request(request, settings)
    team = await _team(db, settings.ui_tenant_id, team_id)
    await _can_manage(db, viewer, team["id"])
    changes = body.model_dump(exclude_none=True)
    if changes:
        sets = ", ".join(f"{k} = :{k}" for k in changes)
        try:
            await db.execute(text(f"UPDATE {TEAMS} SET {sets} WHERE id = :id"), {**changes, "id": team["id"]})
        except IntegrityError:
            await db.rollback()
            raise HTTPException(status_code=409, detail="Another team already has that name") from None
        if "name" in changes:
            # Keep team-derived memberships labelled with the current name.
            await db.execute(
                text("UPDATE project_memberships SET joined_by = :new WHERE joined_by = :old"),
                {"new": f"{TEAM_PREFIX}{changes['name']}", "old": f"{TEAM_PREFIX}{team['name']}"},
            )
        await audit(
            db,
            tenant_id=settings.ui_tenant_id,
            viewer=viewer,
            event_type="team.update",
            scope="session",
            owner_id=team["name"],
            memory_id=None,
            metadata={"changes": changes},
        )
        await db.commit()
    return {"ok": True}


@router.delete("/api/teams/{team_id}", status_code=204)
async def delete_team(team_id: str, request: Request, db: DbDep, settings: SettingsDep):
    viewer = viewer_from_request(request, settings)
    team = await _team(db, settings.ui_tenant_id, team_id)
    await _can_manage(db, viewer, team["id"])
    await db.execute(text(f"DELETE FROM {TEAMS} WHERE id = :id"), {"id": team["id"]})
    sync = await sync_project_access(db, settings.ui_tenant_id)
    await audit(
        db,
        tenant_id=settings.ui_tenant_id,
        viewer=viewer,
        event_type="team.delete",
        scope="session",
        owner_id=team["name"],
        memory_id=None,
        metadata=sync,
    )
    await db.commit()


@router.post("/api/teams/{team_id}/members", status_code=201)
async def add_team_member(team_id: str, body: TeamMemberRequest, request: Request, db: DbDep, settings: SettingsDep):
    viewer = viewer_from_request(request, settings)
    team = await _team(db, settings.ui_tenant_id, team_id)
    await _can_manage(db, viewer, team["id"])
    await db.execute(
        text(
            f"""
            INSERT INTO {MEMBERS} (team_id, user_id, role, added_by) VALUES (:id, :u, :r, :b)
            ON CONFLICT (team_id, user_id) DO UPDATE SET role = EXCLUDED.role
            """
        ),
        {"id": team["id"], "u": body.user_id.strip(), "r": body.role, "b": viewer.username},
    )
    sync = await sync_project_access(db, settings.ui_tenant_id)
    await audit(
        db,
        tenant_id=settings.ui_tenant_id,
        viewer=viewer,
        event_type="team.member_added",
        scope="session",
        owner_id=team["name"],
        memory_id=None,
        metadata={"user_id": body.user_id, "role": body.role, **sync},
    )
    await db.commit()
    return {"ok": True, **sync}


@router.delete("/api/teams/{team_id}/members/{user_id}", status_code=204)
async def remove_team_member(team_id: str, user_id: str, request: Request, db: DbDep, settings: SettingsDep):
    viewer = viewer_from_request(request, settings)
    team = await _team(db, settings.ui_tenant_id, team_id)
    if user_id != viewer.username:
        await _can_manage(db, viewer, team["id"])
    await db.execute(
        text(f"DELETE FROM {MEMBERS} WHERE team_id = :id AND user_id = :u"), {"id": team["id"], "u": user_id}
    )
    sync = await sync_project_access(db, settings.ui_tenant_id)
    await audit(
        db,
        tenant_id=settings.ui_tenant_id,
        viewer=viewer,
        event_type="team.member_removed",
        scope="session",
        owner_id=team["name"],
        memory_id=None,
        metadata={"user_id": user_id, **sync},
    )
    await db.commit()


@router.post("/api/teams/{team_id}/projects", status_code=201)
async def link_project(team_id: str, body: TeamProjectRequest, request: Request, db: DbDep, settings: SettingsDep):
    viewer = viewer_from_request(request, settings)
    team = await _team(db, settings.ui_tenant_id, team_id)
    await _can_grant_project(db, viewer, settings.ui_tenant_id, body.project)
    await db.execute(
        text(
            f"INSERT INTO {LINKS} (team_id, project_id, added_by) VALUES (:id, :p, :b) "
            "ON CONFLICT (team_id, project_id) DO NOTHING"
        ),
        {"id": team["id"], "p": body.project, "b": viewer.username},
    )
    sync = await sync_project_access(db, settings.ui_tenant_id)
    await audit(
        db,
        tenant_id=settings.ui_tenant_id,
        viewer=viewer,
        event_type="team.project_linked",
        scope="project",
        owner_id=body.project,
        memory_id=None,
        metadata={"team": team["name"], **sync},
    )
    await db.commit()
    return {"ok": True, **sync}


@router.delete("/api/teams/{team_id}/projects/{project}", status_code=204)
async def unlink_project(team_id: str, project: str, request: Request, db: DbDep, settings: SettingsDep):
    viewer = viewer_from_request(request, settings)
    team = await _team(db, settings.ui_tenant_id, team_id)
    try:
        await _can_grant_project(db, viewer, settings.ui_tenant_id, project)
    except HTTPException:
        await _can_manage(db, viewer, team["id"])
    await db.execute(
        text(f"DELETE FROM {LINKS} WHERE team_id = :id AND project_id = :p"), {"id": team["id"], "p": project}
    )
    sync = await sync_project_access(db, settings.ui_tenant_id)
    await audit(
        db,
        tenant_id=settings.ui_tenant_id,
        viewer=viewer,
        event_type="team.project_unlinked",
        scope="project",
        owner_id=project,
        memory_id=None,
        metadata={"team": team["name"], **sync},
    )
    await db.commit()


__all__ = ["router", "sync_project_access", "teams_for_project", "teams_overview", "delete"]
