"""Get the full version history of a memory."""

import uuid
from typing import Annotated

from fastmcp import Context
from fastmcp.exceptions import ToolError
from pydantic import Field

from src.core.app import mcp
from src.core.authz import (
    AuthenticationError,
    authorize_read,
    get_claims_from_context,
    get_tenant_filter,
)
from src.tools._deps import get_db_session, release_db_session

from memoryhub_core.services.exceptions import MemoryNotFoundError
from memoryhub_core.services.memory import get_memory_history as _get_memory_history
from memoryhub_core.services.memory import read_memory as _read_memory


@mcp.tool(
    annotations={
        "readOnlyHint": True,
        "idempotentHint": True,
        "openWorldHint": False,
    }
)
async def get_memory_history(
    memory_id: Annotated[
        str,
        Field(
            description=(
                "The ID of any version of the memory (current or historical). "
                "The tool traces the full version chain regardless of which "
                "version ID you provide."
            ),
        ),
    ],
    max_versions: Annotated[
        int,
        Field(
            description="Maximum number of versions to return per page (1-100).",
            ge=1,
            le=100,
        ),
    ] = 20,
    offset: Annotated[
        int,
        Field(
            description="Number of versions to skip from newest. Use for pagination.",
            ge=0,
        ),
    ] = 0,
    ctx: Context = None,
) -> dict:
    """Get the version history of a memory with pagination.

    Shows how the memory evolved over time: what changed, when, and what the
    previous content was. Supports forensics ("what did the agent believe on
    March 15th?") and helps agents understand context drift.

    Returns versions ordered newest-first with full content for each version.
    Use offset/max_versions for pagination on long-lived memories.
    """
    if ctx:
        await ctx.info(f"Fetching version history for memory {memory_id}")

    try:
        parsed_id = uuid.UUID(memory_id)
    except ValueError:
        raise ToolError(
            f"Invalid memory_id format: '{memory_id}'. "
            "Provide a valid UUID (e.g., '550e8400-e29b-41d4-a716-446655440000')."
        )

    try:
        claims = get_claims_from_context()
    except AuthenticationError as exc:
        raise ToolError(str(exc))
    tenant = get_tenant_filter(claims)

    session, gen = await get_db_session()
    try:
        # Authorize against the memory itself before revealing history.
        # Both the node load and the history walk are scoped to the
        # caller's tenant so a cross-tenant ID is indistinguishable from
        # a nonexistent row.
        memory_node = await _read_memory(parsed_id, session, tenant_id=tenant)
        if not authorize_read(claims, memory_node):
            raise ToolError(f"Not authorized to view history for memory {memory_id}.")

        history_result = await _get_memory_history(
            parsed_id,
            session,
            tenant_id=tenant,
            max_versions=max_versions,
            offset=offset,
        )

        page = history_result["versions"]
        total_versions = history_result["total_versions"]
        has_more = history_result["has_more"]

        versions = [
            {
                "version": v.version,
                "content": v.content,
                "stub": v.stub,
                "is_current": v.is_current,
                "created_at": v.created_at.isoformat(),
                "id": str(v.id),
            }
            for v in page
        ]

        if total_versions == 1:
            message = (
                "This memory has no version history "
                f"(version {versions[0]['version']}, never updated)."
            )
        elif not versions:
            message = (
                f"{total_versions} versions exist but offset {offset} "
                "is beyond the available range."
            )
        else:
            current = next((v for v in versions if v["is_current"]), None)
            message = f"{total_versions} versions total."
            if current:
                message += f" Current is version {current['version']}."
            if has_more:
                message += (
                    f" Showing {len(versions)} versions at offset {offset}; "
                    "use offset to see more."
                )

        return {
            "memory_id": memory_id,
            "versions": versions,
            "total_versions": total_versions,
            "has_more": has_more,
            "offset": offset,
            "message": message,
        }

    except MemoryNotFoundError:
        raise ToolError(
            f"Memory {memory_id} not found. "
            "It may have been deleted, or you may not have access to this "
            "memory's scope."
        )
    finally:
        await release_db_session(gen)
