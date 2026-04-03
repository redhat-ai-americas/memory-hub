#!/Users/wjackson/Developer/memory-hub/memory-hub-mcp/.venv/bin/python
"""Run MemoryHub MCP server locally against port-forwarded PostgreSQL."""

import os
import sys

# Database connection for port-forwarded PostgreSQL
os.environ.setdefault("MEMORYHUB_DB_HOST", "localhost")
os.environ.setdefault("MEMORYHUB_DB_PORT", "5432")
os.environ.setdefault("MEMORYHUB_DB_NAME", "memoryhub")
os.environ.setdefault("MEMORYHUB_DB_USER", "memoryhub")
os.environ.setdefault("MEMORYHUB_DB_PASSWORD", "memoryhub-dev-password")

# Ensure memoryhub core library is importable
os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastmcp import FastMCP

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

# Import tools and register with this mcp instance
from src.tools.write_memory import write_memory
from src.tools.read_memory import read_memory
from src.tools.update_memory import update_memory
from src.tools.search_memory import search_memory
from src.tools.get_memory_history import get_memory_history
from src.tools.report_contradiction import report_contradiction

for tool_fn in [write_memory, read_memory, update_memory, search_memory,
                get_memory_history, report_contradiction]:
    mcp.add_tool(tool_fn)

if __name__ == "__main__":
    mcp.run()
