# MemoryHub

Centralized, governed memory for AI agents on OpenShift AI. MemoryHub gives every agent in your organization a shared, persistent memory layer with multi-tier scoping (`user` / `project` / `role` / `organizational` / `enterprise`), version history, semantic search via pgvector, an immutable audit trail, and an OAuth 2.1 authorization story.

It works with any agent framework that speaks MCP — Claude Code, kagenti LangGraph agents, LlamaStack workflows, custom Python agents — and ships a typed Python SDK and a CLI for direct use.

**Status (2026-04-07).** Core memory operations, OAuth 2.1 + JWT auth with service-layer RBAC, the dashboard UI, the published Python SDK, and the agent-memory-ergonomics work (search shape, session focus vector with cross-encoder reranking, project config + rule generation) are all shipped. The Kubernetes operator and the curator-as-background-agent layer are still on the roadmap. See [`docs/SYSTEMS.md`](docs/SYSTEMS.md) for the per-subsystem status table.

## What's in this repo

| Component | Path | What it is |
|---|---|---|
| **MCP server** | [`memory-hub-mcp/`](memory-hub-mcp/) | FastMCP 3 server exposing 13 tools (search, read, write, update, delete, history, similarity, relationships, curation, contradiction, session) over streamable-HTTP. The primary agent surface. |
| **Server-side library** | [`src/memoryhub/`](src/memoryhub/) | SQLAlchemy models, service layer, embedding integration, RBAC enforcement (`core/authz.py`). The MCP server, BFF, and auth service all import from here. |
| **Python SDK** | [`sdk/`](sdk/) | `pip install memoryhub` — typed async client wrapping the MCP tools. OAuth 2.1 token management is automatic. See [`sdk/README.md`](sdk/README.md). |
| **CLI** | [`memoryhub-cli/`](memoryhub-cli/) | `pip install memoryhub-cli` — terminal client for search/read/write/delete plus `memoryhub config init` for generating project-level `.memoryhub.yaml` and `.claude/rules/memoryhub-loading.md` rule files. |
| **Dashboard UI** | [`memoryhub-ui/`](memoryhub-ui/) | React + PatternFly 6 frontend behind a FastAPI BFF, deployed as a single container. Six panels: Memory Graph, Status Overview, Users & Agents, Client Management, Curation Rules, Contradiction Log. OAuth-proxy sidecar in front of OpenShift login. |
| **Auth service** | [`memoryhub-auth/`](memoryhub-auth/) | Standalone OAuth 2.1 authorization server. FastAPI with `client_credentials` and `refresh_token` grants, RSA-2048 JWT signing, JWKS endpoint, admin client management API. |
| **Database migrations** | [`alembic/`](alembic/) | Schema migrations for the server-side library. PostgreSQL with the pgvector extension. |
| **Design docs** | [`docs/`](docs/) | Subsystem designs, the agent-memory-ergonomics design cluster, package layout, RHOAI demo materials, kagenti and LlamaStack integration plans. Start at [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md). |
| **Retrospectives** | [`retrospectives/`](retrospectives/) | Per-session retros documenting decisions, gaps, and patterns. Read these for the "why" behind major design choices. |

## Three ways to use it

### 1. From an agent via MCP (Claude Code, kagenti, anything that speaks MCP)

The deployed server exposes a streamable-HTTP MCP endpoint. Add it to your agent's MCP configuration:

```bash
claude mcp add --transport http \
  -s project \
  memoryhub \
  https://memory-hub-mcp-memory-hub-mcp.apps.<your-cluster>.com/mcp/
```

Then run `memoryhub config init` (from the CLI, see below) to generate a `.claude/rules/memoryhub-loading.md` that tells the agent when and how to call the tools. The generated rule covers session start, working-set loading, pivot detection, memory hygiene, and contradiction handling — all parameterized by your project's session shape (focused / broad / adaptive).

### 2. From Python via the SDK

```bash
pip install memoryhub
```

```python
import asyncio
from memoryhub import MemoryHubClient

async def main():
    client = MemoryHubClient.from_env()  # reads MEMORYHUB_URL, MEMORYHUB_AUTH_URL, MEMORYHUB_CLIENT_ID, MEMORYHUB_CLIENT_SECRET
    async with client:
        results = await client.search(
            "deployment patterns",
            focus="OpenShift",      # optional session focus (Layer 2)
            max_results=10,
        )
        for memory in results.results:
            print(f"[{memory.scope}] {memory.content[:80]}")

asyncio.run(main())
```

The SDK auto-discovers `.memoryhub.yaml` from the current working directory and applies its `retrieval_defaults` to outbound search calls. See [`sdk/README.md`](sdk/README.md) for the full API surface.

### 3. From the terminal via the CLI

```bash
pip install memoryhub-cli
memoryhub login                          # one-time credential setup
memoryhub search "deployment patterns"   # search
memoryhub read <memory-id>               # read by ID
memoryhub write "Use Podman, not Docker" --scope user --weight 0.9
memoryhub config init                    # set up .memoryhub.yaml + agent rule file
```

## Architecture at a glance

```
                    ┌─────────────────────────────────────────┐
                    │  Consumer surfaces                      │
                    │   • Agents over MCP (streamable-HTTP)   │
                    │   • Python SDK (memoryhub on PyPI)      │
                    │   • CLI (memoryhub-cli)                 │
                    │   • Dashboard UI (React + PF6 + BFF)    │
                    └────────────────┬────────────────────────┘
                                     │
                          ┌──────────▼──────────┐
                          │   memory-hub-mcp    │
                          │   (FastMCP 3)       │
                          │   13 tools          │
                          └──────────┬──────────┘
                                     │
              ┌──────────────────────┼──────────────────────┐
              │                      │                      │
      ┌───────▼───────┐    ┌─────────▼─────────┐   ┌────────▼──────────┐
      │  authz / RBAC │    │ services / models │   │  embedding model  │
      │  (JWT verify, │    │  (src/memoryhub/) │   │  + cross-encoder  │
      │   scope match)│    │                   │   │  (RHOAI vLLM)     │
      └───────┬───────┘    └─────────┬─────────┘   └───────────────────┘
              │                      │
      ┌───────▼─────────┐   ┌────────▼─────────┐
      │ memoryhub-auth  │   │  PostgreSQL +    │
      │  (OAuth 2.1 AS) │   │  pgvector        │
      └─────────────────┘   └──────────────────┘
```

Every memory operation flows through the MCP server, which delegates to the service layer in `src/memoryhub/`. The service layer enforces authorization via `core/authz.py` (JWT-first, session-fallback). The OAuth 2.1 authorization server runs as a separate service. PostgreSQL with pgvector handles relational, vector, and graph queries; an external all-MiniLM-L6-v2 embedding model and an `ms-marco-MiniLM-L12-v2` cross-encoder reranker both run on OpenShift AI's vLLM serving. Reranker is optional with graceful cosine fallback when unavailable.

For the full design and the deployment topology, see [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md). For the per-subsystem map, see [`docs/SYSTEMS.md`](docs/SYSTEMS.md).

## Project layout

```
memory-hub/
├── src/memoryhub/              # Server-side library (services, storage, models, authz)
├── memory-hub-mcp/             # FastMCP 3 MCP server (deployed)
├── memoryhub-auth/             # OAuth 2.1 authorization server (deployed)
├── memoryhub-ui/               # Dashboard: React + PatternFly 6 frontend, FastAPI BFF (deployed)
│   ├── backend/
│   └── frontend/
├── sdk/                        # Python SDK published to PyPI as `memoryhub`
├── memoryhub-cli/              # CLI client (`pip install memoryhub-cli`)
├── alembic/                    # Database migrations
├── tests/                      # Server-side library tests
├── docs/                       # Architecture, subsystem designs, agent-memory-ergonomics
├── retrospectives/             # Session retros — read for design context
├── deploy/                     # Top-level deploy assets (PostgreSQL manifests)
└── benchmarks/                 # Empirical benchmark results (e.g. two-vector-retrieval/)
```

A note on the package name: there are two Python packages in this repo that both declare `name = "memoryhub"` — the server-side library at `src/memoryhub/` and the SDK at `sdk/src/memoryhub/`. They never coexist in the same environment (the server is bundled into the MCP container; the SDK is installed from PyPI), but the shared name is a known footgun being tracked as issue #55. See [`docs/package-layout.md`](docs/package-layout.md).

## Development

Set up the server-side library:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest tests/ -v
```

Each subproject has its own venv and `pytest`:

```bash
# MCP server
cd memory-hub-mcp && make install && .venv/bin/pytest tests/ -q --ignore=tests/examples/

# SDK
cd sdk && .venv/bin/pytest tests/ -q --ignore=tests/test_rbac_live.py

# CLI
cd memoryhub-cli && .venv/bin/pytest tests/ -q

# Dashboard BFF
cd memoryhub-ui/backend && .venv/bin/pytest tests/ -q
```

See [`CLAUDE.md`](CLAUDE.md) for project conventions, the issue-tracker workflow, and the MCP-server scaffold rules.

## Contributing

Issues and PRs are welcome. Use the `/issue-tracker` slash command (or follow [`CLAUDE.md`](CLAUDE.md)) when filing — every issue references a design document and follows the Backlog → In Progress → Done flow.

## License

Apache 2.0 — see [`LICENSE`](LICENSE).

## Links

- [Architecture](docs/ARCHITECTURE.md)
- [Subsystems](docs/SYSTEMS.md)
- [Agent memory ergonomics design](docs/agent-memory-ergonomics/)
- [Python SDK on PyPI](https://pypi.org/project/memoryhub/)
- [GitHub issues](https://github.com/rdwj/memory-hub/issues)
