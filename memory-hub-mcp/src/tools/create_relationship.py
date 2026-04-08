"""Create a directed relationship between two memory nodes."""

import uuid
from typing import Annotated, Any

from fastmcp import Context
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
from memoryhub_core.services.exceptions import MemoryNotFoundError
from memoryhub_core.services.graph import create_relationship as create_relationship_service
from memoryhub_core.services.memory import read_memory as _read_memory

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

    Relationships are immutable (create or delete, never update). Edge direction:
    for derived_from, source is the derived node, target is the origin.

    Returns the created relationship with its ID, timestamps, and node stubs.
    """
    if ctx:
        await ctx.info(f"Creating {relationship_type!r} relationship {source_id} -> {target_id}")

    try:
        claims = get_claims_from_context()
    except AuthenticationError as exc:
        return {"error": True, "message": str(exc)}
    tenant = get_tenant_filter(claims)

    if relationship_type not in _VALID_TYPES:
        return {
            "error": True,
            "message": (
                f"Invalid relationship_type {relationship_type!r}. "
                f"Must be one of: {', '.join(_VALID_TYPES)}."
            ),
        }

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

    gen = None
    try:
        session, gen = await get_db_session()

        # Verify read access to both nodes. The tenant filter on
        # read_memory makes a cross-tenant ID indistinguishable from a
        # nonexistent row, so a cross-tenant relationship attempt is
        # rejected here as "not found" rather than surfacing tenant
        # details in the error message.
        for node_id, label in [(parsed_source_id, "source_id"), (parsed_target_id, "target_id")]:
            try:
                node = await _read_memory(node_id, session, tenant_id=tenant)
            except MemoryNotFoundError:
                return {"error": True, "message": f"Memory node {node_id} not found."}
            if not authorize_read(claims, node):
                return {"error": True, "message": f"Not authorized to access {label} ({node_id})."}

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
            return {
                "error": True,
                "message": "Parameter validation failed:\n" + "\n".join(messages),
            }
        result = await create_relationship_service(rel_create, session)
        return result.model_dump(mode="json")

    except MemoryNotFoundError as exc:
        return {
            "error": True,
            "message": (
                f"Memory node {exc.memory_id} not found. "
                "Verify both source_id and target_id refer to existing, current memory nodes."
            ),
        }
    except ValueError as exc:
        return {"error": True, "message": str(exc)}
    except Exception as exc:
        return {"error": True, "message": f"Failed to create relationship: {exc}"}
    finally:
        if gen is not None:
            await release_db_session(gen)
