"""Personal-edition MCP server for MemoryHub.

Starts a stdio FastMCP server backed by SQLite. No background services,
no API keys, no cluster dependencies. The server lives and dies with
the connected agent session.
"""

from __future__ import annotations

import logging
import sys

from fastmcp import FastMCP

from memoryhub_local.tools.admin_memory import admin_memory
from memoryhub_local.tools.memory import memory
from memoryhub_local.tools.register_session import register_session
from memoryhub_local.tools.thread import thread

logger = logging.getLogger(__name__)

_PERSONAL_INSTRUCTIONS = """\
MemoryHub provides persistent, versioned, searchable memory backed by a
local SQLite database. No API key is needed -- sessions are auto-registered.

Use memory(action=...) for all memory operations:
- search, read, list, write, update, delete, similar, relationships, relate, report

Use thread(action=...) for conversation persistence:
- create, append, get, list, archive, extract, delete

Use admin_memory(action=...) for content moderation:
- search, quarantine, restore, hard_delete

register_session() is a no-op that confirms the session is ready.
You do NOT need to call it before using other tools.

Key behaviors:
- write defaults scope to "user" if omitted
- search returns compact results by default
- update creates a new version (old version preserved in history)
- delete is a soft-delete (reversible via admin_memory restore)
- extract runs fact extraction from thread messages via MCP sampling
"""


def create_server() -> FastMCP:
    """Create the FastMCP server instance with personal-edition tools."""
    mcp = FastMCP("MemoryHub", instructions=_PERSONAL_INSTRUCTIONS)
    mcp.add_tool(register_session)
    mcp.add_tool(memory)
    mcp.add_tool(thread)
    mcp.add_tool(admin_memory)
    return mcp


async def run_server() -> None:
    """Start the personal-edition MCP server on stdio."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    from memoryhub_local.startup import initialize_backend

    await initialize_backend()
    mcp = create_server()
    await mcp.run_async(transport="stdio")
