# MemoryHub

Centralized, governed memory for AI agents on OpenShift AI. MemoryHub gives every agent in your organization a shared, persistent memory layer with multi-tier scoping (`user` / `project` / `role` / `organizational` / `enterprise`), version history, semantic search via pgvector, an immutable audit trail, and an OAuth 2.1 authorization story.

It works with any agent framework that speaks MCP — Claude Code, kagenti-deployed agents (LangGraph, CrewAI, AG2, …), LlamaStack workflows, custom Python agents — and ships a typed Python SDK and a CLI for direct use.

**Status (2026-04-07).** Core memory operations, OAuth 2.1 + JWT auth with service-layer RBAC, the dashboard UI, the published Python SDK, and the agent-memory-ergonomics work (search shape, session focus vector with cross-encoder reranking, project config + rule generation) are all shipped. The Kubernetes operator and the curator-as-background-agent layer are still on the roadmap. See [`docs/SYSTEMS.md`](docs/SYSTEMS.md) for the per-subsystem status table.

## What's in this repo

| Component | Path | What it is |
|---|---|---|
| **MCP server** | [`memory-hub-mcp/`](memory-hub-mcp/) | FastMCP 3 server exposing 13 tools (search, read, write, update, delete, history, similarity, relationships, curation, contradiction, session) over streamable-HTTP. The primary agent surface. |
| **Server-side library** | [`src/memoryhub_core/`](src/memoryhub_core/) | SQLAlchemy models, service layer, embedding integration, RBAC enforcement (`core/authz.py`). Distribution name `memoryhub-core`; import name `memoryhub_core`. The MCP server, BFF, alembic migrations, and the seed-OAuth-clients script all import from here. |
| **Python SDK** | [`sdk/`](sdk/) | `pip install memoryhub` — typed async client wrapping the MCP tools. OAuth 2.1 token management is automatic. See [`sdk/README.md`](sdk/README.md). |
| **CLI** | [`memoryhub-cli/`](memoryhub-cli/) | `pip install memoryhub-cli` — terminal client for search/read/write/delete plus `memoryhub config init` for generating project-level `.memoryhub.yaml` and `.claude/rules/memoryhub-loading.md` rule files. |
| **Dashboard UI** | [`memoryhub-ui/`](memoryhub-ui/) | React + PatternFly 6 frontend behind a FastAPI BFF, deployed as a single container. Six panels: Memory Graph, Status Overview, Users & Agents, Client Management, Curation Rules, Contradiction Log. OAuth-proxy sidecar in front of OpenShift login. |
| **Auth service** | [`memoryhub-auth/`](memoryhub-auth/) | Standalone OAuth 2.1 authorization server. FastAPI with `client_credentials` and `refresh_token` grants, RSA-2048 JWT signing, JWKS endpoint, admin client management API. |
| **Database migrations** | [`alembic/`](alembic/) | Schema migrations for the server-side library. PostgreSQL with the pgvector extension. |
| **Design docs** | [`docs/`](docs/) | Subsystem designs, the agent-memory-ergonomics design cluster, package layout, auth and identity model. Start at [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md). |
| **Planning** | [`planning/`](planning/) | In-flight designs for unimplemented features (operator, observability, org-ingestion, session-persistence) and the kagenti/LlamaStack integration plans. |
| **Research** | [`research/`](research/) | Investigations and explorations — FIPS storage analysis, agent-memory-ergonomics research notes. |
| **Demos** | [`demos/`](demos/) | Conference demo scripts (HIMSS, RSA, IACP, IAEM, World AgriTech) and the RHOAI dashboard demo material. |
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

## Project configuration

MemoryHub splits configuration into two files with different lifecycles: project-level policy lives in `.memoryhub.yaml` at the repo root (committed, shared across all contributors), while per-developer connection params and secrets live in `~/.config/memoryhub/config.json` (not committed, managed by `memoryhub login`).

`memoryhub config init` is an interactive wizard that asks about session shape, loading pattern, focus source, and retrieval defaults, then writes `.memoryhub.yaml` and `.claude/rules/memoryhub-loading.md`. Both files are meant to be committed so every contributor's agent inherits the same loading pattern. On first run, any legacy `.claude/rules/memoryhub-integration.md` is backed up to `.bak` before the new rule file is written.

After hand-editing `.memoryhub.yaml`, run `memoryhub config regenerate` to re-render the rule file from the YAML without touching the YAML itself.

The YAML has two top-level keys — `memory_loading` (when and how agents load memory) and `retrieval_defaults` (defaults applied to SDK/agent search calls):

```yaml
memory_loading:
  mode: focused                   # focused | broad
  pattern: lazy_with_rebias       # eager | lazy | lazy_with_rebias | jit
  focus_source: auto              # auto | declared | directory | first_turn
  session_focus_weight: 0.4
  on_topic_shift: rebias          # rebias | warn | ignore

retrieval_defaults:
  max_results: 20
  max_response_tokens: 4000
  default_mode: full              # full | index | full_only
```

See [`docs/agent-memory-ergonomics/design.md`](docs/agent-memory-ergonomics/design.md) for the full schema, field reference, and rule file templates.

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
      │  (JWT verify, │    │ (memoryhub_core)  │   │  + cross-encoder  │
      │   scope match)│    │                   │   │  (RHOAI vLLM)     │
      └───────┬───────┘    └─────────┬─────────┘   └───────────────────┘
              │                      │
      ┌───────▼─────────┐   ┌────────▼─────────┐
      │ memoryhub-auth  │   │  PostgreSQL +    │
      │  (OAuth 2.1 AS) │   │  pgvector        │
      └─────────────────┘   └──────────────────┘
```

Every memory operation flows through the MCP server, which delegates to the service layer in `src/memoryhub_core/`. The service layer enforces authorization via `core/authz.py` (JWT-first, session-fallback). The OAuth 2.1 authorization server runs as a separate service. PostgreSQL with pgvector handles relational, vector, and graph queries; an external all-MiniLM-L6-v2 embedding model and an `ms-marco-MiniLM-L12-v2` cross-encoder reranker both run on OpenShift AI's vLLM serving. Reranker is optional with graceful cosine fallback when unavailable.

For the full design and the deployment topology, see [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md). For the per-subsystem map, see [`docs/SYSTEMS.md`](docs/SYSTEMS.md).

## Documentation

Full documentation lives in four top-level directories. Start with [`docs/README.md`](docs/README.md) for a guided tour, or jump straight to whichever area matches your need:

- **[`docs/`](docs/README.md)** — Shipped architecture and reference material. Subsystem designs (memory tree, storage layer, governance, curator, MCP server), agent memory ergonomics, auth, identity model, admin operations.
- **[`planning/`](planning/)** — In-flight designs, open questions, and integration roadmaps (Kubernetes operator, observability, session persistence, kagenti and LlamaStack integrations).
- **[`research/`](research/)** — Investigations and benchmarks that informed shipped decisions (FIPS storage evaluation, two-vector retrieval ranking, pivot detection, FastMCP push notifications, Claude Code JWT limitations).
- **[`demos/`](demos/)** — Conference demo scripts and scenario material (HIMSS, RSA, IACP, IAEM, World AgriTech, and the RHOAI dashboard tile demo).

Package-specific docs live in each package's own README:

- **[Python SDK](sdk/README.md)** — quickstart, API reference, project config, authentication
- **[CLI](memoryhub-cli/README.md)** — commands, project config, credential setup
- **[MCP server](memory-hub-mcp/README.md)** — tool list, deployment, testing
- **[Auth service](memoryhub-auth/)** — standalone OAuth 2.1 authorization server

For LLM agents crawling this repo: [`llms.txt`](llms.txt) at the repo root follows the [llmstxt.org](https://llmstxt.org/) convention and is the most direct entry point.

## Project layout

```
memory-hub/
├── src/memoryhub_core/         # Server-side library (services, storage, models, authz)
├── memory-hub-mcp/             # FastMCP 3 MCP server (deployed)
├── memoryhub-auth/             # OAuth 2.1 authorization server (deployed)
├── memoryhub-ui/               # Dashboard: React + PatternFly 6 frontend, FastAPI BFF (deployed)
│   ├── backend/
│   └── frontend/
├── sdk/                        # Python SDK published to PyPI as `memoryhub`
├── memoryhub-cli/              # CLI client (`pip install memoryhub-cli`)
├── alembic/                    # Database migrations
├── tests/                      # Server-side library tests
├── docs/                       # Shipped architecture and subsystem designs
├── planning/                   # In-flight designs for unimplemented features
├── research/                   # Investigations and explorations
├── demos/                      # Conference demo scripts and dashboard demo material
├── retrospectives/             # Session retros — read for design context
├── deploy/                     # Top-level deploy assets (PostgreSQL manifests)
└── benchmarks/                 # Empirical benchmark results (e.g. two-vector-retrieval/)
```

A note on the package layout: the server-side library at `src/memoryhub_core/` is published locally as `memoryhub-core` (used by the MCP server, BFF, alembic, and the root test suite), while the client SDK at `sdk/src/memoryhub/` is published to PyPI as `memoryhub`. Distinct distribution names, distinct import names. See [`docs/package-layout.md`](docs/package-layout.md) for the rationale.

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
