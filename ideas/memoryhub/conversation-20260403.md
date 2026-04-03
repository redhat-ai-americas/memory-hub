# First Ideation Session — April 3, 2026

## How this started

The spark came from a video about building multiple memory layers for agents. After watching it, there were days of thinking about why you'd even need multiple layers — memories just get injected into the prompt, right? What does it matter where they come from?

The realization: the layers are about retrieval strategy AND physical location. Different tiers serve different purposes, live in different backends, and get surfaced with different aggressiveness and completeness. A recent project memory might always be injected as a full block. An organizational policy might be injected as a stub with a link to the rationale. A soul-level preference might only surface when it's relevant to the current task. The tier isn't just an organizational concept — it determines how the memory behaves.

## Key insights

**Memory tiers are about both retrieval and storage.** Organizational memories live in graph/vector stores for searchability across the whole organization. Recent project memories live in scoped markdown files where they're fast to read and easy to inspect. The tier defines three things: how aggressively a memory is surfaced, how fully it's injected (stub vs. full content), and where it physically lives. All three matter.

**Rationale as a memory layer.** This one feels genuinely novel. "Prefers Podman" is the memory. "Works for Red Hat and that's what they use" is the rationale. The rationale is a separate, linked record that gets retrieved when the agent needs deeper context — like when someone asks "why Podman?" or when an agent is deciding whether to override a preference. Nobody else in the landscape does this, and it solves a real problem: memories without context are brittle. An agent that knows your preference but not why will override it at the first sign of friction.

**Memory versioning with isCurrent.** Memories evolve. "Prefers Python" becomes "Prefers Rust now." Keeping the full version history lets us answer "what did the agent believe at time T?" — which is critical for forensics and compliance. The isCurrent flag means we only surface current memories by default but can traverse the full history when needed. This is the foundation for temporal awareness.

**Memory staleness detection.** This is where it gets interesting from a UX perspective. "You told me you prefer Podman a few months ago, but you just did a whole project in Docker. Would you like to revise this preference?" That makes agents feel like they actually know you. It's not just recall — it's awareness that recall might be outdated. We're not sure exactly how to detect staleness at scale (behavior analysis? contradiction detection? time-based decay?), but the concept is strong.

**Memory promotion and organizational learning.** The flow we discussed: many users teach their agents "scan for secrets before committing" — MemoryHub detects the pattern across users — promotes it to organizational memory "this organization prefers secrets scanning before commits" — or maybe even policy-level "this organization requires secrets scanning" — then user-level memories get pruned or revised to point at the org-level memory. This is genuine organizational learning. The organization gets smarter over time, and individual agents get simpler (fewer redundant memories, more references to shared knowledge).

**Agentic memory management.** The agents that manage memory within MemoryHub itself are a key architectural decision. They run on schedules to: promote memories across tiers, prune stale ones, scan org documents and posts and emails for new knowledge to ingest, and detect secrets or PII in stored memories. MemoryHub isn't just a store — it's an active system that maintains and improves its own contents.

**Proactive surfacing is a stretch goal.** The architecture would support a sidecar agent that decides what to inject on each turn, rather than requiring the agent to explicitly request memories. But actually building that is complex — it's always running, it needs to be fast, and it needs to be smart about what's relevant. We decided to table it for v1 and focus on explicit memory retrieval. The architecture should enable it later without a rewrite.

**Secrets protection.** Memory scanning prevents enterprises from inadvertently spilling secrets onto hosted APIs and getting those secrets into model training. This is a real enterprise concern — an agent that stores "the production database password is X" in its memory, and that memory gets sent to an external API for processing, is a security incident. MemoryHub's scanning catches this before it happens.

**Enterprise forensics.** We identified multiple forensics use cases: agentic analysis of memory patterns across the organization, searching memories for policy or ethics violations, and incident investigation that combines trace data with memory state. "Did this user intend to release our source code, or did the agent make a mistake based on a misunderstood memory?" That's a question that matters in a post-incident review, and today it's unanswerable.

## Technology choices

We landed on: Milvus for vector storage, Neo4j for graph storage, MinIO/S3 for markdown files, Grafana + Prometheus for observability, MCP server for the agent interface, and a Kubernetes Operator with CRDs for management. FIPS is required throughout.

The three-backend complexity is a known concern. We discussed it and decided the retrieval characteristics justify it — vector search, graph traversal, and file-based access serve fundamentally different memory access patterns. But we should keep the "lite mode on PostgreSQL" idea alive as a simpler deployment option.

## Path to RHOAI

Build as a standalone component deployable to existing RHOAI clusters. Prove it works with real agents doing real work. Then pitch the engineering team. The user meets with them regularly, so the relationship is there. The question is whether we can build something compelling enough that the conversation is "you should take this" rather than "would you consider this."

## Second Session — Later on April 3, 2026

Major architectural decisions made:

**Memory model is a tree, not a layer cake.** Instead of flat tiers stacked on each other, memories form a tree with required and optional branches. A memory node has a weight that tells the system whether to inject the full memory or just a stub, letting the agent decide if it needs to crawl deeper. For example, a preference memory ("prefers Podman") is a node with an optional rationale branch ("works for Red Hat, that's what they use"). The agent gets the stub by default and can search for the rationale if it needs deeper context. A lightweight top-level directive might explain the tree concept to the agent, or we might just provide stubs with indicators that more context is available — to be determined.

**Governance model decided: automated with guardrails.**
- User-level memories: fully automatic, no HITL. Only the user themselves can hand-edit their own memories (nobody else, to prevent attribution manipulation).
- Enterprise/policy-level memories: always HITL for creation and modification.
- Everything in between: automatic by default, auditable and editable by humans.
- Full immutable logging on all memory operations — critical because if someone can alter a memory, they can change system behavior and make a user appear responsible for something.
- Consider: only one designated agent ever writes above user-level, and part of its process is deduplication and conflict checking.

**Conflict resolution strategy:**
- Collision avoidance: transaction processing and a pipeline prevent write conflicts.
- Semantic conflicts (memories that disagree): periodic agent run to detect conflicting memories, auto-resolve where possible, queue for human review where not.
- Levels of conflict: purely duplicate/overlapping (merge), versus genuinely conflicting (escalate).
- User-level conflicts between users are fine (Johnny prefers X, Sally prefers Y — both valid). Above user level, conflicts must be carefully curated.
- Idea: a single designated "memory curator" agent handles all above-user-level writes, checking for duplicates and conflicts before committing.

**No lite mode.** Full storage stack only. The complexity doesn't warrant a stripped-down option, and enterprises needing this can afford the storage. Simplifies the architecture and testing matrix.

**FIPS research kicked off** for Milvus, Neo4j, pgvector, Redis, Qdrant, Weaviate, MinIO. Results pending — this will inform final storage decisions.

**Storage stack finalized:**
- PostgreSQL (OOTB, ships with OpenShift) + pgvector for vector search. Not Crunchy — can't build on external vendor product.
- PostgreSQL for graph queries initially (AGE or adjacency lists). Evolution path: Neo4j, Memgraph, or petgraph (Rust in-process graph library).
- MinIO for S3/markdown storage. Not ODF — not part of RHAI Enterprise.
- Key insight: in-process graph (petgraph) with PostgreSQL as durable backing store could be faster than DB round-trips for graph traversal at our scale. Worth exploring.
- FIPS story is strong: PostgreSQL delegates crypto to OS-level OpenSSL (FIPS-validated on RHEL). pgvector uses math distance computations, not crypto hashes, so works fine in FIPS mode.
