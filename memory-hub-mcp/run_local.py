#!/Users/wjackson/Developer/memory-hub/memory-hub-mcp/.venv/bin/python
"""Run MemoryHub MCP server locally against port-forwarded PostgreSQL."""

import os
import sys

# Database connection for port-forwarded PostgreSQL
os.environ.setdefault("MEMORYHUB_DB_HOST", "localhost")
os.environ.setdefault("MEMORYHUB_DB_PORT", "5432")
os.environ.setdefault("MEMORYHUB_DB_NAME", "memoryhub")
os.environ.setdefault("MEMORYHUB_DB_USER", "memoryhub")
if not os.environ.get("MEMORYHUB_DB_PASSWORD"):
    sys.exit(
        "ERROR: MEMORYHUB_DB_PASSWORD must be set (matching the POSTGRES_PASSWORD "
        "in deploy/postgresql/secret.yaml)."
    )

# Auth: point to the local dev users file
_script_dir = os.path.dirname(os.path.abspath(__file__))
os.environ.setdefault("MEMORYHUB_USERS_FILE", os.path.join(_script_dir, "dev-users.json"))

# Ensure memoryhub core library is importable
os.chdir(_script_dir)
sys.path.insert(0, os.path.dirname(_script_dir))

from src.main import main  # noqa: E402

main()
