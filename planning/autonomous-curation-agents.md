# Autonomous Curation Agents

**Status:** Design exploration
**Date:** June 2026
**Author:** @rdwj (designed with Claude Code Opus 4.6)
**Builds on:** [curator-agent.md](../docs/curator-agent.md) (Phase 3), [knowledge-compilation.md](../docs/knowledge-compilation.md) (#171), [campaign-domain-framework.md](campaign-domain-framework.md), [conversation-persistence.md](../docs/conversation-persistence.md) (#168), [governance.md](../docs/governance.md)

---

## 1. Problem Statement

MemoryHub's curation today is deterministic and inline -- regex scanning and embedding dedup at write time (Phase 2a, shipped). This catches secrets, PII, and exact duplicates but cannot perform deeper analysis: reviewing session traces for missed memories, detecting population-level patterns across hundreds of users, verifying factual claims against current state, or merging convergent discoveries across agents.

The Phase 3 "Background Curator" sketched in [curator-agent.md](../docs/curator-agent.md) describes these needs but envisions a single monolithic curator process. Real-world requirements diverge: trace review needs conversation thread access and fires after sessions complete; fact checking needs tool access and calendar awareness; pattern aggregation needs cross-tenant statistical reads that no other agent should have. These are different workloads with different trust boundaries, different model requirements, different scaling characteristics, and different cost profiles.

This document designs a **fleet of specialized autonomous agents** running on-cluster as Kubernetes Deployments, each with precisely scoped RBAC, independently selectable models (including fine-tuned variants), and independent enable/disable for resource management.

## 2. What This Document Covers vs. What Exists Elsewhere

### Already designed elsewhere (reference, do not restate)

| Topic | Document | Status |
|---|---|---|
| Inline curation pipeline (regex, embedding dedup) | [curator-agent.md](../docs/curator-agent.md) Phase 2a | Implemented |
| Five-stage knowledge promotion pipeline | [campaign-domain-framework.md](campaign-domain-framework.md) | Design |
| Knowledge compilation pods, ACE pattern, Valkey queues | [knowledge-compilation.md](../docs/knowledge-compilation.md) #171 | Design |
| Conversation threads, messages, extraction provenance | [conversation-persistence.md](../docs/conversation-persistence.md) #168 | Design |
| Service agent identity model (`identity_type: "service"`) | [governance.md](../docs/governance.md) | Implemented |
| Content type system (experiential/knowledge/behavioral) | [knowledge-layer.md](knowledge-layer.md), `MemoryNode.content_type` | Implemented |
| Emergent domain ontology and normalization | [campaign-domain-framework.md](campaign-domain-framework.md) Phase 5 | Design |

### New in this document

1. **Trace Reviewer agent** -- post-session extraction from completed conversation threads
2. **Curator agent** -- periodic deep dedup, merge, promotion with cross-scope visibility (detailed specification of the Phase 3 sketch)
3. **Fact Checker agent** -- temporal awareness model, calendar-aware verification, tool access for external state checks
4. **Statistician agent** -- population-level pattern aggregation, convergence signals, summary memories with provenance
5. **Temporal awareness model** -- `relevant_until` semantics, expiry classification, calendar integration
6. **Summary memories with convergence provenance** -- when N agents discover the same thing, collapse to one memory plus a convergence signal that is itself knowledge
7. **Shared deployment topology** -- per-agent pods, scaling, Valkey queue coordination
8. **Per-agent RBAC specifications** -- principle of least privilege across four agents
9. **Model selection framework** -- different models per agent, fine-tuning paths
10. **Memory ownership model** -- on-behalf-of (OBO) vs. actor provenance for service agent writes

---

## 3. Memory Ownership: On-Behalf-Of vs. Actor Provenance

Curation agents write memories, but those memories are *about* users' work, not about the agent itself. The ownership model must distinguish between who created the memory (the agent) and who the memory is for (the user or scope).

### The problem

If the Trace Reviewer extracts a memory from Wes's session and writes it with `owner_id: "trace-reviewer"`, the memory is invisible to Wes's future sessions (his agents search `owner_id: "wjackson"`). If it writes with `owner_id: "wjackson"`, audit logs cannot distinguish agent-written memories from user-written ones.

### Design: dual-field ownership

Memories written by curation agents carry both fields:

- **`owner_id`**: The user or scope the memory belongs to. This is who can read/search it. For the Trace Reviewer extracting from Wes's session, `owner_id: "wjackson"`. For the Statistician writing an organizational summary, `owner_id` follows the existing scope conventions.
- **`actor_id` column** (added in #66): Automatically captures the service agent's identity on every write. Set from `claims["sub"]` (e.g., `"trace-reviewer"`, `"curator-agent"`, `"statistician"`).

This means:
- User-scoped memories extracted by the Trace Reviewer appear in the user's normal search results (owned by them)
- Audit queries filter by the `actor_id` column to see everything a specific agent wrote
- The user's agents can distinguish agent-written memories from their own if needed (e.g., to treat them with different confidence)

### Per-agent ownership rules

| Agent | `owner_id` | `actor_id` column | Rationale |
|---|---|---|---|
| Trace Reviewer | Original thread owner | `"trace-reviewer"` | Memories belong to the user whose session was reviewed |
| Curator | Follows target scope conventions | `"curator-agent"` | Promoted memories are organizational assets, not personal |
| Fact Checker | Original memory owner (unchanged) | `"fact-checker"` | Fact Checker updates metadata, doesn't change ownership |
| Statistician | Follows target scope conventions | `"statistician"` | Summary memories are organizational/campaign assets |

### OBO authorization

When the Trace Reviewer writes a memory with `owner_id: "wjackson"`, it is acting on behalf of (OBO) that user. The MCP server must allow this for service agents with the appropriate scope. The authorization check becomes:

```
if caller.identity_type == "service" and "memory:write:{scope}" in caller.scopes:
    allow write with any owner_id in that scope
```

This is already how the Curator identity works in [governance.md](../docs/governance.md) for organizational scope. The Trace Reviewer extends this pattern to user and project scope.

The `actor_id` column (added in #66) provides the audit trail: "this user-scoped memory was written by the trace-reviewer service agent after reviewing thread X." Combined with the `conversation_extractions` provenance table from #168, the full chain is: thread -> extraction -> memory (owned by user, written by agent).

---

## 4. Architecture Overview


```
+----------------------------------------------------------------------+
|                    Autonomous Curation Agents                         |
|                    (memoryhub-agents namespace)                       |
|                                                                      |
|  +-------------+ +-------------+ +-------------+ +--------------+   |
|  |   Trace     | |   Curator   | |    Fact     | | Statistician |   |
|  |  Reviewer   | |   Agent     | |   Checker   | |    Agent     |   |
|  |  Deployment | |  Deployment | |  Deployment | |  Deployment  |   |
|  |             | |             | |             | |              |   |
|  | trigger:    | | trigger:    | | trigger:    | | trigger:     |   |
|  |  event      | |  periodic   | |  periodic   | |  periodic    |   |
|  | model:      | | model:      | | model:      | | model:       |   |
|  |  mid-tier   | |  top-tier   | |  mid-tier   | |  top-tier    |   |
|  +------+------+ +------+------+ +------+------+ +------+-------+   |
|         |               |               |               |           |
|  +------v---------------v---------------v---------------v--------+  |
|  |              Valkey (job queues + coordination)                 |  |
|  |  trace_review_queue:{tenant}                                   |  |
|  |  curation_queue:{tenant}                                       |  |
|  |  fact_check_queue:{tenant}                                     |  |
|  |  stats_queue:{tenant}                                          |  |
|  |  agent_locks:{agent}:{tenant}                                  |  |
|  +----------------------------------------------------------------+  |
+----------------------------------------------------------------------+
         |                                    |
         | MCP tools (same as any agent)      | LLM inference
         v                                    v
+---------------------+           +----------------------+
|   memory-hub-mcp    |           |   RHOAI vLLM serving |
|   (MCP server)      |           |   (model endpoints)  |
|   + memoryhub-auth   |           |                      |
+----------+----------+           +----------------------+
           |
           v
+---------------------+
|   memoryhub-db      |
|   (PostgreSQL +     |
|    pgvector)        |
+---------------------+
```

**Key architectural decisions:**

1. **Agents are MCP clients, not internal services.** Each agent authenticates via `register_session` with a service API key and calls the standard MCP tools (`memory(action=...)`) exactly like any other consumer. All RBAC, audit logging, and curation pipeline checks apply. No back-door database access.

2. **CronJobs for periodic agents, Deployment for event-driven agents.** The Curator, Fact Checker, and Statistician run as Kubernetes CronJobs -- they start, process their queue, and exit. This avoids idle resource waste between runs and simplifies reasoning about lifecycle. The Trace Reviewer runs as a Deployment because it processes events promptly as sessions complete. All four have independent resource limits, independent model configuration, and independent enable/disable (suspend the CronJob or scale the Deployment to 0).

3. **Valkey for queue coordination.** Consistent with the pattern established in [knowledge-compilation.md](../docs/knowledge-compilation.md). Each agent has its own queue. A scheduler (lightweight sidecar or CronJob) enqueues work; agent pods dequeue and process.

4. **Leader election for singleton agents.** The Curator and Statistician must be singletons within a tenant to avoid conflicting writes. Leader election via Valkey `SET ... NX EX` (same pattern as the compilation scheduler). The Trace Reviewer and Fact Checker can run multiple replicas processing different queue items.

---

## 5. Agent Specifications

### 5.1 Trace Reviewer

**Purpose:** Review completed session traces (conversation threads) to extract memories that working agents missed during their sessions. An agent in the heat of problem-solving may not pause to write "I learned that the billing module requires TLS 1.3" -- the Trace Reviewer catches these.

**Trigger model:** Event-driven. When a conversation thread transitions to `status = 'archived'` (see [conversation-persistence.md](../docs/conversation-persistence.md)), an event is published to `trace_review_queue:{tenant}`. The Trace Reviewer picks up the job.

**Alternative trigger (pre-#168):** Until conversation persistence ships, the Trace Reviewer can operate on the SDK extraction pipeline output (#240). Agents using the SDK's `Extractor` ABC produce candidate memories at session end. The Trace Reviewer's pre-#168 mode reads these candidates and evaluates whether additional memories should be extracted from the session context stored in the extraction provenance.

**Processing flow:**

1. Dequeue `thread_id` from `trace_review_queue:{tenant}`.
2. Call `get_thread(thread_id, limit=..., include_tool_messages=true)` to retrieve the full conversation.
3. Call `search(query=<thread_summary>, options={scope: "project", ...})` to see what memories already exist from this session.
4. Submit the thread transcript + existing memories to the LLM with a review prompt: "What facts, decisions, preferences, or observations from this conversation are not captured in the existing memories?"
5. For each identified gap, call `memory(action="write", content=..., scope=..., options={metadata: {source: "trace_review", thread_id: ...}})`.
6. The `conversation_extractions` provenance table links these new memories back to the source thread and messages.

**What it does NOT do:**
- Does not extract memories during active sessions (that is the SDK extraction pipeline's job)
- Does not promote memories across scopes (that is the Curator's job)
- Does not verify factual claims (that is the Fact Checker's job)

**Scaling:** Multiple replicas can process different threads in parallel. No singleton constraint. HPA on `trace_review_queue` depth.

**RBAC identity:**

```json
{
  "user_id": "trace-reviewer",
  "name": "Trace Reviewer Agent",
  "identity_type": "service",
  "scopes": [
    "memory:read",
    "memory:write:user",
    "memory:write:project",
    "threads:read"
  ]
}
```

The Trace Reviewer needs `threads:read` to access completed conversation threads. It writes memories at user and project scope (matching the scope of the original thread). It cannot write to organizational or enterprise scope -- those require the Curator's promotion pipeline.

**Model selection:** Mid-tier model (e.g., Llama 4 Scout or equivalent). The task is extraction, not complex reasoning. Fine-tuning opportunity: train on (thread, existing_memories, missed_memories) triples from human review of early Trace Reviewer outputs.

### 5.2 Curator Agent

**Purpose:** Periodic deep curation across the memory store. Cross-agent dedup, merge, promotion, staleness processing, and domain ontology refinement. This is the Phase 3 background curator from [curator-agent.md](../docs/curator-agent.md), now specified in detail.

**Trigger model:** Periodic (cron-scheduled). Default schedules:

| Task | Default Schedule | Configurable |
|---|---|---|
| Deep dedup sweep | Daily 02:00 UTC | Yes, via operator CRD |
| Cross-scope conflict detection | Daily 03:00 UTC | Yes |
| Promotion analysis | Daily 04:00 UTC | Yes |
| Staleness processing | Weekly Sunday 05:00 UTC | Yes |
| Domain ontology refinement | Weekly Sunday 06:00 UTC | Yes |

**Processing flow by task:**

**Deep dedup sweep:**
1. Query all current memories in the 0.70-0.80 similarity range (below the inline pipeline's 0.80 flag threshold).
2. For each cluster of near-duplicates, evaluate via LLM: "Are these genuinely different memories or should they be merged?"
3. For merge candidates, create a `conflicts_with` relationship and enqueue for resolution (auto-merge if both memories are from the same owner; flag for human review if cross-owner).
4. Produce merged memory via `memory(action="write", ...)` with `derived_from` relationships to both sources. Mark sources as superseded.

**Cross-scope conflict detection:**
1. For each organizational/campaign-scoped memory, search for user/project-scoped memories with high similarity but contradictory content.
2. Use LLM to classify: genuine contradiction vs. scope-appropriate specialization.
3. For genuine contradictions, call `memory(action="report", memory_id=..., options={observed_behavior: ...})` to file contradiction reports.

**Promotion analysis:**
Uses the five-stage pipeline from [campaign-domain-framework.md](campaign-domain-framework.md): Classification, Decontextualization, Novelty Check, Draft, Human Review. The Curator executes stages 1-4; stage 5 routes to the approval queue.

**Staleness processing:**
1. Query memories with accumulated contradiction reports (count >= `staleness_trigger` threshold, default 5).
2. For each stale candidate, evaluate current validity via LLM.
3. For confirmed stale memories, reduce weight and add `metadata_.staleness = {detected_at, reason, contradiction_count}`.
4. Memories with `relevant_until` in the past (see section 6) are automatically flagged without LLM evaluation.

**Domain ontology refinement:**
1. Scan domain tags across all memories for synonym clusters ("Go" / "golang" / "go-lang").
2. Propose canonical terms via LLM evaluation.
3. Write normalization mappings as organizational-scoped knowledge memories with `content_type: "knowledge"` and `branch_type: "domain_ontology"`.
4. Future: apply normalization retroactively to existing memories (requires batch update capability).

**Scaling:** Singleton per tenant. Leader election via Valkey. The single-agent consistency argument from [curator-agent.md](../docs/curator-agent.md) applies: two concurrent curators could independently create conflicting organizational memories.

**RBAC identity:**

```json
{
  "user_id": "curator-agent",
  "name": "Curator Agent",
  "identity_type": "service",
  "scopes": [
    "memory:read",
    "memory:write:organizational",
    "memory:write:role",
    "memory:write:campaign",
    "memory:knowledge_curator"
  ]
}
```

This is the identity already described in [governance.md](../docs/governance.md). The Curator can read all memories (needed for cross-scope analysis) and write to organizational, role, and campaign scopes (for promotion). It has `memory:knowledge_curator` for graduating experiential memories to knowledge. It cannot write to enterprise scope (that requires human approval) or user scope (that would violate user memory ownership).

**Model selection:** Top-tier model (e.g., Llama 4 Maverick or equivalent). Promotion analysis, conflict detection, and merge decisions require nuanced judgment. The Curator makes the most consequential decisions of any agent in the fleet -- a bad promotion has enterprise-wide blast radius. Fine-tuning opportunity: train on (promotion_candidate, human_decision) pairs from the approval queue.

### 5.3 Fact Checker

**Purpose:** Periodic verification of factual claims in memories against current state. Memories encode claims that may become stale: "PostgreSQL is on version 15" becomes wrong after an upgrade. "The deploy is scheduled for next Friday" becomes irrelevant after that Friday passes. The Fact Checker detects and flags these.

**Trigger model:** Periodic (cron-scheduled). Default: daily at 01:00 UTC. Also triggered on-demand when a memory is flagged with `metadata_.needs_verification = true`.

**Processing flow:**

1. Query memories that have temporal markers (see section 6 for the temporal awareness model):
   - Memories with `relevant_until` in the past or approaching
   - Memories with temporal language detected by the temporal classifier
   - Memories flagged `needs_verification`
2. For each candidate, determine verification strategy:
   - **Calendar-expired:** If `relevant_until < now()`, mark as expired without LLM evaluation. Update `metadata_.temporal_status = "expired"` and reduce weight to 0.1.
   - **Approaching expiry:** If `relevant_until` is within 7 days, flag for review: `metadata_.temporal_status = "expiring_soon"`.
   - **Verifiable claims:** For factual assertions that can be checked against external state, use tool access (see below) to verify.
   - **Unverifiable claims:** For claims that cannot be mechanically verified, flag for human review.
3. For verified-false claims, call `memory(action="report", memory_id=..., options={observed_behavior: "Fact check failed: <evidence>"})`.

**Tool access for verification:**

The Fact Checker needs access to external tools to verify claims. This is distinct from other curation agents, which operate purely within the memory store. Tool access is mediated through a plugin architecture:

```python
class VerificationPlugin(ABC):
    """Base class for fact-checking verification plugins."""

    @abstractmethod
    async def can_verify(self, claim: str, domains: list[str]) -> bool:
        """Can this plugin verify this type of claim?"""

    @abstractmethod
    async def verify(self, claim: str, context: dict) -> VerificationResult:
        """Attempt to verify the claim. Returns confidence + evidence."""
```

Initial plugins:
- **CalendarPlugin:** Checks temporal claims against the current date. "The meeting is next Tuesday" -- is next Tuesday still in the future?
- **GitRepoPlugin:** Checks claims about code against the actual repository state. "We use Spring Boot 2.7" -- check `pom.xml` in the repo.
- **APIHealthPlugin:** Checks claims about service availability. "The staging environment is down" -- ping the endpoint.
- **VersionPlugin:** Checks claims about software versions against package registries.

Plugins are configured per deployment. Each plugin declares which domains it can verify (e.g., `GitRepoPlugin` handles domains `["git", "code", "repository"]`). Unknown domains are skipped, not failed.

**Scaling:** Multiple replicas can verify different memories in parallel. No singleton constraint. The Fact Checker does not create new memories; it flags existing ones via contradiction reports and metadata updates. Concurrent flagging is idempotent.

**RBAC identity:**

```json
{
  "user_id": "fact-checker",
  "name": "Fact Checker Agent",
  "identity_type": "service",
  "scopes": [
    "memory:read",
    "memory:write:user",
    "memory:write:project",
    "memory:write:campaign"
  ]
}
```

The Fact Checker needs `memory:read` to access memories across all scopes for verification. Write permissions at user, project, and campaign scope allow it to update metadata and file contradiction reports on memories at those scopes. It does not need organizational or enterprise write access -- flagging org-scope memories routes through the Curator for resolution.

Note: `memory:write:user` is unusual for a service agent. The Fact Checker uses it narrowly: to update `metadata_.temporal_status` and file contradiction reports on user-scoped memories. It cannot create new user-scoped memories or modify content. This constraint is enforced at the application layer (the Fact Checker's code only calls `update` and `report`, never `write` at user scope), not at the RBAC layer. If this feels too permissive, an alternative is to route all user-scope findings through the Curator.

**Model selection:** Mid-tier model (e.g., Llama 4 Scout). Fact checking is primarily classification (temporal? verifiable? contradicted?) plus evidence summarization. The verification plugins do the heavy lifting; the LLM interprets results.

### 5.4 Statistician (Pattern Aggregator)

**Purpose:** Read across many user/project/campaign memory stores to surface population-level patterns and produce organizational/enterprise-scoped knowledge with full provenance. This is the most novel agent -- it answers questions like "How many agents discovered that dark mode improves code review?" or "What percentage of projects in the Java campaign hit the WebSecurityConfigurerAdapter issue?"

**Trigger model:** Periodic (weekly default). Also triggered when campaign completion events or scope-wide memory thresholds are reached.

**Processing flow:**

1. **Pattern detection phase:**
   - For each scope of interest (organizational, campaign), run embedding-based clustering across all memories in the scope.
   - Identify clusters with high membership count (N >= configurable threshold, default 5).
   - For each cluster, extract the common theme via LLM summarization.
   - Cross-reference with existing organizational/campaign memories to avoid duplicating known patterns.

2. **Convergence signal phase:**
   - For each detected pattern, count unique contributing agents/users (not just memory count -- one agent writing 50 similar memories is noise, 50 agents each writing one is signal).
   - Compute convergence metrics:
     - `unique_contributor_count`: distinct `owner_id` values
     - `scope_coverage`: what fraction of enrolled projects (for campaign) or active users (for org) contributed
     - `temporal_spread`: earliest to latest contributing memory (a pattern discovered over 3 months is more stable than one discovered in 3 minutes)
     - `contradiction_rate`: fraction of contributing memories that have contradiction reports

3. **Summary memory creation:**
   - For patterns meeting the significance threshold (default: `unique_contributor_count >= 5` AND `scope_coverage >= 0.1`), create a summary memory:

   ```json
   {
     "content": "30% of Java campaign projects (47 of 156) reported that replacing WebSecurityConfigurerAdapter with SecurityFilterChain silently breaks custom AuthenticationProvider implementations. The workaround is to register the provider explicitly via HttpSecurity.authenticationProvider().",
     "scope": "campaign",
     "content_type": "knowledge",
     "weight": 0.85,
     "metadata": {
       "source": "statistician",
       "pattern_type": "convergent_discovery",
       "convergence": {
         "unique_contributors": 47,
         "scope_coverage": 0.30,
         "temporal_spread_days": 45,
         "contradiction_rate": 0.02,
         "earliest_source": "2026-03-15T...",
         "latest_source": "2026-04-30T..."
       }
     }
   }
   ```

4. **Provenance linkage:**
   - Create `derived_from` relationships from the summary memory to each contributing source memory.
   - The convergence metadata provides statistical context; the graph relationships provide the audit trail.
   - "Five agents discovered this" is itself information -- the `unique_contributors` count is the convergence signal.

5. **Population-level statistics:**
   - Beyond pattern-specific summaries, produce periodic statistical reports as organizational-scope memories:
     - "Memory growth rate: 15 memories/agent/day across 200 active agents"
     - "Top domains by memory count: PostgreSQL (1,247), Spring Boot (892), React (756)"
     - "Cross-project pattern emergence rate: 3.2 new convergent patterns per week"
   - These inform product design and agent default configuration.

**Privacy, statistical disclosure control, and aggregation rules:**

The Statistician operates on aggregate data, but it reads individual memories to compute aggregates. Publishing "23 patients with tuberculosis" does not violate patient privacy -- unless there are only 23 patients in the hospital. The risk is not in the count itself but in whether the count, combined with context, enables re-identification.

This is a well-studied problem. Statistical Disclosure Control (SDC) provides the framework. MemoryHub adopts SDC principles with the following rules:

**Core rules:**

1. **Minimum cell size (k-anonymity).** Summary memories must aggregate from at least k unique contributors, where k is configurable per scope and domain. Defaults:
   - General: k >= 5
   - Healthcare/medical domains: k >= 11 (matching CMS cell suppression policy)
   - HR/personnel domains: k >= 11
   - Custom: configurable via curator rule at organizational layer

2. **Small cell suppression.** When a summary includes crosstabs or breakdowns (e.g., "30% prefer X, 70% prefer Y"), any sub-group below the k threshold is suppressed. The summary reports "fewer than k" rather than the exact count. Secondary suppression applies: if suppressing one cell allows back-calculation of another small cell, suppress both.

3. **No verbatim quoting.** Summary memories must not contain individual user content verbatim. The LLM prompt instructs: "Summarize the common pattern. Do not quote any individual memory directly." This prevents memorized content from surfacing in aggregate outputs.

4. **Provenance vs. content separation.** Contributing owner IDs are stored in `metadata_.convergence` for audit provenance but are never included in the summary content itself. Access to the convergence metadata requires `memory:read` on the summary memory AND the source memories (enforced at read time, not at write time).

5. **Sensitive domain filtering.** Memories in domains tagged `sensitive` (e.g., HR, medical, legal, financial) are excluded from statistical aggregation by default. Opt-in requires an organizational-layer curator rule with explicit approval, which also sets the k threshold for that domain.

**What we need to study further (Phase 4 prerequisite):**

- Re-identification risk from combining multiple summary memories (intersection attacks). If two summaries share enough dimensional overlap, their intersection may identify individuals even when each summary alone is safe.
- Whether differential privacy (adding calibrated noise to aggregates) is warranted for specific regulated domains. For most MemoryHub use cases (agent workflow patterns, technology preferences), traditional SDC with k-anonymity and cell suppression is sufficient. For deployments processing healthcare or financial data, differential privacy may be required by policy. This is a deployment-time configuration decision, not an architecture decision.
- Regulatory landscape: HIPAA Safe Harbor (US healthcare), GDPR Article 11/Recital 26 (EU), CMS cell suppression policy. The Statistician's SDC configuration should map to the deployment's regulatory context.

**References for implementation:** CMS Cell Size Suppression Policy, UK Data Service SDC Handbook v2.0, OpenSAFELY SDC documentation, NIST differential privacy guidelines.

**Scaling:** Singleton per tenant. Statistical analysis must be consistent within a run -- two Statistician instances running concurrently on the same tenant could produce contradictory population summaries. Leader election via Valkey.

**RBAC identity:**

```json
{
  "user_id": "statistician",
  "name": "Statistician Agent",
  "identity_type": "service",
  "scopes": [
    "memory:read",
    "memory:write:organizational",
    "memory:write:campaign",
    "memory:knowledge_curator"
  ]
}
```

The Statistician needs the broadest read access of any agent: it reads across all user, project, and campaign memories within the tenant to detect population-level patterns. Its write access is limited to organizational and campaign scope -- it produces aggregate knowledge, not individual memories. `memory:knowledge_curator` allows it to write `content_type: "knowledge"` directly, since statistical summaries are by definition governed assertions, not experiential observations.

**Model selection:** Top-tier model (e.g., Llama 4 Maverick). Pattern synthesis from many sources requires strong summarization and reasoning capabilities. The Statistician processes large context windows (hundreds of memory stubs for clustering analysis) and must produce accurate statistical summaries. Fine-tuning opportunity: train on (memory_cluster, human_summary) pairs.

---

## 6. Temporal Awareness Model

### The problem

Memories encode claims with implicit or explicit temporal bounds. "The upgrade is scheduled for next weekend" is useful for five days and harmful after seven. "PostgreSQL is on version 15" is useful until the upgrade to 16. The current data model has no way to express this, so temporally-bound memories accumulate as stale noise.

### Schema changes

**`relevant_until` as a new column (recommended over repurposing `expires_at`).**

The `expires_at` column on `memory_nodes` currently exists but is used only for superseded versions (previous versions of a memory get an `expires_at` set to `now() + retention_period`). Current versions always have `expires_at = NULL`.

The two concepts are genuinely different. Version expiry is about storage lifecycle; semantic expiry is about content validity. Conflating them creates confusion in queries and in the cleanup job.

```sql
ALTER TABLE memory_nodes ADD COLUMN relevant_until TIMESTAMPTZ NULL;
CREATE INDEX ix_memory_nodes_relevant_until
  ON memory_nodes (relevant_until)
  WHERE relevant_until IS NOT NULL;
```

Alembic migration: one column add, one partial index. Non-destructive, no backfill.

### Temporal classification

When a memory is written, a background classifier (async, not inline) tags temporal markers:

| Category | Examples | `relevant_until` | Action |
|---|---|---|---|
| **Explicit deadline** | "deploy next Friday", "meeting on June 15" | Set to the specific date | Auto-expire |
| **Relative deadline** | "within the next two weeks", "by end of sprint" | Set to computed date | Auto-expire |
| **Version-bound** | "PostgreSQL 15", "Spring Boot 2.7" | NULL (no auto-expire) | Fact Checker verifies periodically |
| **Evergreen** | "prefers dark mode", "uses pytest" | NULL | No temporal processing |
| **Implicit temporal** | "currently", "right now", "at the moment" | Set to `now() + 90 days` (configurable default) | Flag for review at expiry |

The temporal classifier runs as a background task after the write succeeds, similar to entity extraction (#170). It is NOT in the inline deterministic pipeline (that would add latency and violate the no-LLM-on-write-path constraint from [curator-agent.md](../docs/curator-agent.md)).

### MCP tool changes

**`memory(action="write", ...)`:** Accept optional `relevant_until` in `options`. When provided by the calling agent, use it directly. When not provided, the background temporal classifier may set it asynchronously.

**`memory(action="search", ...)`:** Add optional `temporal_status` filter to `options`:
- `"current"` -- `relevant_until IS NULL OR relevant_until > now()`
- `"expired"` -- `relevant_until IS NOT NULL AND relevant_until <= now()`
- `"expiring_soon"` -- `relevant_until IS NOT NULL AND relevant_until BETWEEN now() AND now() + interval '7 days'`
- `"all"` -- no temporal filter

Default behavior: no filter (backward compatible). Agents that want to exclude stale memories can opt in to `temporal_status: "current"`.

**`memory(action="read", ...)`:** Response includes `relevant_until` and a computed `temporal_status` field (`"current"`, `"expired"`, `"expiring_soon"`, or `null` for evergreen memories).

### Integration with existing temporal fields

The `memory_relationships` table already has `valid_from` and `valid_until` (shipped in Phase 1 of #170). These express temporal validity of **edges**, not nodes. `relevant_until` on `memory_nodes` expresses temporal validity of the **memory content itself**. They compose: a memory that is semantically current (`relevant_until > now()`) may have a relationship that has been invalidated (`valid_until IS NOT NULL`).

---

## 7. Summary Memories and Convergence Provenance

### The convergence problem

When 50 agents independently discover the same thing ("Spring Boot's WebSecurityConfigurerAdapter removal causes silent AuthenticationProvider breakage"), the memory store accumulates 50 near-duplicate memories across 50 user/project scopes. The inline dedup catches duplicates within a single owner's scope but not across owners. The Curator's deep dedup sweep catches cross-owner near-duplicates but treats them as merge candidates, not as a convergence signal.

**The insight: convergence count is itself information.** "Five agents discovered this" means something different from "one agent discovered this." The convergence signal should be preserved, not erased by dedup.

### Summary memory structure

When the Statistician (section 5.4) or Curator detects convergent discoveries, it creates a summary memory:

```python
MemoryNode(
    content="<synthesized summary of the common discovery>",
    scope="organizational",  # or "campaign"
    content_type="knowledge",
    weight=0.85,
    owner_id="statistician",  # service identity
    branch_type=None,  # root memory
    domains=["spring-boot", "security"],  # inherited from source domain union
    metadata_={
        "source": "statistician",
        "pattern_type": "convergent_discovery",
        "convergence": {
            "unique_contributors": 47,
            "scope_coverage": 0.30,
            "temporal_spread_days": 45,
            "contradiction_rate": 0.02,
        },
    },
)
```

### Provenance graph

```
Summary Memory (organizational scope)
    |-- derived_from --> User Memory A (project:app-247)
    |-- derived_from --> User Memory B (project:app-312)
    |-- derived_from --> User Memory C (project:app-089)
    ...
    +-- derived_from --> User Memory N (project:app-401)
```

The `derived_from` relationships use the existing `memory_relationships` table. No new relationship type is needed. The `convergence` metadata on the summary memory provides the statistical context; the graph provides the audit trail.

### Dedup interaction

Once a summary memory exists, the inline dedup pipeline should recognize it. When a new agent writes a memory that is similar to an existing summary memory:

1. The `write_memory` response includes `curation.nearest_id` pointing at the summary memory.
2. The calling agent sees: "A summary memory already captures this pattern, with 47 other contributors."
3. The agent can choose to write its own project-scoped memory anyway (legitimate -- their local context may differ) or acknowledge the existing knowledge.

If the agent writes the memory, the Statistician's next run detects the new contributor and updates the summary memory's `convergence.unique_contributors` count (via `memory(action="update", ...)`).

### Weight dynamics

Summary memories start at weight 0.85. As convergence grows:
- `unique_contributors >= 10` and `scope_coverage >= 0.2`: weight increases to 0.90
- `unique_contributors >= 50` or `scope_coverage >= 0.5`: weight increases to 0.95
- Any contradiction report: weight freezes at current level until contradiction is resolved

Weight updates are made by the Statistician during its periodic runs.

### Product-level pattern examples

The Statistician's population-level analysis enables a class of insights that no individual agent could produce:

- "200 users requested dark mode today" -- surfaces demand signal from individual preference memories
- "30% of doctors prefer reviewing SOAP notes prior to patient leaving office; 70% show no consistent pattern" -- clinical workflow insight from user behavioral memories
- "Teams using the `async-first` pattern in the Python campaign have 40% fewer timeout-related memories than teams using sync patterns" -- correlational insight across project scopes
- "3 of 5 projects that adopted pgvector in Q1 wrote memories about index rebuild latency under load" -- technology adoption friction signal

These become organizational or campaign-scoped knowledge memories with full provenance, directly informing product design decisions, agent default configurations, and onboarding materials.

### Within-user pattern surfacing

The examples above are all cross-user (population-level). But there is a distinct, arguably higher-value pattern mode: detecting patterns *within a single user's own memory stream* and surfacing them during an active session.

**Clinical example:** A doctor is reviewing SOAP notes for a patient. The doctor's agent, during its normal `search` call, could surface: "This is the 5th patient you've seen this week with this symptom cluster. Worth a deeper look?" The doctor hasn't consciously assembled this pattern -- each patient was seen in a separate session, each set of notes filed independently. But the memory store holds all five, and a pattern-aware retrieval layer can detect the cluster.

**FDE example:** A field delivery engineer working on a customer's Spring Boot migration encounters an error with `AuthenticationProvider`. Their agent surfaces: "You've seen this pattern in 3 of the last 4 engagements. In the Project Alpha engagement, the fix was to register the provider explicitly via `HttpSecurity.authenticationProvider()`." The FDE didn't remember this because each engagement had its own context, but the memory store bridges them.

**Engineering example:** A developer opens a new Claude Code session on a React project. The agent surfaces: "In your last 3 sessions across different repos, you spent time debugging stale closures in `useEffect`. You wrote a memory in the `widget-app` project about the fix pattern." Cross-project learning within a single user's experience.

These within-user patterns differ from the Statistician's cross-user patterns in important ways:

| Dimension | Within-user | Cross-user (Statistician) |
|---|---|---|
| Privacy risk | None (user's own data) | Requires SDC safeguards |
| RBAC needed | User-scope read only | Cross-scope read |
| Timing | Real-time (during session) | Periodic (batch) |
| Output | Surfaced as retrieval annotation | Written as organizational memory |
| Agent | No dedicated agent needed | Statistician |

**Implementation path:** Within-user pattern surfacing does not require a new curation agent. It can be implemented as an enhancement to the `search` response:

1. When `search` returns results, compute a lightweight clustering pass over the user's recent memories (last 7-30 days) in the same domain.
2. If a cluster exceeds a configurable threshold (e.g., 3+ memories with cosine similarity > 0.80 within the time window), annotate the search response with a `pattern_signal`:

```json
{
  "results": [...],
  "pattern_signals": [
    {
      "pattern": "symptom_cluster",
      "matching_memories": 5,
      "time_window_days": 7,
      "representative_id": "uuid",
      "summary_hint": "5 recent memories match this topic cluster"
    }
  ]
}
```

3. The calling agent's LLM interprets the signal and decides whether to surface it to the user. The memory system provides the data; the agent provides the judgment.

This is a read-path enhancement, not a write-path change. It adds a small amount of compute to `search` (one additional pgvector query scoped to the user's recent memories) but requires no new agent, no new RBAC, and no new infrastructure.

**Design note: who bears the cost of pattern detection?**

In humans, pattern recognition is pre-conscious -- "I've seen this before" is a feeling before it's a thought. The brain's retrieval system fires before you can articulate why, surfacing relevant memories into conscious awareness when something matches a learned pattern. We cannot replicate this, but the design choice of where to put the pattern detection burden matters.

If the agent must decide when to check for patterns (agent-side rule), the heuristic is either too narrow (misses patterns) or too broad (queries on everything). It's also fragile across agent implementations -- a clinical agent has different trigger signals than a code review agent.

If the memory system detects patterns as a side effect of operations it's already performing (memory-side signal), the agent doesn't need to know when to ask. The `pattern_signals` annotation above follows this approach: the agent was already searching for context, and the memory system appends the signal when one exists.

The remaining gap: `pattern_signals` only fires when the agent searches, and it only detects patterns related to what the agent searched for. If a SOAP note agent doesn't include the symptom findings in its memory search, it won't get the signal. This means domain-specific agent prompting must ensure that key observations flow through `search`. This is a thin prompting pattern ("when processing clinical observations, include key findings in your memory search"), not a complex heuristic. The memory system handles pattern detection; the agent just needs to search with enough context for the signal to surface.

This constraint should inform the system prompt guidance and agent integration documentation: agents that want pattern surfacing must search with contextually rich queries, not just task-specific ones.

**Option B+: harness-level push on every turn.**

The gap in Option B is that the agent must search for the signal to appear. Option B+ eliminates this dependency: the agent harness (the runtime layer between the user and the LLM) processes the finalized form of every turn and runs a lightweight pattern check against the user's memory store, injecting a signal into the context if one is found. The agent receives the signal without having searched for it.

Processing flow:

1. A turn completes (user message or agent response).
2. Before assembling the next LLM call, the harness embeds the turn content and runs a fast pgvector query against the user's recent memories (same scope, last 7-30 days, cosine similarity > 0.80).
3. If a cluster is detected (3+ memories matching), the harness injects a `<memory-pattern-signal>` block into the system context for the next turn:

```xml
<memory-pattern-signal>
You have 5 memories from the past 7 days that are similar to the current
topic. The earliest is from 2026-06-02 (patient with similar symptom
cluster). Consider whether this pattern is clinically significant.
Memory IDs: [uuid1, uuid2, ...] — use memory(action="read") to review.
</memory-pattern-signal>
```

4. The agent sees the signal as part of its context and decides whether to act on it. No explicit search was needed.

Cost: one embedding call + one pgvector query per turn. This is milliseconds, comparable to the existing inline curation pipeline on writes. The harness already processes the turn before forwarding it to the model, so this is inserted into an existing processing step, not a new one.

**Hook integration:** In Claude Code, the `UserPromptSubmit` hook intercepts the user's turn before the LLM sees it, and the `Stop` hook intercepts the agent's completed response. Both provide finalized text at the right interception points for pattern checking. The existing `SessionStart` hook already injects memories via a `<memoryhub-context>` block; the per-turn pattern check would use `UserPromptSubmit` to inject a `<memory-pattern-signal>` block alongside the user's message. The infrastructure path is: SessionStart hook (shipped) -> UserPromptSubmit pattern hook (new) -> live subscription push (Pattern E, #62).

For agents beyond Claude Code, the hook mechanism needs to be implemented at the harness level. This is currently in development for fips-agents, which will provide the hook infrastructure for custom agent deployments. The `.memoryhub.yaml` config already has `live_subscription` and push pattern fields that could govern this behavior across both Claude Code and fips-agents runtimes.

**Precedent in industry:** Windsurf's agent harness exhibits this behavior -- the harness observes what's happening in the conversation and pushes relevant context in, independent of whether the agent explicitly searched. The agent's behavior suggests a system-level check is running on every turn, not agent-initiated retrieval.

**Configuration:** This should be opt-in per project via `.memoryhub.yaml`:

```yaml
memory_loading:
  pattern_signals:
    enabled: true
    min_cluster_size: 3
    time_window_days: 7
    similarity_threshold: 0.80
```

Disabled by default to avoid surprising agents that don't expect injected context. When enabled, the cost is bounded and predictable (one embed + one query per turn), and the benefit scales with the density of the user's memory store.

---

## 8. RBAC Summary

| Agent | `identity_type` | Read scope | Write scope | Special permissions | Singleton? |
|---|---|---|---|---|---|
| Trace Reviewer | `service` | All (via `memory:read`) | user, project | `threads:read` | No |
| Curator | `service` | All (via `memory:read`) | organizational, role, campaign | `memory:knowledge_curator` | Yes |
| Fact Checker | `service` | All (via `memory:read`) | user, project, campaign (metadata only) | None | No |
| Statistician | `service` | All (via `memory:read`) | organizational, campaign | `memory:knowledge_curator` | Yes |

**Principle of least privilege:** Each agent has the minimum permissions required for its task. The Trace Reviewer cannot promote to organizational scope. The Fact Checker cannot create summary memories. The Statistician cannot modify individual user memories.

**Audit trail:** All four agents operate through the standard MCP tool path, so every operation is audit-logged. The `actor_id` on audit entries distinguishes `trace-reviewer`, `curator-agent`, `fact-checker`, and `statistician` from each other and from human-bound agents.

---

## 9. Deployment Topology

### Namespace

All four agents deploy to a new `memoryhub-agents` namespace, separate from `memory-hub-mcp` (the MCP server) and `memoryhub-db` (PostgreSQL). This separation:
- Isolates agent workloads from the MCP server's request-handling path
- Allows independent RBAC at the Kubernetes level (ServiceAccount per agent)
- Enables resource quotas per namespace (agents don't steal CPU from the MCP server)
- Follows the existing namespace-per-concern pattern (mcp, auth, db, agents)

### Deployment patterns

Two patterns, depending on trigger model:

**Event-driven agent (Deployment)** -- Trace Reviewer only:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: trace-reviewer
  namespace: memoryhub-agents
spec:
  replicas: 1  # HPA on trace_review_queue depth; set to 0 to disable
  selector:
    matchLabels:
      app: memoryhub-agent
      agent: trace-reviewer
  template:
    spec:
      serviceAccountName: trace-reviewer
      containers:
      - name: agent
        image: memoryhub-agent:latest
        env:
        - name: AGENT_TYPE
          value: "trace-reviewer"
        - name: MH_MCP_URL
          value: "http://memory-hub-mcp.memory-hub-mcp.svc:8000"
        - name: MH_API_KEY
          valueFrom:
            secretKeyRef:
              name: trace-reviewer-credentials
              key: api-key
        - name: LLM_ENDPOINT
          value: "http://llm-serving.rhoai-serving.svc:8080/v1"
        - name: LLM_MODEL
          value: "meta-llama/Llama-4-Scout-17B-16E"
        - name: VALKEY_URL
          value: "redis://valkey.memoryhub-agents.svc:6379"
        resources:
          requests:
            cpu: 250m
            memory: 256Mi
          limits:
            cpu: 1000m
            memory: 512Mi
```

**Periodic agent (CronJob)** -- Curator, Fact Checker, Statistician:

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: curator-agent
  namespace: memoryhub-agents
spec:
  schedule: "0 2 * * *"  # Daily 02:00 UTC (configurable via operator CRD)
  suspend: false          # Set to true to disable
  concurrencyPolicy: Forbid  # Singleton enforcement at K8s level
  jobTemplate:
    spec:
      activeDeadlineSeconds: 3600  # 1-hour max runtime
      template:
        spec:
          serviceAccountName: curator-agent
          restartPolicy: OnFailure
          containers:
          - name: agent
            image: memoryhub-agent:latest
            env:
            - name: AGENT_TYPE
              value: "curator"
            - name: MH_MCP_URL
              value: "http://memory-hub-mcp.memory-hub-mcp.svc:8000"
            - name: MH_API_KEY
              valueFrom:
                secretKeyRef:
                  name: curator-credentials
                  key: api-key
            - name: LLM_ENDPOINT
              value: "http://llm-serving.rhoai-serving.svc:8080/v1"
            - name: LLM_MODEL
              value: "meta-llama/Llama-4-Maverick-17B-128E"
            - name: VALKEY_URL
              value: "redis://valkey.memoryhub-agents.svc:6379"
            resources:
              requests:
                cpu: 500m
                memory: 512Mi
              limits:
                cpu: 2000m
                memory: 1Gi
```

CronJobs are the right fit for periodic agents because they avoid idle resource waste between runs and simplify lifecycle reasoning. The tradeoff is startup latency (MCP connection, model warming) on each invocation, but periodic agents are not latency-sensitive. `concurrencyPolicy: Forbid` enforces the singleton constraint for the Curator and Statistician at the Kubernetes level, complementing the Valkey leader election.

### Resource budget per agent

| Agent | K8s kind | CPU request | Memory request | LLM calls/run |
|---|---|---|---|---|
| Trace Reviewer | Deployment | 250m | 256Mi | 1-5 per thread |
| Curator | CronJob | 500m | 512Mi | 50-200 per sweep |
| Fact Checker | CronJob | 250m | 256Mi | 10-50 per sweep |
| Statistician | CronJob | 500m | 512Mi | 20-100 per run |

**Enable/disable:** For the Trace Reviewer Deployment, set `replicas: 0`. For CronJob agents, set `suspend: true`. The Valkey queue accumulates work while an agent is disabled; it drains the backlog on the next run.

### Valkey topology

All four agents share a single Valkey instance in the `memoryhub-agents` namespace. Queue key patterns:

| Queue | Key pattern | Consumers |
|---|---|---|
| Trace review | `trace_review_queue:{tenant_id}` | Trace Reviewer |
| Curation tasks | `curation_queue:{tenant_id}:{task_type}` | Curator |
| Fact check | `fact_check_queue:{tenant_id}` | Fact Checker |
| Statistics | `stats_queue:{tenant_id}` | Statistician |
| Leader election | `agent_lock:{agent_type}:{tenant_id}` | Curator, Statistician |

This Valkey instance is separate from any future Valkey used by the MCP server for session persistence (#86) or compilation (#171). Agent work queues have different durability requirements (AOF persistence) and different scaling characteristics than ephemeral session state.

---

## 10. Model Selection Framework

### Per-agent model configuration

Each agent specifies its LLM endpoint and model via environment variables. There is no shared model pool. This allows:

- **Cost optimization:** Lower-tier agents (Trace Reviewer, Fact Checker) use cheaper models.
- **Quality optimization:** Higher-stakes agents (Curator, Statistician) use more capable models.
- **Independent upgrades:** Upgrading the Curator's model does not affect the Fact Checker.
- **Fine-tuning:** Each agent can use a fine-tuned variant of its base model without affecting others.

### Model recommendations

| Agent | Recommended tier | Rationale |
|---|---|---|
| Trace Reviewer | Mid-tier | Extraction task; moderate context; high volume |
| Curator | Top-tier | Judgment-heavy; promotion has blast radius; low volume |
| Fact Checker | Mid-tier | Classification task; plugin-assisted; high volume |
| Statistician | Top-tier | Synthesis from many sources; statistical accuracy matters |

Model-specific recommendations are intentionally omitted -- the available models on RHOAI will determine the actual selection at deployment time. The architecture supports any OpenAI-compatible inference endpoint.

### Fine-tuning paths

Each agent accumulates training signal from its operations:

| Agent | Training signal | Training data shape |
|---|---|---|
| Trace Reviewer | Human review of extracted memories | (thread_transcript, existing_memories, reviewer_additions) |
| Curator | Promotion approval queue decisions | (candidate_memory, decontextualized_version, approve/reject + reason) |
| Fact Checker | Verified/false-positive fact check results | (memory_content, verification_evidence, correct/incorrect) |
| Statistician | Human review of summary memories | (source_memory_cluster, generated_summary, accept/edit/reject) |

Fine-tuning is a Phase 6 concern. Initial deployment uses base models with carefully crafted system prompts. Training data collection begins in Phase 1 via metadata on agent outputs (`metadata_.human_review_result`).

---

## 11. Interaction with Knowledge Compilation (#171)

The autonomous curation agents and the knowledge compilation service (#171) are complementary but distinct systems:

| Concern | Curation Agents | Knowledge Compilation |
|---|---|---|
| **Input** | Individual memories | Memory clusters + entity graph |
| **Output** | Curated memories (merged, flagged, promoted) | Compiled articles (Markdown, S3-stored) |
| **Trigger** | Events + periodic cron | On-demand + periodic |
| **Scope of change** | Modifies existing memory nodes | Creates new `compiled_article` nodes |
| **LLM usage** | Classification, judgment, synthesis | Full article generation |

**Interaction points:**

1. **Curator promotes, compilation consumes.** When the Curator promotes a memory to organizational scope, the compilation service's staleness signal fires (compilation epoch invalidation), and the next compilation run incorporates the promoted memory.

2. **Statistician produces, compilation indexes.** Summary memories created by the Statistician are source material for compilation. A summary memory about "47 projects hit the AuthenticationProvider issue" would be incorporated into a compiled article on Spring Boot security migration.

3. **Fact Checker flags, compilation reflects.** When the Fact Checker flags a memory as expired, the compiled article referencing it gets `lint_status: "issues"` on its next lint sweep.

4. **Trace Reviewer extracts, compilation grows.** New memories extracted by the Trace Reviewer expand the source material pool. Delta compilation picks up new memories and integrates them.

The curation agents do NOT call compilation tools (`compile_knowledge`, `query_knowledge`). They operate at the memory node level; compilation operates at the article level. The bridge is the memory store itself -- curation agents modify memories, and the compilation service reads them.

---

## 12. Phasing Plan

### Phase 0: Prerequisites (before any agent work)

- [ ] **Conversation persistence (#168) -- at least thread archival.** The Trace Reviewer needs `get_thread` to function. Without #168, the Trace Reviewer can only operate on SDK extraction pipeline output (#240), which is a degraded mode.
- [ ] **`relevant_until` column migration.** The Fact Checker needs temporal metadata. Single Alembic migration, no backfill.
- [ ] **Valkey deployment in `memoryhub-agents` namespace.** Job queues require Valkey. Follow the pattern from knowledge compilation (#171).

### Phase 1: Curator Agent (months 1-2)

The Curator is the highest-value agent and the one most directly descended from existing design work (Phase 3 of curator-agent.md).

- [ ] Service identity and API key for `curator-agent` in the users ConfigMap
- [ ] Agent framework: Python process that authenticates via MCP, dequeues from Valkey, processes tasks
- [ ] Deep dedup sweep (0.70-0.80 similarity range, cross-owner)
- [ ] Staleness processing (contradiction count threshold)
- [ ] Leader election via Valkey for singleton constraint
- [ ] Deployment manifest for `memoryhub-agents` namespace
- [ ] Operator CRD stub: `spec.agents.curator.schedule`, `spec.agents.curator.enabled`
- [ ] Prometheus metrics: `memoryhub_curator_run_duration_seconds`, `memoryhub_curator_promotions_total`, etc.

### Phase 2: Fact Checker (months 2-3)

The Fact Checker depends on the `relevant_until` schema change and is lower-risk than the Curator (it flags but does not promote).

- [ ] `relevant_until` column and temporal classifier (background task at write time)
- [ ] Service identity and API key for `fact-checker`
- [ ] Calendar-aware expiry processing (auto-expire past `relevant_until`)
- [ ] Verification plugin architecture (`VerificationPlugin` ABC)
- [ ] CalendarPlugin (the simplest plugin, ships first)
- [ ] MCP tool changes: `relevant_until` in write options, `temporal_status` in search/read responses

### Phase 3: Trace Reviewer (months 3-4)

The Trace Reviewer depends on conversation persistence (#168) for full functionality. It can ship in degraded mode (SDK extraction pipeline only) before #168.

- [ ] Service identity and API key for `trace-reviewer`
- [ ] Event listener for thread archival events (requires #168 event integration)
- [ ] Thread review pipeline: load thread, compare to existing memories, identify gaps
- [ ] Provenance linkage via `conversation_extractions` table
- [ ] HPA scaling on `trace_review_queue` depth

### Phase 4: Statistician (months 4-6)

The Statistician is the most novel agent and depends on sufficient multi-user data to be useful. It should ship after the other agents have been running long enough to generate meaningful cross-user patterns.

- [ ] Service identity and API key for `statistician`
- [ ] Pattern detection: embedding-based clustering across owner boundaries
- [ ] Convergence signal computation (unique contributors, scope coverage, temporal spread)
- [ ] Summary memory creation with convergence metadata
- [ ] Statistical Disclosure Control: configurable k-anonymity thresholds, cell suppression, domain-specific SDC rules
- [ ] Privacy constraints: minimum aggregation threshold, no verbatim quoting, provenance/content separation
- [ ] Population-level statistics reports as organizational memories

### Phase 5: Promotion Pipeline Integration (months 5-7)

Connects the Curator to the five-stage promotion pipeline from [campaign-domain-framework.md](campaign-domain-framework.md). This is the highest-governance phase.

- [ ] Classification stage (observation / preference / directive detection)
- [ ] Decontextualization stage (strip project-specific details)
- [ ] Novelty check (cross-scope duplicate detection)
- [ ] Draft promotion (proposed state, approval queue)
- [ ] Human review UI/API integration
- [ ] Safety: directive blocking, prescriptive content rejection

### Phase 6: Fine-tuning and Optimization (months 6+)

- [ ] Training data collection from Phase 1-5 operations
- [ ] Fine-tuned model evaluation for each agent
- [ ] GitRepoPlugin, APIHealthPlugin, VersionPlugin for Fact Checker
- [ ] Domain ontology refinement in Curator
- [ ] Auto-approval for high-confidence promotion categories

---

## 13. Open Questions

### Architecture

1. **Shared agent framework or independent codebases?** All four agents follow the same pattern (authenticate, dequeue, process, report). A shared `memoryhub-agent` Python package with agent-type-specific plugins would reduce duplication. But shared frameworks create coupling -- a bug in the framework breaks all four agents simultaneously. **Recommendation:** Start with a shared framework (the pattern repeats four times), but keep the agent-specific logic in separate modules that can be split out if coupling becomes a problem.

2. **Valkey vs. PostgreSQL for job queues?** Valkey is the established pattern (from #171). PostgreSQL with `SKIP LOCKED` is an alternative that avoids a new infrastructure dependency. **Recommendation:** Valkey. The compilation service already requires it; adding agent queues is lower marginal cost than building a PostgreSQL queue.

### Data Model

3. **Convergence metadata in `metadata_` JSON vs. a dedicated table?** The `convergence` object in the Statistician's summary memories is rich (contributor lists, coverage metrics). Storing it in `metadata_` JSON is flexible but not queryable at the SQL level. A `convergence_signals` table would enable queries like "which summary memories have > 50 contributors?" without JSON path extraction. **Recommendation:** Start in `metadata_` (simpler, no migration). Add a dedicated table only if convergence queries become a performance bottleneck.

4. **Should the temporal classifier run inline or async?** Section 6 recommends async (background task after write). Inline would guarantee every memory has temporal classification before first read, at the cost of write latency. **Recommendation:** Async. The Fact Checker's daily sweep catches unclassified memories, so the gap between write and classification is bounded.

### Operational

5. **Agent observability: how much logging is too much?** Each agent processes potentially thousands of memories per sweep. Full logging of every decision creates an observability firehose. **Recommendation:** Log decisions at the aggregate level (per-sweep summary metrics), log individual decisions only for actions taken (flagged, promoted, expired), not for "no action" decisions. Prometheus metrics are the primary observability surface.

6. **Cost management: per-agent token budgets?** The Curator and Statistician use higher-tier models and could generate significant LLM costs. Should there be per-agent daily token budgets? **Recommendation:** Yes. Configure via operator CRD: `spec.agents.curator.daily_token_budget: 100000`. When exhausted, the agent stops processing and logs a warning. Resume on next UTC day.

7. **How do agents handle MCP server unavailability?** If the MCP server pod restarts while an agent is mid-sweep, the agent's tool calls fail. **Recommendation:** Exponential backoff with jitter, up to 5 retries per tool call. If the MCP server is down for the full retry window, the agent marks the current job as failed and moves to the next queue item. The failed job can be retried on the next sweep.

8. **Tenant isolation for multi-tenant deployments.** Each agent queue is keyed by `tenant_id`. But should there be one agent Deployment per tenant, or one shared Deployment that processes all tenants? **Recommendation:** Shared Deployment, per-tenant queues. The agent authenticates as its service identity, and the MCP server's tenant isolation ensures it cannot cross tenant boundaries even if the agent code has a bug. Separate Deployments per tenant are only needed if tenants have different model or resource requirements.

---

## 14. Dependencies

**What this depends on:**
- [curator-agent.md](../docs/curator-agent.md) Phase 2a (inline pipeline) -- **implemented**
- [governance.md](../docs/governance.md) service agent identity model -- **implemented**
- [conversation-persistence.md](../docs/conversation-persistence.md) #168 -- **designed, not implemented** (required for Trace Reviewer full mode)
- Valkey infrastructure -- **required for all agents** (can share with #171 compilation or deploy separately)
- LLM inference endpoints on RHOAI -- **existing infrastructure** (embedding model deployed; LLM for agent reasoning is new)

**What depends on this:**
- [knowledge-compilation.md](../docs/knowledge-compilation.md) #171 -- compilation consumes promoted/curated memories as source material
- [campaign-domain-framework.md](campaign-domain-framework.md) Phase 3-5 -- the Curator agent is the executor of the promotion pipeline
- [operator.md](operator.md) -- the operator CRD needs `spec.agents` for lifecycle management of the agent fleet
