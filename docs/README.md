# MemoryHub Documentation

MemoryHub is a Kubernetes-native agent memory component for OpenShift AI. See the [root README](../README.md) for the project overview.

This directory holds shipped architecture and user-facing reference material, organized as: `design/` (subsystem designs — the source of truth for shipped architecture), `guides/` (integrator and user guides), plus topic folders for auth, admin, identity, UI, and runbooks. In-flight designs live in [`../planning/`](../planning/), research in [`../research/`](../research/).

## Start here

- [`ARCHITECTURE.md`](ARCHITECTURE.md) — System architecture, consumer surfaces, deployment topology, and the "why" behind the major design choices.
- [`SYSTEMS.md`](SYSTEMS.md) — Per-subsystem inventory with status (shipped, in-flight, roadmap) and downstream consumers.

## Subsystem designs ([`design/`](design/))

- [`memory-tree.md`](design/memory-tree.md) — Tree/branch model, versioning, weights, rationale and provenance branches.
- [`storage-layer.md`](design/storage-layer.md) — PostgreSQL + pgvector schema, MinIO, migration conventions, storage FAQ/rationale.
- [`governance.md`](design/governance.md) — Scopes, visibility, ownership, tenant isolation, RBAC.
- [`mcp-server.md`](design/mcp-server.md) — FastMCP 3 server, tool profiles, transport, session handling.
- [`curator-agent.md`](design/curator-agent.md) — Inline curation pipeline and rules engine.
- [`two-vector-retrieval.md`](design/two-vector-retrieval.md) — Query + focus retrieval via RRF, cross-encoder rerank, pivot detection, temporal awareness (#282/#292).
- [`graph-enhanced-memory.md`](design/graph-enhanced-memory.md) — Entity extraction (POLE+O), relationships, graph queries.
- [`conversation-persistence.md`](design/conversation-persistence.md) — Governed threads, extraction pipeline, retention (#168).
- [`context-compaction.md`](design/context-compaction.md) — Governed thread compaction (#169).
- [`knowledge-compilation.md`](design/knowledge-compilation.md) — Compiled-article knowledge pipeline (#171).
- [`context-assembly-at-inference.md`](design/context-assembly-at-inference.md) — Assembling memory into prompts at inference time.
- [`projects-lifecycle.md`](design/projects-lifecycle.md) — Projects feature: lifecycle, enrollment, membership. (Repo governance is [MAINTAINERS.md](../MAINTAINERS.md).)

## Guides ([`guides/`](guides/))

- [`what-is-agent-memory.md`](guides/what-is-agent-memory.md) — What agent memory really is: context assembly, the harness, local vs. platform locality, and when you don't need MemoryHub. Start here if you're new to agentic memory.
- [`agent-integration-guide.md`](guides/agent-integration-guide.md) — How agents use MemoryHub (loading patterns, session lifecycle) plus the full integration reference. Start here to wire up an agent.
- [`hooks-integration.md`](guides/hooks-integration.md) — SessionStart/hook-based memory injection for agent harnesses.
- [`local-development.md`](guides/local-development.md) — Running MemoryHub locally.
- [`ogx-integration.md`](guides/ogx-integration.md) — Giving an OGX (LlamaStack) agent memory via the MCP connector.

## Topic folders

- [`auth/`](auth/README.md) — OAuth 2.1 auth service, LibreChat integration, OpenShift broker.
- [`admin/`](admin/README.md) — Agent/user management, content moderation, filter rules, contributor cluster access, build/deploy hardening.
- [`identity-model/`](identity-model/README.md) — Owner/actor/driver triple, authorization, data model.
- [`agent-memory-ergonomics/`](agent-memory-ergonomics/design.md) — The ergonomics design cluster (search shape, focus vector, loading patterns); research half in [`../research/agent-memory-ergonomics/`](../research/agent-memory-ergonomics/).
- [`ui/`](ui/design.md) — Dashboard design.
- [`runbooks/`](runbooks/) — Operational runbooks (e.g. adding an MCP API user).
- `public/` — GitHub Pages artifact (`discovery.json` endpoint discovery); not documentation.

## Related directories

- [`../planning/`](../planning/) — In-flight designs (see its README for the active/archive split).
- [`../research/`](../research/) — Consolidated research with status index.
- [`../demos/`](../demos/) — Demo scripts and scenario material.
- [`../retrospectives/`](../retrospectives/) — Session retros; the project's institutional memory.
- Historical: [`../ideas/memoryhub-inception.md`](../ideas/memoryhub-inception.md) (origin document), [`../planning/archive/package-layout.md`](../planning/archive/package-layout.md) (#55 rename record).
