# OpenClaw Enterprise Gateway: Competitive Analysis

**Date:** 2026-09-02
**Source:** [Why OpenClaw](https://docs.openclaw.ai/start/why-openclaw), [Memory overview](https://docs.openclaw.ai/concepts/memory), [Memory architecture](https://docs.openclaw.ai/concepts/memory-architecture), [Dreaming](https://docs.openclaw.ai/concepts/dreaming)

## What OpenClaw is

OpenClaw is an extensible, open-source AI agent platform stewarded by the OpenClaw Foundation (501(c)(3) nonprofit), with backing from Atlassian, GitHub, Microsoft, NVIDIA, OpenAI, and Tencent. MIT-licensed, no separate enterprise edition.

The 2.0+ direction is an **AI gateway** that manages shared harness features across many agents running on different runtimes. Instead of each harness (Claude Code, Codex, Copilot, custom agents) reimplementing policy, channels, secrets, and memory independently, OpenClaw provides a shared control plane above all of them.

## Architecture: Gateway-Executor Model

OpenClaw separates a **trusted Gateway** (control plane) from **untrusted, movable execution**:

- **Gateway** owns: channel connections, configuration, credentials, versioned state, memory artifacts, and the control-plane API
- **Execution** runs in configured sandboxes (Docker/Podman/SSH/OpenShell), paired nodes, or cloud workers without standing Gateway credentials

Vendor harnesses are treated as first-class runtimes within the gateway:
- Codex plugin drives Codex's own app-server loop
- Copilot plugin runs GitHub Copilot SDK's session loop
- Anthropic plugin runs Claude Agent SDK
- MCP client supports streamable-HTTP, SSE, stdio transports with OAuth

The gateway keeps ownership of channels, sessions, policy, and state regardless of which runtime is executing.

## OpenClaw's Memory System

### Storage

Markdown artifacts plus SQLite index and metadata. File-based, designed for the gateway's own consumption.

### Provenance

Each indexed chunk carries an origin class: `owner`, `agent`, `untrusted`, `system`. Classification is stored outside the prose, so recalled text cannot promote its own trust level. Classification never defaults to `owner`.

**Turn taint:** After network-sourced tool results, every later assistant message in that turn is marked tainted and classifies `untrusted` for memory. This prevents prompt injection via web content from poisoning long-term memory.

### Dreaming (Background Consolidation)

Three-phase scheduled background sweep:
1. **Light** -- dedup recent signals, stage candidates
2. **REM** -- reflect and surface themes
3. **Deep** -- promote durable facts into MEMORY.md

Promotions must pass score, recall-frequency, and query-diversity gates. Untrusted and system-derived candidates never enter the consolidation prompt. Phase summaries are written to DREAMS.md for human review.

### Deletion

`openclaw memory forget` purges attributable entries, exact diary quotations, index rows, vectors, embedding caches, and rewrite backups. Durable forgotten-session records prevent reingestion. Explicitly does not cover direct file writes, untracked memories, original transcripts, other agents' stores, exports, or external copies. No time-based retention bound on promoted memories.

## What OpenClaw has that MemoryHub doesn't

| Capability | Notes |
|---|---|
| Full agent runtime | Gateway-executor model with configurable sandboxing |
| Policy-as-code enforcement | Structural tool policy with deterministic denial; exec approvals bound to command, working directory, environment hash |
| Multi-channel communications | Matrix, IRC, Nostr, Email (IMAP), A2A protocol (Linux Foundation) |
| Vendor harness integration | Native Codex, Copilot, Claude Agent SDK runtimes |
| Plugin ecosystem | ClawHub registry with security scanning, ~150 SDK entrypoints |
| Cloud workers | Throwaway execution environments with proxied inference, 10-minute TTL credentials |
| Built-in secrets management | SecretRefs with egress sentinels, vault integration (1Password/Vault/Bitwarden/sops) |
| Foundation governance | 501(c)(3), signed releases, public threat model mapped to MITRE ATLAS |
| Formal verification | TLA+ models on authorization/isolation paths |
| Multi-user sessions | Immutable creator, assignable owner, co-author credit with verified GitHub identity |
| Audit ledger | Metadata-only (never stores prompts/bodies), 30-day retention cutoff |

None of these are memory capabilities. They are agent platform capabilities.

## What MemoryHub has that OpenClaw doesn't

| Capability | OpenClaw | MemoryHub |
|---|---|---|
| **Storage** | Markdown files + SQLite index | PostgreSQL + pgvector (structured, queryable, scalable) |
| **Memory structure** | Flat notes with indexed chunks | Tree-structured nodes with typed branches (rationale, provenance) |
| **Versioning** | File-level (overwrite) | UUID-lineage versioning, old versions preserved, edges auto-repoint |
| **Scoping** | Per-agent, single trust domain | 6-tier hierarchy: user, project, campaign, role, organizational, enterprise |
| **Retrieval** | Notes-file search over SQLite index | Two-layer: pgvector cosine similarity + cross-encoder reranking with RRF |
| **Cache optimization** | None documented | Epoch-locked deterministic ordering for KV cache prefix hits (2x throughput on vLLM, 90% cost reduction on Anthropic) |
| **Graph** | No relationship model | Directed graph edges between memories, entity extraction (spaCy NER, POLE+O), near-duplicate detection |
| **Auth** | Gateway-level roles (one trust domain per gateway) | OAuth 2.1 authorization server with client_credentials, auth_code+PKCE, token_exchange; actor/driver identity |
| **Multi-agent** | Agents must run inside the gateway | Any agent via MCP (streamable-HTTP), SDK, or CLI |
| **PII protection** | Provenance-gated promotion | Inline PII blocking in curation pipeline |
| **Background curation** | Dreaming (3-phase consolidation) | Curation agents on Valkey queues (Fact Checker, Trace Reviewer) + dreaming-style extraction |
| **Benchmark** | No published memory benchmark | 83.7% AMB PersonaMem |
| **Consumer surfaces** | CLI + agent-internal | MCP server, Python SDK (PyPI), CLI, React+PatternFly dashboard, agent-harness hooks |

## The Framework Lock-In Problem

The question "Why not just use OpenClaw?" assumes an agent can use OpenClaw's memory without adopting the full platform. It can't:

- OpenClaw's memory is tightly coupled to its gateway. Agents must run inside OpenClaw to access the memory system.
- Tenancy is one gateway = one trust domain. Multiple gateways (via experimental `openclaw fleet`) have no shared memory.
- Vendor harnesses (Codex, Copilot, Claude SDK) run as runtimes *within* OpenClaw. They don't receive memory when running independently.

MemoryHub takes the opposite approach: a standalone service that any agent connects to via MCP or SDK, regardless of what runtime it uses.

## How MemoryHub Fits in the OpenClaw Gateway Architecture

OpenClaw's 2.0 direction as a shared gateway above heterogeneous harnesses creates a natural integration surface.

### 1. Memory backend, not competitor

OpenClaw's current memory is Markdown + SQLite. It could use a pluggable memory backend the same way it uses pluggable execution backends. MemoryHub slots in as that backend, providing structured storage, vector retrieval, scoping, and governance that the file-based system lacks, while OpenClaw provides gateway services (policy, channels, identity, execution isolation) that MemoryHub doesn't touch.

### 2. Provenance handshake

OpenClaw has a good provenance model (owner/agent/untrusted/system trust levels, taint propagation). MemoryHub has a good governance model (6-tier scopes, version history, curation agents, PII blocking). These compose naturally: OpenClaw's trust classification feeds into MemoryHub's write-time governance. A memory tagged `untrusted` by OpenClaw's taint propagation gets stored with that provenance in MemoryHub's tree, and MemoryHub's curation agents can apply additional rules before promotion.

### 3. Cross-gateway memory

OpenClaw's tenancy model (one gateway = one trust domain) means multiple gateways have no shared memory. MemoryHub provides that cross-gateway memory layer: organizational and enterprise-scoped memories accessible to agents regardless of which gateway they're behind.

### 4. Harness-agnostic coverage

Some agents won't run inside OpenClaw. A Claude Code session on a developer's laptop, a LlamaStack agent in a pipeline, a custom agent in a Jupyter notebook. MemoryHub serves those agents directly via MCP or SDK. OpenClaw-managed agents and standalone agents share the same memory service.

## Where OpenClaw's Memory Design is Genuinely Good

- **Provenance tracking** with trust levels and taint propagation is well-designed. Content from a web page with injected instructions is permanently tagged `untrusted` and can never auto-inject or gain instruction authority.
- **Dreaming consolidation** (light, REM, deep) is a thoughtful background curation system. Their insight that "what was written matters more than how it is indexed" aligns with our own curation philosophy.
- **Write-path-as-security-boundary**: enforce provenance at write time rather than trying to detect bad memories after the fact.

Good design principles, but the implementation (file-based, single-gateway-scoped) limits the reach for enterprise use.

## Positioning

OpenClaw is building a great gateway. Gateway-layer memory and purpose-built memory are not the same thing. The best architecture uses both: OpenClaw as the gateway providing execution, policy, and channels; MemoryHub as the memory service providing structured, governed, cross-agent memory via MCP. The two systems are complementary layers, and MemoryHub is more valuable *with* an OpenClaw gateway than without one, because OpenClaw solves the execution/policy/channel problems that MemoryHub deliberately does not address.
