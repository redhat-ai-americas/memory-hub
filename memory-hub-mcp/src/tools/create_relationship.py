"""Create a directed relationship between two memory nodes."""

import uuid
from typing import Annotated, Any

from fastmcp import Context
from pydantic import Field, ValidationError

from src.core.app import mcp
from src.tools._deps import get_authenticated_owner, get_db_session, release_db_session
from src.tools.auth import require_auth

from memoryhub.models.schemas import RelationshipCreate, RelationshipType
from memoryhub.services.exceptions import MemoryNotFoundError
from memoryhub.services.graph import create_relationship as create_relationship_service

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
    ctx: Context = None,
) -> dict[str, Any]:
    """Create a directed relationship between two memory nodes.

    Use this to link memories that are semantically connected — for example,
    marking that an organizational memory was derived_from several user memories,
    or that one memory supersedes another.

    Returns the created relationship with its ID, timestamps, and node stubs.
    """
    if ctx:
        await ctx.info(f"Creating {relationship_type!r} relationship {source_id} -> {target_id}")

    try:
        current_user = require_auth()
    except RuntimeError as exc:
        return {"error": True, "message": str(exc)}

    # Validate relationship_type against the controlled vocabulary
    if relationship_type not in _VALID_TYPES:
        return {
            "error": True,
            "message": (
                f"Invalid relationship_type {relationship_type!r}. "
                f"Must be one of: {', '.join(_VALID_TYPES)}."
            ),
        }

    # Parse UUIDs
    try:
        parsed_source_id = uuid.UUID(source_id)
    except ValueError:
        return {
            "error": True,
            "message": f"Invalid source_id format: {source_id!r}. Must be a valid UUID.",
        }

    try:
        parsed_target_id = uuid.UUID(target_id)
    except ValueError:
        return {
            "error": True,
            "message": f"Invalid target_id format: {target_id!r}. Must be a valid UUID.",
        }

    if parsed_source_id == parsed_target_id:
        return {
            "error": True,
            "message": "source_id and target_id must be different — self-referential edges are not allowed.",
        }

    try:
        rel_create = RelationshipCreate(
            source_id=parsed_source_id,
            target_id=parsed_target_id,
            relationship_type=relationship_type,
            created_by=current_user["user_id"],
            metadata=metadata,
        )
    except ValidationError as exc:
        errors = exc.errors()
        messages = [f"  - {e['loc'][-1]}: {e['msg']}" for e in errors]
        return {
            "error": True,
            "message": "Parameter validation failed:\n" + "\n".join(messages),
        }

    session = None
    gen = None
    try:
        session, gen = await get_db_session()
        result = await create_relationship_service(rel_create, session)
        return result.model_dump(mode="json")

    except MemoryNotFoundError as exc:
        return {
            "error": True,
            "message": (
                f"Memory node {exc.memory_id} not found. "
                "Verify both source_id and target_id refer to existing memory nodes."
            ),
        }
    except ValueError as exc:
        # Duplicate edge from the service layer
        return {"error": True, "message": str(exc)}
    except Exception as exc:
        return {"error": True, "message": f"Failed to create relationship: {exc}"}
    finally:
        if gen is not None:
            await release_db_session(gen)
