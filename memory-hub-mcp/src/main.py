"""MemoryHub MCP server entry point.

Registers tools directly with a FastMCP 3 instance. The template's
original dynamic loader (UnifiedMCPServer) is not used — it was
designed for FastMCP 2 and doesn't register tools correctly in v3.
"""

from fastmcp import FastMCP

from src.tools.write_memory import write_memory
from src.tools.read_memory import read_memory
from src.tools.update_memory import update_memory
from src.tools.search_memory import search_memory
from src.tools.get_memory_history import get_memory_history
from src.tools.report_contradiction import report_contradiction
from src.tools.register_session import register_session

mcp = FastMCP(
    "MemoryHub",
    instructions=(
        "MemoryHub provides centralized, governed memory for AI agents. "
        "Memories form a tree with branches (rationale, provenance, etc.). "
        "IMPORTANT: Call register_session(api_key=...) at the start of every "
        "conversation to authenticate. Then use write_memory to create, "
        "search_memory to find, read_memory to expand details, update_memory "
        "to revise, get_memory_history for forensics, and report_contradiction "
        "for staleness detection."
    ),
)

for tool_fn in [register_session, write_memory, read_memory, update_memory,
                search_memory, get_memory_history, report_contradiction]:
    mcp.add_tool(tool_fn)


def main():
    mcp.run()


if __name__ == "__main__":
    main()
