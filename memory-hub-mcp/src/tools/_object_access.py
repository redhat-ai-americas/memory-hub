"""Object-level MCP permissions for operations that mutate existing memories."""

from src.core.authz import authorize_read, authorize_write

from memoryhub_core.services.campaign import get_campaigns_for_project
from memoryhub_core.services.project import get_projects_for_user_in_tenant
from memoryhub_core.services.role import get_roles_for_user


async def memory_object_access(session, claims: dict, node, project_id: str | None = None) -> tuple[bool, bool]:
    """Return (can_read, can_write) using the target object's actual scope."""
    tenant = claims.get("tenant_id", "default")
    if node.tenant_id != tenant:
        return False, False

    tier = node.scope.value if hasattr(node.scope, "value") else node.scope
    project_ids = None
    campaign_ids = None
    role_names = None
    if tier in ("project", "campaign"):
        project_ids = await get_projects_for_user_in_tenant(session, claims["sub"], tenant)
    # A caller cannot name someone else's enrolled project as proof of access.
    if tier == "campaign" and project_id and project_id in project_ids:
        campaign_ids = await get_campaigns_for_project(session, project_id, tenant)
    if tier == "role":
        role_names = await get_roles_for_user(session, claims["sub"], tenant, claims=claims)

    can_read = authorize_read(
        claims,
        node,
        campaign_ids=campaign_ids,
        project_ids=project_ids,
        role_names=role_names,
    )
    can_write = authorize_write(
        claims,
        tier,
        node.owner_id,
        node.tenant_id,
        campaign_ids=campaign_ids,
        project_ids=project_ids,
        role_names=role_names,
        scope_id=getattr(node, "scope_id", None),
    )
    return can_read, can_write
