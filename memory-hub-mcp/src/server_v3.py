"""MemoryHub MCP server entry point (FastMCP 3).

This replaces the template's src.main for production use. It registers
tools directly with a FastMCP instance rather than using the template's
dynamic loader, which was designed for FastMCP 2.
"""

from fastmcp import FastMCP

from src.tools.write_memory import write_memory
from src.tools.read_memory import read_memory
from src.tools.update_memory import update_memory
from src.tools.search_memory import search_memory
from src.tools.get_memory_history import get_memory_history
from src.tools.report_contradiction import report_contradiction

mcp = FastMCP(
    "MemoryHub",
    instructions=(
        "MemoryHub provides centralized, governed memory for AI agents. "
        "Memories form a tree with branches (rationale, provenance, etc.). "
        "Use write_memory to create, search_memory to find, read_memory to "
        "expand details, update_memory to revise, get_memory_history for "
        "forensics, and report_contradiction for staleness detection."
    ),
)

for tool_fn in [write_memory, read_memory, update_memory, search_memory,
                get_memory_history, report_contradiction]:
    mcp.add_tool(tool_fn)


def main():
    mcp.run()


if __name__ == "__main__":
    main()
