# Curator Agent

The curator agent is MemoryHub's internal maintenance system. It's a single designated agent responsible for all above-user-level memory writes, plus periodic maintenance tasks like pruning, deduplication, and conflict detection. Making it a single agent (rather than distributed) is a deliberate consistency choice: one agent checking for duplicates and conflicts before committing means no two agents can independently create conflicting organizational memories.

**Status: largely TBD on implementation.** The responsibilities are clear; the implementation details need design work.

## Responsibilities

### Memory promotion

The curator's signature capability: detecting patterns in user-level memories and proposing organizational memories. If 30 engineers have all independently taught their agents to scan for secrets before commits, that's a pattern worth promoting to organizational knowledge.

The detection mechanism is conceptually straightforward: periodically scan user memories, cluster by semantic similarity (using pgvector embeddings), identify clusters above a configurable threshold, and generate a candidate organizational memory. The hard part is quality. A bad organizational memory that propagates to every agent is worse than no organizational memory at all. "Most engineers prefer tabs over spaces" is a generalization that will annoy half the organization.

Promotion governance varies by target scope. Promoting to organizational scope might be automatic with audit trail. Promoting to enterprise/policy scope always requires human approval. The curator proposes; a human (or the governance policy) approves.

Every promoted memory must carry provenance: which user memories it was derived from, when the promotion happened, and the confidence level of the pattern detection. This enables reversal if a promotion turns out to be wrong.

### Pruning and consolidation

When a memory gets promoted to a higher scope, the source user-level memories become partially redundant. The curator handles this by either marking them as superseded (keeping them for forensics but removing them from active retrieval) or consolidating them into references to the organizational memory.

Pruning also covers genuinely stale memories -- nodes that haven't been accessed in a long time and whose content may no longer be accurate. The curator flags these for review rather than deleting them outright, because "stale" and "wrong" aren't the same thing.

### Deduplication

Within a scope, memories can drift into near-duplication through multiple agents writing similar observations. The curator periodically scans for semantically similar memories within the same scope and merges them, preserving the most complete version and linking the others as provenance.

### Conflict detection

This is the hardest problem the curator handles. Two types of conflicts exist:

**Write conflicts** are prevented upstream by the transaction pipeline -- the governance engine serializes writes to prevent two agents from creating contradictory memories simultaneously. The curator doesn't need to handle these.

**Semantic conflicts** are memories that coexist but disagree. "User prefers Python" and "User prefers Rust" in the same user scope. At user level, this might be fine -- the user's preference genuinely changed, and the version history captures it. But at organizational level, conflicting memories are a problem that needs resolution.

The curator's conflict resolution strategy: auto-resolve where the resolution is obvious (one memory supersedes the other based on timestamp, the more recent one wins), and queue for human review where the conflict is genuine. The queuing mechanism is TBD -- it could be a CRD, a notification, or an integration with an external ticketing system.

An important nuance: user-level conflicts between different users are not conflicts at all. Johnny preferring Python and Sally preferring Rust is expected and correct. The curator only looks for conflicts within a single scope context.

### Secrets and PII scanning

The curator periodically scans memory content for patterns that look like secrets (API keys, passwords, tokens) or PII (email addresses, phone numbers, SSNs). When found, it flags the memory for review and optionally quarantines it (removes from active retrieval until reviewed).

This is a safety net, not the primary defense. The MCP server should also scan at write time. But memories can become problematic after the fact -- a token that was valid at write time might have been rotated, making its presence in memory both stale and a security concern.

The scanner needs configurable sensitivity levels. Too aggressive and it generates false positives on every memory that mentions "key" or "token" in a technical context. Too lenient and it misses actual secrets. Users should be able to acknowledge and whitelist specific findings.

## Scheduling and Execution

The curator runs on a configurable schedule within the MemoryHub deployment. It's not event-driven for most tasks -- periodic batch processing is simpler and more predictable than reacting to every write.

Suggested schedule (configurable via CRD):

- **Deduplication**: hourly or daily, depending on write volume
- **Conflict detection**: daily
- **Promotion analysis**: daily or weekly
- **Staleness scanning**: weekly
- **Secrets/PII scanning**: on every memory write (inline) plus a daily full scan

The curator runs as a single-instance deployment with leader election to prevent duplicate runs. If the pod crashes mid-run, it should be idempotent -- rerunning the same scan produces the same results without side effects.

## Staleness Detection

This is a stretch capability that builds on the curator's scanning infrastructure. The idea: when an agent observes behavior that contradicts a stored memory, it reports the contradiction back to MemoryHub. The curator accumulates these contradiction signals and, when a threshold is reached, prompts the user for revision.

Example flow: a user's memory says "prefers Podman." Over the last month, agents have observed the user consistently using Docker in three separate projects. The curator flags the memory as potentially stale and generates a prompt: "You said you prefer Podman, but your recent projects have used Docker. Would you like to update this preference?"

How contradiction signals get reported and aggregated is TBD. This might be a dedicated MCP tool (`report_contradiction`) or an implicit signal derived from agent behavior analysis.

## Availability and Failure Modes

The curator is a single point of failure for above-user-level writes. If it's down, user-level memories still work (they don't go through the curator), but organizational and policy memory operations queue up until it recovers.

Failure handling needs:
- Dead-letter queue for operations that fail during processing
- Monitoring and alerting on curator health (see [observability.md](observability.md))
- Graceful degradation: if the curator is down, the system should still serve reads and accept user-level writes
- Idempotent operations: a curator restart should be able to pick up where it left off

## Design Questions

- What's the right threshold for promotion? How many users need to have semantically similar memories before promotion is warranted? Is it a count (e.g., 10+ users), a percentage (e.g., 20% of active users), or something more nuanced?
- How do we handle promotion reversals? If a promoted memory turns out to be wrong, what's the undo process? Do we just mark it as not-current, or do we need to restore the original user-level memories?
- What's the feedback loop when a promoted memory is contested? Does the curator surface it for human review automatically, or does someone need to flag it?
- Should the curator use an LLM for pattern detection and conflict resolution, or can we get by with embedding similarity and heuristics? LLM calls add cost and latency; heuristics might miss nuanced conflicts.
- What's the schema for the human review queue? Is it a CRD, a database table, or an external system integration?
- How do we prevent the curator from becoming a bottleneck? At scale, scanning all memories periodically could be expensive. Incremental scanning (only memories modified since last run) helps, but the promotion analysis might need the full picture.
- Leader election mechanism: built into the operator, or a separate leader election sidecar?
