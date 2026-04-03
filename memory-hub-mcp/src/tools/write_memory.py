"""Create a new memory node or branch in the memory tree."""

import uuid
from typing import Annotated, Any

from fastmcp import Context
from pydantic import Field, ValidationError

from src.core.app import mcp
from src.tools._deps import (
    get_authenticated_owner,
    get_db_session,
    get_embedding_service,
    release_db_session,
)
from src.tools.auth import has_scope, require_auth

from memoryhub.models.schemas import MemoryNodeCreate
from memoryhub.services.exceptions import MemoryAccessDeniedError, MemoryNotFoundError
from memoryhub.services.memory import create_memory


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

    Returns the created memory node with its generated ID, stub text, and timestamp.
    """
    if ctx:
        await ctx.info("Creating memory node")

    # Resolve owner_id from authenticated session if not supplied explicitly.
    if owner_id is None:
        try:
            current_user = require_auth()
        except RuntimeError as exc:
            return {"error": True, "message": str(exc)}
        owner_id = current_user["user_id"]
    else:
        # Explicit owner_id: validate the caller has access to that scope.
        current_user = None
        authenticated_owner = get_authenticated_owner()
        if authenticated_owner is not None:
            current_user = require_auth()
            # For user scope, the owner must be the authenticated user.
            if scope == "user" and owner_id != authenticated_owner:
                return {
                    "error": True,
                    "message": (
                        f"Cannot write user-scope memory for owner '{owner_id}': "
                        f"you are authenticated as '{authenticated_owner}'. "
                        "Use your own user_id or omit owner_id to use your identity."
                    ),
                }
            # For higher scopes, verify the user has that scope.
            if not has_scope(current_user, scope):
                return {
                    "error": True,
                    "message": (
                        f"Your account does not have access to the '{scope}' scope. "
                        f"Allowed scopes: {', '.join(current_user.get('scopes', []))}."
                    ),
                }

    # Validate branch_type requirement
    if parent_id is not None and branch_type is None:
        return {
            "error": True,
            "message": (
                "branch_type is required when parent_id is set. "
                "Common types: rationale, provenance, description, evidence."
            ),
        }

    # Parse parent_id to UUID if provided
    parsed_parent_id: uuid.UUID | None = None
    if parent_id is not None:
        try:
            parsed_parent_id = uuid.UUID(parent_id)
        except ValueError:
            return {
                "error": True,
                "message": f"Invalid parent_id format: '{parent_id}'. Must be a valid UUID.",
            }

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
        return {
            "error": True,
            "message": "Parameter validation failed:\n" + "\n".join(messages),
        }

    session = None
    gen = None
    try:
        session, gen = await get_db_session()
        embedding_service = get_embedding_service()

        result = await create_memory(node_create, session, embedding_service)

        return result.model_dump(mode="json")

    except MemoryNotFoundError:
        return {
            "error": True,
            "message": (
                f"Parent memory {parent_id} not found. Check the parent_id — "
                "it may have been deleted or you may not have access to it."
            ),
        }
    except MemoryAccessDeniedError as exc:
        return {"error": True, "message": f"Access denied: {exc.reason}"}
    except Exception as exc:
        return {"error": True, "message": f"Failed to create memory: {exc}"}
    finally:
        if gen is not None:
            await release_db_session(gen)
