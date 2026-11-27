"""Human authorization policy shared by Core services and HTTP adapters.

Authentication and role provisioning belong to the transport. This module
accepts an already verified principal and explicit grants, never HTTP headers.
Agent token scopes cannot confer a direct human membership.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import and_, or_

from memoryhub_core.models.memory import MemoryNode

ADMIN_MODERATION_SCOPES = frozenset({"project", "campaign", "role", "organizational"})
ADMIN_VISIBLE_SCOPES = ADMIN_MODERATION_SCOPES


@dataclass(frozen=True)
class Principal:
    username: str
    role: str
    tenant_id: str


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
                and_(
                    node.scope == "project", "project" in self.moderation_scopes, node.scope_id.in_(self.human_projects)
                ),
                and_(node.scope == "role", "role" in self.moderation_scopes, node.scope_id.in_(self.human_roles)),
                and_(
                    node.scope == "campaign",
                    "campaign" in self.moderation_scopes,
                    node.owner_id.in_(self.human_campaigns),
                ),
            ),
        )

    def can_read(self, node: MemoryNode) -> bool:
        if node.tenant_id != self.principal.tenant_id:
            return False
        if self.principal.role == "admin":
            return node.scope in ADMIN_VISIBLE_SCOPES
        if node.status != "active":
            return False
        return (
            node.scope == "user"
            and node.owner_id in self.identities
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
            node.scope == "user"
            and node.owner_id in self.identities
            or (node.scope == "project" and node.scope_id in self.human_projects and (authored or project_admin))
        )

    def can_review(self, node: MemoryNode) -> bool:
        """Only an existing project admin grant permits a human review decision."""
        return (
            self.principal.role == "admin"
            and node.tenant_id == self.principal.tenant_id
            and (node.scope == "project")
            and (node.scope in self.moderation_scopes)
            and (node.scope_id in self.human_project_admins)
        )

    def can_resolve_report(self, node: MemoryNode, reporter: str) -> bool:
        """Publish review permission without exposing redacted author identities."""
        authors = {reporter, node.owner_id, node.actor_id, node.driver_id}
        return self.can_review(node) and (not self.identities.intersection(authors))

    def can_write(self, node: MemoryNode) -> bool:
        """A human write grant is independent of the MCP token scopes."""
        if (
            node.tenant_id != self.principal.tenant_id
            or node.status != "active"
            or node.deleted_at is not None
            or (not node.is_current)
        ):
            return False
        if self.principal.role == "user":
            return (
                node.scope == "user"
                and node.owner_id in self.identities
                or (node.scope == "project" and node.scope_id in self.human_projects)
            )
        return (
            node.scope == "project"
            and node.scope_id in self.human_project_admins
            or (node.scope == "organizational" and node.scope in self.admin_write_scopes)
        )

    def can_moderate(self, node: MemoryNode) -> bool:
        """Moderation requires an explicit category grant and object authority."""
        if (
            self.principal.role != "admin"
            or node.tenant_id != self.principal.tenant_id
            or node.deleted_at is not None
            or (node.scope not in self.moderation_scopes)
        ):
            return False
        if node.scope == "project":
            return node.scope_id in self.human_project_admins
        return node.scope == "organizational" and node.owner_id in self.identities

    def hides_content(self, node: MemoryNode) -> bool:
        if self.principal.role != "admin":
            return False
        return not (
            node.scope == "organizational"
            and "organizational" in self.moderation_scopes
            or (
                node.scope == "project"
                and "project" in self.moderation_scopes
                and (node.scope_id in self.human_projects)
            )
            or (node.scope == "role" and "role" in self.moderation_scopes and (node.scope_id in self.human_roles))
            or (
                node.scope == "campaign"
                and "campaign" in self.moderation_scopes
                and (node.owner_id in self.human_campaigns)
            )
        )

    @property
    def sees_individual_activity(self) -> bool:
        """Admins get no per-person activity: no counts, last-active times or
        per-person filters, which would show who works when and how much (#667)."""
        return self.principal.role != "admin"

    def visible_identity(self, identity: str | None) -> str | None:
        """Keep writer attribution out of administrator memory projections."""
        return identity if self.sees_individual_activity else None

    def can_see_content(self, node: MemoryNode) -> bool:
        return (
            node.tenant_id == self.principal.tenant_id
            and node.deleted_at is None
            and self.can_read(node)
            and not self.hides_content(node)
        )

    def can_edit_entity(self, node: MemoryNode) -> bool:
        return (
            self.principal.role == "user"
            and node.tenant_id == self.principal.tenant_id
            and node.scope == "entity"
            and node.owner_id == self.principal.username
            and node.status == "active"
            and node.deleted_at is None
            and node.is_current
        )

    def live_content_clause(self, node=MemoryNode):
        return and_(node.deleted_at.is_(None), self.content_clause(node))

    def search_grants(self) -> tuple[dict, set[str], set[str], set[str]]:
        """Core retrieval grants, using the same direct memberships as row policy."""
        scopes = {}
        if self.principal.role == "user":
            scopes.update(user=sorted(self.identities), organizational=None, enterprise=None)
            projects, roles, campaigns = self.human_projects, self.human_roles, self.human_campaigns
        else:
            projects = self.human_projects if "project" in self.moderation_scopes else set()
            roles = self.human_roles if "role" in self.moderation_scopes else set()
            campaigns = self.human_campaigns if "campaign" in self.moderation_scopes else set()
            if "organizational" in self.moderation_scopes:
                scopes["organizational"] = None
        if projects:
            scopes["project"] = sorted(projects)
        if roles:
            scopes["role"] = None
        if campaigns:
            scopes["campaign"] = None
        return scopes, projects, roles, campaigns

    def can_read_rule(self, rule) -> bool:
        if rule.tenant_id != self.principal.tenant_id:
            return False
        if rule.layer in ("system", "organizational"):
            return True
        # Personal rules (their names and patterns) belong to their owner only;
        # an Admin sees no personal data (#667, PR 710 review).
        return rule.layer == "user" and rule.owner_id == self.principal.username

    def can_change_rule(self, rule) -> bool:
        if rule.tenant_id != self.principal.tenant_id:
            return False
        if rule.layer == "user":
            return rule.owner_id == self.principal.username
        return self.principal.role == "admin" and rule.layer == "organizational"
