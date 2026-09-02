# MemoryHub

Persistent, governed memory for AI agents. MemoryHub gives agents a shared memory layer with semantic search, version history, scoped access control, and audit logging. It works with any agent framework that speaks MCP.

**Try it now** -- `pip install "memoryhub[local]"` for a personal edition backed by SQLite (no infrastructure needed), or deploy the [cluster edition](docs/guides/cluster-install.md) on OpenShift AI for multi-agent governance, OAuth 2.1, and team-wide shared memory.

Retrieval quality: 83.7% on [AMB PersonaMem 32k](benchmarks/RESULTS.md) (submitted to leaderboard, pending review), R@5=0.999 on LongMemEval oracle. Requires Python 3.10+.

## How to think about agent memory

**Agent memory is experiential knowledge — decisions made, preferences discovered, outcomes observed — accumulated through agent interactions, persisted across sessions, and recalled to shape future behavior.** It is distinct from documents retrieved (RAG), information found (search), or domains modeled (ontology). See [How Information Enters Context](docs/guides/context-assembly.md) for a visual breakdown of how these sources converge into the model's context window.

The model never remembers anything -- at inference time, a memory is just tokens in context, and it makes no difference whether they came from a markdown file, a vector store, or a graph. Memory is a **context-assembly policy problem**: how did the right items get selected, who was allowed to see them, what happens when they conflict, and can you reconstruct what an agent knew when it acted?

Two principles drive everything here. First, give the agent **100% of what it needs and 0% of what it doesn't** -- no retrieval trick compensates for missing context, and garbage overlap degrades performance even when the right facts are present. Second, **work backwards from the forensic investigation**: who or what did the thing, what memories were in context, who wrote them, were they in conflict, did storing them violate policy, and which other agents were exposed to them?

That second principle is the honest dividing line. One developer coding on one machine? Use your harness's built-in memory and you are well-served. Just you, beyond coding? llm-wiki or Obsidian is the right answer. But a fleet of agents sharing fast-changing operational memory, a team of developers with coding agents in a controlled environment, or agents in a healthcare process -- and any scenario where the forensic questions will actually be asked -- need identity, scopes, curation, contradiction handling, and audit. That's what MemoryHub is.

The full argument, including when *not* to use MemoryHub: [What Agent Memory Really Is](docs/guides/what-is-agent-memory.md).

## Get started

### Personal edition

Zero infrastructure. Memories are stored locally in SQLite at `~/.local/share/memoryhub/`.

```bash
pip install "memoryhub[local]"
claude mcp add memoryhub -- memoryhub mcp
```

Start a new Claude Code session and your agent has persistent memory. See [`memoryhub-local/README.md`](memoryhub-local/README.md) for configuration, dreaming (offline fact extraction), and how it works under the hood.

### Cluster edition

Full governed stack on OpenShift AI: PostgreSQL + pgvector, OAuth 2.1, embedding + reranker models, dashboard UI.

```bash
git clone https://github.com/redhat-ai-americas/memory-hub.git
cd memory-hub
oc login <cluster-api-url>      # cluster-admin required
make install                    # full stack deploy (~10 min)
```

The deploy script auto-creates a Python virtualenv, generates API keys, writes the first key to `~/.config/memoryhub/api-key`, and runs a smoke test. See the [cluster install guide](docs/guides/cluster-install.md) for prerequisites, deploy options, troubleshooting, and post-install setup.

## Why MemoryHub

- **Governed memory operations.** Every write, read, update, and deletion is access-controlled by [six-tier scope isolation](docs/design/governance.md) enforced at the SQL level. Memories carry [version history with provenance branches](docs/design/memory-tree.md), contradiction detection, and a [three-layer curation rules engine](docs/design/curator-agent.md) with inline secrets/PII scanning. Enterprise-scope memories require human approval. This is the substrate that makes all other capabilities trustworthy.

- **Shared agent memory.** Agents don't just remember for themselves -- they build an organizational hive mind. [Project-scoped memories](docs/design/memory-tree.md) surface for every agent working in that context, with auto-enrollment on first write to open projects so agents can start contributing without manual membership setup. [Campaign scoping](planning/archive/campaign-domain-framework.md) enables bounded cross-project initiatives where knowledge discovered by one project's agent is available to all enrolled projects. Domain tags enable crosscutting retrieval. [Two-vector retrieval](docs/design/two-vector-retrieval.md) blends query relevance with session focus context via RRF and cross-encoder reranking, so search results match both what the agent asked and what it's currently working on. [Real-time push notifications](docs/agent-memory-ergonomics/design.md) keep agent swarms current. A promotion pipeline lifts patterns discovered by individual agents into organizational knowledge.

- **Inference cost optimization.** [Cache-optimized assembly](research/infra/vllm-kv-cache.md) returns memories in a deterministic, epoch-locked order designed for KV cache prefix hits across vLLM (2x throughput, 152x TTFT), Anthropic (90% cost reduction), OpenAI (50%), and Gemini (75-90%). The key insight: the first agent pays full inference cost; subsequent agents with overlapping memory contexts get the cached prefix nearly free. Token budget caps and weight-based stub/full injection keep context windows lean. [Governed context compaction](research/surveys/retrieval-compaction-persistence.md) is on the roadmap.

- **Compliance-oriented architecture.** Version history, provenance branches, structured audit events, and a durable [audit trail](docs/design/governance.md) position MemoryHub for EU AI Act transparency requirements (enforcement begins August 2026), GDPR data governance, HIPAA, and financial regulations. Compaction will use readable summaries -- not opaque tokens -- so the compliance team can inspect what was kept.

- **Framework-agnostic integration.** Works with any agent framework that speaks MCP. A [typed Python SDK](sdk/README.md), a CLI, a [project config wizard](docs/agent-memory-ergonomics/design.md) that generates agent rule files, and a designed integration path for [LlamaStack](planning/llamastack-integration/overview.md).

- **Kubernetes-native on OpenShift AI.** [PostgreSQL + pgvector](docs/design/storage-layer.md) handling relational, vector, and graph queries in one database, with MinIO for object storage. FIPS compliance by delegation. Air-gap deployable with on-cluster embedding models. Red Hat UBI images. An [llm-d integration path](research/infra/vllm-kv-cache.md) for automatic cache-aware routing at the infrastructure level.

Per-subsystem status and dependency graph: [`docs/SYSTEMS.md`](docs/SYSTEMS.md).

## What's in this repo

| Component | Path | What it is |
|---|---|---|
| **MCP server** | [`memory-hub-mcp/`](memory-hub-mcp/) | FastMCP 3 server exposing memory operations over streamable-HTTP. Four action-dispatch tools (compact profile, default) or 13 individual tools (full profile). The primary agent surface. |
| **Server-side library** | [`src/memoryhub_core/`](src/memoryhub_core/) | SQLAlchemy models, service layer, embedding integration, RBAC enforcement (`core/authz.py`). Distribution name `memoryhub-core`; import name `memoryhub_core`. The MCP server, BFF, alembic migrations, and the seed-OAuth-clients script all import from here. |
| **Python SDK** | [`sdk/`](sdk/) | `pip install memoryhub` -- typed async client wrapping the MCP tools. OAuth 2.1 token management is automatic. See [`sdk/README.md`](sdk/README.md). |
| **CLI** | [`memoryhub-cli/`](memoryhub-cli/) | `pip install memoryhub-cli` -- terminal client for search/read/write/delete plus `memoryhub config init` for generating project-level `.memoryhub.yaml` and `.claude/rules/memoryhub-loading.md` rule files. |
| **Personal edition** | [`memoryhub-local/`](memoryhub-local/) | SQLite backend + local runtime for zero-infrastructure agent memory. `pip install "memoryhub[local]"`. |
| **Curation agents** | [`memoryhub-agents/`](memoryhub-agents/) | Background agents (Fact Checker, Trace Reviewer) running on Valkey job queues with leader election. |
| **Dashboard UI** | [`memoryhub-ui/`](memoryhub-ui/) | React + PatternFly 6 frontend behind a FastAPI BFF, deployed as a single container. Six panels: Memory Graph, Status Overview, Users & Agents, Client Management, Curation Rules, Contradiction Log. OAuth-proxy sidecar in front of OpenShift login. |
| **Auth service** | [`memoryhub-auth/`](memoryhub-auth/) | Standalone OAuth 2.1 authorization server. FastAPI with `client_credentials` and `refresh_token` grants, RSA-2048 JWT signing, JWKS endpoint, admin client management API. |
| **Database migrations** | [`alembic/`](alembic/) | Schema migrations for the server-side library. PostgreSQL with the pgvector extension. |
| **Design docs** | [`docs/`](docs/) | Subsystem designs, the agent-memory-ergonomics design cluster, package layout, auth and identity model. Start at [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md). |
| **Planning** | [`planning/`](planning/) | In-flight designs for unimplemented features (operator, observability, org-ingestion) and the LlamaStack integration plan. |
| **Research** | [`research/`](research/) | Investigations and explorations -- FIPS storage analysis, agent-memory-ergonomics research notes. |
| **Demos** | [`demos/`](demos/) | Conference demo scripts (HIMSS, RSA, IACP, IAEM, World AgriTech) and the RHOAI dashboard demo material. |
| **Retrospectives** | [`retrospectives/`](retrospectives/) | Per-session retros documenting decisions, gaps, and patterns. Read these for the "why" behind major design choices. |

## Three ways to use it

### 1. From an agent via MCP (Claude Code, or anything that speaks MCP)

The deployed server exposes a streamable-HTTP MCP endpoint. Add it to your agent's MCP configuration (note: the server name `memoryhub` is a required positional argument):

```bash
claude mcp add memoryhub \
  --transport http \
  -s user \
  https://memory-hub-mcp-memory-hub-mcp.apps.<your-cluster>.com/mcp/
```

Then run `memoryhub config init` to generate a `.memoryhub.yaml` and agent rule file that tells the agent when and how to call the tools. For zero-overhead startup, add a [SessionStart hook](docs/guides/hooks-integration.md) that pre-loads memories before the first prompt.

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

`memoryhub config init` is an interactive wizard that asks about session shape, loading pattern, focus source, and retrieval defaults, then writes both files -- commit them so every contributor's agent inherits the same loading pattern. After hand-editing the YAML, `memoryhub config regenerate` re-renders the rule file. The YAML schema (`memory_loading` + `retrieval_defaults`), field reference, rule-file templates, and the `/memoryhub-init` slash command for running the wizard from inside Claude Code are all documented in [`docs/agent-memory-ergonomics/design.md`](docs/agent-memory-ergonomics/design.md) and the [CLI README](memoryhub-cli/README.md).

## Architecture

Every memory operation flows through the MCP server; authorization, curation, and governance are enforced in the service layer -- no surface talks to PostgreSQL directly. The full design, data flows, and deployment topology live in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md); the per-subsystem map is [`docs/SYSTEMS.md`](docs/SYSTEMS.md).

## Documentation

Full documentation lives in four top-level directories. Start with [`docs/README.md`](docs/README.md) for a guided tour, or jump straight to whichever area matches your need:

- **[`docs/`](docs/README.md)** -- Shipped architecture and reference material. Subsystem designs (memory tree, storage layer, governance, curator, MCP server), agent memory ergonomics, auth, identity model, admin operations.
- **[`planning/`](planning/)** -- In-flight designs, open questions, and integration roadmaps (Kubernetes operator, observability, LlamaStack integration).
- **[`research/`](research/)** -- Investigations and benchmarks that informed shipped decisions (FIPS storage evaluation, two-vector retrieval ranking, pivot detection, FastMCP push notifications, Claude Code JWT limitations).
- **[`demos/`](demos/)** -- Conference demo scripts and scenario material (HIMSS, RSA, IACP, IAEM, World AgriTech, and the RHOAI dashboard tile demo).

Package-specific docs live in each package's own README:

- **[Python SDK](sdk/README.md)** -- quickstart, API reference, project config, authentication
- **[CLI](memoryhub-cli/README.md)** -- commands, project config, credential setup
- **[MCP server](memory-hub-mcp/README.md)** -- tool list, deployment, testing
- **[Auth service](memoryhub-auth/)** -- standalone OAuth 2.1 authorization server
- **[Hooks integration](docs/guides/hooks-integration.md)** -- zero-overhead memory injection at Claude Code session start
- **[Personal edition](memoryhub-local/README.md)** -- local SQLite backend, dreaming, configuration
- **[Benchmarks](benchmarks/RESULTS.md)** -- AMB PersonaMem and LongMemEval results, methodology, competitive context

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
├── memoryhub-local/            # Personal edition: SQLite backend + local runtime
├── memoryhub-agents/           # Curation agents (Fact Checker, Trace Reviewer)
├── alembic/                    # Database migrations
├── tests/                      # Server-side library tests
├── docs/                       # Shipped architecture and subsystem designs
├── planning/                   # In-flight designs for unimplemented features
├── research/                   # Investigations and explorations
├── demos/                      # Conference demo scripts and dashboard demo material
├── retrospectives/             # Session retros -- read for design context
├── deploy/                     # K8s manifests (PostgreSQL, MinIO, Valkey, embedding, reranker)
└── benchmarks/                 # Empirical benchmark results (e.g. two-vector-retrieval/)
```

See [`planning/archive/package-layout.md`](planning/archive/package-layout.md) for the package naming rationale.

## Development

Requires Python 3.11+. We recommend [uv](https://docs.astral.sh/uv/) for environment management -- it handles Python installation, venv creation, and dependency resolution in one tool. Each subproject maintains its own venv to avoid dependency conflicts.

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for the full development setup and PR flow, or [`docs/guides/local-development.md`](docs/guides/local-development.md) for per-subproject instructions.

## Contributing

Issues and PRs are welcome. Start with [`CONTRIBUTING.md`](CONTRIBUTING.md) for the local dev setup, coding conventions, and PR flow. Use the `/issue-tracker` slash command (or follow [`CLAUDE.md`](CLAUDE.md)) when filing -- every issue references a design document and follows the Backlog -> In Progress -> Done flow.

Most contributions do not need access to the demo OpenShift cluster -- local SQLite or a podman PostgreSQL container is enough. If you do need cluster access, see [`docs/admin/contributor-cluster-access.md`](docs/admin/contributor-cluster-access.md) for the access policy, GitHub IdP setup, and the no-deploy rule for new contributors.

## License

Apache 2.0 -- see [`LICENSE`](LICENSE).

## Links

- [What agent memory really is](docs/guides/what-is-agent-memory.md) · [Agent integration guide](docs/guides/agent-integration-guide.md) · [Architecture](docs/ARCHITECTURE.md) · [Subsystems](docs/SYSTEMS.md) · [Benchmarks](benchmarks/RESULTS.md)
- [Python SDK on PyPI](https://pypi.org/project/memoryhub/) · [Personal edition](memoryhub-local/README.md) · [GitHub issues](https://github.com/redhat-ai-americas/memory-hub/issues)
