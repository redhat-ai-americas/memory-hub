"""Create a directed relationship between two memory nodes."""

import logging
import uuid
from typing import Annotated, Any

from fastmcp import Context
from fastmcp.exceptions import ToolError
from pydantic import Field, ValidationError

from src.core.app import mcp
from src.core.authz import (
    AuthenticationError,
    authorize_read,
    get_claims_from_context,
    get_tenant_filter,
)
from src.tools._deps import get_db_session, release_db_session

from memoryhub_core.models.schemas import RelationshipCreate, RelationshipType
from memoryhub_core.services.campaign import get_campaigns_for_project
from memoryhub_core.services.exceptions import MemoryNotFoundError
from memoryhub_core.services.graph import create_relationship as create_relationship_service
from memoryhub_core.services.memory import read_memory as _read_memory

logger = logging.getLogger(__name__)

_VALID_TYPES = [t.value for t in RelationshipType]


@mcp.tool(
    annotations={
        "readOnlyHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    }
)
async def create_relationship(
    source_id: Annotated[
        str,
        Field(description="UUID of the source memory node (the 'from' end of the edge)."),
    ],
    target_id: Annotated[
        str,
        Field(description="UUID of the target memory node (the 'to' end of the edge)."),
    ],
    relationship_type: Annotated[
        str,
        Field(
            description=(
                "Type of relationship. Must be one of: "
                "derived_from, supersedes, conflicts_with, related_to."
            ),
        ),
    ],
    metadata: Annotated[
        dict[str, Any] | None,
        Field(description="Optional key-value pairs to attach to the relationship edge."),
    ] = None,
    project_id: Annotated[
        str | None,
        Field(
            description=(
                "Your project identifier. Required when either memory node has "
                "campaign scope — used to verify your project is enrolled in "
                "the campaign."
            ),
        ),
    ] = None,
    ctx: Context = None,
) -> dict[str, Any]:
    """Create a directed relationship between two memory nodes.

    Use this to link memories that are semantically connected — for example,
    marking that an organizational memory was derived_from several user memories,
    or that one memory supersedes another.

    To suggest a merge between duplicate or overlapping memories, use
    relationship_type="conflicts_with" with
    metadata={"merge_suggested": true, "reasoning": "why they should merge"}.
    Use get_relationships to find pending merge suggestions.

    Relationships are immutable (create or delete, never update). Edge direction:
    for derived_from, source is the derived node, target is the origin.

    Returns the created relationship with its ID, timestamps, and node stubs.
    """
    if ctx:
        await ctx.info(f"Creating {relationship_type!r} relationship {source_id} -> {target_id}")

    try:
        claims = get_claims_from_context()
    except AuthenticationError as exc:
        raise ToolError(str(exc)) from exc
    tenant = get_tenant_filter(claims)

    if relationship_type not in _VALID_TYPES:
        raise ToolError(
            f"Invalid relationship_type {relationship_type!r}. "
            f"Must be one of: {', '.join(_VALID_TYPES)}."
        )

    try:
        parsed_source_id = uuid.UUID(source_id)
    except ValueError:
        raise ToolError(
            f"Invalid source_id format: {source_id!r}. Must be a valid UUID."
        )

    try:
        parsed_target_id = uuid.UUID(target_id)
    except ValueError:
        raise ToolError(
            f"Invalid target_id format: {target_id!r}. Must be a valid UUID."
        )

    if parsed_source_id == parsed_target_id:
        raise ToolError(
            "source_id and target_id must be different — self-referential edges are not allowed."
        )

    gen = None
    try:
        session, gen = await get_db_session()

        # Resolve campaign membership once — used for both nodes if either
        # is campaign-scoped.
        campaign_ids: set[str] | None = None

        # Verify read access to both nodes. The tenant filter on
        # read_memory makes a cross-tenant ID indistinguishable from a
        # nonexistent row, so a cross-tenant relationship attempt is
        # rejected here as "not found" rather than surfacing tenant
        # details in the error message.
        for node_id, label in [(parsed_source_id, "source_id"), (parsed_target_id, "target_id")]:
            try:
                node = await _read_memory(node_id, session, tenant_id=tenant)
            except MemoryNotFoundError:
                raise ToolError(f"Memory node {node_id} not found.")
            if node.scope == "campaign" and campaign_ids is None:
                if not project_id:
                    raise ToolError(
                        f"project_id is required when {label} is a campaign-scoped memory. "
                        "Set it to your project identifier so enrollment can be verified."
                    )
                campaign_ids = await get_campaigns_for_project(session, project_id, tenant)
            if not authorize_read(claims, node, campaign_ids=campaign_ids):
                raise ToolError(f"Not authorized to access {label} ({node_id}).")

        try:
            rel_create = RelationshipCreate(
                source_id=parsed_source_id,
                target_id=parsed_target_id,
                relationship_type=relationship_type,
                created_by=claims["sub"],
                metadata=metadata,
            )
        except ValidationError as exc:
            errors = exc.errors()
            messages = [f"  - {e['loc'][-1]}: {e['msg']}" for e in errors]
            raise ToolError("Parameter validation failed:\n" + "\n".join(messages)) from exc
        result = await create_relationship_service(rel_create, session)
        return result.model_dump(mode="json")

    except ToolError:
        raise
    except MemoryNotFoundError as exc:
        raise ToolError(
            f"Memory node {exc.memory_id} not found. "
            "Verify both source_id and target_id refer to existing, current memory nodes."
        ) from exc
    except ValueError as exc:
        raise ToolError(str(exc)) from exc
    except Exception as exc:
        logger.error("Failed to create relationship %s->%s: %s", source_id, target_id, exc, exc_info=True)
        raise ToolError("Failed to create relationship. See server logs for details.") from exc
    finally:
        if gen is not None:
            await release_db_session(gen)
