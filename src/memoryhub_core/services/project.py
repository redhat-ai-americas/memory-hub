"""Project membership resolution for RBAC.

Provides helpers that resolve which projects a user has access to,
based on project_memberships rows. Used by the authz layer and search
filters to include project-scoped memories in results.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from memoryhub_core.models.project import ProjectMembership


async def get_projects_for_user(
    session: AsyncSession,
    user_id: str,
) -> set[str]:
    """Return the set of project IDs the user is a member of.

    Used by the search and authz layers to filter project-scoped memories.
    A user sees only memories whose scope_id matches one of their projects.
    """
    stmt = (
        select(ProjectMembership.project_id)
        .where(ProjectMembership.user_id == user_id)
    )
    result = await session.execute(stmt)
    return {row[0] for row in result.all()}
