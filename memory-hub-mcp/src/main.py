"""MemoryHub MCP server entry point.

Registers tools directly with a FastMCP 3 instance. The template's
original dynamic loader (UnifiedMCPServer) is not used — it was
designed for FastMCP 2 and doesn't register tools correctly in v3.
"""

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

mcp = FastMCP(
    "MemoryHub",
    instructions=(
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
    ),
)

for tool_fn in [register_session, write_memory, read_memory, update_memory,
                delete_memory, search_memory,
                manage_session, manage_graph, manage_curation,
                manage_project]:
    mcp.add_tool(tool_fn)


def main():
    # Detect transport from environment or use default
    transport = os.getenv("MCP_TRANSPORT", "stdio")
    
    if transport == "http":
        # HTTP mode for OpenShift deployment
        host = os.getenv("MCP_HTTP_HOST", "0.0.0.0")
        port = int(os.getenv("MCP_HTTP_PORT", "8080"))
        path = os.getenv("MCP_HTTP_PATH", "/mcp/")
        mcp.run(transport="http", host=host, port=port, path=path)
    else:
        # STDIO mode for local development
        mcp.run()


if __name__ == "__main__":
    main()
