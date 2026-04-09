"""Get graph relationships for a memory node, with optional provenance tracing."""

import logging
import uuid
from types import SimpleNamespace
from typing import Annotated, Any

from fastmcp import Context
from fastmcp.exceptions import ToolError
from pydantic import Field

logger = logging.getLogger(__name__)

from src.core.app import mcp
from src.core.authz import (
    AuthenticationError,
    authorize_read,
    get_claims_from_context,
    get_tenant_filter,
)
from src.tools._deps import get_db_session, release_db_session

from memoryhub_core.models.schemas import RelationshipType
from memoryhub_core.services.exceptions import MemoryNotFoundError
from memoryhub_core.services.graph import (
    get_relationships as get_relationships_service,
    trace_provenance,
)

_VALID_TYPES = [t.value for t in RelationshipType]
_VALID_DIRECTIONS = ("outgoing", "incoming", "both")


@mcp.tool(
    annotations={
        "readOnlyHint": True,
        "idempotentHint": True,
        "openWorldHint": False,
    }
)
async def get_relationships(
    node_id: Annotated[
        str,
        Field(description="UUID of the memory node to query relationships for."),
    ],
    relationship_type: Annotated[
        str | None,
        Field(
            description=(
                "Filter by relationship type. One of: "
                "derived_from, supersedes, conflicts_with, related_to. "
                "Omit to return all types."
            ),
        ),
    ] = None,
    direction: Annotated[
        str,
        Field(
            description=(
                "Which edges to return: 'outgoing' (this node is the source), "
                "'incoming' (this node is the target), or 'both'. Default: 'both'."
            ),
        ),
    ] = "both",
    include_provenance: Annotated[
        bool,
        Field(
            description=(
                "If true, follows derived_from edges backward from this node to "
                "build a provenance chain showing which source memories this node "
                "was derived from."
            ),
        ),
    ] = False,
    ctx: Context = None,
) -> dict[str, Any]:
    """Get all graph relationships for a memory node.

    Use this to understand how memories are connected — trace provenance chains,
    find conflicts, discover related memories. The include_provenance flag follows
    derived_from edges backward to find source memories.

    Returns the list of relationships and their count. With include_provenance=true,
    also returns a provenance_chain showing the ancestry of this memory.
    """
    if ctx:
        await ctx.info(f"Getting {direction} relationships for {node_id}")

    try:
        claims = get_claims_from_context()
    except AuthenticationError as exc:
        raise ToolError(str(exc)) from exc
    tenant = get_tenant_filter(claims)

    try:
        parsed_node_id = uuid.UUID(node_id)
    except ValueError:
        raise ToolError(
            f"Invalid node_id format: {node_id!r}. Must be a valid UUID."
        )

    if direction not in _VALID_DIRECTIONS:
        raise ToolError(
            f"Invalid direction {direction!r}. "
            f"Must be one of: {', '.join(_VALID_DIRECTIONS)}."
        )

    if relationship_type is not None and relationship_type not in _VALID_TYPES:
        raise ToolError(
            f"Invalid relationship_type {relationship_type!r}. "
            f"Must be one of: {', '.join(_VALID_TYPES)}."
        )

    gen = None
    try:
        session, gen = await get_db_session()

        rels = await get_relationships_service(
            parsed_node_id,
            session,
            tenant_id=tenant,
            relationship_type=relationship_type,
            direction=direction,
        )

        result: dict[str, Any] = {
            "relationships": [r.model_dump(mode="json") for r in rels],
            "count": len(rels),
        }

        # Post-fetch RBAC filter on related nodes
        original_rels = result["relationships"]
        accessible_rels = []
        for rel in original_rels:
            for node_key in ("source_node", "target_node"):
                node_data = rel.get(node_key)
                if node_data and isinstance(node_data, dict):
                    proxy = SimpleNamespace(
                        scope=node_data.get("scope", "user"),
                        owner_id=node_data.get("owner_id", ""),
                        tenant_id=node_data.get("tenant_id", "default"),
                    )
                    if not authorize_read(claims, proxy):
                        break
            else:
                accessible_rels.append(rel)
        omitted = len(original_rels) - len(accessible_rels)
        result["relationships"] = accessible_rels
        result["count"] = len(accessible_rels)
        if omitted > 0:
            result["omitted_count"] = omitted

        if include_provenance:
            provenance_steps = await trace_provenance(parsed_node_id, session)
            accessible_steps = []
            for step in provenance_steps:
                node_dump = step["node"].model_dump(mode="json")
                proxy = SimpleNamespace(
                    scope=node_dump.get("scope", "user"),
                    owner_id=node_dump.get("owner_id", ""),
                    tenant_id=node_dump.get("tenant_id", "default"),
                )
                if authorize_read(claims, proxy):
                    accessible_steps.append({
                        "hop": step["hop"],
                        "node": node_dump,
                        "relationship": step["relationship"].model_dump(mode="json"),
                    })
            result["provenance_chain"] = accessible_steps

        return result

    except ToolError:
        raise
    except MemoryNotFoundError as exc:
        raise ToolError(
            f"Memory node {exc.memory_id} not found. "
            "Verify the node_id refers to an existing memory node."
        ) from exc
    except Exception as exc:
        logger.error("Failed to get relationships for %s: %s", node_id, exc, exc_info=True)
        raise ToolError(
            f"Failed to get relationships for node {node_id}. See server logs for details."
        ) from exc
    finally:
        if gen is not None:
            await release_db_session(gen)
