"""Personal-edition MCP server for MemoryHub.

Starts a stdio FastMCP server backed by SQLite. No background services,
no API keys, no cluster dependencies. The server lives and dies with
the connected agent session.
"""

from __future__ import annotations

import logging
import sys

from fastmcp import FastMCP

from memoryhub_local.database import auto_migrate, create_local_engine, make_session_factory
from memoryhub_local.embeddings import (
    MockEmbeddingService,
    OnnxEmbeddingService,
    download_model,
    get_default_model_dir,
    is_model_downloaded,
)
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
    await auto_migrate(engine)
    session_factory = make_session_factory(engine)
    model_dir = get_default_model_dir()
    if not is_model_downloaded(model_dir):
        try:
            download_model(model_dir)
        except Exception:
            logger.warning(
                "Model download failed. Falling back to mock embeddings. "
                "Run 'memoryhub doctor' for diagnostics.",
                exc_info=True,
            )

    if is_model_downloaded(model_dir):
        embedding_service = OnnxEmbeddingService(model_dir)
        embed_label = "onnx"
    else:
        embedding_service = MockEmbeddingService()
        embed_label = "mock (run 'memoryhub doctor' to check model status)"
        print(  # noqa: T201
            "WARNING: Using mock embeddings. Search results will not be "
            "semantically meaningful. Run 'memoryhub doctor' for details.",
            file=sys.stderr,
        )

    recall_backend = SQLiteBackend()
    init_state(session_factory, embedding_service, recall_backend)

    from memoryhub_local.database import get_default_db_path

    db_path = get_default_db_path()
    logger.info("MemoryHub personal edition ready (db: %s, embeddings: %s)", db_path, embed_label)
    print(f"MemoryHub personal edition ready (db: {db_path}, embeddings: {embed_label})", file=sys.stderr)  # noqa: T201, E501


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
