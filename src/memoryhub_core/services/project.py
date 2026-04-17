"""Project membership resolution and auto-enrollment for RBAC.

Provides helpers that resolve which projects a user has access to,
based on project_memberships rows. Used by the authz layer and search
filters to include project-scoped memories in results.

Also provides auto-enrollment: when a user writes to a project they
are not yet a member of, ``ensure_project_membership`` creates the
project (if needed) and the membership row automatically — unless the
project is invite-only.
"""

import logging
import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from memoryhub_core.models.memory import MemoryNode
from memoryhub_core.models.project import Project, ProjectMembership
from memoryhub_core.services.exceptions import (
    LastAdminError,
    MembershipNotFoundError,
    ProjectAlreadyExistsError,
    ProjectInviteOnlyError,
    ProjectNotFoundError,
)

logger = logging.getLogger(__name__)


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


async def get_project(
    session: AsyncSession,
    project_name: str,
) -> Project | None:
    """Fetch a project by name, or None if it doesn't exist."""
    stmt = select(Project).where(Project.name == project_name)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def ensure_project_membership(
    session: AsyncSession,
    project_id: str,
    user_id: str,
    tenant_id: str,
    description: str | None = None,
) -> tuple[set[str], bool]:
    """Ensure the user is a member of the project, auto-enrolling if allowed.

    Returns:
        A tuple of (project_ids, was_auto_enrolled) where project_ids is
        the user's full set of project memberships after any enrollment.

    Raises:
        ProjectInviteOnlyError: If the project exists and is invite-only.
    """
    # Fast path: user is already a member.
    project_ids = await get_projects_for_user(session, user_id)
    if project_id in project_ids:
        return project_ids, False

    # Fetch or create the project.
    project = await get_project(session, project_id)
    if project is not None and project.invite_only:
        raise ProjectInviteOnlyError(project_id)

    if project is None:
        project = Project(
            name=project_id,
            description=description,
            created_by=user_id,
            tenant_id=tenant_id,
        )
        session.add(project)
        try:
            await session.flush()
        except IntegrityError:
            # Concurrent creation — project was created by another session.
            await session.rollback()
            project = await get_project(session, project_id)
            if project is not None and project.invite_only:
                raise ProjectInviteOnlyError(project_id) from None

    # Create the membership.
    membership = ProjectMembership(
        id=uuid.uuid4(),
        project_id=project_id,
        user_id=user_id,
        joined_by="auto-enroll",
    )
    session.add(membership)
    try:
        await session.flush()
    except IntegrityError:
        # Concurrent enrollment — membership was created by another session.
        await session.rollback()

    logger.info(
        "Auto-enrolled user %r in project %r", user_id, project_id,
    )

    # Re-query to get the authoritative membership set.
    project_ids = await get_projects_for_user(session, user_id)
    return project_ids, True


async def create_project(
    session: AsyncSession,
    name: str,
    tenant_id: str,
    created_by: str,
    description: str | None = None,
    invite_only: bool = False,
) -> Project:
    """Create a new project.

    Raises:
        ProjectAlreadyExistsError: If a project with this name already exists.
    """
    existing = await get_project(session, name)
    if existing is not None:
        raise ProjectAlreadyExistsError(name)

    project = Project(
        name=name,
        description=description,
        invite_only=invite_only,
        tenant_id=tenant_id,
        created_by=created_by,
    )
    session.add(project)

    # Auto-enroll the creator as admin.
    membership = ProjectMembership(
        id=uuid.uuid4(),
        project_id=name,
        user_id=created_by,
        role="admin",
        joined_by=created_by,
    )
    session.add(membership)

    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise ProjectAlreadyExistsError(name) from exc

    logger.info("Created project %r by %r", name, created_by)
    return project


async def get_project_members(
    session: AsyncSession,
    project_name: str,
) -> list[dict]:
    """Return all members of a project with their roles.

    Raises:
        ProjectNotFoundError: If the project does not exist.
    """
    project = await get_project(session, project_name)
    if project is None:
        raise ProjectNotFoundError(project_name)

    stmt = (
        select(ProjectMembership)
        .where(ProjectMembership.project_id == project_name)
        .order_by(ProjectMembership.joined_at)
    )
    result = await session.execute(stmt)
    members = result.scalars().all()

    return [
        {
            "user_id": m.user_id,
            "role": m.role,
            "joined_at": m.joined_at.isoformat() if m.joined_at else None,
        }
        for m in members
    ]


async def add_project_member(
    session: AsyncSession,
    project_name: str,
    user_id: str,
    added_by: str,
    role: str = "member",
) -> bool:
    """Add a user to a project.

    Returns True if the user was newly added, False if already a member.

    Raises:
        ProjectNotFoundError: If the project does not exist.
    """
    project = await get_project(session, project_name)
    if project is None:
        raise ProjectNotFoundError(project_name)

    membership = ProjectMembership(
        id=uuid.uuid4(),
        project_id=project_name,
        user_id=user_id,
        role=role,
        joined_by=added_by,
    )
    session.add(membership)
    try:
        await session.flush()
    except IntegrityError:
        # Already a member.
        await session.rollback()
        logger.info("User %r already a member of project %r", user_id, project_name)
        return False

    logger.info(
        "Added user %r to project %r as %r (by %r)",
        user_id, project_name, role, added_by,
    )
    return True


async def remove_project_member(
    session: AsyncSession,
    project_name: str,
    user_id: str,
) -> None:
    """Remove a user from a project.

    Raises:
        ProjectNotFoundError: If the project does not exist.
        MembershipNotFoundError: If the user is not a member.
        LastAdminError: If removing this user would leave no admins.
    """
    project = await get_project(session, project_name)
    if project is None:
        raise ProjectNotFoundError(project_name)

    stmt = (
        select(ProjectMembership)
        .where(
            ProjectMembership.project_id == project_name,
            ProjectMembership.user_id == user_id,
        )
    )
    result = await session.execute(stmt)
    membership = result.scalar_one_or_none()

    if membership is None:
        raise MembershipNotFoundError(project_name, user_id)

    # Guard: don't remove the last admin.
    if membership.role == "admin":
        admin_count_stmt = (
            select(func.count())
            .select_from(ProjectMembership)
            .where(
                ProjectMembership.project_id == project_name,
                ProjectMembership.role == "admin",
            )
        )
        admin_count_result = await session.execute(admin_count_stmt)
        if admin_count_result.scalar_one() <= 1:
            raise LastAdminError(project_name)

    await session.delete(membership)
    await session.flush()

    logger.info("Removed user %r from project %r", user_id, project_name)


async def list_projects_for_tenant(
    session: AsyncSession,
    tenant_id: str,
    user_id: str | None = None,
    include_all_open: bool = False,
) -> list[dict]:
    """List projects visible to a user within a tenant.

    Args:
        tenant_id: Tenant boundary for project visibility.
        user_id: The requesting user. Required when include_all_open=False.
        include_all_open: If True, return all open projects in the tenant
            (with an ``is_member`` flag), plus any invite-only projects the
            user belongs to. If False, return only the user's projects.

    Returns:
        List of project dicts with keys: name, description, invite_only,
        created_at, created_by, is_member.
    """
    if include_all_open:
        # All open projects + user's invite-only projects.
        stmt = select(Project).where(Project.tenant_id == tenant_id)
        result = await session.execute(stmt)
        projects = result.scalars().all()

        user_project_ids: set[str] = set()
        if user_id:
            user_project_ids = await get_projects_for_user(session, user_id)

        project_names = [p.name for p in projects]
        counts = await memory_counts(session, tenant_id, project_names)

        out = []
        for p in projects:
            is_member = p.name in user_project_ids
            # Skip invite-only projects the user is not a member of.
            if p.invite_only and not is_member:
                continue
            out.append({
                "name": p.name,
                "description": p.description,
                "invite_only": p.invite_only,
                "created_at": p.created_at.isoformat() if p.created_at else None,
                "created_by": p.created_by,
                "is_member": is_member,
                "memory_count": counts.get(p.name, 0),
            })
        return out

    # Default: only the user's projects.
    if not user_id:
        return []

    user_project_ids = await get_projects_for_user(session, user_id)
    if not user_project_ids:
        return []

    stmt = (
        select(Project)
        .where(Project.name.in_(user_project_ids))
        .where(Project.tenant_id == tenant_id)
    )
    result = await session.execute(stmt)
    projects = result.scalars().all()
    project_names = [p.name for p in projects]
    counts = await memory_counts(session, tenant_id, project_names)

    return [
        {
            "name": p.name,
            "description": p.description,
            "invite_only": p.invite_only,
            "created_at": p.created_at.isoformat() if p.created_at else None,
            "created_by": p.created_by,
            "is_member": True,
            "memory_count": counts.get(p.name, 0),
        }
        for p in projects
    ]


async def memory_counts(
    session: AsyncSession,
    tenant_id: str,
    project_names: list[str],
) -> dict[str, int]:
    """Count current project-scoped memories per project in one query."""
    if not project_names:
        return {}
    stmt = (
        select(MemoryNode.scope_id, func.count(MemoryNode.id))
        .where(MemoryNode.scope == "project")
        .where(MemoryNode.tenant_id == tenant_id)
        .where(MemoryNode.is_current.is_(True))
        .where(MemoryNode.scope_id.in_(project_names))
        .group_by(MemoryNode.scope_id)
    )
    result = await session.execute(stmt)
    return dict(result.all())
