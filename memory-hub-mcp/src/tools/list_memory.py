"""Enumerate memories without semantic ranking.

Returns memories ordered by created_at DESC for deterministic pagination.
No embedding cost. RBAC enforcement is identical to search_memory.
"""

import logging
from typing import Annotated, Any

from fastmcp import Context
from fastmcp.exceptions import ToolError
from pydantic import Field

from memoryhub_core.models.schemas import MemoryNodeRead, MemoryScope
from memoryhub_core.services.campaign import get_campaigns_for_project
from memoryhub_core.services.memory import list_memories
from memoryhub_core.services.project import get_projects_for_user
from memoryhub_core.services.role import get_roles_for_user
from src.core.app import mcp
from src.core.authz import (
    AuthenticationError,
    PROJECT_ISOLATION_ENABLED,
    ROLE_ISOLATION_ENABLED,
    build_authorized_scopes,
    get_claims_from_context,
    get_tenant_filter,
)
from src.tools._deps import get_db_session, release_db_session

logger = logging.getLogger(__name__)

VALID_SCOPES = {s.value for s in MemoryScope}


@mcp.tool(
    annotations={
        "readOnlyHint": True,
        "idempotentHint": True,
        "openWorldHint": False,
    }
)
async def list_memory(
    scope: Annotated[
        str | None,
        Field(description=(
            "Filter to a specific scope: user, project, campaign, role, "
            "organizational, enterprise. Omit to list all accessible scopes."
        )),
    ] = None,
    project_id: Annotated[
        str | None,
        Field(description="Project identifier. Limits results to this project."),
    ] = None,
    max_results: Annotated[
        int,
        Field(
            description="Maximum results to return (1-200).",
            ge=1,
            le=200,
        ),
    ] = 100,
    cursor: Annotated[
        str | None,
        Field(description=(
            "Pagination cursor from a previous list response. "
            "Pass next_cursor to get the next page."
        )),
    ] = None,
    include_branches: Annotated[
        bool,
        Field(description="If true, include branch memories. Default false."),
    ] = False,
    current_only: Annotated[
        bool,
        Field(description="If true, only returns current versions."),
    ] = True,
    content_type: Annotated[
        str | None,
        Field(
            description=(
                "(Advanced) Filter by content type. 'declarative' for facts and "
                "preferences, 'behavioral' for demonstrated patterns. Omit to list all types."
            ),
        ),
    ] = None,
    verbose: Annotated[
        bool,
        Field(
            description=(
                "Return full metadata per result. When False, returns only "
                "id + content, dramatically reducing token overhead. "
                "The unified memory() dispatcher defaults to False for agent callers."
            ),
        ),
    ] = True,
    ctx: Context = None,
) -> dict[str, Any]:
    """List memories in a scope without semantic search.

    Returns memories ordered by creation time (newest first). No embedding
    cost. Use this for enumeration, cleanup, and admin tooling. For
    discovery by meaning, use search instead.
    """
    try:
        claims = get_claims_from_context()
    except AuthenticationError as exc:
        raise ToolError(str(exc))

    authorized = build_authorized_scopes(claims)
    tenant = get_tenant_filter(claims)

    campaign_ids: set[str] | None = None
    if project_id:
        session_c, gen_c = await get_db_session()
        try:
            campaign_ids = await get_campaigns_for_project(
                session_c, project_id, tenant,
            )
        finally:
            await release_db_session(gen_c)

    project_ids: set[str] | None = None
    if PROJECT_ISOLATION_ENABLED:
        if project_id:
            project_ids = {project_id}
        else:
            session_p, gen_p = await get_db_session()
            try:
                project_ids = await get_projects_for_user(
                    session_p, claims["sub"],
                )
            finally:
                await release_db_session(gen_p)

    role_names: set[str] | None = None
    if ROLE_ISOLATION_ENABLED:
        session_r, gen_r = await get_db_session()
        try:
            role_names = await get_roles_for_user(
                session_r, claims["sub"], tenant, claims=claims,
            )
        finally:
            await release_db_session(gen_r)

    if scope is not None and scope not in VALID_SCOPES:
        raise ToolError(
            f"Invalid scope filter: '{scope}'. "
            f"Valid scopes: {', '.join(sorted(VALID_SCOPES))}."
        )

    session, gen = await get_db_session()
    try:
        results, next_cursor = await list_memories(
            session,
            tenant_id=tenant,
            scope=scope,
            owner_id=claims["sub"],
            max_results=max_results,
            cursor=cursor,
            current_only=current_only,
            authorized_scopes=authorized,
            campaign_ids=campaign_ids,
            project_ids=project_ids,
            role_names=role_names,
            content_type=content_type,
        )
    finally:
        await release_db_session(gen)

    formatted: list[dict[str, Any]] = []
    for item in results:
        if not include_branches and item.branch_type is not None:
            continue
        if verbose:
            entry = item.model_dump(mode="json")
            entry["result_type"] = "full" if isinstance(item, MemoryNodeRead) else "stub"
        else:
            entry = {"id": str(item.id)}
            if isinstance(item, MemoryNodeRead):
                entry["content"] = item.content
            else:
                entry["content"] = item.stub
        formatted.append(entry)

    return {
        "results": formatted,
        "count": len(formatted),
        "has_more": next_cursor is not None,
        "next_cursor": next_cursor,
    }
