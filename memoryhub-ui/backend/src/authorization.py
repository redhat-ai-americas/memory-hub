"""Human dashboard authorization, separate from MCP token scopes.

The OpenShift OAuth sidecar authenticates the human and overwrites
X-Forwarded-User. The application is bound to loopback in the deployment;
the peer check below also rejects direct calls to the application port.
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass, field
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from memoryhub_core.models.campaign import Campaign, CampaignMembership
from memoryhub_core.models.memory import MemoryNode
from memoryhub_core.models.project import Project, ProjectMembership
from memoryhub_core.models.role import RoleAssignment
from sqlalchemy import Column, Index, String, and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import declarative_base

from src.config import Settings, get_settings
from src.database import get_db

OwnerBase = declarative_base()
ADMIN_MODERATION_SCOPES = frozenset({"project", "campaign", "role", "organizational"})


class AgentOwner(OwnerBase):
    """Authorization binding; the OAuth client itself remains in auth service."""

    __tablename__ = "memoryhub_ui_agent_owners"

    tenant_id = Column(String(255), primary_key=True)
    client_id = Column(String(255), primary_key=True)
    owner = Column(String(255), nullable=False)
    __table_args__ = (Index("ix_memoryhub_ui_agent_owners_owner", "tenant_id", "owner"),)


@dataclass(frozen=True)
class Principal:
    username: str
    role: str
    tenant_id: str


def get_principal(request: Request, settings: Annotated[Settings, Depends(get_settings)]) -> Principal:
    peer = request.client.host if request.client else ""
    try:
        local = ipaddress.ip_address(peer).is_loopback
    except ValueError:
        local = False
    if not local:
        raise HTTPException(status_code=401, detail="OAuth proxy required")
    username = request.headers.get("x-forwarded-user", "").strip()
    if not username or len(username) > 255 or any(c in username for c in "\r\n\x00"):
        raise HTTPException(status_code=401, detail="Authenticated user required")
    admins = {item.strip() for item in settings.ui_admin_users.split(",") if item.strip()}
    allowed = {item.strip() for item in settings.ui_allowed_users.split(",") if item.strip()}
    if username not in admins and username not in allowed:
        raise HTTPException(status_code=403, detail="Tenant access forbidden")
    return Principal(username=username, role="admin" if username in admins else "user", tenant_id=settings.ui_tenant_id)


@dataclass
class Access:
    principal: Principal
    agents: set[str] = field(default_factory=set)
    projects: set[str] = field(default_factory=set)
    roles: set[str] = field(default_factory=set)
    campaigns: set[str] = field(default_factory=set)
    moderation_scopes: set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        if self.principal.role not in ("user", "admin"):
            raise ValueError("Unsupported dashboard role")
        self.moderation_scopes.intersection_update(ADMIN_MODERATION_SCOPES)

    @property
    def identities(self) -> set[str]:
        return {self.principal.username} | self.agents

    def clause(self, node=MemoryNode):
        """SQL predicate applied before graph/search/stats/contradiction rows leave DB."""
        if self.principal.role == "admin":
            return node.tenant_id == self.principal.tenant_id
        return and_(
            node.tenant_id == self.principal.tenant_id,
            node.status == "active",
            or_(
                and_(node.scope == "user", node.owner_id.in_(self.identities)),
                node.scope.in_(("organizational", "enterprise")),
                and_(node.scope == "project", node.scope_id.in_(self.projects)),
                and_(node.scope == "role", node.scope_id.in_(self.roles)),
                and_(node.scope == "campaign", node.owner_id.in_(self.campaigns)),
            ),
        )

    def can_read(self, node: MemoryNode) -> bool:
        if node.tenant_id != self.principal.tenant_id:
            return False
        if self.principal.role == "admin":
            return True  # metadata only for user-scope memories
        if node.status != "active":
            return False
        return (
            (node.scope == "user" and node.owner_id in self.identities)
            or node.scope in ("organizational", "enterprise")
            or (node.scope == "project" and node.scope_id in self.projects)
            or (node.scope == "role" and node.scope_id in self.roles)
            or (node.scope == "campaign" and node.owner_id in self.campaigns)
        )

    def can_delete(self, node: MemoryNode) -> bool:
        if node.tenant_id != self.principal.tenant_id:
            return False
        if self.principal.role == "admin":
            return node.scope in ADMIN_MODERATION_SCOPES and node.scope in self.moderation_scopes
        return (
            node.status == "active" and (
                (node.scope == "user" and node.owner_id in self.identities)
                or (node.scope == "project" and node.scope_id in self.projects)
            )
        )

    def hides_content(self, node: MemoryNode) -> bool:
        return self.principal.role == "admin" and node.scope == "user"

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
    scopes = {s.strip() for s in settings.ui_admin_moderation_scopes.split(",") if s.strip()}
    scopes &= ADMIN_MODERATION_SCOPES
    access = Access(principal=principal, moderation_scopes=scopes)
    if principal.role == "admin":
        return access
    tenant = principal.tenant_id
    # Explicit owner bindings are the only proof that an OAuth client belongs
    # to a person. Existing unbound clients remain admin-managed until linked.
    access.agents = set((await db.execute(select(AgentOwner.client_id).where(
        AgentOwner.tenant_id == tenant, AgentOwner.owner == principal.username,
    ))).scalars().all())
    identities = access.identities
    access.projects = set((await db.execute(select(ProjectMembership.project_id).join(
        Project, Project.name == ProjectMembership.project_id,
    ).where(Project.tenant_id == tenant, ProjectMembership.user_id.in_(identities)))).scalars().all())
    access.roles = set((await db.execute(select(RoleAssignment.role_name).where(
        RoleAssignment.tenant_id == tenant, RoleAssignment.user_id.in_(identities),
    ))).scalars().all())
    if access.projects:
        access.campaigns = {str(c) for c in (await db.execute(select(CampaignMembership.campaign_id).join(
            Campaign, Campaign.id == CampaignMembership.campaign_id,
        ).where(Campaign.tenant_id == tenant, CampaignMembership.project_id.in_(access.projects)))).scalars().all()}
    return access


AccessDep = Annotated[Access, Depends(get_access)]
