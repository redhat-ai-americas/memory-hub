"""Role assignment resolution for RBAC.

Provides helpers that resolve which roles a user holds, based on
role_assignments rows and (optionally) JWT claims. Used by the authz
layer and search filters to include role-scoped memories in results.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from memoryhub_core.models.role import RoleAssignment


async def get_roles_for_user(
    session: AsyncSession,
    user_id: str,
    tenant_id: str,
    claims: dict | None = None,
) -> set[str]:
    """Return the set of role names the user holds in this tenant.

    Merges two sources:
    1. role_assignments table (admin-managed, authoritative)
    2. JWT claims["roles"] list (when OAuth 2.1 auth server manages roles)

    Used by the search and authz layers to filter role-scoped memories.
    A user sees only memories whose scope_id matches one of their roles.
    """
    stmt = (
        select(RoleAssignment.role_name)
        .where(
            RoleAssignment.user_id == user_id,
            RoleAssignment.tenant_id == tenant_id,
        )
    )
    result = await session.execute(stmt)
    roles = {row[0] for row in result.all()}

    # Merge roles from JWT claims if available
    if claims:
        jwt_roles = claims.get("roles", [])
        if isinstance(jwt_roles, list):
            roles.update(jwt_roles)

    return roles
