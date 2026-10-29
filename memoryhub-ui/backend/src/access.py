"""Role-based access for dashboard reads.

Two rules, enforced here on the server so the browser never receives what a
viewer may not see:

* **Users** read memories through the same RBAC predicate agents get: their
  own user-scope memories, projects they belong to, roles assigned to them,
  campaigns their projects are enrolled in, and every organizational and
  enterprise memory.
* **Platform admins** (#667 tier 2) see every memory's metadata (scope,
  owner, writer, weight, version, links, flags, activity) and read and
  moderate the content of the scopes in the tenant's
  ``privacy.admin_readable_scopes`` — every scope except user by default.
  User-scope content is never readable to an admin.
* **Super-users** (#667 tier 3) are admins who may also open user-scope
  content, only while they hold a time-limited incident grant
  (``src.breakglass``). Every user memory revealed under a grant is audited
  with the incident reference and HIGH severity.

The open-mode ``operator`` (no sign-in configured, development only) keeps the
legacy tenant-wide view.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request
from memoryhub_core.models.campaign import CampaignMembership
from memoryhub_core.models.memory import MemoryNode
from memoryhub_core.models.project import ProjectMembership
from memoryhub_core.models.role import RoleAssignment
from sqlalchemy import false, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import Settings, get_settings
from src.ui_common import DEFAULT_TENANT_SETTINGS, Viewer, load_tenant_settings, viewer_from_request

HIDDEN_TEXT = "Content hidden"
OPEN_SCOPES_DEFAULT = tuple(DEFAULT_TENANT_SETTINGS["privacy"]["admin_readable_scopes"])
# Scopes an admin may ever be allowed to read; user scope needs a super-user grant.
ADMIN_SCOPES = ("project", "campaign", "role", "organizational", "enterprise")


# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------


def require_labs(settings: Annotated[Settings, Depends(get_settings)]) -> None:
    """Gate for MemoryHub Labs features (MEMORYHUB_UI_LABS)."""
    if not settings.ui_labs:
        raise HTTPException(
            status_code=404, detail="This is a MemoryHub Labs feature; set MEMORYHUB_UI_LABS=true to enable it"
        )


LabsDep = Depends(require_labs)


def current_viewer(request: Request, settings: Annotated[Settings, Depends(get_settings)]) -> Viewer:
    return viewer_from_request(request, settings)


def admin_viewer(request: Request, settings: Annotated[Settings, Depends(get_settings)]) -> Viewer:
    viewer = viewer_from_request(request, settings)
    if not viewer.can_admin:
        raise HTTPException(status_code=403, detail="Only platform admins can do this")
    return viewer


def content_viewer(request: Request, settings: Annotated[Settings, Depends(get_settings)]) -> Viewer:
    """For endpoints whose whole purpose is reading memory content."""
    viewer = viewer_from_request(request, settings)
    if viewer.redacts_content:
        raise HTTPException(
            status_code=403,
            detail="Memory content is confidential. Platform admins see metadata only; request break-glass access.",
        )
    return viewer


def legacy_viewer(request: Request, settings: Annotated[Settings, Depends(get_settings)]) -> Viewer:
    """The original (pre-redesign) read endpoints are not role-aware.

    They stay available in open development mode only; signed-in viewers use
    the dashboard endpoints, which filter and redact per role.
    """
    viewer = viewer_from_request(request, settings)
    if viewer.role != "operator":
        raise HTTPException(status_code=403, detail="This endpoint is not available to signed-in viewers")
    return viewer


ViewerDep = Annotated[Viewer, Depends(current_viewer)]
AdminDep = Annotated[Viewer, Depends(admin_viewer)]
ContentDep = Annotated[Viewer, Depends(content_viewer)]


# ---------------------------------------------------------------------------
# Read predicate for users
# ---------------------------------------------------------------------------


@dataclass
class Grants:
    identity: str
    projects: set[str] = field(default_factory=set)
    roles: set[str] = field(default_factory=set)
    campaigns: set[str] = field(default_factory=set)
    # The person's own agents (see ownership.py): their memories are the person's too.
    agents: set[str] = field(default_factory=set)
    tenant_id: str = "default"

    @property
    def identities(self) -> set[str]:
        return {self.identity} | self.agents


async def load_grants(db: AsyncSession, tenant_id: str, identity: str) -> Grants:
    from src.ownership import owned_agents

    agents = await owned_agents(db, tenant_id, identity)
    who = list({identity} | agents)
    projects = set(
        (await db.execute(select(ProjectMembership.project_id).where(ProjectMembership.user_id.in_(who))))
        .scalars()
        .all()
    )
    roles = set(
        (
            await db.execute(
                select(RoleAssignment.role_name).where(
                    RoleAssignment.user_id.in_(who), RoleAssignment.tenant_id == tenant_id
                )
            )
        )
        .scalars()
        .all()
    )
    campaigns: set[str] = set()
    if projects:
        campaigns = {
            str(c)
            for c in (
                await db.execute(
                    select(CampaignMembership.campaign_id).where(CampaignMembership.project_id.in_(list(projects)))
                )
            )
            .scalars()
            .all()
        }
    return Grants(
        identity=identity, projects=projects, roles=roles, campaigns=campaigns, agents=agents, tenant_id=tenant_id
    )


def readable_clause(grants: Grants, node=MemoryNode):
    """SQL read predicate for a person — the MCP server's rules (see ``src.authz``)."""
    from src.authz import read_clause

    return read_clause(grants, grants.tenant_id, node)


class _WithTenant:
    """Duck-typed memory for rows that do not carry ``tenant_id`` (already tenant-filtered)."""

    def __init__(self, n: Any, tenant_id: str):
        self.scope = n.scope
        self.scope_id = getattr(n, "scope_id", None)
        self.owner_id = n.owner_id
        self.tenant_id = getattr(n, "tenant_id", None) or tenant_id


def readable_python(grants: Grants):
    from src.authz import person_can_read

    def visible(n: Any) -> bool:
        return person_can_read(grants, grants.tenant_id, _WithTenant(n, grants.tenant_id))

    return visible


@dataclass
class Access:
    """Everything an endpoint needs to filter and redact for one viewer."""

    viewer: Viewer
    grants: Grants | None
    open_scopes: tuple[str, ...]
    # Active super-user incident grant (src.breakglass), when there is one.
    break_glass: dict | None = None

    @property
    def hidden_scopes(self) -> tuple[str, ...]:
        """Scopes whose content this viewer cannot read (shown as a capability hint)."""
        if not self.viewer.redacts_content:
            return ()
        return tuple(s for s in ("user", *ADMIN_SCOPES) if s not in self.open_scopes)

    def can_moderate(self, n: Any) -> bool:
        """Quarantine, restore or delete: admins only where they can read the content."""
        if not self.viewer.redacts_content:
            return self.can_read_row(n)
        return n.scope in self.open_scopes

    def ensure_moderatable(self, n: Any) -> None:
        if n is None:
            raise HTTPException(status_code=404, detail="Memory not found")
        if not self.can_moderate(n):
            raise HTTPException(
                status_code=403,
                detail=(
                    "User memories are private. Only a super-user with an incident reference can moderate them."
                    if n.scope == "user"
                    else f"Admins on this tenant cannot moderate {n.scope} memories"
                ),
            )

    def _reveal(self, item: dict, scope: str | None) -> None:
        if self.break_glass and scope == "user" and item.get("id"):
            from src.breakglass import record_reveal

            record_reveal(str(item["id"]), item.get("owner_id"))

    def clause(self, node=MemoryNode):
        """Extra WHERE clause, or None when the viewer is not row-restricted."""
        if self.grants is None:
            return None
        return readable_clause(self.grants, node)

    def filters(self, node=MemoryNode) -> list:
        clause = self.clause(node)
        return [clause] if clause is not None else []

    def can_read_row(self, n: Any) -> bool:
        if self.grants is None:
            return True
        return readable_python(self.grants)(n)

    def hides(self, scope: str | None) -> bool:
        return self.viewer.redacts_content and (scope or "") not in self.open_scopes

    def redact(self, item: dict, scope: str | None = None) -> dict:
        """Strip content-bearing fields from a serialised memory for admins."""
        own = scope if scope is not None else item.get("scope")
        if not self.hides(own):
            if self.viewer.redacts_content:
                self._reveal(item, own)
            item.setdefault("redacted", False)
            return item
        out = dict(item)
        sid = str(out.get("id", ""))
        short = f"mem_{sid.replace('-', '')[:4]}…{sid.replace('-', '')[-3:]}" if sid else "memory"
        for key in ("stub", "title"):
            if key in out:
                out[key] = short
        for key in ("content", "content_preview", "text", "observed_behavior", "memory_stub"):
            if key in out and out[key] is not None:
                out[key] = HIDDEN_TEXT
        if "domains" in out:
            out["domains"] = []
        if "entities" in out:
            out["entity_count"] = len(out["entities"] or [])
            out["entities"] = []
        if "metadata" in out:
            out["metadata"] = None
        out["redacted"] = True
        return out

    def redact_tree(self, obj: Any, scope: str | None = None) -> Any:
        """Redact every serialised memory inside a nested response.

        Dicts carrying ``content`` / ``stub`` / ``content_preview`` are memories;
        their own ``scope`` wins, otherwise they inherit the enclosing one (for
        versions and branches of a memory).
        """
        if not self.viewer.redacts_content:
            return obj
        if isinstance(obj, list):
            return [self.redact_tree(x, scope) for x in obj]
        if not isinstance(obj, dict):
            return obj
        own = obj.get("scope", scope)
        if any(k in obj for k in ("content", "content_preview", "stub", "observed_behavior", "memory_stub")):
            if self.hides(own):
                obj = self.redact(obj, own)
            else:
                self._reveal(obj, own)
        return {
            k: self.redact_tree(v, own) if isinstance(v, (list, dict)) and k != "metadata" else v
            for k, v in obj.items()
        }

    def ensure_readable(self, n: Any) -> None:
        if n is None or not self.can_read_row(n):
            raise HTTPException(status_code=404, detail="Memory not found")


async def access_for(db: AsyncSession, settings: Settings, viewer: Viewer) -> Access:
    grants = await load_grants(db, settings.ui_tenant_id, viewer.username) if viewer.restricted else None
    open_scopes = OPEN_SCOPES_DEFAULT
    grant = None
    if viewer.redacts_content:
        privacy = (await load_tenant_settings(db, settings.ui_tenant_id)).get("privacy", {})
        scopes = privacy.get("admin_readable_scopes")
        if isinstance(scopes, list):
            open_scopes = tuple(s for s in scopes if s in ADMIN_SCOPES)
        if viewer.is_superuser:
            from src.breakglass import active_grant, bind_request

            grant = await active_grant(db, settings.ui_tenant_id, viewer.username)
            if grant:
                open_scopes = ("user", *open_scopes)
                bind_request(viewer, grant, settings.ui_tenant_id)
    return Access(viewer=viewer, grants=grants, open_scopes=open_scopes, break_glass=grant)


def nothing():
    return false()
