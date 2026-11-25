"""Resolve tenant-bound human owner and membership grants in one place."""

from sqlalchemy import any_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from memoryhub_core.authorization.human import Access
from memoryhub_core.models.agent_owner import AgentOwner
from memoryhub_core.models.campaign import Campaign, CampaignMembership
from memoryhub_core.models.conversation import ConversationThread
from memoryhub_core.models.curation import CuratorRule
from memoryhub_core.models.memory import MemoryNode
from memoryhub_core.models.project import Project, ProjectMembership
from memoryhub_core.models.role import RoleAssignment


async def load_human_grants(db: AsyncSession, access: Access) -> Access:
    tenant = access.principal.tenant_id
    # Explicit owner bindings are the only proof that an OAuth client belongs
    # to a person. Existing unbound clients remain admin-managed until linked.
    access.agents = set(
        (
            await db.execute(
                select(AgentOwner.client_id).where(
                    AgentOwner.tenant_id == tenant,
                    AgentOwner.owner == access.principal.username,
                )
            )
        )
        .scalars()
        .all()
    )
    identities = access.identities
    memberships = (
        await db.execute(
            select(
                ProjectMembership.project_id,
                ProjectMembership.role,
                ProjectMembership.user_id,
            )
            .join(
                Project,
                Project.name == ProjectMembership.project_id,
            )
            .where(Project.tenant_id == tenant, ProjectMembership.user_id.in_(identities))
        )
    ).all()
    access.projects = {project_id for project_id, _role, _user_id in memberships}
    access.project_admins = {project_id for project_id, role, _user_id in memberships if role == "admin"}
    access.human_projects = {
        project_id for project_id, _role, user_id in memberships if user_id == access.principal.username
    }
    access.human_project_admins = {
        project_id
        for project_id, role, user_id in memberships
        if user_id == access.principal.username and role == "admin"
    }
    role_rows = (
        await db.execute(
            select(RoleAssignment.role_name, RoleAssignment.user_id).where(
                RoleAssignment.tenant_id == tenant,
                RoleAssignment.user_id.in_(identities),
            )
        )
    ).all()
    access.roles = {role_name for role_name, _user_id in role_rows}
    access.human_roles = {role_name for role_name, user_id in role_rows if user_id == access.principal.username}
    if access.projects:
        campaign_rows = (
            await db.execute(
                select(
                    CampaignMembership.campaign_id,
                    CampaignMembership.project_id,
                )
                .join(
                    Campaign,
                    Campaign.id == CampaignMembership.campaign_id,
                )
                .where(Campaign.tenant_id == tenant, CampaignMembership.project_id.in_(access.projects))
            )
        ).all()
        access.campaigns = {str(campaign_id) for campaign_id, _project_id in campaign_rows}
        access.human_campaigns = {
            str(campaign_id) for campaign_id, project_id in campaign_rows if project_id in access.human_projects
        }
    return access


async def identity_in_use(db: AsyncSession, client_id, tenant_id):
    occupied = or_(
        select(MemoryNode.id)
        .where(
            MemoryNode.tenant_id == tenant_id,
            or_(MemoryNode.owner_id == client_id, MemoryNode.actor_id == client_id, MemoryNode.driver_id == client_id),
        )
        .exists(),
        select(ProjectMembership.id)
        .join(Project, Project.name == ProjectMembership.project_id)
        .where(
            Project.tenant_id == tenant_id,
            ProjectMembership.user_id == client_id,
        )
        .exists(),
        select(RoleAssignment.id)
        .where(
            RoleAssignment.tenant_id == tenant_id,
            RoleAssignment.user_id == client_id,
        )
        .exists(),
        select(CuratorRule.id)
        .where(
            CuratorRule.tenant_id == tenant_id,
            CuratorRule.layer == "user",
            CuratorRule.owner_id == client_id,
        )
        .exists(),
        select(ConversationThread.id)
        .where(
            ConversationThread.tenant_id == tenant_id,
            or_(
                ConversationThread.owner_id == client_id,
                ConversationThread.actor_id == client_id,
                ConversationThread.driver_id == client_id,
                client_id == any_(ConversationThread.participant_ids),
            ),
        )
        .exists(),
    )
    return (await db.execute(select(occupied))).scalar_one()


async def owner_binding_exists(db: AsyncSession, client_id, tenant):
    stmt = select(AgentOwner.client_id).where(AgentOwner.tenant_id == tenant, AgentOwner.client_id == client_id)
    return (await db.execute(stmt)).scalar_one_or_none() is not None
