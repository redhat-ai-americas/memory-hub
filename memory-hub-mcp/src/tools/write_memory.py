"""Create a new memory node or branch in the memory tree."""

import logging
import uuid
from typing import Annotated, Any

from fastmcp import Context
from fastmcp.exceptions import ToolError
from pydantic import Field, ValidationError

logger = logging.getLogger(__name__)

from src.core.app import mcp
from src.core.authz import (
    AuthenticationError,
    authorize_write,
    get_claims_from_context,
    get_tenant_filter,
)
from src.tools._deps import (
    get_db_session,
    get_embedding_service,
    release_db_session,
)
from src.tools._push_helpers import broadcast_after_write

from memoryhub_core.models.schemas import MemoryNodeCreate
from memoryhub_core.services.exceptions import MemoryAccessDeniedError, MemoryNotFoundError
from memoryhub_core.services.memory import create_memory
from memoryhub_core.services.push_broadcast import build_uri_only_notification


@mcp.tool(
    annotations={
        "readOnlyHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    }
)
async def write_memory(
    content: Annotated[
        str,
        Field(description="The memory text. Should be clear and self-contained."),
    ],
    scope: Annotated[
        str,
        Field(
            description=(
                "One of: user, project, role, organizational, enterprise. "
                "Most agent-created memories are 'user' scope."
            ),
        ),
    ],
    owner_id: Annotated[
        str | None,
        Field(
            description=(
                "The user, project, or org this memory belongs to. "
                "For user-scope, this is the user ID. "
                "Omit to use your authenticated user_id (requires register_session)."
            ),
        ),
    ] = None,
    weight: Annotated[
        float,
        Field(
            description=(
                "Injection priority from 0.0 to 1.0. High-weight (0.8-1.0) "
                "memories get full content injected. Default 0.7."
            ),
        ),
    ] = 0.7,
    parent_id: Annotated[
        str | None,
        Field(
            description=(
                "UUID of the parent memory node when creating a branch. "
                "Omit for root-level memories."
            ),
        ),
    ] = None,
    branch_type: Annotated[
        str | None,
        Field(
            description=(
                "Required when parent_id is set. Common types: rationale, "
                "provenance, description, evidence, approval."
            ),
        ),
    ] = None,
    metadata: Annotated[
        dict[str, Any] | None,
        Field(
            description="Arbitrary key-value pairs for tags, source references, etc.",
        ),
    ] = None,
    ctx: Context = None,
) -> dict[str, Any]:
    """Create a new memory node or branch in the memory tree.

    Records preferences, facts, project context, rationale, and other knowledge.
    For user-scope memories, the write happens immediately. For higher scopes
    (organizational, enterprise), the write is queued for curator review.

    Returns the created memory node with its generated ID, stub text, and timestamp,
    along with curation metadata. If curation.similar_count is greater than 0, there
    are existing memories that are similar to the one you just created. Consider
    reviewing them with get_similar_memories to check for duplicates. If an existing
    memory covers the same information, consider using update_memory instead of
    creating duplicates.

    If the write is blocked by a curation rule (e.g., exact duplicate detected),
    a ToolError is raised with a message starting with "Curation rule blocked".
    """
    if ctx:
        await ctx.info("Creating memory node")

    try:
        claims = get_claims_from_context()
    except AuthenticationError as exc:
        raise ToolError(str(exc)) from exc

    if owner_id is None:
        owner_id = claims["sub"]

    # Tool-layer writes always create new memories in the caller's own
    # tenant. Phase 2 wired this into authorize_write; Phase 3 plumbs the
    # same tenant_id through the service-layer insert so every row is
    # stamped explicitly (rather than relying on the column's
    # server_default of "default").
    write_tenant_id = get_tenant_filter(claims)
    if not authorize_write(claims, scope, owner_id, write_tenant_id):
        raise ToolError(
            f"Not authorized to write {scope}-scope memory for owner '{owner_id}'."
        )

    # Validate branch_type / parent_id pairing in both directions:
    # - parent_id without branch_type: branch with no kind label
    # - branch_type without parent_id: orphan branch with no parent to attach to
    if parent_id is not None and branch_type is None:
        raise ToolError(
            "branch_type is required when parent_id is set. "
            "Common types: rationale, provenance, description, evidence."
        )
    if branch_type is not None and parent_id is None:
        raise ToolError(
            "parent_id is required when branch_type is set. "
            "A branch must attach to a parent memory; omit branch_type "
            "to create a root-level memory instead."
        )

    # Parse parent_id to UUID if provided
    parsed_parent_id: uuid.UUID | None = None
    if parent_id is not None:
        try:
            parsed_parent_id = uuid.UUID(parent_id)
        except ValueError:
            raise ToolError(
                f"Invalid parent_id format: '{parent_id}'. Must be a valid UUID."
            )

    # Build the create schema with validation
    try:
        node_create = MemoryNodeCreate(
            content=content,
            scope=scope,
            weight=weight,
            owner_id=owner_id,
            parent_id=parsed_parent_id,
            branch_type=branch_type,
            metadata=metadata,
        )
    except ValidationError as exc:
        errors = exc.errors()
        messages = [f"  - {e['loc'][-1]}: {e['msg']}" for e in errors]
        raise ToolError(
            "Parameter validation failed:\n" + "\n".join(messages)
        ) from exc

    session = None
    gen = None
    try:
        session, gen = await get_db_session()
        embedding_service = get_embedding_service()

        memory, curation_result = await create_memory(
            node_create,
            session,
            embedding_service,
            tenant_id=write_tenant_id,
        )

        if curation_result["blocked"]:
            # No broadcast on a blocked write — the memory wasn't persisted,
            # so subscribers should not be told about it.
            raise ToolError(
                f"Curation rule blocked write: {curation_result['reason']}"
            )

        # Pattern E (#62): broadcast to other connected agents post-commit.
        # Non-fatal — broadcast failures never roll back the write.
        await broadcast_after_write(
            memory_id=str(memory.id),
            notification=build_uri_only_notification(str(memory.id)),
            claims=claims,
            content_for_filter=memory.content,
            embedding_service=embedding_service,
        )

        return {
            "memory": memory.model_dump(mode="json"),
            "curation": {
                "blocked": False,
                "similar_count": curation_result["similar_count"],
                "nearest_id": str(curation_result["nearest_id"]) if curation_result["nearest_id"] else None,
                "nearest_score": curation_result["nearest_score"],
                "flags": curation_result["flags"],
            },
        }

    except ToolError:
        raise
    except MemoryNotFoundError:
        raise ToolError(
            f"Parent memory {parent_id} not found. Check the parent_id — "
            "it may have been deleted or you may not have access to it."
        )
    except MemoryAccessDeniedError as exc:
        raise ToolError(f"Access denied: {exc.reason}") from exc
    except Exception as exc:
        logger.error("Failed to create memory: %s", exc, exc_info=True)
        raise ToolError("Failed to create memory. See server logs for details.") from exc
    finally:
        if gen is not None:
            await release_db_session(gen)
