"""Soft-delete a memory and its entire version chain.

Marks the memory and all related versions as deleted. Deleted memories are
excluded from search results and graph queries but remain accessible via
forensic searches. Only the memory owner or a memory:admin can delete.
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
from src.core.authz import AuthenticationError, authorize_write, get_claims_from_context
from src.tools._deps import get_db_session, release_db_session


@mcp.tool(
    annotations={
        "readOnlyHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    }
)
async def delete_memory(
    memory_id: Annotated[
        str,
        Field(
            description="ID of the memory to delete. All versions in the chain will be soft-deleted."
        ),
    ],
    ctx: Context = None,
) -> dict[str, Any]:
    """Soft-delete a memory and its entire version chain.

    Marks the memory and all related versions as deleted. Deleted memories
    are excluded from search results and graph queries but can still be
    found with forensic searches. Only the memory owner or a memory:admin
    can delete.
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

        # Fetch existing memory to check authorization
        existing = await _read_memory(parsed_id, session)
        if not (
            authorize_write(claims, existing.scope, existing.owner_id)
            or "memory:admin" in claims.get("scopes", [])
        ):
            raise ToolError(
                f"Not authorized to delete this {existing.scope}-scope memory."
            )

        if ctx:
            await ctx.info(f"Deleting memory {memory_id}")

        result = await svc_delete_memory(
            memory_id=parsed_id,
            session=session,
        )
        return result

    except MemoryNotFoundError:
        raise ToolError(f"Memory {memory_id} not found.")
    except MemoryAlreadyDeletedError:
        raise ToolError(f"Memory {memory_id} has already been deleted.")
    except MemoryAccessDeniedError as exc:
        raise ToolError(f"Access denied: {exc.reason}")
    finally:
        await release_db_session(gen)
