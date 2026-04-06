"""Soft-delete a memory and its entire version chain.

Marks the memory and all related versions as deleted via a deleted_at
timestamp; child branches go with the chain. Deleted memories are
excluded from search, read, and graph queries — from an agent's
perspective the deletion is final, and there is no MCP-exposed undelete.
A deleted_at row remains in the database for compliance/audit but only
out-of-band admin tooling can recover it. Only the memory owner or
memory:admin can delete. This is a destructive operation.
"""

import uuid
from typing import Annotated, Any

from fastmcp import Context
from fastmcp.exceptions import ToolError
from pydantic import Field

from memoryhub.services.exceptions import (
    MemoryAccessDeniedError,
    MemoryAlreadyDeletedError,
    MemoryNotFoundError,
)
from memoryhub.services.memory import delete_memory as svc_delete_memory
from memoryhub.services.memory import read_memory as _read_memory

from src.core.app import mcp
from src.core.authz import (
    AuthenticationError,
    authorize_write,
    get_claims_from_context,
)
from src.tools._deps import get_db_session, release_db_session


@mcp.tool(
    annotations={
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": False,
        "openWorldHint": False,
    }
)
async def delete_memory(
    memory_id: Annotated[
        str,
        Field(
            description=(
                "ID of any version of the memory to delete. The entire version "
                "chain (older + newer versions) plus child branches will be "
                "soft-deleted. You can pass any version ID — the tool walks "
                "the chain in both directions."
            )
        ),
    ],
    ctx: Context = None,
) -> dict[str, Any]:
    """Soft-delete a memory and its entire version chain.

    Marks the memory and every node in its version chain as deleted via a
    `deleted_at` timestamp. Child branches (rationale, provenance, etc.)
    attached to any version in the chain are also deleted. Deleted memories
    are excluded from search, read, and graph queries — from an agent's
    perspective the deletion is final. The row remains in the database for
    compliance/audit, but recovery requires out-of-band admin tooling.

    Authorization: caller must either own the memory (via memory:write
    for the memory's scope) or hold the memory:admin scope. The owner check
    follows the same rules as update_memory.

    Args:
        memory_id: ID of any version of the memory to delete. The tool
            walks the version chain in both directions, so passing an old
            version ID still removes the entire chain.
        ctx: FastMCP context for logging.

    Returns:
        A dict with deletion counts:
            - deleted_id: the memory_id passed in (echoed back)
            - versions_deleted: number of version-chain nodes soft-deleted
            - branches_deleted: number of child branch nodes soft-deleted
            - total_deleted: sum of versions + branches

    Raises:
        ToolError: For invalid UUID format, missing/inaccessible memory,
            already-deleted memory, or insufficient authorization.
    """
    try:
        parsed_id = uuid.UUID(memory_id)
    except ValueError:
        raise ToolError(
            f"Invalid memory_id format: '{memory_id}'. Expected a UUID string."
        )

    session, gen = await get_db_session()
    try:
        try:
            claims = get_claims_from_context()
        except AuthenticationError as exc:
            raise ToolError(str(exc))

        # Read the existing memory to check authorization. read_memory
        # already filters deleted_at IS NULL, so an already-deleted memory
        # will surface as "not found" here — that's the right behavior:
        # we don't want to leak existence of deleted memories to callers
        # who couldn't see them. The MemoryAlreadyDeletedError path below
        # is reached only if the row's deleted_at gets set between this
        # read and the service call (race condition).
        existing = await _read_memory(parsed_id, session)

        is_owner = authorize_write(claims, existing.scope, existing.owner_id)
        is_admin = "memory:admin" in claims.get("scopes", [])
        if not (is_owner or is_admin):
            raise ToolError(
                f"Not authorized to delete this {existing.scope}-scope memory. "
                "You need either ownership of the memory or the memory:admin scope."
            )

        if ctx:
            await ctx.info(f"Deleting memory {memory_id}")

        result = await svc_delete_memory(
            memory_id=parsed_id,
            session=session,
        )
        return result

    except MemoryNotFoundError:
        raise ToolError(
            f"Memory {memory_id} not found. It may have already been "
            "deleted, or you may not have read access to its scope."
        )
    except MemoryAlreadyDeletedError:
        # Reachable only via race condition: between our read_memory call
        # (which filters deleted_at IS NULL) and the service call, another
        # caller deleted the same memory. The non-race "already deleted"
        # case surfaces as MemoryNotFoundError above, which is the right
        # behavior — we don't want to leak deleted-memory existence to
        # callers who couldn't see them.
        raise ToolError(
            f"Memory {memory_id} was deleted by another caller during this "
            "operation. No further action needed."
        )
    except MemoryAccessDeniedError as exc:
        raise ToolError(f"Access denied: {exc.reason}")
    finally:
        await release_db_session(gen)
