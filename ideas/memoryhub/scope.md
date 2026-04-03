# Scope

## In scope

The core deliverable is a Kubernetes Operator with CRDs for memory tier management. This is the foundation everything else builds on — memory tiers, policies, and storage backends declared as Kubernetes resources, reconciled by an operator.

Tree-structured memory architecture spanning recent/markdown storage, vector store, and graph store. Memories form a tree of nodes with required and optional branches, not flat tiers. Each node carries a weight that determines whether the system injects full content or a stub. Storage backend is selected per node based on retrieval characteristics. We are starting with the full storage stack (Milvus, Neo4j, MinIO) — there is no lite mode.

Memory metadata, versioning, rationale as an optional branch on any memory node, and the isCurrent temporal model. These are what make MemoryHub more than "just another vector store with an API." Versioning enables forensics. Rationale branches enable deeper context without bloating every injection. isCurrent enables temporal awareness.

Agentic memory promotion and pruning — scheduled agents within MemoryHub that analyze patterns across individual memories, propose organizational memories, and consolidate or retire superseded user-level memories.

Agentic organizational memory ingestion. Agents that scan org posts, emails, documents, and other sources to ingest new knowledge into the organizational memory tier. This is how the organization's memory stays current without manual curation.

MCP server interface. The primary way agents interact with MemoryHub. Read, write, search, get rationale, list versions — all exposed as MCP tools.

Grafana dashboards for observability. Memory utilization, staleness, policy violations, relationship graphs. Using the dashboards and monitoring stack that's already in the cluster.

Memory forensics and audit trail. Immutable logging of all memory operations. Ability to reconstruct agent memory state at any point in time.

Secrets and PII scanning of memories. Automated detection before sensitive content gets injected into prompts sent to external APIs.

FIPS compliance throughout.

## Stretch goals

These are enabled by the architecture but not required for v1.

Proactive memory surfacing — a sidecar agent that runs in the agent's stack and decides what to inject on each turn, rather than the agent explicitly requesting memories. This would make memory feel seamless, but it's architecturally complex and we want to nail the basics first.

Real-time organizational event integration. New announcements, policy changes, or team updates get reflected in organizational memory immediately rather than on a scan schedule. The infrastructure supports it; the question is whether the complexity is worth it for v1.

## Out of scope

We're not building a new agent framework. MemoryHub is infrastructure; agents are consumers. If someone wants to use LangChain, CrewAI, or bare API calls — MemoryHub doesn't care as long as they speak MCP.

We're not replacing existing tools' local memory. Claude Code's `~/.claude/memory/`, Cursor's memory files — those could feed into MemoryHub via import tools, but we're not trying to replace them. They serve a purpose at the local level.

We're not doing model training or fine-tuning. This is inference-time memory, not training-time learning. The models don't change; what gets injected into their context does.

We're not building a custom UI. Grafana is the visualization layer. If someone wants a fancier UI later, that's a separate project.
