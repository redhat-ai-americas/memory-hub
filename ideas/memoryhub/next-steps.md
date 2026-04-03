# Next Steps and Open Questions

Things to explore in future ideation sessions, roughly in order of how much they block other work.

## Architecture questions to resolve

**Tree structure schema design.** The memory model is a tree of nodes with required and optional branches, not flat tiers. Rationale is an optional branch on any node, not a separate tier. What we haven't formalized: what does a memory node look like in each storage backend? How are parent-child relationships represented in PostgreSQL (pgvector for search, AGE or adjacency lists for graph structure, MinIO for documents)? How does the weight field map to concrete injection behavior?

**CRD design.** What do MemoryTier, MemoryPolicy, MemoryStore CRDs look like? How do they compose? Can you declare a new memory tier by just applying a CRD, or are tiers fixed? The CRD design is one of the first things the RHOAI engineering team will evaluate, so it needs to be clean and idiomatic.

**Weight calibration.** Each memory node carries a weight that determines whether the system injects full content or a stub. How do we determine the right weight for a given node? Is it set at write time by the writing agent? Does it decay over time? Does it vary by context? The weight mechanism is central to the tree model and needs a clear design.

**Memory curator agent design.** A single designated agent handles all above-user-level writes, checking for duplicates and conflicts before committing. What are its full responsibilities? How often does it run — event-driven vs. scheduled? What are its decision criteria for merge vs. escalate? What happens when it's unavailable?

**Top-level directive design.** Agents need to understand the tree model to use it well — specifically that stubs signal available depth, and that they should decide whether to crawl deeper based on task relevance. Do we need an explicit directive injected at the top of every context explaining this? Or is the stub-plus-indicator pattern self-explanatory enough that agents will figure it out? This has implications for how much overhead MemoryHub adds to every conversation.

## Validation needed

**FIPS storage decisions — decided.** PostgreSQL (OOTB) + pgvector for vector search, PostgreSQL for graph queries (AGE or adjacency lists), MinIO for S3/object storage. Milvus, Neo4j, Crunchy Data, and ODF are all ruled out. See research-fips-storage.md for the full analysis. The remaining validation items are below.

**Validate OOTB PostgreSQL extension support.** Confirm that the OOTB operator (not Crunchy) supports installing the pgvector extension and either Apache AGE or the adjacency list approach we choose for graph queries. This is a hands-on cluster check, not a documentation review.

**Evaluate petgraph (Rust) as an in-memory graph layer.** For graph traversals at scale, an in-process graph library with PostgreSQL as the durable store may be faster than round-tripping through a database. Petgraph is the Rust equivalent of NetworkX. Pattern: load graph data from PostgreSQL at startup, run traversals in-memory, write mutations back to PostgreSQL. Worth prototyping when graph query performance becomes a concern — it's a viable evolution path that doesn't require a separate graph database.

**Grafana node graph panel at scale.** We're assuming Grafana can visualize memory relationship graphs effectively. Test this with a realistic dataset — thousands of nodes, complex relationships — before committing to Grafana as the graph visualization layer.

## Design work

**Memory promotion governance implementation.** The governance model is decided (user-level automatic, enterprise HITL, middle tiers automatic with audit). What's still open is the implementation: configurable thresholds for promotion, the feedback loop when a promoted memory is wrong, and how the memory curator agent surfaces candidates for human review.

**MCP server tool design.** What tools does the MCP server expose? The obvious ones: `read_memory`, `write_memory`, `search_memory`, `get_rationale`, `list_versions`. But there are subtleties — does `search_memory` return full content or stubs? Is there a `suggest_memory` tool for proactive surfacing? Save detailed planning for the `/plan-tools` workflow, but sketch the surface area first.

**Multi-cluster story.** How does memory work across multiple OpenShift clusters in an organization? Federation? Centralization? This doesn't need to be solved for v1, but the architecture shouldn't make it impossible.

**Import/migration.** How do agents with existing local memory (like Claude Code's `~/.claude/memory/`) feed into MemoryHub? Import tools seem natural, but each source has a different format and set of assumptions.

## Research to do

**The "Governed Memory" paper** (arXiv:2603.17787) needs a detailed read. It's the closest academic work to what we're building and reportedly achieves 99.6% fact recall with zero cross-entity leakage. There may be architectural insights we can adopt or learn from.

## When ready to move forward

- `/imagine` again to continue exploring and refining ideas
- `/pitch` to create an internal pitch for the RHOAI engineering team
- `/brief` to create a structured briefing document for broader stakeholders
- `/propose` to dive into technical architecture and start making concrete design decisions
