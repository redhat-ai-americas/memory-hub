"""Personal-edition register_session tool -- no-op, always succeeds."""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import Field


async def register_session(
    api_key: Annotated[
        str | None,
        Field(description="Ignored in personal edition. No API key needed."),
    ] = None,
    default_driver_id: Annotated[
        str | None,
        Field(description="Identity of the upstream human or system."),
    ] = None,
) -> dict[str, Any]:
    """Register this session with MemoryHub.

    In the personal edition, sessions are auto-registered. No API key is
    needed. This tool exists for compatibility with agents that expect
    the cluster edition's registration flow.
    """
    from memoryhub_local.identity import get_owner_id
    user_id = get_owner_id()

    return {
        "session_id": "local",
        "user_id": user_id,
        "name": user_id,
        "scopes": ["user", "project"],
        "project_memberships": [],
        "default_driver_id": default_driver_id,
        "projects": [],
        "quick_start": [
            "memory(action='write', content='...') to save a memory",
            "memory(action='search', query='...') to find memories",
            "memory(action='read', memory_id='...') to retrieve by ID",
        ],
        "message": f"Personal edition ready. User: {user_id}",
    }
