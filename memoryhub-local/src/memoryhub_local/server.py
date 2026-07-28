"""Personal-edition MCP server for MemoryHub.

Starts a stdio FastMCP server backed by SQLite. No background services,
no API keys, no cluster dependencies. The server lives and dies with
the connected agent session.
"""

from __future__ import annotations

import logging
import sys

from fastmcp import FastMCP

from memoryhub_local.database import create_local_engine, create_tables, make_session_factory
from memoryhub_local.embeddings.base import MockEmbeddingService
from memoryhub_local.storage.sqlite import SQLiteBackend
from memoryhub_local.tools._state import init_state
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
- create, append, get, list, archive, delete

Use admin_memory(action=...) for content moderation:
- search, quarantine, restore, hard_delete

register_session() is a no-op that confirms the session is ready.
You do NOT need to call it before using other tools.

Key behaviors:
- write defaults scope to "user" if omitted
- search returns compact results by default
- update creates a new version (old version preserved in history)
- delete is a soft-delete (reversible via admin_memory restore)
"""


def create_server() -> FastMCP:
    """Create the FastMCP server instance with personal-edition tools."""
    mcp = FastMCP("MemoryHub", instructions=_PERSONAL_INSTRUCTIONS)
    mcp.add_tool(register_session)
    mcp.add_tool(memory)
    mcp.add_tool(thread)
    mcp.add_tool(admin_memory)
    return mcp


async def _startup() -> None:
    """Initialize database and server state."""
    engine = await create_local_engine()
    await create_tables(engine)
    session_factory = make_session_factory(engine)
    embedding_service = MockEmbeddingService()
    recall_backend = SQLiteBackend()
    init_state(session_factory, embedding_service, recall_backend)

    from memoryhub_local.database import get_default_db_path

    db_path = get_default_db_path()
    logger.info("MemoryHub personal edition ready (db: %s)", db_path)
    print(f"MemoryHub personal edition ready (db: {db_path})", file=sys.stderr)


async def run_server() -> None:
    """Start the personal-edition MCP server on stdio."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    await _startup()
    mcp = create_server()
    await mcp.run_async(transport="stdio")
