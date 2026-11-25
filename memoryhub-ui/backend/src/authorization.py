"""Human dashboard authorization, separate from MCP token scopes.

Identity and entitlement are resolved in ``src.identity``; this module
decides data access. The OpenShift OAuth sidecar authenticates the human;
the application is bound to loopback in the deployment and the identity
provider also rejects direct calls to the application port.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from memoryhub_core.models.campaign import Campaign, CampaignMembership
from memoryhub_core.models.memory import MemoryNode
from memoryhub_core.models.project import Project, ProjectMembership
from memoryhub_core.models.role import RoleAssignment
from sqlalchemy import Column, Index, String, and_, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import declarative_base

from src.config import Settings, get_settings
from src.database import get_db
from src.human_identity import profile_for
from src.identity import entitlement_resolver_for, identity_provider_for

logger = logging.getLogger(__name__)
OwnerBase = declarative_base()
ADMIN_MODERATION_SCOPES = frozenset({"project", "campaign", "role", "organizational"})
# Enterprise approval/moderation is not implemented in the human dashboard.
# Keep its metadata out of Admin views as well as its content and mutations.
ADMIN_VISIBLE_SCOPES = ADMIN_MODERATION_SCOPES


class AgentOwner(OwnerBase):
    """Authorization binding; the OAuth client itself remains in auth service."""

    __tablename__ = "memoryhub_ui_agent_owners"

    tenant_id = Column(String(255), primary_key=True)
    client_id = Column(String(255), primary_key=True)
    owner = Column(String(255), nullable=False)
    __table_args__ = (Index("ix_memoryhub_ui_agent_owners_owner", "tenant_id", "owner"),)


@dataclass(frozen=True)
class Principal:
    username: str  # display name; ownership and memberships still use it
    role: str
    tenant_id: str
    # Durable internal id (human_identities.id) when roles come from OpenShift
    # RBAC; None in the lists and local modes, which have no durable subject.
    user_id: str | None = None


async def get_principal(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Principal:
    """Identity first, then entitlement; data access is decided later by ``Access``."""
    problem = settings.identity_problem()
    if problem:
        raise HTTPException(status_code=503, detail=problem)
    authn = await identity_provider_for(settings).authenticate(request)
    role = await entitlement_resolver_for(settings).resolve(authn)
    if role not in ("user", "admin"):
        raise HTTPException(status_code=403, detail="Unsupported dashboard role")
    user_id = None
    if settings.ui_role_source == "openshift-rbac":
        # Just-in-time profile of a person who has already been admitted;
        # refused when the username belongs to a different account.
        try:
            profile = await profile_for(db, settings.ui_tenant_id, authn.identity, refresh=authn.fresh)
        except SQLAlchemyError:
            logger.exception("Could not read the dashboard profile of %r", authn.identity.username)
            raise HTTPException(status_code=503, detail="Profile store unavailable") from None
        user_id = profile.id
    return Principal(username=authn.identity.username, role=role, tenant_id=settings.ui_tenant_id,
                     user_id=user_id)


@dataclass
class Access:
    principal: Principal
    agents: set[str] = field(default_factory=set)
    projects: set[str] = field(default_factory=set)
    project_admins: set[str] = field(default_factory=set)
    human_projects: set[str] = field(default_factory=set)
    human_project_admins: set[str] = field(default_factory=set)
    roles: set[str] = field(default_factory=set)
    campaigns: set[str] = field(default_factory=set)
    human_roles: set[str] = field(default_factory=set)
    human_campaigns: set[str] = field(default_factory=set)
    moderation_scopes: set[str] = field(default_factory=set)
    admin_write_scopes: set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        if self.principal.role not in ("user", "admin"):
            raise ValueError("Unsupported dashboard role")
        self.moderation_scopes.intersection_update(ADMIN_MODERATION_SCOPES)
        self.admin_write_scopes.intersection_update(ADMIN_MODERATION_SCOPES)

    @property
    def identities(self) -> set[str]:
        return {self.principal.username} | self.agents

    def clause(self, node=MemoryNode):
        """SQL predicate applied before graph/search/stats/contradiction rows leave DB.

        Admins never see user-scope (personal) memories, not even their
        metadata: IDs, owners, timestamps and counts stay out of every admin
        path that is built on this predicate or on ``can_read`` (#667).
        """
        if self.principal.role == "admin":
            return and_(node.tenant_id == self.principal.tenant_id, node.scope.in_(ADMIN_VISIBLE_SCOPES))
        return and_(
            node.tenant_id == self.principal.tenant_id,
            node.status == "active",
            or_(
                and_(node.scope == "user", node.owner_id.in_(self.identities)),
                node.scope.in_(("organizational", "enterprise")),
                and_(node.scope == "project", node.scope_id.in_(self.human_projects)),
                and_(node.scope == "role", node.scope_id.in_(self.human_roles)),
                and_(node.scope == "campaign", node.owner_id.in_(self.human_campaigns)),
            ),
        )

    def content_clause(self, node=MemoryNode):
        """SQL visibility for operations that inspect memory content."""
        if self.principal.role == "user":
            return self.clause(node)
        return and_(
            node.tenant_id == self.principal.tenant_id,
            or_(
                and_(node.scope == "organizational", "organizational" in self.moderation_scopes),
                and_(node.scope == "project", "project" in self.moderation_scopes,
                     node.scope_id.in_(self.human_projects)),
                and_(node.scope == "role", "role" in self.moderation_scopes,
                     node.scope_id.in_(self.human_roles)),
                and_(node.scope == "campaign", "campaign" in self.moderation_scopes,
                     node.owner_id.in_(self.human_campaigns)),
            ),
        )

    def can_read(self, node: MemoryNode) -> bool:
        if node.tenant_id != self.principal.tenant_id:
            return False
        if self.principal.role == "admin":
            # Shared scopes only; metadata of personal memories is not an admin's (#667).
            return node.scope in ADMIN_VISIBLE_SCOPES
        if node.status != "active":
            return False
        return (
            (node.scope == "user" and node.owner_id in self.identities)
            or node.scope in ("organizational", "enterprise")
            or (node.scope == "project" and node.scope_id in self.human_projects)
            or (node.scope == "role" and node.scope_id in self.human_roles)
            or (node.scope == "campaign" and node.owner_id in self.human_campaigns)
        )

    def can_delete(self, node: MemoryNode) -> bool:
        if node.tenant_id != self.principal.tenant_id:
            return False
        if node.status != "active":
            return False
        authored = node.owner_id in self.identities or getattr(node, "actor_id", None) in self.identities
        project_admin = node.scope == "project" and node.scope_id in self.human_project_admins
        if self.principal.role == "admin":
            if node.scope not in self.moderation_scopes:
                return False
            if node.scope == "project":
                return node.scope_id in self.human_projects and (authored or project_admin)
            if node.scope == "campaign":
                return node.owner_id in self.human_campaigns and authored
            if node.scope == "role":
                return node.scope_id in self.human_roles and authored
            return node.scope == "organizational" and authored
        return (
            (node.scope == "user" and node.owner_id in self.identities)
            or (node.scope == "project" and node.scope_id in self.human_projects and (authored or project_admin))
        )

    def can_review(self, node: MemoryNode) -> bool:
        """Only an existing project admin grant permits a human review decision."""
        return (
            self.principal.role == "admin"
            and node.tenant_id == self.principal.tenant_id
            and node.scope == "project"
            and node.scope in self.moderation_scopes
            and node.scope_id in self.human_project_admins
        )

    def can_write(self, node: MemoryNode) -> bool:
        """A human write grant is independent of the MCP token scopes."""
        if (node.tenant_id != self.principal.tenant_id or node.status != "active"
                or node.deleted_at is not None or not node.is_current):
            return False
        if self.principal.role == "user":
            return (
                (node.scope == "user" and node.owner_id in self.identities)
                or (node.scope == "project" and node.scope_id in self.human_projects)
            )
        return (
            (node.scope == "project" and node.scope_id in self.human_project_admins)
            or (node.scope == "organizational" and node.scope in self.admin_write_scopes)
        )

    def can_moderate(self, node: MemoryNode) -> bool:
        """Moderation requires an explicit category grant and object authority."""
        if (self.principal.role != "admin" or node.tenant_id != self.principal.tenant_id
                or node.deleted_at is not None or node.scope not in self.moderation_scopes):
            return False
        if node.scope == "project":
            return node.scope_id in self.human_project_admins
        return node.scope == "organizational" and node.owner_id in self.identities

    def hides_content(self, node: MemoryNode) -> bool:
        if self.principal.role != "admin":
            return False
        return not (
            (node.scope == "organizational" and "organizational" in self.moderation_scopes)
            or (node.scope == "project" and "project" in self.moderation_scopes
                and node.scope_id in self.human_projects)
            or (node.scope == "role" and "role" in self.moderation_scopes
                and node.scope_id in self.human_roles)
            or (node.scope == "campaign" and "campaign" in self.moderation_scopes
                and node.owner_id in self.human_campaigns)
        )

    @property
    def sees_individual_activity(self) -> bool:
        """Admins get no per-person activity: no counts, last-active times or
        per-person filters, which would show who works when and how much (#667)."""
        return self.principal.role != "admin"

    def forbid_person_filter(self, *values) -> None:
        if not self.sees_individual_activity and any(values):
            raise HTTPException(status_code=403, detail="Per-person filters are not available to admins")

    def visible_identity(self, identity: str | None) -> str | None:
        """Keep writer attribution out of administrator memory projections."""
        return identity if self.sees_individual_activity else None

    def require_read(self, node: MemoryNode) -> None:
        if not self.can_read(node):
            raise HTTPException(status_code=404, detail="Memory not found")

    def require_delete(self, node: MemoryNode) -> None:
        if not self.can_delete(node):
            raise HTTPException(status_code=403, detail="Memory delete forbidden")


async def get_access(
    principal: Annotated[Principal, Depends(get_principal)],
    db: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> Access:
    if principal.role not in ("user", "admin"):
        raise HTTPException(status_code=403, detail="Unsupported dashboard role")
    scopes = {s.strip() for s in settings.ui_admin_moderation_scopes.split(",") if s.strip()}
    scopes &= ADMIN_MODERATION_SCOPES
    write_scopes = {s.strip() for s in settings.ui_admin_write_scopes.split(",") if s.strip()}
    access = Access(
        principal=principal,
        moderation_scopes=scopes,
        admin_write_scopes=write_scopes,
    )
    tenant = principal.tenant_id
    # Explicit owner bindings are the only proof that an OAuth client belongs
    # to a person. Existing unbound clients remain admin-managed until linked.
    access.agents = set((await db.execute(select(AgentOwner.client_id).where(
        AgentOwner.tenant_id == tenant, AgentOwner.owner == principal.username,
    ))).scalars().all())
    identities = access.identities
    memberships = (await db.execute(select(
        ProjectMembership.project_id, ProjectMembership.role, ProjectMembership.user_id,
    ).join(
        Project, Project.name == ProjectMembership.project_id,
    ).where(Project.tenant_id == tenant, ProjectMembership.user_id.in_(identities)))).all()
    access.projects = {project_id for project_id, _role, _user_id in memberships}
    access.project_admins = {project_id for project_id, role, _user_id in memberships if role == "admin"}
    access.human_projects = {
        project_id for project_id, _role, user_id in memberships if user_id == principal.username
    }
    access.human_project_admins = {
        project_id for project_id, role, user_id in memberships
        if user_id == principal.username and role == "admin"
    }
    role_rows = (await db.execute(select(RoleAssignment.role_name, RoleAssignment.user_id).where(
        RoleAssignment.tenant_id == tenant, RoleAssignment.user_id.in_(identities),
    ))).all()
    access.roles = {role_name for role_name, _user_id in role_rows}
    access.human_roles = {role_name for role_name, user_id in role_rows if user_id == principal.username}
    if access.projects:
        campaign_rows = (await db.execute(select(
            CampaignMembership.campaign_id, CampaignMembership.project_id,
        ).join(
            Campaign, Campaign.id == CampaignMembership.campaign_id,
        ).where(Campaign.tenant_id == tenant, CampaignMembership.project_id.in_(access.projects)))).all()
        access.campaigns = {str(campaign_id) for campaign_id, _project_id in campaign_rows}
        access.human_campaigns = {
            str(campaign_id) for campaign_id, project_id in campaign_rows if project_id in access.human_projects
        }
    return access


AccessDep = Annotated[Access, Depends(get_access)]
