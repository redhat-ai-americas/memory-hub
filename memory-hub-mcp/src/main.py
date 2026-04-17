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
from src.tools.report_contradiction import report_contradiction
from src.tools.register_session import register_session

from src.tools.create_relationship import create_relationship
from src.tools.get_relationships import get_relationships
from src.tools.get_similar_memories import get_similar_memories
from src.tools.set_curation_rule import set_curation_rule

from src.tools.set_session_focus import set_session_focus
from src.tools.get_focus_history import get_focus_history
from src.tools.list_projects import list_projects
from src.tools.get_session import get_session

mcp = FastMCP(
    "MemoryHub",
    instructions=(
        "MemoryHub provides centralized, governed memory for AI agents. "
        "Memories form a tree with branches (rationale, provenance, etc.). "
        "IMPORTANT: Call register_session(api_key=...) at the start of every "
        "conversation to authenticate. Then use write_memory to create, "
        "search_memory to find, read_memory to expand details (with optional "
        "paginated version history via include_versions), update_memory "
        "to revise, and report_contradiction for staleness detection. "
        "Curation tools: get_similar_memories to inspect near-duplicates flagged "
        "during write, create_relationship to link memories (use "
        "relationship_type='conflicts_with' with merge metadata to suggest "
        "merges), and set_curation_rule to tune duplicate-detection thresholds. "
        "Use list_projects to discover available projects before writing "
        "project-scoped memories; writing to a new project auto-enrolls you."
    ),
)

for tool_fn in [register_session, write_memory, read_memory, update_memory,
                delete_memory, search_memory,
                report_contradiction, create_relationship, get_relationships,
                get_similar_memories, set_curation_rule,
                set_session_focus, get_focus_history,
                list_projects, get_session]:
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
