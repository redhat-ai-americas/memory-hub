# High-Level Requirements

These are declarative requirements, not implementation specs. The "how" comes later.

## Memory Architecture

Memories form a tree structure with required and optional branches, not flat tiers. A memory node carries a weight that determines whether the system injects its full content or just a stub, letting the agent decide whether to crawl deeper. This replaces the "layer cake" tier model — the tree is the architecture.

Each memory node can have an optional rationale branch. The "why" behind a preference or fact lives as a child node that's retrieved when the agent or an investigator needs deeper context. "Prefers Podman" is the node. "Works for Red Hat and that's their container runtime" is its rationale branch. Rationale is not a separate tier — it's an optional branch on any memory node. The rationale doesn't get injected by default; the node stub signals that more context is available if needed.

The system must support multiple storage backends with different retrieval strategies and injection behaviors. Not everything belongs in a vector store, and not everything belongs in a markdown file. The storage backend is determined by retrieval characteristics — vector search, graph traversal, and file-based access serve fundamentally different access patterns. The decided stack: PostgreSQL (OOTB) + pgvector for vector search, PostgreSQL for graph queries (Apache AGE or adjacency lists initially, with an evolution path to a dedicated graph database or in-process graph library if complexity demands it), and MinIO for S3-compatible object storage.

Memories must carry metadata: scope (user, project, role, organization), shareability, timestamps, versioning, and an isCurrent flag. This metadata isn't decoration — it drives retrieval, access control, and governance decisions.

Memory versioning is required. The full history of how a memory changed over time must be preserved. This isn't just nice-to-have — it's the foundation of forensics and staleness detection.

Memory promotion must be supported: detecting patterns in user-level memories and surfacing generalized organizational memories. If 30 users all teach their agents the same thing, the system should notice and propose an organizational memory.

Memory pruning must be supported: revising or retiring user-level memories that are superseded by higher-level ones. Once "scan for secrets" becomes organizational policy, individual memories saying the same thing can be consolidated.

Memory staleness detection: the system should identify when agent behavior contradicts stored memories and prompt for revision.

## Enterprise & Governance

FIPS compliance is required — this is a Red Hat enterprise environment.

Memory access control must be metadata-driven. Which agents and users can read or write which memories is determined by scope, role, and policy — not by manual ACLs on individual records.

Governance tiers for memory writes are fixed:
- User-level memories: fully automatic creation and update, no human-in-the-loop required. Only the owning user can hand-edit their own memories — no other human or agent can modify them, to prevent attribution manipulation.
- Enterprise/policy-level memories: always require human-in-the-loop for creation and modification.
- Middle tiers (project, role, organization): automatic by default, but auditable and editable by authorized humans.

Consider a single designated "memory curator" agent responsible for all above-user-level writes. This agent checks for duplicates and semantic conflicts before committing any new memory at those levels.

An immutable audit trail is required for all memory operations: create, read, update, promote, prune. This is non-negotiable for enterprise forensics — if someone can alter a memory undetected, they can change system behavior and make a user appear responsible for something they didn't authorize.

Memory forensics must be possible: reconstructing agent memory state at any historical point in time. "What did agent X know on March 15th?" needs to be answerable.

Secrets and PII detection must run automatically on stored memories. An API key that accidentally ends up in memory must be flagged before it gets injected into a prompt sent to a hosted API.

Policy enforcement must be configurable: organizational policies about what can and cannot be stored in memory.

## Integration & Interface

The system must expose capabilities as an MCP server, using the fips-agents CLI and existing MCP workflow. MCP is the lingua franca for agent tools — any agent that speaks MCP can use MemoryHub.

It must deploy to existing RHOAI clusters as a standalone component. No forking RHOAI, no requiring source modifications.

Grafana integration for dashboards and observability. Prometheus (or compatible) for metrics. These are already present in OpenShift clusters — we use what's there.

Kubernetes-native: Operator with CRDs. Memory tiers, policies, and storage backends are declared as Kubernetes resources.

## Scale

Must support hundreds of agents per cluster, thousands per organization. There's no hard upper limit on agent or memory count — the architecture should scale horizontally.
