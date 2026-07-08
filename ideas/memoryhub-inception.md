# MemoryHub — Inception

> **Historical inception document (2026-04-03).** Consolidated 2026-07-08 from the original ideas/memoryhub/ folder (12 files; full text in git history). Terminology here predates the shipped system — e.g. the original tiers 'recent, personal, soul' became the scope model (user/project/campaign/role/organizational/enterprise), and 'personal' became 'user'. Current architecture: docs/ARCHITECTURE.md.

## Vision & problem

MemoryHub makes agent memory a first-class, managed infrastructure component — like a database or message queue, but for what agents know and remember. A Kubernetes-native, multi-layered memory system for AI agents running on OpenShift AI: structured memory tiers (recent, organizational, personal, role, soul, rationale), enterprise-grade governance, forensics, and observability, all managed via a Kubernetes Operator with CRDs.

The problem: agents today are amnesiacs. Every new conversation, deployment, or onboarding starts cold.

- **Agents forget.** Even with memory features in tools like Claude Code, memories are local, siloed, and non-transferable. "Never commit without scanning for secrets" lives and dies with a single agent instance.
- **No organizational learning.** When 50 engineers all teach their agents the same lesson about deployments, nobody benefits from the collective learning. Each agent is an island.
- **Enterprise blind spots.** There's no way to audit what an agent "knew" when it took an action. Was a data leak the user's intent or the agent's mistake? Did a memory leak an API key to a hosted API? For regulated industries this is a showstopper — EU AI Act enforcement starts August 2026.
- **Memory doesn't scale.** Inject everything (token waste) or inject nothing (amnesia). "Just stuff it in the system prompt" has a ceiling, and we're hitting it.
- **No transfer learning.** New agents and new employees bootstrap from nothing instead of from organizational knowledge and role-based defaults.

The end state: an organization deploys MemoryHub to their OpenShift AI cluster. Every agent reads from and writes to a shared, governed memory system. Memories have layers, scope, metadata, versions, and rationale. Organizational learning happens automatically — patterns in individual memories get promoted to organizational knowledge. An admin opens Grafana and sees memory utilization, staleness, policy violations, and relationship graphs. A security investigator can reconstruct exactly what an agent believed at any point in time.

What becomes possible: an agent surfaces today's org-wide announcement because it matched your context. A new hire's agent behaves like a veteran's on day one. An agent notices you're contradicting a stored preference and asks, with the original rationale in hand: "You told me you prefer Podman a few months ago because of your Red Hat work, but you just used Docker for this whole project. Want to update this?" The memory layer becomes a firewall between what agents know and what gets sent to hosted APIs.

### Differentiation vs. existing solutions

Mem0, Zep, Letta, Cognee and others exist, but MemoryHub differs in ways that matter for enterprise adoption:

- Kubernetes-native: a proper Operator with CRDs; tiers, policies, and storage backends declared as K8s resources.
- Multi-agent memory governance: promotion from individual to organizational scope, pruning of superseded memories, managed by scheduled agents inside MemoryHub. Genuine organizational learning, not per-agent recall.
- Memory versioning with temporal awareness (the isCurrent model): "What did the agent believe on March 15th?" is answerable.
- A rationale layer: memories carry their "why" as a linked record. Nobody else does this.
- Enterprise forensics: reconstruct beliefs at any point in time, trace provenance, distinguish intent from mistake.
- FIPS compliance, secrets detection, policy enforcement — requirements commercial solutions wave away or paywall.
- MCP server interface for universal agent compatibility; Grafana-native observability.

The development path: build it as a standalone component deployable to existing RHOAI clusters, prove it works, then pitch the RHOAI engineering team (whom the user meets with regularly).

## Scope & requirements

### In scope (v1)

- **Kubernetes Operator with CRDs** for memory tier management — the foundation everything builds on.
- **Tree-structured memory architecture.** Memories form a tree of nodes with required and optional branches, not flat tiers ("the tree is the architecture," replacing the layer-cake model). Each node carries a weight determining whether the system injects full content or a stub, letting the agent decide whether to crawl deeper. Storage backend is selected per node by retrieval characteristics.
- **Metadata, versioning, rationale, isCurrent.** Memories carry scope (user, project, role, organization), shareability, timestamps, versions, and an isCurrent flag — metadata drives retrieval, access control, and governance. Rationale is an optional branch on any node, not a separate tier: "Prefers Podman" is the node; "Works for Red Hat and that's their container runtime" is its rationale branch, retrieved only when deeper context is needed. Full version history is required — it's the foundation of forensics and staleness detection.
- **Agentic memory promotion and pruning.** Scheduled agents detect patterns across user-level memories ("30 users all taught their agents the same thing"), propose organizational memories, and consolidate or retire superseded user-level ones. Staleness detection: identify when agent behavior contradicts stored memories and prompt for revision.
- **Agentic organizational memory ingestion** from org posts, emails, and documents, so organizational memory stays current without manual curation.
- **MCP server interface** — the primary agent interaction surface (read, write, search, get rationale, list versions), built via the fips-agents CLI workflow.
- **Grafana dashboards** for utilization, staleness, policy violations, relationship graphs — using the monitoring stack already in the cluster.
- **Forensics and audit trail.** Immutable logging of all memory operations (create, read, update, promote, prune); reconstruct agent memory state at any historical point. Non-negotiable: if someone can alter a memory undetected, they can change system behavior and make a user appear responsible for something they didn't authorize.
- **Secrets and PII scanning** of stored memories before sensitive content gets injected into prompts sent to external APIs; configurable policy enforcement on what can be stored.
- **FIPS compliance throughout.** Access control is metadata-driven (scope, role, policy), not manual ACLs.
- **Scale:** hundreds of agents per cluster, thousands per organization; horizontal scaling, no hard upper limit.

### Governance tiers (decided)

- User-level memories: fully automatic creation and update, no human-in-the-loop. Only the owning user can hand-edit their own memories — nobody else, to prevent attribution manipulation.
- Enterprise/policy-level memories: always HITL for creation and modification.
- Middle tiers (project, role, organization): automatic by default, auditable and editable by authorized humans.
- Consider a single designated "memory curator" agent responsible for all above-user-level writes, checking duplicates and semantic conflicts before committing.

### Stretch goals

- **Proactive memory surfacing** — a sidecar agent that decides what to inject each turn rather than the agent requesting memories. Architecturally complex; nail the basics first.
- **Real-time organizational event integration** rather than scheduled scans.

### Out of scope

- Not a new agent framework — MemoryHub is infrastructure; agents are consumers (LangChain, CrewAI, bare API calls — anything that speaks MCP).
- Not replacing tools' local memory (Claude Code's `~/.claude/memory/`, Cursor's files) — those could feed in via import tools.
- No model training or fine-tuning — this is inference-time memory.
- No custom UI — Grafana is the visualization layer; a fancier UI later is a separate project.

## Assumptions & constraints

### Assumptions (unvalidated at inception)

- OpenShift AI continues toward multi-agent workloads (signals: Kagenti, Llama Stack integration, the Agent Sandbox CRD in SIG Apps).
- The RHOAI engineering team will be receptive to a well-proven memory component — not guaranteed; be prepared for "not right now." Mitigation: build something that works so well the conversation is easy.
- Grafana's node graph panel scales to thousands of memory nodes (untested).
- MCP continues to gain adoption as the standard agent tool protocol.
- Enterprises will increasingly need agent memory governance as deployments scale (EU AI Act may accelerate this) — a bet on an emerging market.
- Memory promotion can be done effectively by an LLM agent analyzing patterns — conceptually sound, unproven at scale, and a bad promoted memory that propagates to every agent is worse than none.
- (Original assumption that Milvus and Neo4j are viable on OpenShift was overturned by the FIPS research — see constraints.)

### Constraints

- Deployable to existing RHOAI clusters without RHOAI source modifications — a custom build kills the adoption path.
- FIPS compliance required; every component must be compliant or have a path to it.
- Red Hat UBI base images only (UBI9). No Alpine, no Debian, no random Docker Hub images.
- **Storage stack (finalized after FIPS research):** PostgreSQL (OOTB — the operator that ships with OpenShift, not Crunchy Data) + pgvector for vector search; PostgreSQL for graph queries initially (Apache AGE extension or adjacency lists), with an evolution path to Neo4j/Memgraph or an in-process graph library (petgraph, with PostgreSQL as durable store); MinIO for S3-compatible object storage. Two constraints drove this: no Crunchy Data (can't build on an external vendor product) and no OpenShift Data Foundation (not part of Red Hat AI Enterprise). FIPS story: PostgreSQL delegates crypto to OS-level OpenSSL (FIPS-validated on RHEL); pgvector uses mathematical distance computations, not cryptographic hashes; MinIO AIStor has FIPS 140-3 mode via Go 1.24's validated crypto module. Milvus was disqualified (no encryption at rest, bcrypt auth, no validation); Neo4j Enterprise is technically FIPS-compatible but has no certified OpenShift operator. No lite mode — full storage stack only.
- Grafana + Prometheus for observability — use what's already in the cluster.
- Must be viable as a future upstream contribution to OpenShift AI: clean code, good docs, no shortcuts that would embarrass in a code review with the engineering team.
- Proof over proposals: a working demo on a real cluster beats any architecture document. Building beats theorizing.
- MCP development uses the fips-agents CLI workflow (`/plan-tools`, `/create-tools`, `/exercise-tools`, `/deploy-mcp`).

## Risks

**Architecture**

- Apache AGE / adjacency lists in PostgreSQL may not scale for deep multi-hop graph traversals. AGE is an Apache incubator project; the evolution path (Neo4j, Memgraph, petgraph) is viable but adds migration complexity.
- OOTB PostgreSQL operator capabilities need hands-on validation — does it support installing pgvector and AGE? Crunchy's operator explicitly includes pgvector; OOTB's extension support is less documented.
- Memory promotion by an LLM agent is unproven at scale. What happens when the promotion agent generalizes badly ("most engineers prefer tabs over spaces")? Feedback loop, detection, and HITL boundaries undefined.
- The tree model needs careful conflict resolution. Decided two-track approach: write conflicts prevented by transaction processing and a pipeline; semantic conflicts detected by a periodic agent that auto-resolves where possible and queues the rest for human review. Strategy defined; implementation details open.

**Enterprise**

- FIPS compliance for the storage stack: resolved in favor of PostgreSQL + pgvector + MinIO (see constraints).
- Forensics at scale could be expensive — audit logs of every read grow fast; retention policies and tiered audit storage needed.
- Secrets detection has inherent tradeoffs: false positives create alert fatigue, false negatives create risk. Needs configurable sensitivity and whitelisting.

**Adoption**

- RHOAI engineering may prefer this stays external. Wouldn't kill the project — build for standalone viability first.
- The memory curator agent is a single point of failure for above-user-level writes: needs robust error handling, dead-letter queuing, and dedicated monitoring.
- If Mem0 or Zep add K8s operators and governance, differentiation narrows — though enterprise/FIPS requirements create natural moat.

**Open questions at inception:** multi-cluster/multi-region memory (federation vs. central service); migration/import from existing local memory stores; the concrete schema and criteria for the semantic conflict detection agent.

## Stakeholders

- **AI agents on OpenShift AI** — the most direct users, via MCP on every turn. If the interface is clunky or slow, agents will work around it.
- **Developers and data scientists** — their agents remember preferences, project context, and organizational standards; the difference between a tool and a colleague.
- **New employees and new agent deployments** — disproportionate beneficiaries of organizational memory bootstrapping.
- **Platform administrators** — manage tiers, policies, and resources via CRDs; care about operational simplicity.
- **Security and compliance teams** — forensics, audit trails, secrets scanning; often the gatekeepers for enterprise adoption ("if they can't audit it, it doesn't ship").
- **Organization leadership** — collective learning and policy enforcement at the aggregate level.
- **RHOAI engineering team** — the most important external stakeholder and gatekeeper for upstream contribution. Build everything assuming they'll eventually review the code and architecture.

## Early research notes (April 2026)

Landscape survey of existing solutions:

- **Mem0** (51.8k stars, Apache 2.0): most popular OSS memory layer; hybrid vector+graph+KV, MCP support. But graph memory, analytics, and governance are cloud-only; no K8s operator, no multi-agent coordination, no temporal awareness.
- **Letta/MemGPT** (21.9k stars): LLM self-managed memory blocks (NeurIPS 2023). Clever, but Docker-centric, no compliance framework, no shared memory, and memory ops consume tokens.
- **Zep/Graphiti**: strongest temporal model in the market (bi-temporal validity intervals, hybrid retrieval without query-time LLM calls). Requires Neo4j; full platform is commercial SaaS; no K8s story.
- **Cognee** (14.9k stars): ECL pipeline, 14 retrieval modes, self-improving memory; well-funded but young, no compliance or K8s narrative.
- **Hindsight** (7.1k stars): retain/recall/reflect learning, first to cross 90% on LongMemEval; unclear OSS/commercial boundary.
- **Redis Agent Memory Server** (218 stars): clean two-tier design, REST+MCP; very early, no graph memory or governance.

Academic work: the **"Governed Memory" paper** (arXiv:2603.17787, in production at Personize.ai, 99.6% fact recall with zero cross-entity leakage) is the closest to what we're building and needs a detailed read. Also relevant: "Multi-Agent Memory from Computer Architecture Perspective" (arXiv:2603.10062) and MAGMA (arXiv:2601.03236, multi-graph architecture). ICLR 2026's dedicated MemAgents workshop signals the field has reached critical mass.

Kubernetes landscape: Agent Sandbox CRD (SIG Apps) handles execution, not memory. Kagenti (Red Hat Emerging Technologies) handles agent deployment with no memory component — a natural complement. OpenShift AI has agent infrastructure via Llama Stack but no dedicated memory component.

**The whitespace:** nobody has built a Kubernetes-native agent memory operator; nobody ships multi-agent memory governance in open source; nobody provides memory observability through standard K8s monitoring; nobody offers FIPS-compliant memory with forensics. MemoryHub sits right in this gap.

## Key decisions from the first ideation sessions (2026-04-03)

Two sessions on April 3 (raw transcript summarized; full text in git history):

- The spark: a video on multi-layer agent memory led to the realization that tiers are about retrieval strategy *and* physical location — a tier defines how aggressively a memory is surfaced, how fully it's injected (stub vs. full), and where it lives.
- **The memory model is a tree, not a layer cake** (second session): nodes with required and optional branches, weights driving stub-vs-full injection, agents crawling deeper on demand. Rationale became an optional branch on any node rather than a separate tier.
- Governance model decided: automated with guardrails (user-level automatic, enterprise HITL, middle tiers automatic-but-audited), immutable logging on all operations, and the single memory-curator-agent idea for above-user-level writes.
- Conflict resolution: transaction pipeline for write conflicts; periodic agent for semantic conflicts (merge duplicates, escalate genuine disagreements). Inter-user conflicts at user level are fine (Johnny prefers X, Sally prefers Y); above user level, conflicts must be curated.
- Storage: the first session landed on Milvus + Neo4j + MinIO; the second session kicked off FIPS research that overturned it, finalizing PostgreSQL (OOTB) + pgvector + AGE/adjacency-lists + MinIO, with petgraph noted as an in-process graph evolution path. "No lite mode" was decided — full stack only.
- Path to RHOAI: standalone first, prove it with real agents, then pitch — aiming for "you should take this" rather than "would you consider this."

## Next steps as of inception (historical)

These were the open items in April 2026, preserved as a snapshot; most have since been resolved.

- **Architecture to resolve:** tree schema per storage backend; CRD design (MemoryTier, MemoryPolicy, MemoryStore — the first thing RHOAI engineering would evaluate); weight calibration (set at write time? decay? context-dependent?); memory curator agent design (event-driven vs. scheduled, merge-vs-escalate criteria, unavailability handling); whether agents need an explicit top-level directive explaining the tree/stub model.
- **Validation needed:** OOTB PostgreSQL extension support for pgvector and AGE (hands-on cluster check); petgraph as an in-memory graph layer over PostgreSQL; Grafana node graph panel at realistic scale.
- **Design work:** promotion governance implementation (thresholds, feedback loop for bad promotions); MCP tool surface (`read_memory`, `write_memory`, `search_memory`, `get_rationale`, `list_versions` — detailed planning deferred to `/plan-tools`); multi-cluster story (don't solve for v1, don't preclude); import/migration from local memory stores.
- **Research:** detailed read of the Governed Memory paper (arXiv:2603.17787).
- **When ready:** `/imagine` to keep exploring, `/pitch` for the RHOAI team, `/brief` for stakeholders, `/propose` for technical architecture.

## What actually happened

The project shipped. As of July 2026, docs/SYSTEMS.md lists eighteen subsystems, most Implemented: the memory-tree model (tree, weights, scopes), the PostgreSQL + pgvector + MinIO storage layer, an inline curator pipeline plus a curation-agents framework, governance with OAuth 2.1/RBAC/audit logging, conversation threads, an MCP server, a Python SDK, a CLI, and a PatternFly dashboard (the "no custom UI" decision didn't survive). The operator and Grafana observability — the original headline deliverables — remain skeleton/TBD, and the tier vocabulary here (recent/personal/soul) gave way to the shipped scope model.
