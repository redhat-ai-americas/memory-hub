# Local Development

Get MemoryHub's MCP server running on your machine for development and testing. No cluster access required.

## Prerequisites

- Python 3.11+
- Git
- Podman (optional, for production-like PostgreSQL testing)

## Quick start: MCP server with dev API keys

The MCP server runs locally in STDIO mode with `dev-users.json` providing pre-populated API keys so you can skip OAuth entirely.

```bash
cd memory-hub-mcp
make install
make run-local
```

`make install` creates a `.venv` and installs dependencies. `make run-local` starts the server with `MCP_TRANSPORT=stdio` and hot-reload enabled. The server uses the compact tool profile by default (3 tools: `register_session`, `memory`, `thread`).

The `dev-users.json` file ships two users:

| user_id | API key | Scopes |
|---------|---------|--------|
| `wjackson` | `mh-dev-a76811f5d871a3ee` | all five tiers |
| `dev-test` | `mh-dev-test-01e80abf` | user, project |

The server loads this file automatically when `MEMORYHUB_USERS_FILE` is set (which `make run-local` does via the `MCP_TRANSPORT=stdio` path in `src/main.py`). No database is needed for tool listing and basic auth testing; service-layer calls that touch PostgreSQL will fail until you set up a database (see "With PostgreSQL" below).

## Testing with cmcp

With the server running, open a second terminal:

```bash
cmcp ".venv/bin/python -m src.main" tools/list
```

This lists all registered tools. To call a tool:

```bash
cmcp ".venv/bin/python -m src.main" tools/call register_session \
  '{"api_key": "mh-dev-a76811f5d871a3ee"}'
```

Install cmcp with `pip install cmcp` if you don't have it.

## Pointing Claude Code at the local server

Add the server to your project's `.claude/settings.json` (or use `claude mcp add`):

```json
{
  "mcpServers": {
    "memoryhub-local": {
      "command": "/path/to/memory-hub/memory-hub-mcp/.venv/bin/python",
      "args": ["-m", "src.main"],
      "cwd": "/path/to/memory-hub/memory-hub-mcp",
      "env": {
        "MCP_TRANSPORT": "stdio",
        "MEMORYHUB_USERS_FILE": "/path/to/memory-hub/memory-hub-mcp/dev-users.json"
      }
    }
  }
}
```

Replace `/path/to/memory-hub` with your actual checkout path. Claude Code will start the server as a child process using STDIO transport.

## Running tests

The MCP server's test suite mocks the service layer and does not require a running database:

```bash
cd memory-hub-mcp
make test
```

The server-side library tests (in the repo root) use an in-memory SQLite database:

```bash
cd memory-hub    # repo root
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest tests/ -q
```

See [CONTRIBUTING.md](../CONTRIBUTING.md) for per-subproject test commands.

## With PostgreSQL + pgvector

For production-like testing where service-layer calls actually persist data, run PostgreSQL with pgvector in a Podman container:

```bash
podman run -d --name memoryhub-pg \
  -e POSTGRES_DB=memoryhub \
  -e POSTGRES_USER=memoryhub \
  -e POSTGRES_PASSWORD=devpassword \
  -p 5432:5432 \
  pgvector/pgvector:pg16

# Wait for PostgreSQL to be ready
podman exec memoryhub-pg pg_isready -U memoryhub
```

Run Alembic migrations from the repo root:

```bash
cd memory-hub    # repo root
source .venv/bin/activate
export MEMORYHUB_DB_HOST=localhost MEMORYHUB_DB_PORT=5432
export MEMORYHUB_DB_NAME=memoryhub MEMORYHUB_DB_USER=memoryhub
export MEMORYHUB_DB_PASSWORD=devpassword
alembic upgrade head
```

Then start the MCP server with `run_local.py` (which wires up the database connection):

```bash
cd memory-hub-mcp
export MEMORYHUB_DB_PASSWORD=devpassword
.venv/bin/python run_local.py
```

`run_local.py` sets `MEMORYHUB_DB_*` env vars pointing at localhost and loads `dev-users.json` for API key auth.

To stop and remove the database container:

```bash
podman stop memoryhub-pg && podman rm memoryhub-pg
```

## With the full stack on OpenShift

For a complete deployment (MCP server, auth service, dashboard UI, PostgreSQL, MinIO, Valkey), see the cluster install section in the [README](../README.md). The entry point is `make install` from the repo root. Most contributors do not need this -- local PostgreSQL testing covers the vast majority of development scenarios.
