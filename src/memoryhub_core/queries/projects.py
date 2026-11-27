"""Project lookup and human project summaries shared by Core clients."""

from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from memoryhub_core.authorization.human import Access
from memoryhub_core.models.campaign import Campaign, CampaignMembership
from memoryhub_core.models.memory import MemoryNode
from memoryhub_core.models.project import Project, ProjectMembership


async def project_by_name(db: AsyncSession, name: str, tenant: str | None = None, *, lock=False):
    stmt = select(Project).where(Project.name == name)
    if tenant is not None:
        stmt = stmt.where(Project.tenant_id == tenant)
    if lock:
        stmt = stmt.with_for_update()
    return (await db.execute(stmt)).scalar_one_or_none()


async def human_membership(db: AsyncSession, access: Access, name: str, *, admin=False):
    stmt = (
        select(ProjectMembership)
        .join(Project, ProjectMembership.project_id == Project.name)
        .where(
            Project.tenant_id == access.principal.tenant_id,
            ProjectMembership.project_id == name,
            ProjectMembership.user_id == access.principal.username,
        )
        .with_for_update(of=ProjectMembership)
    )
    rows = (await db.execute(stmt)).scalars().all()
    return any(row.role == "admin" for row in rows) if admin else bool(rows)


async def select_projects(db: AsyncSession, tenant: str, user_id: str | None, *, visibility="member"):
    """One tenant-bound project selection for human and agent transports."""
    memberships = select(ProjectMembership.project_id).where(ProjectMembership.user_id == user_id)
    stmt = select(Project).where(Project.tenant_id == tenant)
    if visibility == "member":
        if user_id is None:
            return []
        stmt = stmt.where(Project.name.in_(memberships))
    elif visibility == "open":
        stmt = stmt.where(or_(Project.invite_only.is_(False), Project.name.in_(memberships)))
    elif visibility != "all":
        raise ValueError("Invalid project visibility")
    return (await db.execute(stmt.order_by(Project.name))).scalars().all()


async def project_member_stats(db: AsyncSession, names: list[str], user_id: str | None):
    if not names:
        return {}
    rows = (await db.execute(
        select(ProjectMembership.project_id, func.count(), func.max(case(
            (ProjectMembership.user_id == user_id, ProjectMembership.role), else_=None,
        )))
        .where(ProjectMembership.project_id.in_(names))
        .group_by(ProjectMembership.project_id)
    )).all()
    return {name: (count, role) for name, count, role in rows}


async def project_memory_stats(db: AsyncSession, tenant: str, names: list[str]):
    """Batch current, undeleted counts and last-write times in one query."""
    if not names:
        return {}
    rows = (await db.execute(
        select(MemoryNode.scope_id, func.count(MemoryNode.id), func.max(MemoryNode.updated_at))
        .where(
            MemoryNode.tenant_id == tenant, MemoryNode.scope == "project",
            MemoryNode.scope_id.in_(names), MemoryNode.deleted_at.is_(None), MemoryNode.is_current.is_(True),
        )
        .group_by(MemoryNode.scope_id)
    )).all()
    return {name: (count, last_write) for name, count, last_write in rows}


async def project_summaries(db: AsyncSession, access: Access, projects: list[Project]):
    """Batch UI-only enrichment over the same selection and aggregates as MCP."""
    names = [project.name for project in projects]
    if not names:
        return {}
    members = await project_member_stats(db, names, access.principal.username)
    memories = await project_memory_stats(db, access.principal.tenant_id, names)
    rows = (await db.execute(
        select(CampaignMembership.project_id, Campaign)
        .join(Campaign, Campaign.id == CampaignMembership.campaign_id)
        .where(Campaign.tenant_id == access.principal.tenant_id, CampaignMembership.project_id.in_(names))
    )).all()
    campaigns = {name: [] for name in names}
    for name, campaign in rows:
        campaigns[name].append(campaign)
    return {name: (
        members.get(name, (0, None))[0], memories.get(name, (0, None)),
        campaigns[name], members.get(name, (0, None))[1],
    ) for name in names}


async def project_summary(db: AsyncSession, access: Access, project: Project):
    return (await project_summaries(db, access, [project]))[project.name]


async def visible_projects(db: AsyncSession, access: Access, *, mine=False):
    visibility = "member" if mine else "all" if access.principal.role == "admin" else "open"
    return await select_projects(db, access.principal.tenant_id, access.principal.username, visibility=visibility)


async def writable_by_human(db: AsyncSession, access: Access, node):
    """The same live membership check for memory and entity mutations."""
    if not access.can_write(node):
        return False
    return node.scope != "project" or await human_membership(
        db,
        access,
        node.scope_id,
        admin=access.principal.role == "admin",
    )
