# Risks and Uncertainties

## Architecture risks

**Apache AGE or adjacency list patterns in PostgreSQL may not scale for complex graph traversals.** The decided approach is PostgreSQL for graph queries initially — either via the Apache AGE extension (openCypher on PostgreSQL) or adjacency list table patterns. This is operationally simple and FIPS-safe, but AGE is an Apache incubator project with less maturity than purpose-built graph databases, and deep multi-hop traversals in SQL can get expensive. An evolution path exists: Neo4j, Memgraph, or an in-process graph library (petgraph in Rust, using PostgreSQL as the durable store). That path is viable, but it adds migration complexity — the graph query API would need to change.

**OOTB PostgreSQL operator capabilities need validation.** We're using OOTB (the PostgreSQL operator that ships with OpenShift) rather than Crunchy Data. OOTB is the right call — we can't build on an external vendor's product — but we need to verify that OOTB supports pgvector extension installation and either Apache AGE or the graph query approach we choose. Crunchy's operator explicitly includes pgvector; OOTB's extension support is less documented. This needs a hands-on validation before we commit to the storage architecture.

**Memory promotion by an LLM agent is unproven at scale.** The concept is sound — detect patterns, generalize, promote — but what happens when the promotion agent generates a bad organizational memory? "Most engineers prefer tabs over spaces" is a generalization that will annoy half the org. What's the feedback loop? How do we detect and correct bad promotions? Do we need human-in-the-loop review for all promotions, just some, or none? We're not sure yet.

**The tree model needs careful conflict resolution design.** In the tree model, intra-scope conflicts are the hard case: if one agent writes "user prefers Python" and another writes "user prefers Rust," which is current? We've decided on a two-track approach — write conflicts are prevented by transaction processing and a pipeline, while semantic conflicts (memories that disagree at the meaning level) are detected by a periodic agent that auto-resolves where possible and queues the rest for human review. The strategy is defined; the implementation details need to be worked out before building versioning.

## Enterprise risks

**FIPS compliance for the storage stack is resolved.** The research came back strongly in favor of PostgreSQL + pgvector + MinIO. PostgreSQL on RHEL has the strongest FIPS posture of any option — it delegates all crypto to OS-level OpenSSL, which is FIPS-validated on RHEL/RHCOS. pgvector uses mathematical distance computations (not cryptographic hashes), so it's clean in FIPS mode. MinIO AIStor has FIPS 140-3 mode via Go 1.24's validated crypto module. Milvus was disqualified: no encryption at rest, bcrypt auth (not FIPS-approved), no validation. Neo4j Enterprise is technically FIPS-compatible but has no certified OpenShift operator and requires complex configuration. The stack we chose avoids all of those problems.

**Memory forensics at scale could be expensive.** Storing every memory operation — every create, read, update, promote, prune — generates a lot of audit data. For an agent that reads memories on every turn across hundreds of conversations, the audit log grows fast. We need to think about retention policies, tiered storage for audit data, and what level of granularity is actually necessary for forensics vs. what's just noise.

**Secrets detection has inherent tradeoffs.** An API key in a memory about "how to configure the dev environment" might be intentional — or it might be an accident. False positives create alert fatigue; false negatives create security risk. We'll need configurable sensitivity levels and probably a way for users to acknowledge and whitelist certain findings. This is a solvable problem but not a trivial one.

## Adoption risks

**The RHOAI engineering team may not want this as a component.** They might prefer it stays external, as a partner solution or community project rather than something integrated into the product. This wouldn't kill the project — it's useful as a standalone component — but it changes the value proposition and the development priorities. We should build for standalone viability first.

**The memory curator agent is a single point of failure for above-user-level writes.** We've decided that a single designated agent handles all writes above user-level, including deduplication and conflict checking. This is good for consistency but means that agent's availability and correctness become critical. If it's down, no organizational or policy memories can be written. If it has a bug, bad memories can be promoted at scale. We need robust error handling, dead-letter queuing for failed write attempts, and monitoring on this agent specifically.

**If Mem0 or Zep add Kubernetes operators and governance features, our differentiation narrows.** Both are well-funded and actively developing. We're not racing them — our enterprise and FIPS requirements create natural differentiation — but we should be aware of the competitive landscape evolving.

## Open questions

These are things we don't have answers for yet, and we should be honest about that.

How do we handle multi-cluster / multi-region memory? An organization might have agents across multiple OpenShift clusters. Does each cluster get its own MemoryHub instance with some federation layer? Or is there a central memory service? The answer has big implications for architecture and complexity.

What's the migration path for agents already using local memory? Claude Code's `~/.claude/memory/`, Cursor's memory files, other tools' memory stores — can we import from these? Should we? Import tools seem like a natural feature but designing them requires understanding each source format.

How do we handle memory conflicts when multiple agents write contradictory information? The high-level strategy is decided (transaction pipeline for write conflicts, periodic semantic conflict detection agent for meaning-level disagreements). The open question is the implementation details: what exactly does the conflict detection agent check for, and what's the schema for queuing conflicts for human review?
