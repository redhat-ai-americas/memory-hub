# MemoryHub

Kubernetes-native agent memory component for OpenShift AI. Provides centralized, governed memory for AI agents with multi-tier scoping, version history, semantic search, and enterprise forensics.

## Quick Start: Connecting Claude Code

MemoryHub is deployed and available as an MCP server. To connect your Claude Code instance:

### 1. Get an API key

Contact William Jackson (wjackson) to get a MemoryHub API key. Each user gets their own key that scopes memories to their identity.

### 2. Add the MCP server

```bash
claude mcp add --transport http \
  -e MEMORYHUB_API_KEY=<your-key> \
  -s project \
  memoryhub \
  https://memory-hub-mcp-memory-hub-mcp.apps.cluster-n7pd5.n7pd5.sandbox5167.opentlc.com/mcp/
```

Replace `<your-key>` with the API key you received. The `-s project` flag scopes this to the MemoryHub project so it doesn't affect other work.

### 3. Start using it

The project includes rules (`.claude/rules/memoryhub-integration.md`) that instruct Claude Code to:
- Read `MEMORYHUB_API_KEY` and call `register_session` at the start of every conversation
- Search memory for relevant context before starting work
- Write important preferences, decisions, and project context to memory
- Use version history and contradiction reporting

If you work on this project in Claude Code, the agent will automatically use MemoryHub for persistent memory across conversations.

## Architecture

See `docs/ARCHITECTURE.md` for the full system design. Key components:

- **MCP Server** (memory-hub-mcp/) — FastMCP 3, streamable-http transport, 7 tools
- **Core Library** (src/memoryhub/) — SQLAlchemy models, service layer, embedding integration
- **PostgreSQL + pgvector** — Vector similarity search for semantic memory retrieval
- **all-MiniLM-L6-v2** — 384-dimensional embeddings for memory encoding

## Project Structure

```
memory-hub/
├── src/memoryhub/          # Core library (models, services, storage)
├── memory-hub-mcp/         # MCP server (FastMCP 3)
├── deploy/postgresql/      # PostgreSQL + pgvector manifests
├── docs/                   # Design documents
├── tests/                  # Core library tests
├── alembic/                # Database migrations
└── ideas/                  # Ideation notes
```

## Development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest tests/ -v
```

See `CLAUDE.md` for project conventions and `docs/SYSTEMS.md` for the subsystem inventory.
