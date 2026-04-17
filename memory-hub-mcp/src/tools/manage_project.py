"""Consolidated project management tool (#166).

Replaces the previous list_projects tool. Provides list, create, describe,
add_member, and remove_member actions in a single tool, following Anthropic's
guidance on consolidating related operations.
"""

import logging
from typing import Annotated, Any

from fastmcp import Context
from fastmcp.exceptions import ToolError
from pydantic import Field

from memoryhub_core.services.exceptions import (
    LastAdminError,
    MembershipNotFoundError,
    ProjectAlreadyExistsError,
    ProjectNotFoundError,
)
from memoryhub_core.services.project import (
    add_project_member,
    create_project,
    get_project,
    get_project_members,
    list_projects_for_tenant,
    memory_counts,
    remove_project_member,
)
from src.core.app import mcp
from src.core.authz import (
    AuthenticationError,
    get_claims_from_context,
    get_tenant_filter,
)
from src.tools._deps import get_db_session, release_db_session

logger = logging.getLogger(__name__)

_VALID_ACTIONS = {"list", "create", "describe", "add_member", "remove_member"}
_VALID_FILTERS = {"mine", "all"}
_VALID_ROLES = {"member", "admin"}
_ACTIONS_REQUIRING_PROJECT = {"create", "describe", "add_member", "remove_member"}
_ACTIONS_REQUIRING_USER = {"add_member", "remove_member"}


def _require_param(action: str, name: str, value: str | None) -> str:
    """Validate that a required parameter is present for the given action."""
    if not value or not value.strip():
        raise ToolError(
            f"action='{action}' requires a {name}. "
            f"Example: manage_project(action='{action}', {name}='...')"
        )
    return value.strip()


@mcp.tool(
    annotations={
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    }
)
async def manage_project(
    action: Annotated[
        str,
        Field(
            description=(
                "The operation to perform. One of: "
                "'list' (discover projects), "
                "'create' (new project), "
                "'describe' (project details + members), "
                "'add_member' (add user to project), "
                "'remove_member' (remove user from project)."
            ),
        ),
    ],
    project_name: Annotated[
        str | None,
        Field(
            description=(
                "Project identifier. Required for create, describe, "
                "add_member, remove_member."
            ),
        ),
    ] = None,
    description: Annotated[
        str | None,
        Field(
            description="Project description. Used with action='create'.",
        ),
    ] = None,
    invite_only: Annotated[
        bool,
        Field(
            description=(
                "Enrollment policy. Used with action='create'. "
                "False (default): anyone can join by writing a project-scoped "
                "memory. True: members must be added explicitly."
            ),
        ),
    ] = False,
    filter: Annotated[
        str,
        Field(
            description=(
                "Used with action='list'. "
                "'mine' (default): only your projects. "
                "'all': also shows open projects you could join."
            ),
        ),
    ] = "mine",
    user_id: Annotated[
        str | None,
        Field(
            description=(
                "Target user. Required for add_member and remove_member."
            ),
        ),
    ] = None,
    role: Annotated[
        str,
        Field(
            description=(
                "Role for the user. Used with action='add_member'. "
                "One of: 'member' (default), 'admin'."
            ),
        ),
    ] = "member",
    ctx: Context = None,
) -> dict[str, Any]:
    """Manage projects: list, create, describe, add/remove members.

    Projects organize memories by team or topic. Use action='list' to discover
    projects, 'create' to start a new one, 'describe' to see details and
    members, and 'add_member'/'remove_member' to manage membership.

    Open projects allow auto-enrollment when writing project-scoped memories.
    Invite-only projects require explicit add_member by an admin.
    """
    try:
        claims = get_claims_from_context()
    except AuthenticationError:
        raise ToolError(
            "No authenticated session found. Call register_session first, "
            "or provide a JWT in the Authorization header."
        ) from None

    if action not in _VALID_ACTIONS:
        raise ToolError(
            f"Invalid action '{action}'. Must be one of: "
            f"{', '.join(sorted(_VALID_ACTIONS))}."
        )

    if action in _ACTIONS_REQUIRING_PROJECT:
        project_name = _require_param(action, "project_name", project_name)

    if action in _ACTIONS_REQUIRING_USER:
        user_id = _require_param(action, "user_id", user_id)

    if action == "list" and filter not in _VALID_FILTERS:
        raise ToolError(
            f"Invalid filter value '{filter}'. Must be one of: mine, all."
        )

    if action == "add_member" and role not in _VALID_ROLES:
        raise ToolError(
            f"Invalid role '{role}'. Must be one of: member, admin."
        )

    tenant = get_tenant_filter(claims)
    caller = claims["sub"]

    gen = None
    try:
        session, gen = await get_db_session()

        if action == "list":
            return await _handle_list(session, tenant, caller, filter)
        elif action == "create":
            return await _handle_create(
                session, tenant, caller, project_name, description, invite_only,
            )
        elif action == "describe":
            return await _handle_describe(session, tenant, project_name)
        elif action == "add_member":
            return await _handle_add_member(
                session, tenant, caller, project_name, user_id, role,
            )
        else:  # remove_member
            return await _handle_remove_member(
                session, caller, project_name, user_id,
            )

    except ToolError:
        raise
    except Exception as exc:
        logger.error("manage_project(%s) failed: %s", action, exc, exc_info=True)
        raise ToolError(
            f"Failed to {action} project. See server logs for details."
        ) from exc
    finally:
        if gen is not None:
            await release_db_session(gen)


async def _handle_list(
    session: Any, tenant: str, caller: str, filter_mode: str,
) -> dict[str, Any]:
    projects = await list_projects_for_tenant(
        session,
        tenant_id=tenant,
        user_id=caller,
        include_all_open=(filter_mode == "all"),
    )
    return {"projects": projects, "total": len(projects)}


async def _handle_create(
    session: Any,
    tenant: str,
    caller: str,
    name: str,
    desc: str | None,
    invite_only: bool,
) -> dict[str, Any]:
    try:
        project = await create_project(
            session,
            name=name,
            tenant_id=tenant,
            created_by=caller,
            description=desc,
            invite_only=invite_only,
        )
    except ProjectAlreadyExistsError:
        raise ToolError(
            f"Project '{name}' already exists. "
            "Use action='describe' to see its details."
        ) from None

    await session.commit()
    return {
        "project": {
            "name": project.name,
            "description": project.description,
            "invite_only": project.invite_only,
            "created_by": project.created_by,
        },
        "message": (
            f"Project '{name}' created. "
            f"{'Invite-only: members must be added explicitly.' if invite_only else 'Open: anyone can join by writing a project-scoped memory.'}"
        ),
    }


async def _handle_describe(
    session: Any, tenant: str, name: str,
) -> dict[str, Any]:
    project = await get_project(session, name)
    if project is None:
        raise ToolError(
            f"Project '{name}' not found. "
            "Use action='list' with filter='all' to see available projects."
        ) from None

    members = await get_project_members(session, name)
    counts = await memory_counts(session, tenant, [name])

    return {
        "project": {
            "name": project.name,
            "description": project.description,
            "invite_only": project.invite_only,
            "created_at": project.created_at.isoformat() if project.created_at else None,
            "created_by": project.created_by,
            "memory_count": counts.get(name, 0),
        },
        "members": members,
        "total_members": len(members),
    }


async def _handle_add_member(
    session: Any,
    tenant: str,
    caller: str,
    project_name: str,
    target_user: str,
    role: str,
) -> dict[str, Any]:
    project = await get_project(session, project_name)
    if project is None:
        raise ToolError(
            f"Project '{project_name}' not found. "
            "Use action='list' with filter='all' to see available projects."
        ) from None

    # Caller must be a member. Invite-only projects require admin role.
    caller_membership = await _get_membership(session, project_name, caller)
    if caller_membership is None:
        raise ToolError(
            f"You are not a member of project '{project_name}'. "
            "Join the project first by writing a project-scoped memory, "
            "or ask an admin to add you."
        )
    if project.invite_only and caller_membership.role != "admin":
        raise ToolError(
            f"Only project admins can add members to invite-only project "
            f"'{project_name}'."
        )

    try:
        was_added = await add_project_member(
            session, project_name, target_user, added_by=caller, role=role,
        )
    except ProjectNotFoundError:
        raise ToolError(
            f"Project '{project_name}' not found."
        ) from None

    await session.commit()
    if was_added:
        return {
            "message": (
                f"User '{target_user}' added to project '{project_name}' "
                f"as {role}."
            ),
        }
    return {
        "message": (
            f"User '{target_user}' is already a member of project "
            f"'{project_name}'."
        ),
    }


async def _handle_remove_member(
    session: Any,
    caller: str,
    project_name: str,
    target_user: str,
) -> dict[str, Any]:
    # Authorization: self-removal is always allowed; otherwise require admin.
    if caller != target_user:
        caller_membership = await _get_membership(session, project_name, caller)
        if caller_membership is None or caller_membership.role != "admin":
            raise ToolError(
                f"Only project admins can remove other members from "
                f"'{project_name}'. You can remove yourself by passing "
                f"your own user_id."
            )

    try:
        await remove_project_member(session, project_name, target_user)
    except ProjectNotFoundError:
        raise ToolError(
            f"Project '{project_name}' not found. "
            "Use action='list' with filter='all' to see available projects."
        ) from None
    except MembershipNotFoundError:
        raise ToolError(
            f"User '{target_user}' is not a member of project "
            f"'{project_name}'."
        ) from None
    except LastAdminError:
        raise ToolError(
            f"Cannot remove the last admin from project '{project_name}'. "
            "Promote another member to admin first."
        ) from None

    await session.commit()
    return {
        "message": f"User '{target_user}' removed from project '{project_name}'.",
    }


async def _get_membership(
    session: Any, project_name: str, user_id: str,
) -> Any | None:
    """Fetch a specific membership row, or None."""
    from sqlalchemy import select as sa_select

    from memoryhub_core.models.project import ProjectMembership

    stmt = sa_select(ProjectMembership).where(
        ProjectMembership.project_id == project_name,
        ProjectMembership.user_id == user_id,
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()
