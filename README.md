# MemoryHub

Centralized, governed memory for AI agents on OpenShift AI. MemoryHub gives every agent in your organization a shared, persistent memory layer with multi-tier scoping (`user` / `project` / `campaign` / `role` / `organizational` / `enterprise`), version history, semantic search via pgvector, audit logging (structured events shipped; durable audit store in progress), and an OAuth 2.1 authorization story.

It works with any agent framework that speaks MCP — Claude Code, LlamaStack workflows, LangGraph/CrewAI/AG2 agents, custom Python agents — and ships a typed Python SDK and a CLI for direct use.

**Requires Python 3.11+** (use [uv](https://docs.astral.sh/uv/) to install it automatically). See [Local Development](docs/guides/local-development.md) to get the MCP server running on your machine, or the [Agent Integration Guide](docs/guides/agent-integration-guide.md) for the conceptual overview of rules, hooks, and agent-driven memory plus the integration reference.

## How to think about agent memory

The model never remembers anything — at inference time, a memory is just tokens in context, and it makes no difference whether they came from a markdown file, a vector store, or a graph. Memory is a **context-assembly policy problem**: how did the right items get selected, who was allowed to see them, what happens when they conflict, and can you reconstruct what an agent knew when it acted?

Two principles drive everything here. First, give the agent **100% of what it needs and 0% of what it doesn't** — no retrieval trick compensates for missing context, and garbage overlap degrades performance even when the right facts are present. Second, **work backwards from the forensic investigation**: who or what did the thing, what memories were in context, who wrote them, were they in conflict, did storing them violate policy, and which other agents were exposed to them?

That second principle is the honest dividing line. One developer coding on one machine? Use your harness's built-in memory and you are well-served. Just you, beyond coding? llm-wiki or Obsidian is the right answer. But a fleet of agents sharing fast-changing operational memory, a team of developers with coding agents in a controlled environment, or agents in a healthcare process — and any scenario where the forensic questions will actually be asked — need identity, scopes, curation, contradiction handling, and audit. That's what MemoryHub is.

The full argument, including when *not* to use MemoryHub: [What Agent Memory Really Is](docs/guides/what-is-agent-memory.md).

## Why MemoryHub

- **Governed memory operations.** Every write, read, update, and deletion is access-controlled by [six-tier scope isolation](docs/design/governance.md) enforced at the SQL level. Memories carry [version history with provenance branches](docs/design/memory-tree.md), contradiction detection, and a [three-layer curation rules engine](docs/design/curator-agent.md) with inline secrets/PII scanning. Enterprise-scope memories require human approval. This is the substrate that makes all other capabilities trustworthy.

- **Shared agent memory.** Agents don't just remember for themselves — they build an organizational hive mind. [Project-scoped memories](docs/design/memory-tree.md) surface for every agent working in that context, with auto-enrollment on first write to open projects so agents can start contributing without manual membership setup. [Campaign scoping](planning/archive/campaign-domain-framework.md) enables bounded cross-project initiatives where knowledge discovered by one project's agent is available to all enrolled projects. Domain tags enable crosscutting retrieval. [Two-vector retrieval](docs/design/two-vector-retrieval.md) blends query relevance with session focus context via RRF and cross-encoder reranking, so search results match both what the agent asked and what it's currently working on. [Real-time push notifications](docs/agent-memory-ergonomics/design.md) keep agent swarms current. A planned promotion pipeline will lift patterns discovered by individual agents into organizational knowledge.

- **Inference cost optimization.** [Cache-optimized assembly](research/infra/vllm-kv-cache.md) returns memories in a deterministic, epoch-locked order designed for KV cache prefix hits across vLLM (2x throughput, 152x TTFT), Anthropic (90% cost reduction), OpenAI (50%), and Gemini (75-90%). The key insight: the first agent pays full inference cost; subsequent agents with overlapping memory contexts get the cached prefix nearly free. Token budget caps and weight-based stub/full injection keep context windows lean. [Governed context compaction](research/surveys/retrieval-compaction-persistence.md) is on the roadmap.

- **Compliance-oriented architecture.** Version history, provenance branches, structured audit events, and a planned [durable audit trail](docs/design/governance.md) position MemoryHub for EU AI Act transparency requirements (enforcement begins August 2026), GDPR data governance, HIPAA, and financial regulations. Compaction will use readable summaries — not opaque tokens — so the compliance team can inspect what was kept.

- **Framework-agnostic integration.** Works with any agent framework that speaks MCP. A [typed Python SDK](sdk/README.md), a CLI, a [project config wizard](docs/agent-memory-ergonomics/design.md) that generates agent rule files, and a designed integration path for [LlamaStack](planning/llamastack-integration/overview.md).

- **Kubernetes-native on OpenShift AI.** [PostgreSQL + pgvector](docs/design/storage-layer.md) handling relational, vector, and graph queries in one database, with MinIO for object storage. FIPS compliance by delegation. Air-gap deployable with on-cluster embedding models. Red Hat UBI images. An [llm-d integration path](research/infra/vllm-kv-cache.md) for automatic cache-aware routing at the infrastructure level.

**Status (2026-04-15).** Core memory operations, OAuth 2.1 + JWT auth with service-layer RBAC, the dashboard UI, the published Python SDK, the agent-memory-ergonomics work (search shape, session focus vector with cross-encoder reranking, project config + rule generation), and cache-optimized memory assembly with compilation epochs are all shipped. The Kubernetes operator and the curator-as-background-agent layer are still on the roadmap. See [`docs/SYSTEMS.md`](docs/SYSTEMS.md) for the per-subsystem status table.

## What's in this repo

| Component | Path | What it is |
|---|---|---|
| **MCP server** | [`memory-hub-mcp/`](memory-hub-mcp/) | FastMCP 3 server exposing memory operations (search, read, write, update, delete, similarity, relationships, curation, contradictions, threads, session registration, project discovery) over streamable-HTTP via profile-selectable tool sets — compact (4 action-dispatch tools, default), full (13), minimal (5). The primary agent surface. |
| **Server-side library** | [`src/memoryhub_core/`](src/memoryhub_core/) | SQLAlchemy models, service layer, embedding integration, RBAC enforcement (`core/authz.py`). Distribution name `memoryhub-core`; import name `memoryhub_core`. The MCP server, BFF, alembic migrations, and the seed-OAuth-clients script all import from here. |
| **Python SDK** | [`sdk/`](sdk/) | `pip install memoryhub` — typed async client wrapping the MCP tools. OAuth 2.1 token management is automatic. See [`sdk/README.md`](sdk/README.md). |
| **CLI** | [`memoryhub-cli/`](memoryhub-cli/) | `pip install memoryhub-cli` — terminal client for search/read/write/delete plus `memoryhub config init` for generating project-level `.memoryhub.yaml` and `.claude/rules/memoryhub-loading.md` rule files. |
| **Dashboard UI** | [`memoryhub-ui/`](memoryhub-ui/) | React + PatternFly 6 frontend behind a FastAPI BFF, deployed as a single container. Six panels: Memory Graph, Status Overview, Users & Agents, Client Management, Curation Rules, Contradiction Log. OAuth-proxy sidecar in front of OpenShift login. |
| **Auth service** | [`memoryhub-auth/`](memoryhub-auth/) | Standalone OAuth 2.1 authorization server. FastAPI with `client_credentials` and `refresh_token` grants, RSA-2048 JWT signing, JWKS endpoint, admin client management API. |
| **Database migrations** | [`alembic/`](alembic/) | Schema migrations for the server-side library. PostgreSQL with the pgvector extension. |
| **Design docs** | [`docs/`](docs/) | Subsystem designs, the agent-memory-ergonomics design cluster, package layout, auth and identity model. Start at [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md). |
| **Planning** | [`planning/`](planning/) | In-flight designs for unimplemented features (operator, observability, org-ingestion) and the LlamaStack integration plan. |
| **Research** | [`research/`](research/) | Investigations and explorations — FIPS storage analysis, agent-memory-ergonomics research notes. |
| **Demos** | [`demos/`](demos/) | Conference demo scripts (HIMSS, RSA, IACP, IAEM, World AgriTech) and the RHOAI dashboard demo material. |
| **Retrospectives** | [`retrospectives/`](retrospectives/) | Per-session retros documenting decisions, gaps, and patterns. Read these for the "why" behind major design choices. |

## Install in your cluster

MemoryHub installs to any OpenShift cluster with Red Hat OpenShift AI (RHOAI). The full stack is seven services across six namespaces, all deployed by a single `make install`.

### Prerequisites

- `oc` logged in with cluster-admin on a cluster with RHOAI installed
- `podman` on your PATH (checked but not required for server-side builds)
- A default StorageClass (most clusters have one)
- Python 3.11+ on your PATH (the deploy script creates `.venv` automatically)

Run `make check-prereqs` to verify all of these non-destructively. GPUs are not required; the default install uses CPU-based embedding and reranker models.

### Quick start

```bash
git clone https://github.com/redhat-ai-americas/memory-hub.git
cd memory-hub
oc login <cluster-api-url>      # cluster-admin required
make install                    # full stack deploy (~10 min)
```

That's it. The deploy script auto-creates the Python virtualenv (for Alembic migrations), generates API keys for the users ConfigMap if it doesn't exist, writes the first key to `~/.config/memoryhub/api-key` for CLI/SDK use, and runs a write/search/read smoke test at the end.

To bring your own API keys instead, copy the template before running install:

```bash
cp memory-hub-mcp/deploy/users-configmap.example.yaml \
   memory-hub-mcp/deploy/users-configmap.yaml
# Replace REPLACE-ME placeholders with: openssl rand -hex 16
make install
```

### What gets deployed

| Service | Namespace | What |
|---------|-----------|------|
| PostgreSQL + pgvector | `memoryhub-db` | Database (memories, threads, graph, auth tables) |
| MinIO | `memory-hub-mcp` | S3-compatible object storage for oversized content |
| Valkey | `memory-hub-mcp` | Session focus state and compilation epoch cache |
| Embedding model | `embedding-model` | all-MiniLM-L6-v2 via HuggingFace TEI (CPU, 384-dim) |
| Reranker model | `reranker-model` | ms-marco-MiniLM-L12-v2 cross-encoder via TEI (CPU) |
| Auth service | `memoryhub-auth` | OAuth 2.1 authorization server (JWT, PKCE, API keys) |
| MCP server | `memory-hub-mcp` | FastMCP 3 server exposing memory operations |
| Dashboard UI | `memoryhub-ui` | React + PatternFly 6 frontend with FastAPI BFF |

All service URLs (auth JWKS, embedding, reranker) are resolved dynamically from cluster state at deploy time. No hardcoded cluster domains.

Expect 8-15 minutes on a first install. The MCP server, auth service, and UI each go through an OpenShift BuildConfig, and the embedding/reranker models need to download weights on first run.

**Prerequisites:** `oc` and `podman` on your PATH, cluster-admin on a cluster with RHOAI installed, a default StorageClass. `make check-prereqs` verifies all of these -- run it first. See [`CONTRIBUTING.md`](CONTRIBUTING.md) for the "new contributor no-deploy" rule: if you're onboarding to this codebase, work against a local SQLite or Podman PostgreSQL instead of deploying to a cluster.

### Targeting a specific cluster

If you have multiple clusters configured in your kubeconfig, set `MEMORYHUB_CONTEXT` to target a specific one without switching your active context:

```bash
MEMORYHUB_CONTEXT=my-cluster make install
MEMORYHUB_CONTEXT=my-cluster make uninstall
```

This passes `--context` on every `oc` command and never mutates your kubeconfig.

### Deploy options

```bash
make install                           # full stack (CPU models, default)
make install -- --gpu-models           # use GPU embedding/reranker models instead
make install -- --skip-models          # skip embedding/reranker (mock search)
make install -- --skip-ui --skip-tile  # headless (no dashboard)
```

### Uninstall

```bash
make uninstall                         # prompts for confirmation
make uninstall -- --yes                # non-interactive (CI)
make uninstall -- --skip-db            # preserve database across reinstall
make uninstall -- --skip-models        # keep embedding/reranker models running
```

### Partial deploys (advanced)

`make deploy-db`, `make deploy-mcp`, `make deploy-auth`, `make deploy-ui`, `make deploy-tile` each deploy a single service and skip the others. `make help` lists everything.

### Post-install verification

The deploy script prints a summary banner with all Route URLs. Verify the MCP endpoint with:

```bash
# Health check (406 = correct for streamable-HTTP MCP)
curl -s -o /dev/null -w "%{http_code}" \
  https://memory-hub-mcp-memory-hub-mcp.apps.<cluster>/mcp/

# Auth health
curl -s https://auth-server-memoryhub-auth.apps.<cluster>/healthz
```

For full tool verification, use `mcp-test-mcp` to connect to the deployed MCP server and list its tools.

### After install

The install summary banner prints the routes for each service. Follow these steps to verify the deployment and connect your first agent.

**1. Get an API key.** The install creates a `memoryhub-users` ConfigMap in the `memory-hub-mcp` namespace with pre-seeded users and API keys. To view the available keys:

```bash
oc get configmap memoryhub-users -n memory-hub-mcp \
  -o jsonpath='{.data.users\.json}' | python3 -m json.tool
```

Copy a key (format: `mh-dev-<hex>`) and store it locally:

```bash
mkdir -p ~/.config/memoryhub
echo "mh-dev-<your-key>" > ~/.config/memoryhub/api-key
```

To add new users or rotate keys, see the [API key provisioning runbook](docs/runbooks/add-mcp-api-user.md).

**2. Install the CLI and SDK.**

```bash
pip install memoryhub-cli    # terminal client
pip install memoryhub        # Python SDK (optional, for scripting)
```

**3. Verify the deployment.** Use the CLI to test the connection:

```bash
memoryhub login              # configures endpoint + API key
memoryhub search "test"      # should return empty results on a fresh install
```

Or use the SDK directly:

```bash
python scripts/seed-sample-data.py \
  --url https://<your-mcp-route>/mcp/
```

This writes sample memories across multiple scopes so the dashboard has content to display.

**4. Connect Claude Code.** Add the MCP server to Claude Code (the server name `memoryhub` is required as the first positional argument):

```bash
claude mcp add memoryhub \
  --transport http \
  -s user \
  https://<your-mcp-route>/mcp/
```

Then set up the agent rule file so Claude Code knows how to use the tools:

```bash
memoryhub config init        # interactive wizard — generates .memoryhub.yaml + .claude/rules/
```

**5. Open the dashboard from RHOAI.** The install adds a MemoryHub tile to the Red Hat OpenShift AI application catalog:

1. Open the RHOAI dashboard (the URL printed in the install summary, or find it at `https://rhods-dashboard-redhat-ods-applications.apps.<your-cluster>/`)
2. Click **Applications** in the left sidebar, then **Explore**
3. Find the **MemoryHub** tile and click it
4. Click **Open application** to launch the admin dashboard

The dashboard has six panels: Memory Graph (visual node/edge view of memories and relationships), Status Overview (system health), Users & Agents (active sessions), Client Management (OAuth clients), Curation Rules (content filtering), and Contradiction Log (conflicting memories). If you ran `seed-sample-data.py` in step 3, the Memory Graph will show the seeded memories and their relationships.

## Three ways to use it

### 1. From an agent via MCP (Claude Code, or anything that speaks MCP)

The deployed server exposes a streamable-HTTP MCP endpoint. Add it to your agent's MCP configuration (note: the server name `memoryhub` is a required positional argument):

```bash
claude mcp add memoryhub \
  --transport http \
  -s user \
  https://memory-hub-mcp-memory-hub-mcp.apps.<your-cluster>.com/mcp/
```

Then run `memoryhub config init` (from the CLI, see below) to generate a `.claude/rules/memoryhub-loading.md` that tells the agent when and how to call the tools. The generated rule covers session start, working-set loading, pivot detection, memory hygiene, and contradiction handling -- all parameterized by your project's session shape (focused / broad / adaptive).

For zero-overhead startup, add a [SessionStart hook](docs/guides/hooks-integration.md) that pre-loads memories into the conversation context before the first prompt — no MCP calls, no token overhead from structural metadata. The MCP server remains available for mid-session searches and writes.

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

## Authentication: API key vs OAuth

MemoryHub supports two authentication paths. **API keys** are the simplest option: obtain a key from your administrator, store it at `~/.config/memoryhub/api-key`, and call `register_session(api_key=...)` at the start of each conversation. This is the right choice for Claude Code, the CLI, scripts, and most integrations. **OAuth 2.1** (`client_credentials` grant) is available for production agents that need automatic token refresh, multi-tenant isolation, and fine-grained scopes via the auth service's client management API. Most users should start with API keys and move to OAuth only when their deployment requires it.

## Project configuration

MemoryHub splits configuration into two files with different lifecycles: project-level policy lives in `.memoryhub.yaml` at the repo root (committed, shared across all contributors), while per-developer connection params and secrets live in `~/.config/memoryhub/config.json` (not committed, managed by `memoryhub login`).

`memoryhub config init` is an interactive wizard that asks about session shape, loading pattern, focus source, and retrieval defaults, then writes both files — commit them so every contributor's agent inherits the same loading pattern. After hand-editing the YAML, `memoryhub config regenerate` re-renders the rule file. The YAML schema (`memory_loading` + `retrieval_defaults`), field reference, rule-file templates, and the `/memoryhub-init` slash command for running the wizard from inside Claude Code are all documented in [`docs/agent-memory-ergonomics/design.md`](docs/agent-memory-ergonomics/design.md) and the [CLI README](memoryhub-cli/README.md).

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
                          │   4 tools (compact) │
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

Every memory operation flows through the MCP server; authorization, curation, and governance are enforced in the service layer — no surface talks to PostgreSQL directly. The full design, data flows, and deployment topology live in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md); the per-subsystem map is [`docs/SYSTEMS.md`](docs/SYSTEMS.md).

## Documentation

Full documentation lives in four top-level directories. Start with [`docs/README.md`](docs/README.md) for a guided tour, or jump straight to whichever area matches your need:

- **[`docs/`](docs/README.md)** — Shipped architecture and reference material. Subsystem designs (memory tree, storage layer, governance, curator, MCP server), agent memory ergonomics, auth, identity model, admin operations.
- **[`planning/`](planning/)** — In-flight designs, open questions, and integration roadmaps (Kubernetes operator, observability, LlamaStack integration).
- **[`research/`](research/)** — Investigations and benchmarks that informed shipped decisions (FIPS storage evaluation, two-vector retrieval ranking, pivot detection, FastMCP push notifications, Claude Code JWT limitations).
- **[`demos/`](demos/)** — Conference demo scripts and scenario material (HIMSS, RSA, IACP, IAEM, World AgriTech, and the RHOAI dashboard tile demo).

Package-specific docs live in each package's own README:

- **[Python SDK](sdk/README.md)** — quickstart, API reference, project config, authentication
- **[CLI](memoryhub-cli/README.md)** — commands, project config, credential setup
- **[MCP server](memory-hub-mcp/README.md)** — tool list, deployment, testing
- **[Auth service](memoryhub-auth/)** — standalone OAuth 2.1 authorization server
- **[Hooks integration](docs/guides/hooks-integration.md)** — zero-overhead memory injection at Claude Code session start

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
├── deploy/                     # K8s manifests (PostgreSQL, MinIO, Valkey, embedding, reranker)
└── benchmarks/                 # Empirical benchmark results (e.g. two-vector-retrieval/)
```

A note on the package layout: the server-side library at `src/memoryhub_core/` is published locally as `memoryhub-core` (used by the MCP server, BFF, alembic, and the root test suite), while the client SDK at `sdk/src/memoryhub/` is published to PyPI as `memoryhub`. Distinct distribution names, distinct import names. See [`planning/archive/package-layout.md`](planning/archive/package-layout.md) for the rationale.

## Development

Requires Python 3.11+. We recommend [uv](https://docs.astral.sh/uv/) for environment management -- it handles Python installation, venv creation, and dependency resolution in one tool. If you don't have Python 3.11, uv fetches it automatically.

Each subproject maintains its own venv to avoid dependency conflicts.

Set up the server-side library:

```bash
# With uv (recommended — installs Python 3.11 if needed)
uv venv --python 3.11
uv pip install -e ".[dev]"
source .venv/bin/activate
pytest tests/ -v

# Or with plain venv (requires Python 3.11+ already installed)
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest tests/ -v
```

Each subproject (MCP server, SDK, CLI, BFF, auth) has its own venv and `pytest` suite — per-subproject setup commands are in [`CONTRIBUTING.md`](CONTRIBUTING.md). See [`CLAUDE.md`](CLAUDE.md) for project conventions, the issue-tracker workflow, and the MCP-server scaffold rules.

## Contributing

Issues and PRs are welcome. Start with [`CONTRIBUTING.md`](CONTRIBUTING.md) for the local dev setup, coding conventions, and PR flow. Use the `/issue-tracker` slash command (or follow [`CLAUDE.md`](CLAUDE.md)) when filing — every issue references a design document and follows the Backlog → In Progress → Done flow.

Most contributions do not need access to the demo OpenShift cluster — local SQLite or a podman PostgreSQL container is enough. If you do need cluster access, see [`docs/admin/contributor-cluster-access.md`](docs/admin/contributor-cluster-access.md) for the access policy, GitHub IdP setup, and the no-deploy rule for new contributors.

Maintainers inviting new contributors should follow the checklist in [`docs/admin/inviting-new-contributors.md`](docs/admin/inviting-new-contributors.md).

## License

Apache 2.0 — see [`LICENSE`](LICENSE).

## Links

- [What agent memory really is](docs/guides/what-is-agent-memory.md) · [Agent integration guide](docs/guides/agent-integration-guide.md) · [Architecture](docs/ARCHITECTURE.md) · [Subsystems](docs/SYSTEMS.md)
- [Python SDK on PyPI](https://pypi.org/project/memoryhub/) · [GitHub issues](https://github.com/redhat-ai-americas/memory-hub/issues)
