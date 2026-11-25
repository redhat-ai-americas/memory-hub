"""Project lookup and human project summaries shared by Core clients."""

from sqlalchemy import func, or_, select
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


async def project_summary(db: AsyncSession, access: Access, project: Project):
    tenant = access.principal.tenant_id
    member_count = (
        await db.execute(
            select(func.count())
            .select_from(ProjectMembership)
            .where(
                ProjectMembership.project_id == project.name,
            )
        )
    ).scalar_one()
    memory_info = (
        await db.execute(
            select(func.count(MemoryNode.id), func.max(MemoryNode.updated_at)).where(
                MemoryNode.tenant_id == tenant,
                MemoryNode.scope == "project",
                MemoryNode.scope_id == project.name,
                MemoryNode.deleted_at.is_(None),
                MemoryNode.is_current.is_(True),
            )
        )
    ).one()
    campaigns = (
        (
            await db.execute(
                select(Campaign)
                .join(
                    CampaignMembership,
                    CampaignMembership.campaign_id == Campaign.id,
                )
                .where(Campaign.tenant_id == tenant, CampaignMembership.project_id == project.name)
            )
        )
        .scalars()
        .all()
    )
    my_role = (
        await db.execute(
            select(ProjectMembership.role).where(
                ProjectMembership.project_id == project.name,
                ProjectMembership.user_id == access.principal.username,
            )
        )
    ).scalar_one_or_none()
    return member_count, memory_info, campaigns, my_role


async def visible_projects(db: AsyncSession, access: Access, *, mine=False):
    tenant = access.principal.tenant_id
    my_projects = select(ProjectMembership.project_id).where(
        ProjectMembership.user_id == access.principal.username,
    )
    stmt = select(Project).where(Project.tenant_id == tenant)
    if mine:
        stmt = stmt.where(Project.name.in_(my_projects))
    elif access.principal.role == "user":
        stmt = stmt.where(or_(Project.name.in_(my_projects), Project.invite_only.is_(False)))
    projects = (await db.execute(stmt.order_by(Project.name))).scalars().all()
    return projects


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
