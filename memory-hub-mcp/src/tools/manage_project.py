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
    InvalidProjectPolicyError,
    LastAdminError,
    MembershipNotFoundError,
    ProjectAlreadyExistsError,
    ProjectNotFoundError,
)
from memoryhub_core.services.project import (
    provisioning_mode,
    add_project_member,
    archive_project,
    create_project,
    delete_project,
    get_project,
    get_project_members,
    list_projects_for_tenant,
    memory_counts,
    remove_project_member,
    unarchive_project,
    update_member_role,
    update_project,
    validate_policies,
)
from src.core.app import mcp
from src.core.authz import (
    AuthenticationError,
    get_claims_from_context,
    get_tenant_filter,
)
from src.tools._deps import get_db_session, release_db_session

logger = logging.getLogger(__name__)

_VALID_ACTIONS = {
    "list", "create", "describe", "add_member", "remove_member",
    "update", "archive", "unarchive", "delete", "set_role",
}
_VALID_FILTERS = {"mine", "all"}
_VALID_ROLES = {"member", "admin"}
# Central provisioning: who may create projects and manage any project's members.
_PROVISIONING_SCOPES = {"memory:admin", "project:admin"}


def _can_provision(claims: dict) -> bool:
    return bool(_PROVISIONING_SCOPES & set(claims.get("scopes", [])))
_ACTIONS_REQUIRING_PROJECT = {
    "create", "describe", "add_member", "remove_member",
    "update", "archive", "unarchive", "delete", "set_role",
}
_ACTIONS_REQUIRING_USER = {"add_member", "remove_member", "set_role"}


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
                "'remove_member' (remove user from project), "
                "'update' (description, enrollment, policies), "
                "'archive' / 'unarchive' (read-only on/off), "
                "'delete' (soft-delete with all project memories), "
                "'set_role' (member or admin)."
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
            description="Project description. Used with action='create' or 'update'.",
        ),
    ] = None,
    invite_only: Annotated[
        bool | None,
        Field(
            description=(
                "Enrollment policy. Used with action='create' or 'update'. With central "
                "provisioning (the default) members are always added "
                "explicitly. In self-service mode, False lets anyone join by "
                "writing a project-scoped memory; True requires an invitation."
            ),
        ),
    ] = None,
    filter: Annotated[  # noqa: A002
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
                "Role for the user. Used with action='add_member' or 'set_role'. "
                "One of: 'member' (default), 'admin'."
            ),
        ),
    ] = "member",
    policies: Annotated[
        dict[str, Any] | None,
        Field(
            description=(
                "Project policies, used with action='create' or 'update': "
                "ttl_days (new memories go stale after N days), max_memories "
                "(cap on current memories), default_weight (0.0-1.0 for writes "
                "that set no weight). Set a key to null to remove it."
            ),
        ),
    ] = None,
    ctx: Context = None,
) -> dict[str, Any]:
    """Manage projects: list, create, describe, members, lifecycle and policies.

    Projects organize memories by team or topic. Use action='list' to discover
    projects, 'create' to start a new one, 'describe' to see details and
    members, and 'add_member'/'remove_member' to manage membership.

    With central provisioning (MEMORYHUB_PROJECT_PROVISIONING=central, the
    default) only administrators (memory:admin or project:admin) create
    projects, and project admins add members; writing to a project never
    creates or joins it. In self-service mode open projects allow
    auto-enrollment when writing project-scoped memories, and invite-only
    projects require explicit add_member by an admin.

    Lifecycle: project admins (and memory:admin / project:admin holders)
    update, archive, unarchive and change roles. An archived project is
    read-only: its memories stay readable, writes and updates are refused.
    Deleting soft-deletes the project and every memory in it and needs
    memory:admin or project:admin; prefer archiving. A deleted project's name
    is never reused.
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
            if provisioning_mode() == "central" and not _can_provision(claims):
                raise ToolError(
                    "Projects are created by a MemoryHub administrator on this deployment. "
                    "Ask your admin to create the project and add you, then use "
                    "action='list' to see the projects you belong to."
                )
            result = await _handle_create(
                session, tenant, caller, project_name, description, bool(invite_only),
            )
            if policies:
                await _apply_update(session, project_name, None, None, policies)
                await session.commit()
                result["project"]["policies"] = validate_policies(policies)
            return result
        elif action == "describe":
            return await _handle_describe(session, tenant, project_name)
        elif action == "add_member":
            return await _handle_add_member(
                session, tenant, caller, project_name, user_id, role,
                provisioner=_can_provision(claims),
            )
        elif action == "remove_member":
            return await _handle_remove_member(
                session, caller, project_name, user_id,
                provisioner=_can_provision(claims),
            )
        else:
            return await _handle_lifecycle(
                session, tenant, caller, action, project_name,
                provisioner=_can_provision(claims),
                description=description, invite_only=invite_only,
                policies=policies, user_id=user_id, role=role,
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
            f"{_enrollment_note(invite_only)}"
        ),
    }


async def _apply_update(session, name, description, invite_only, policies):
    try:
        return await update_project(
            session, name, description=description, invite_only=invite_only, policies=policies,
        )
    except InvalidProjectPolicyError as exc:
        raise ToolError(str(exc)) from None


async def _handle_lifecycle(
    session: Any,
    tenant: str,
    caller: str,
    action: str,
    name: str,
    *,
    provisioner: bool,
    description: str | None,
    invite_only: bool | None,
    policies: dict | None,
    user_id: str | None,
    role: str,
) -> dict[str, Any]:
    """update / archive / unarchive / set_role (project admins) and delete (provisioners)."""
    project = await get_project(session, name)
    if project is None or project.tenant_id != tenant:
        raise ToolError(f"Project '{name}' not found. Use action='list' to see your projects.")
    if action == "delete":
        if not provisioner:
            raise ToolError(
                "Deleting a project removes every memory in it, so it needs memory:admin or "
                "project:admin. Project admins can archive it instead (action='archive')."
            )
        result = await delete_project(session, name, tenant, by=caller)
        await session.commit()
        return {**result, "message": f"Project '{name}' and {result['memories_deleted']} memories deleted."}

    membership = await _get_membership(session, name, caller)
    if not provisioner and (membership is None or membership.role != "admin"):
        raise ToolError(f"Only project admins can {action.replace('_', ' ')} project '{name}'.")

    if action == "update":
        if description is None and invite_only is None and policies is None:
            raise ToolError("action='update' needs description, invite_only or policies.")
        project = await _apply_update(session, name, description, invite_only, policies)
        await session.commit()
        return {
            "project": {
                "name": project.name,
                "description": project.description,
                "invite_only": project.invite_only,
                "policies": dict(project.policies or {}),
            },
            "message": f"Project '{name}' updated.",
        }
    if action == "archive":
        project = await archive_project(session, name, by=caller)
        await session.commit()
        return {
            "project": {"name": name, "archived_at": project.archived_at.isoformat()},
            "message": f"Project '{name}' archived: its memories stay readable, new writes are refused.",
        }
    if action == "unarchive":
        await unarchive_project(session, name)
        await session.commit()
        return {"project": {"name": name, "archived_at": None}, "message": f"Project '{name}' is writable again."}

    # set_role
    if role not in _VALID_ROLES:
        raise ToolError(f"Invalid role '{role}'. Must be one of: member, admin.")
    try:
        changed = await update_member_role(session, name, user_id, role)
    except MembershipNotFoundError:
        raise ToolError(f"User '{user_id}' is not a member of project '{name}'.") from None
    except LastAdminError:
        raise ToolError(
            f"'{user_id}' is the last admin of project '{name}'. Make another member admin first."
        ) from None
    await session.commit()
    return {
        "message": (
            f"'{user_id}' is now {role} of project '{name}'."
            if changed
            else f"'{user_id}' already is {role} of project '{name}'."
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
            "archived": getattr(project, "archived_at", None) is not None,
            "policies": dict(getattr(project, "policies", None) or {}),
        },
        "members": members,
        "total_members": len(members),
    }


def _enrollment_note(invite_only: bool) -> str:
    if provisioning_mode() == "central":
        return "Members are added explicitly with action='add_member'."
    if invite_only:
        return "Invite-only: members must be added explicitly."
    return "Open: anyone can join by writing a project-scoped memory."


async def _handle_add_member(
    session: Any,
    tenant: str,
    caller: str,
    project_name: str,
    target_user: str,
    role: str,
    provisioner: bool = False,
) -> dict[str, Any]:
    project = await get_project(session, project_name)
    if project is None:
        raise ToolError(
            f"Project '{project_name}' not found. "
            "Use action='list' with filter='all' to see available projects."
        ) from None

    # Caller must be a member. Invite-only projects require admin role; with
    # central provisioning every project does, unless the caller provisions.
    caller_membership = await _get_membership(session, project_name, caller)
    central = provisioning_mode() == "central"
    if central and provisioner:
        caller_membership = caller_membership or _Provisioner()
    if caller_membership is None:
        raise ToolError(
            f"You are not a member of project '{project_name}'. "
            + ("Ask a project admin to add you." if central else
               "Join the project first by writing a project-scoped memory, "
               "or ask an admin to add you.")
        )
    if central and caller_membership.role != "admin":
        raise ToolError(
            f"Only project admins can add members to project '{project_name}'."
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
    provisioner: bool = False,
) -> dict[str, Any]:
    # Authorization: self-removal is always allowed; otherwise require admin
    # (a deployment administrator counts as one under central provisioning).
    if caller != target_user and not (provisioner and provisioning_mode() == "central"):
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


class _Provisioner:
    """Stand-in membership for a deployment administrator managing any project."""

    role = "admin"
