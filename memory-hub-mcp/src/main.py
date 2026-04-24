"""MemoryHub MCP server entry point.

Registers tools directly with a FastMCP 3 instance. The template's
original dynamic loader (UnifiedMCPServer) is not used — it was
designed for FastMCP 2 and doesn't register tools correctly in v3.

Tool profiles (MEMORYHUB_TOOL_PROFILE env var):

  compact  — register_session + memory (2 tools).
             Action-dispatch with options dict. Best for frontier models
             (Claude, GPT-4) where tool count is the constraint.

  full     — register_session + 9 flat-param tools (10 tools).
             Each operation is a separate tool with typed parameters.
             Best for mid-range models that need schema discoverability.

  minimal  — register_session + search_memory + write_memory +
             read_memory (4 tools). Just the essentials for small
             models (7B) that work best with few, simple tools.

Default: compact.
"""

import logging
import os

from fastmcp import FastMCP

from src.tools.write_memory import write_memory
from src.tools.read_memory import read_memory
from src.tools.update_memory import update_memory
from src.tools.delete_memory import delete_memory
from src.tools.search_memory import search_memory
from src.tools.register_session import register_session
from src.tools.manage_session import manage_session
from src.tools.manage_graph import manage_graph
from src.tools.manage_curation import manage_curation
from src.tools.manage_project import manage_project
from src.tools.memory import memory

logger = logging.getLogger(__name__)

TOOL_PROFILE = os.getenv("MEMORYHUB_TOOL_PROFILE", "compact")
_VALID_PROFILES = {"compact", "full", "minimal"}

if TOOL_PROFILE not in _VALID_PROFILES:
    logger.warning(
        "Unknown MEMORYHUB_TOOL_PROFILE=%r, falling back to 'compact'. "
        "Valid profiles: %s", TOOL_PROFILE, ", ".join(sorted(_VALID_PROFILES)),
    )
    TOOL_PROFILE = "compact"

# ── Profile-specific instructions ──────────────────────────────────────────

_INSTRUCTIONS_COMPACT = (
    "MemoryHub provides centralized, governed memory for AI agents. "
    "Memories form a tree with branches (rationale, provenance, etc.). "
    "IMPORTANT: Call register_session(api_key=...) at the start of every "
    "conversation to authenticate. Then use memory(action=...) for all "
    "operations — search, read, write, update, delete, and more. "
    "See the memory tool's docstring for the full action reference."
)

_INSTRUCTIONS_FULL = (
    "MemoryHub provides centralized, governed memory for AI agents. "
    "Memories form a tree with branches (rationale, provenance, etc.). "
    "IMPORTANT: Call register_session(api_key=...) at the start of every "
    "conversation to authenticate. Then use write_memory to create, "
    "search_memory to find, read_memory to expand details (with optional "
    "paginated version history via include_versions), update_memory "
    "to revise, and delete_memory to remove. Use manage_session to "
    "check session status, declare focus, and view focus history. "
    "Use manage_graph to create relationships between memories, "
    "query relationships, and find similar memories. Use "
    "manage_curation to report and resolve contradictions and tune "
    "curation rules. Use manage_project to discover, create, and "
    "manage projects and their members; writing to a new project "
    "auto-enrolls you."
)

_INSTRUCTIONS_MINIMAL = (
    "MemoryHub provides centralized, governed memory for AI agents. "
    "IMPORTANT: Call register_session(api_key=...) at the start of every "
    "conversation to authenticate. Then use search_memory to find "
    "relevant memories, write_memory to store new ones, and read_memory "
    "to retrieve details by ID."
)

# ── Profile-specific tool sets ─────────────────────────────────────────────

_TOOLS_COMPACT = [register_session, memory]

_TOOLS_FULL = [
    register_session, write_memory, read_memory, update_memory,
    delete_memory, search_memory,
    manage_session, manage_graph, manage_curation, manage_project,
]

_TOOLS_MINIMAL = [register_session, search_memory, write_memory, read_memory]

_PROFILE_MAP = {
    "compact": (_TOOLS_COMPACT, _INSTRUCTIONS_COMPACT),
    "full": (_TOOLS_FULL, _INSTRUCTIONS_FULL),
    "minimal": (_TOOLS_MINIMAL, _INSTRUCTIONS_MINIMAL),
}

tools, instructions = _PROFILE_MAP[TOOL_PROFILE]

mcp = FastMCP("MemoryHub", instructions=instructions)

for tool_fn in tools:
    mcp.add_tool(tool_fn)

logger.info(
    "MemoryHub tool profile: %s (%d tools registered)", TOOL_PROFILE, len(tools),
)


def main():
    transport = os.getenv("MCP_TRANSPORT", "stdio")

    if transport == "http":
        host = os.getenv("MCP_HTTP_HOST", "0.0.0.0")
        port = int(os.getenv("MCP_HTTP_PORT", "8080"))
        path = os.getenv("MCP_HTTP_PATH", "/mcp/")
        mcp.run(transport="http", host=host, port=port, path=path)
    else:
        mcp.run()


if __name__ == "__main__":
    main()
