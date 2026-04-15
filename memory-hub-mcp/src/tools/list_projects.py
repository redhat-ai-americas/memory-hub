"""List projects the caller belongs to or can discover."""

import logging
from typing import Annotated, Any

from fastmcp import Context
from fastmcp.exceptions import ToolError
from pydantic import Field

from src.core.app import mcp
from src.core.authz import (
    AuthenticationError,
    get_claims_from_context,
    get_tenant_filter,
)
from src.tools._deps import get_db_session, release_db_session

from memoryhub_core.services.project import list_projects_for_tenant

logger = logging.getLogger(__name__)

_VALID_FILTERS = {"mine", "all"}


@mcp.tool(
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    }
)
async def list_projects(
    filter: Annotated[
        str,
        Field(
            description=(
                "Which projects to return. "
                "'mine' (default) returns only projects you belong to. "
                "'all' also includes open projects you could join, "
                "with an is_member flag on each."
            ),
        ),
    ] = "mine",
    ctx: Context = None,
) -> dict[str, Any]:
    """List projects you belong to or that are available to join.

    Use filter='mine' (default) to see only your projects.
    Use filter='all' to also see open projects you could join by writing
    a project-scoped memory with that project_id (auto-enrollment).
    Invite-only projects you are not a member of are hidden.
    """
    try:
        claims = get_claims_from_context()
    except AuthenticationError:
        raise ToolError(
            "No authenticated session found. Call register_session first, "
            "or provide a JWT in the Authorization header."
        ) from None

    if filter not in _VALID_FILTERS:
        raise ToolError(
            f"Invalid filter value '{filter}'. Must be one of: mine, all."
        )

    tenant = get_tenant_filter(claims)

    gen = None
    try:
        session, gen = await get_db_session()
        projects = await list_projects_for_tenant(
            session,
            tenant_id=tenant,
            user_id=claims["sub"],
            include_all_open=(filter == "all"),
        )
        return {
            "projects": projects,
            "total": len(projects),
        }
    except ToolError:
        raise
    except Exception as exc:
        logger.error("Failed to list projects: %s", exc, exc_info=True)
        raise ToolError("Failed to list projects. See server logs.") from exc
    finally:
        if gen is not None:
            await release_db_session(gen)
