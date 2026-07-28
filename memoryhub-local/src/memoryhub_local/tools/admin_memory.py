"""Personal-edition admin_memory tool.

In the personal edition, admin operations work without scope checks
since there's only one user.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastmcp.exceptions import ToolError
from pydantic import Field
from sqlalchemy import delete, update

from memoryhub_local.identity import TENANT_ID
from memoryhub_local.models.memory import MemoryNode
from memoryhub_local.tools._state import get_state

_VALID_ACTIONS = frozenset({"search", "quarantine", "restore", "hard_delete"})


async def admin_memory(
    action: Annotated[
        str,
        Field(description="Admin action: search, quarantine, restore, hard_delete"),
    ],
    memory_id: Annotated[
        str | None,
        Field(description="Memory UUID (required for quarantine/restore/hard_delete)"),
    ] = None,
    query: Annotated[
        str | None,
        Field(description="Search query (required for search)"),
    ] = None,
    options: Annotated[
        dict[str, Any] | None,
        Field(description=(
            "Action-specific options. search: regex, max_results. "
            "quarantine: reason (required). restore: reason (required). "
            "hard_delete: reason (required)."
        )),
    ] = None,
) -> dict[str, Any]:
    """Admin content moderation operations.

    Actions:
      search(query, [options: max_results])
        Search across all memories ignoring ownership.
      quarantine(memory_id, options: {reason})
        Hide memory from non-admin queries.
      restore(memory_id, options: {reason})
        Restore a quarantined memory to active status.
      hard_delete(memory_id, options: {reason})
        Physically remove memory from database. IRREVERSIBLE.
    """
    if action not in _VALID_ACTIONS:
        raise ToolError(
            f"Invalid action '{action}'. Must be one of: "
            f"{', '.join(sorted(_VALID_ACTIONS))}."
        )

    opts = options or {}

    if action == "search":
        return await _do_search(query, opts)
    if action == "quarantine":
        return await _do_quarantine(memory_id, opts)
    if action == "restore":
        return await _do_restore(memory_id, opts)
    if action == "hard_delete":
        return await _do_hard_delete(memory_id, opts)

    raise ToolError(f"Unhandled action: {action}")


async def _do_search(query, opts):
    if not query:
        raise ToolError("action='search' requires 'query'.")

    state = get_state()
    async with state.session_factory() as session:
        from memoryhub_local.services.memory import search_memories

        return await search_memories(
            session, query, state.embedding_service, state.recall_backend,
            max_results=opts.get("max_results", 20),
        )


async def _do_quarantine(memory_id, opts):
    if not memory_id:
        raise ToolError("action='quarantine' requires 'memory_id'.")
    if not opts.get("reason"):
        raise ToolError("action='quarantine' requires 'reason' in options.")

    state = get_state()
    async with state.session_factory() as session:
        await session.execute(
            update(MemoryNode)
            .where(MemoryNode.id == uuid.UUID(memory_id), MemoryNode.tenant_id == TENANT_ID)
            .values(status="quarantined")
        )
        await session.commit()
        return {"memory_id": memory_id, "status": "quarantined", "reason": opts["reason"]}


async def _do_restore(memory_id, opts):
    if not memory_id:
        raise ToolError("action='restore' requires 'memory_id'.")
    if not opts.get("reason"):
        raise ToolError("action='restore' requires 'reason' in options.")

    state = get_state()
    async with state.session_factory() as session:
        await session.execute(
            update(MemoryNode)
            .where(MemoryNode.id == uuid.UUID(memory_id), MemoryNode.tenant_id == TENANT_ID)
            .values(status="active")
        )
        await session.commit()
        return {"memory_id": memory_id, "status": "active", "reason": opts["reason"]}


async def _do_hard_delete(memory_id, opts):
    if not memory_id:
        raise ToolError("action='hard_delete' requires 'memory_id'.")
    if not opts.get("reason"):
        raise ToolError("action='hard_delete' requires 'reason' in options.")

    state = get_state()
    async with state.session_factory() as session:
        result = await session.execute(
            delete(MemoryNode).where(
                MemoryNode.id == uuid.UUID(memory_id),
                MemoryNode.tenant_id == TENANT_ID,
            )
        )
        await session.commit()
        return {
            "memory_id": memory_id,
            "deleted": result.rowcount > 0,
            "reason": opts["reason"],
        }
