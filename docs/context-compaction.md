# Context Compaction Services

## Summary

MemoryHub's context compaction subsystem introduces governed, auditable compression across four layers of agent context: the memory store itself, retrieval-time token-budget assembly, session-level conversation compaction (coordinated with #168), and cross-agent context coordination. Every compaction event produces a provenance branch and an entry in the audit log. Full originals move to cold storage (MinIO) while compacted forms stay hot in PostgreSQL. This design applies the ACE Generator/Reflector/Curator pattern to make compaction policies self-improving over time, and it blocks compaction when unresolved contradiction reports exist — preventing silent conflict resolution.

---

## Strategic Context

Existing agent frameworks (LangGraph, CrewAI, AutoGen) all compact context, but none treat compaction as a governed operation. Compaction happens when a token threshold is crossed, the original is discarded, and there is no audit record of what was dropped. This is incompatible with MemoryHub's governance model.

The transparency fork between Anthropic and OpenAI matters here. OpenAI's compaction produces opaque encrypted tokens — 99.3% compression, zero interpretability, unauditable. Anthropic's approach produces readable structured summaries that a compliance team can inspect. Factory.ai's benchmark confirmed that structured summarization (3.70) outperforms both Anthropic default (3.44) and OpenAI opaque (3.35) on recall, artifact recovery, continuation, and decision-rationale probes. MemoryHub uses structured summarization, not freeform, and not opaque tokens.

Regulatory drivers:

- **EU AI Act** (phased enforcement through August 2026): high-risk AI systems must demonstrate what happened and why. Opaque compaction cannot satisfy this.
- **GDPR Art. 5** (data minimization): argues for compaction — don't retain more than necessary.
- **GDPR Art. 22** (right to explanation): argues against losing context — if a decision was informed by compacted material, can you explain the decision?
- **HIPAA, DORA, financial services retention**: 6–7 year retention mandates.

The resolution is dual-track storage: the LLM sees the compacted hot path; the compliance record is the full cold-path archive. Both are governed by the same RBAC and tenant isolation as the rest of MemoryHub.

---

## Architecture Overview

Four compaction layers, each with a distinct trigger and scope:

```
┌────────────────────────────────────────────────────────────────┐
│                    Compaction Orchestrator                       │
│   Policy Engine → Provenance Writer → Epoch Invalidator         │
└───────────┬────────────────┬────────────────┬──────────────────┘
            │                │                │
   ┌────────▼─────┐  ┌───────▼──────┐  ┌─────▼──────────────────┐
   │ Memory Store │  │ Retrieval    │  │ Session / Cross-Agent   │
   │ Compaction   │  │ Token Budget │  │ Compaction              │
   │ (background) │  │ (per-query)  │  │ (conversation #168)     │
   └────────┬─────┘  └───────┬──────┘  └─────┬──────────────────┘
            │                │                │
   ┌────────▼────────────────▼────────────────▼──────────────────┐
   │                  Dual-Track Storage                           │
   │   Hot: PostgreSQL (compacted, embeddings, provenance)         │
   │   Cold: MinIO/S3 (full originals, structured by retention)    │
   └────────────────────────────────────────────────────────────────┘
```

**Layer 1 — Memory Store Compaction (background):** Periodic background job that deduplicates, merges near-duplicates, archives stale memories, and decays weights. Evolves from the existing curation pipeline (duplicate detection, `manage_graph(action="get_similar", ...)`, weight decay). Compaction events produce `compaction_provenance` branches and trigger compilation epoch invalidation.

**Layer 2 — Retrieval-Time Token Budget Assembly:** At `search_memory` time, if the caller specifies a `max_response_tokens` budget, results are structured-summarized to fit. Operates on the already-retrieved result set; no LLM call unless the caller opts into summarization. This is filtering and structured truncation, not lossy compression.

**Layer 3 — Session-Level Conversation Compaction:** Compact conversation history from `ConversationThread` (#168) while preserving memory-derived context. Triggers when a thread nears the configured token threshold. Compacted summaries are stored as `CompactionSummary` records linked to the thread. The underlying memory store is the recovery mechanism — compacted facts can be re-retrieved from Layer 1's memory store.

**Layer 4 — Cross-Agent Context Coordination:** MemoryHub as the coordination point for multi-agent token budgets. Agents register their per-session token budget via `register_session`. Retrieval assembles context that fits each agent's budget rather than a generic result set.

---

## Policy Engine

Compaction policy is admin-configurable via a new rule tier on the existing `curator_rules` table. No new table is required; the `trigger` column is extended with compaction-specific triggers and a new `tier` value, `compaction`, is added alongside the existing `regex` and `embedding` tiers.

### New trigger values

| Trigger | When it fires |
|---|---|
| `on_compaction_candidate` | Background sweep identifies a candidate memory |
| `on_token_budget` | Retrieval would exceed `max_response_tokens` |
| `on_thread_threshold` | Conversation thread crosses token threshold |
| `periodic_compaction` | Scheduled sweep (cron-based, configured in rule config) |

### New action values

| Action | Effect |
|---|---|
| `archive` | Move full content to cold storage (MinIO), retain stub and embedding in hot path |
| `merge` | Merge two or more memories into a single compacted memory with provenance branch |
| `summarize` | Replace full content with structured summary; original goes to cold storage |
| `protect` | Mark memory as never-compact; takes priority over all other rules |
| `decay_weight` | Reduce weight by configured factor; existing action, now also available on compaction trigger |

### Rule schema additions (config keys for `compaction` tier)

```json
{
  "compaction": {
    "method": "structured_summarization",
    "max_age_days": 90,
    "min_weight": 0.5,
    "domain_tags": ["experimental"],
    "retention_days": 2555,
    "require_human_approval": false
  }
}
```

- `method`: one of `structured_summarization`, `archive_only`, `merge` (default: `archive_only`)
- `max_age_days`: only compact if `created_at` is older than this (default: null, no age restriction)
- `min_weight`: only compact if `weight` is below this value (default: null, no weight restriction)
- `domain_tags`: array of tags from `metadata_`; if set, only match memories with these tags
- `retention_days`: how long to retain full content in cold storage before purge (default: 2555 = 7 years)
- `require_human_approval`: if true, queue for human review rather than auto-compact

### Built-in compaction policies (system layer, cannot be overridden by user rules)

| Name | Trigger | Scope | Action | Config |
|---|---|---|---|---|
| `enterprise_protect` | `on_compaction_candidate` | `enterprise` | `protect` | Protects all enterprise-scope memories from auto-compaction |
| `contradiction_block` | `on_compaction_candidate` | all | block (see §Contradiction-Aware Compaction) | Blocks compaction when unresolved contradiction reports exist |

### Integration with RBAC

- Users can create `compaction` tier rules at the `user` layer for their own memories.
- Org admins can create org-layer rules.
- System rules (including `enterprise_protect` and `contradiction_block`) have `override=true` and cannot be weakened.
- The `protect` action at any layer blocks all lower-layer compaction rules for that memory.

---

## Compaction Pipeline

### Memory Store Compaction (Background)

The background compaction job runs on a configurable schedule. It does not call an LLM on the candidate identification path; LLM calls are isolated to the `summarize` action and are bounded by per-job token budgets.

**Candidate identification:**

1. Load enabled compaction rules for the tenant (periodic + on_compaction_candidate triggers).
2. Query `memory_nodes` for candidates matching rule predicates: `weight < threshold`, `created_at < cutoff`, `domain_tags intersection`, `is_current = true`, `deleted_at IS NULL`.
3. For each candidate, check contradiction block (see §Contradiction-Aware Compaction). Skip if blocked.
4. For each candidate, check `protect` rules. Skip if protected.
5. For similarity-merge candidates, call `manage_graph(action="get_similar", ...)` with the candidate's embedding to find merge partners above the configured merge threshold (default: 0.92).

**Generator/Reflector/Curator pattern (ACE):**

- **Generator**: Normal agent operation — memory writes and reads. The generator produces the raw signal.
- **Reflector**: Background analysis job that reads the compaction event log and the re-retrieval log. Identifies: which compacted memories were re-retrieved frequently (over-aggressive compaction), which candidates were never re-retrieved (safe to compact), which merge decisions caused downstream errors. Reflector writes its findings as `compaction_policy_adjustment` memories at the system layer.
- **Curator**: Updates compaction rule configs based on Reflector findings. For example, raises the weight threshold if frequently-re-retrieved memories were below the current threshold at compaction time. The Curator is the only component that writes to `curator_rules` automatically; all such writes are logged to the audit trail.

**Trigger conditions:**

- Scheduled: configurable cron expression in rule config (e.g., `"schedule": "0 2 * * *"` for nightly at 02:00).
- Threshold-based: when the appendix fraction of the current compilation epoch exceeds `auto_recompile_threshold` (see §Compilation Epochs), a compaction pass is triggered before recompilation.
- On-demand: via `compact_memories` MCP tool (admin or service identity only).

**Execution:**

For each candidate that passes all guards:

1. If action is `archive`: write full content to MinIO at `{tenant_id}/compaction/{memory_id}/{compaction_event_id}`; update `content` column to structured stub (first 500 chars of existing content); write cold-storage reference to the `compaction_events.cold_storage_key` column for this event; create `compaction_provenance` branch. Embeddings for archived memories are recomputed against the structured stub within the same compaction transaction. The pre-compaction embedding is preserved in the cold-storage archive metadata for forensic queries but is not used in retrieval.
2. If action is `merge`: run structured summarization across the candidate group (one LLM call per group, not per memory); write merged content to the compacted memory; archive all source memories to cold storage; create `compaction_provenance` branch linking all sources to the merged output.
3. If action is `summarize`: call the summarization endpoint with the structured template (see below); replace `content` with the summary; archive original to cold storage; create `compaction_provenance` branch.
4. Invalidate the compilation epoch for the affected `(tenant_id, owner_id)` pair by deleting the Valkey key `memoryhub:compilation:<tenant>:<owner>`. The next `search_memory` call recompiles from the new state.
5. Insert a row into `compaction_events` (see §Compaction Provenance).

**Structured summarization template:**

Summaries use a fixed schema, not freeform prose. The LLM is given the template as a structured output constraint:

```json
{
  "core_fact": "One sentence capturing the primary assertion.",
  "context": "One sentence on when or where this applies.",
  "rationale": "One sentence on why this was recorded (if known).",
  "confidence": 0.0,
  "tags": [],
  "compacted_from_count": 1,
  "compacted_from_ids": []
}
```

This is Factory.ai's "structured summarization" approach, adapted to MemoryHub's memory schema. The schema prevents silent drops: if a field cannot be filled from the source content, it is set to null explicitly, not omitted.

### Retrieval-Time Token Budget Assembly

When `search_memory` is called with a `max_response_tokens` parameter:

1. Retrieve the full result set (existing logic, up to `max_results`).
2. Estimate token cost per result using the stub length as a proxy (1 token ≈ 4 characters for English text).
3. If the estimated total is within budget, return results as-is.
4. If over budget, apply the following strategy in order:
   a. Truncate results at the boundary where cumulative cost would exceed budget. Append `truncated: true` and `truncated_count` to the response.
   b. If the caller also sets `allow_summarize: true`, replace the lowest-weight results with single-sentence stubs derived from the `core_fact` field (if the memory was previously compacted and has a structured summary) or a content prefix (otherwise).
5. Return `token_budget_used` and `token_budget_remaining` in the response envelope.

This is not lossy compression — it is structured truncation with explicit signaling. The agent knows exactly what was dropped and can retrieve specific memories by ID if needed.

### Session-Level Conversation Compaction

Coordinates with #168 (`ConversationThread` + `ConversationMessage`).

**Trigger:** A conversation thread crosses `compaction_threshold_tokens` (default: 70% of the configured context window). The 70% trigger is proactive — reactive triggers at 95% (Anthropic's current default) leave too little headroom for the summary itself.

**Compaction process:**

1. Identify the compaction boundary: the oldest N messages whose cumulative token cost brings the thread within the token budget (leaving 25% headroom).
2. For each message in the compaction window, check whether any memory-derived context was injected at that turn (via the `compilation_hash` in the injection metadata). If yes, record the `memory_id` list for provenance.
3. Call the structured summarization endpoint with the compaction window.  The template for conversation compaction is different from memory compaction:

```json
{
  "topic": "What was being worked on.",
  "decisions": ["Decision A.", "Decision B."],
  "open_questions": ["Question still unresolved."],
  "file_paths_modified": [],
  "commands_run": [],
  "memory_ids_referenced": []
}
```

4. Write the summary as a `CompactionSummary` record on the thread (see #168 schema extension).
5. Mark the compacted messages as `compacted: true` in `conversation_messages`. They are not deleted — cold-path retrieval can still hydrate them.
6. Create a `compaction_provenance` memory branch linking the `ConversationThread` ID and the list of compacted `ConversationMessage` IDs.

**Memory-derived context recovery:** If a compacted-out fact needs to be recovered, `search_memory` can retrieve it from the memory store. The session-level compaction complements, not replaces, the memory store — facts the agent explicitly wrote as memories survive session compaction.

### Cross-Agent Context Coordination

Agents register a `token_budget` in `register_session` (optional integer, tokens). When `search_memory` is called from a session with a registered budget, `max_response_tokens` defaults to the registered budget minus an overhead reserve (configurable, default: 512 tokens for the memory injection wrapper).

For multi-agent scenarios:

- Each agent's retrieval is already bounded by its registered budget.
- MemoryHub does not attempt to coordinate across agents' active context windows — that is the orchestrator's responsibility. MemoryHub provides the bounded retrieval; the orchestrator decides how to combine results.
- The star topology saturation limit (N ~ W/m agents, where W = context window and m = average message length) does not apply to MemoryHub's retrieval layer because each agent's retrieval is independent and budget-bounded. Saturation is a concern for the orchestrator's shared context, not for MemoryHub's per-agent result sets.

---

## Compaction Provenance

Every compaction event — background merge, session compaction, retrieval truncation with `allow_summarize` — produces a `compaction_provenance` branch in the memory tree and a row in the `compaction_events` table.

### `compaction_events` table

| Column | Type | Purpose |
|---|---|---|
| `id` | UUID PK | Compaction event ID |
| `tenant_id` | String | Tenant isolation |
| `compaction_type` | String(30) | `memory_merge`, `memory_archive`, `memory_summarize`, `conversation_compaction`, `retrieval_truncation` |
| `triggered_by` | String(30) | `scheduled`, `threshold`, `on_demand`, `retrieval` |
| `policy_rule_id` | UUID FK → curator_rules | Which rule triggered this event (null for retrieval truncation) |
| `source_memory_ids` | JSONB (array of UUID) | Source memories included in this compaction |
| `output_memory_id` | UUID FK → memory_nodes | The compacted/merged output memory (null for archive-only) |
| `cold_storage_key` | VARCHAR(512) | The MinIO object key where the pre-compaction original content is archived. NULL for merge/summarize actions that don't archive a single source; populated for archive actions. |
| `cold_storage_keys` | JSONB (array of String) | MinIO object keys for all archived originals (used by merge/summarize compaction types) |
| `summary_schema_version` | String(10) | Version of the structured summary template used |
| `token_delta` | Integer | Tokens saved (estimated); negative = expansion |
| `actor` | String(255) | `system`, `owner_id`, or service identity that initiated |
| `created_at` | TIMESTAMPTZ | Event timestamp |
| `approved_by` | String(255) | If `require_human_approval=true`, who approved |
| `approved_at` | TIMESTAMPTZ | When approved |

### `compaction_provenance` branch

In the memory tree, each compaction that produces an output memory (merge, summarize) creates a child branch of type `compaction_provenance` on the output memory. The branch `content` is a JSON document:

```json
{
  "compaction_event_id": "uuid",
  "compaction_type": "memory_merge",
  "source_memory_ids": ["uuid-a", "uuid-b"],
  "cold_storage_keys": ["tenant/compaction/uuid-a/event-uuid", "tenant/compaction/uuid-b/event-uuid"],
  "method": "structured_summarization",
  "summary_schema_version": "1.0",
  "policy_rule_name": "stale_user_memory_archive",
  "triggered_by": "scheduled"
}
```

**Bidirectional traceability:** From any compacted memory, follow the `compaction_provenance` branch to find the `compaction_event_id`. From any `compaction_event_id`, find all `source_memory_ids` and their `cold_storage_keys`. The cold-storage keys are stable S3 URIs that resolve to the original full content. This chain survives memory deletion — the `compaction_events` row and the cold-storage objects persist until the configured `retention_days` expires, even if the output memory is later deleted.

---

## Dual-Track Storage

### Hot path (PostgreSQL)

Compacted memories in the hot path are the normal `memory_nodes` rows: stub text, embedding, weight, provenance branches, metadata. The `content` column holds the compacted form (structured summary or archive stub). The `content_ref` column retains its existing semantics (oversized-content S3 offload via `storage_type='s3'`). Compaction archive locations live on the `compaction_events` row, keyed by the memory's most recent compaction event.

Reads from the hot path are unchanged — `search_memory`, `read_memory` without `hydrate=True`, retrieval-time token budget assembly all operate on hot-path rows.

### Cold path (MinIO)

Cold-path objects are written by the compaction pipeline under the key schema:

```
{tenant_id}/compaction/{memory_id}/{compaction_event_id}
```

This is distinct from the existing version chain key schema (`{tenant_id}/{memory_id}/{version_id}`). Compaction objects are not versions — they are full originals archived by the compaction event.

Cold-path objects contain the complete original `content` string (or the full S3-backed document if the memory was already oversized). They also include a JSON metadata header:

```json
{
  "memory_id": "uuid",
  "compaction_event_id": "uuid",
  "original_version_id": "uuid",
  "compacted_at": "ISO8601",
  "schema_version": "1.0"
}
```

**Hydration from cold path:** `read_memory(memory_id, hydrate_cold=True)` queries `compaction_events` for the memory's most recent event with a populated `cold_storage_key`, then fetches that object from MinIO. Distinct from the existing `hydrate=True` flag (which follows `content_ref` for oversized-content offload). The MCP tool `read_memory` exposes `hydrate_cold` as an optional parameter, restricted to callers with `memory:admin` scope or the memory's original `owner_id`.

**When to move to cold:** The compaction pipeline writes to cold storage at compaction time. There is no deferred migration — the original is archived in the same transaction as the hot-path update. If the MinIO write fails, the compaction is rolled back and the event is not recorded.

**Retention and purge:** Cold-path objects are retained for `retention_days` (from the triggering rule's config, or the system default). A separate background job scans `compaction_events` for rows where `created_at + retention_days < now()` and deletes the corresponding MinIO objects. The `compaction_events` row itself is retained indefinitely (it is the audit record; only its cold-storage pointers become invalid after purge).

**Integration with existing S3 infrastructure:** The compaction cold path uses the same MinIO deployment and credentials as the existing oversized content storage. The bucket is the same (`memoryhub-data` or whatever the operator configures). The key prefix (`compaction/`) distinguishes compaction archives from content versions.

---

## Contradiction-Aware Compaction

The `contradiction_block` system rule prevents compaction from silently resolving contradictions.

**Rule logic:** Before any compaction action (archive, merge, summarize) executes against a memory, the pipeline queries `contradiction_reports` for unresolved reports targeting that memory:

```sql
SELECT COUNT(*) FROM contradiction_reports
WHERE memory_id = $1 AND resolved = false AND confidence >= 0.5;
```

Compaction is blocked only when at least one unresolved contradiction has `confidence >= 0.5`. Low-confidence contradictions (below 0.5) are informational and do not block compaction. The threshold is configurable via `MEMORYHUB_COMPACTION_CONTRADICTION_THRESHOLD` (default 0.5). When blocked, the event is logged with `status = 'blocked_contradiction'`. The rule cannot be overridden by user or org layer rules (`override = true`).

**For merge candidates:** If any memory in a merge group has unresolved contradictions, the entire group is blocked — not just the individual memory. This prevents a merge from obscuring which source memory was contradicted.

**Resolution path:** Contradictions must be resolved (via `manage_curation(action="report_contradiction", ...)`'s resolution mechanism, or via direct admin action) before compaction can proceed. After resolution, the memory is eligible for the next compaction sweep.

**Operator override:** Admin users can force compaction despite unresolved contradictions by calling `compact_memories` with `force_contradiction_override: true`. This is logged with the actor's identity and the count of overridden contradictions.

---

## ACE-Style Reflection

The Reflector tracks re-retrieval of compacted memories as a signal of over-aggressive compaction.

### Re-retrieval log

When `search_memory` or `read_memory` returns a result for a memory that has a `compaction_provenance` branch (i.e., the memory was produced by a compaction), the retrieval is logged to a lightweight table:

**`compaction_retrievals` table:**

| Column | Type | Purpose |
|---|---|---|
| `id` | UUID PK | |
| `memory_id` | UUID FK → memory_nodes | The compacted memory retrieved |
| `compaction_event_id` | UUID FK → compaction_events | Which compaction event produced it |
| `retrieved_by` | String | Owner or service identity |
| `retrieved_at` | TIMESTAMPTZ | |
| `hydrate_cold_requested` | Boolean | Whether the caller requested the original |

`hydrate_cold_requested = true` is a strong signal of over-aggressive compaction — the agent needed the full original. Writes to `compaction_retrievals` are sampled at 10% of search hits to bound write load; a 30-day TTL purge job keeps the table bounded. Sampling rate and TTL are configurable.

### Reflector job

Runs on a configurable schedule (default: weekly). For each compaction rule, the Reflector computes:

- **Re-retrieval rate**: `compaction_retrievals.count / source_memories.count` for memories compacted under this rule in the past N days.
- **Cold hydration rate**: `hydrate_cold_requested = true` fraction of re-retrievals.
- **Candidate miss rate**: Memories that matched a rule's predicates but were blocked by contradiction (would have been compacted but weren't).

If the re-retrieval rate exceeds a configured threshold (default: 15%), the Reflector emits a `compaction_policy_adjustment` recommendation memory at the system layer, flagged for admin review. It does not modify rules automatically — it recommends. Admins approve recommendations via the admin API or the `compact_memories` tool with `apply_reflector_suggestion: <event_id>`.

---

## MCP Tools

### `compact_memories`

Initiates an on-demand compaction pass for the caller's memories. Admin or service identity can run against any tenant; regular users run against their own owner_id only.

**Input:**
```
compact_memories(
    scope: str | None,          # Filter to this scope; null = all scopes
    dry_run: bool = True,       # Default: dry_run — return candidates without acting
    max_candidates: int = 50,   # Safety limit
    force_contradiction_override: bool = False,  # Admin only
)
```

**Output:**
```json
{
  "dry_run": true,
  "candidates": [
    {
      "memory_id": "uuid",
      "stub": "...",
      "recommended_action": "archive",
      "reason": "weight=0.3, age=120 days, policy=stale_user_memory_archive",
      "blocked": false
    }
  ],
  "blocked_count": 2,
  "estimated_token_savings": 8400
}
```

### `compact_thread`

Initiates compaction of a conversation thread (requires #168). Admin or the thread owner.

**Input:**
```
compact_thread(
    thread_id: str,
    dry_run: bool = True,
)
```

**Output:** Summary of what would be compacted (message count, estimated token savings, memory IDs that would be referenced in the provenance branch).

### `get_compaction_history`

Returns the compaction event log for a memory or thread.

**Input:**
```
get_compaction_history(
    memory_id: str | None,
    thread_id: str | None,
    limit: int = 20,
    offset: int = 0,
)
```

**Output:** Paged list of `compaction_events` rows with `source_memory_ids`, `cold_storage_keys`, and `policy_rule_name`.

### `set_retention_policy`

Admin tool. Creates or updates a `compaction` tier rule on the `curator_rules` table.

**Input:**
```
set_retention_policy(
    name: str,
    scope_filter: str | None,
    action: str,               # archive, summarize, merge, protect
    config: dict,              # compaction tier config keys
    layer: str = "user",       # user | organizational | system
)
```

### `get_compaction_candidates`

Read-only. Returns memories that would be compacted on the next sweep, given current rules, without actually compacting them.

**Input:**
```
get_compaction_candidates(
    scope: str | None,
    limit: int = 20,
    offset: int = 0,
)
```

**Output:** Paged list of candidate memories with `recommended_action`, `blocking_reason` (if any), and `estimated_token_savings`.

### Authorization

All compaction write tools (`compact_memories`, `compact_thread`, `set_retention_policy`) require the caller to be the memory's owner, have `memory:admin` scope, or have a service identity. `get_compaction_history` and `get_compaction_candidates` require the same read authorization as `read_memory`.

---

## Compliance

### EU AI Act

The audit trail for each compaction event records: source memory IDs, compaction method, triggering policy rule, structured summary (inspectable, not opaque), actor, timestamp, and cold-storage keys for the full originals. This satisfies the demonstrability requirement for high-risk AI systems — a compliance team can reconstruct what the agent knew, when it knew it, and what was compressed away.

### GDPR

**Data minimization (Art. 5):** Compaction reduces retention of redundant or stale memories. The policy engine's age-based and weight-based rules are the operationalization of data minimization.

**Right to erasure (Art. 17):** Cold-path objects are deleted when `retention_days` expires or when the memory owner requests deletion. The `compaction_events` row audit entry is retained (it is the audit record, not personal data in most interpretations — it records that a compaction happened, not the compacted content). Legal teams should review this interpretation per deployment context.

**Right to explanation (Art. 22):** The bidirectional provenance chain satisfies this: from any compacted memory, the agent or compliance team can trace back through `compaction_provenance` branches to the original content in cold storage.

### HIPAA and Financial Services

Cold-path objects inherit MinIO's DARE (AES-256-GCM) encryption. `retention_days` can be set to 2555 (7 years) for financial retention requirements or 2190 (6 years) for HIPAA. The retention purge job is audited — each purge event logs the `compaction_event_id` and the cold-storage keys deleted.

---

## Migration

### New tables

```sql
-- Compaction event log
CREATE TABLE compaction_events (
    id                    UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id             TEXT NOT NULL,
    compaction_type       TEXT NOT NULL,
    triggered_by          TEXT NOT NULL,
    policy_rule_id        UUID REFERENCES curator_rules(id),
    source_memory_ids     JSONB NOT NULL DEFAULT '[]',
    output_memory_id      UUID REFERENCES memory_nodes(id),
    cold_storage_key      VARCHAR(512),
    cold_storage_keys     JSONB NOT NULL DEFAULT '[]',
    summary_schema_version TEXT,
    token_delta           INTEGER,
    actor                 TEXT NOT NULL,
    status                TEXT NOT NULL DEFAULT 'completed',
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    approved_by           TEXT,
    approved_at           TIMESTAMPTZ
);

CREATE INDEX ix_compaction_events_tenant_created ON compaction_events (tenant_id, created_at DESC);
CREATE INDEX ix_compaction_events_output_memory ON compaction_events (output_memory_id) WHERE output_memory_id IS NOT NULL;
CREATE INDEX ix_compaction_events_source_ids ON compaction_events USING GIN (source_memory_ids);

-- Re-retrieval tracking for ACE Reflector
CREATE TABLE compaction_retrievals (
    id                       UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    memory_id                UUID NOT NULL REFERENCES memory_nodes(id) ON DELETE CASCADE,
    compaction_event_id      UUID REFERENCES compaction_events(id),
    retrieved_by             TEXT NOT NULL,
    retrieved_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    hydrate_cold_requested   BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE INDEX ix_compaction_retrievals_memory ON compaction_retrievals (memory_id, retrieved_at DESC);
CREATE INDEX ix_compaction_retrievals_event ON compaction_retrievals (compaction_event_id);
```

### New columns

```sql
-- curator_rules: no schema change needed
-- New tier value 'compaction' and new trigger values added as application-layer
-- enums; the column is TEXT, so no migration needed.

-- memory_nodes: add cold-path flag
ALTER TABLE memory_nodes ADD COLUMN compaction_archived BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE memory_nodes ADD COLUMN compaction_event_id UUID REFERENCES compaction_events(id);
```

### New branch_type value

Add `compaction_provenance` to the application-layer enum of valid `branch_type` values. No schema migration needed (the column is `TEXT`).

### Alembic migrations

Two migrations:
1. `add_compaction_events_and_retrievals` — creates the two new tables and their indexes.
2. `add_compaction_columns_to_memory_nodes` — adds `compaction_archived` and `compaction_event_id` to `memory_nodes`.

Both migrations must be committed alongside the service code that uses them, per the IaC requirement in CLAUDE.md.

---

## Dependencies

- **#168 (conversation thread persistence):** Required before implementing Layer 3 (session-level conversation compaction). `compact_thread` cannot be implemented without `ConversationThread` and `ConversationMessage` entities.
- **MinIO/S3 infrastructure:** Already deployed in the `memory-hub-mcp` namespace. The compaction cold path reuses existing credentials and bucket configuration.
- **Valkey:** Compilation epoch invalidation writes to the existing Valkey key space (`memoryhub:compilation:<tenant>:<owner>`). No new Valkey infrastructure needed.
- **LLM access for `summarize` action:** The `summarize` compaction action requires an LLM endpoint. This should use the same Llama 4 Scout handler configured for `review_my_memories`. The `archive` and `merge` (without summarization) actions do not require LLM access.
- **#175 (compilation epochs):** Already shipped. Compaction invalidates epochs by deleting Valkey keys; this is already the invalidation mechanism.

---

## Open Questions

**Summarization endpoint:** Should the `summarize` action use the Llama 4 Scout sampling handler (already configured) or a dedicated embeddings/completions endpoint? The sampling handler introduces HITL friction if the client is interactive. A direct completions endpoint (same model, no HITL) is preferable for background compaction. Needs a decision before implementing the `summarize` action.

**Merge identity:** When two memories are merged, the output memory inherits the `owner_id` and `scope` of the source memories (which must match — merging across owners or scopes is not allowed). What happens if the source memories have different `weight` values? Options: take the max, take the mean, or use a configurable strategy in the rule config. Recommend max as the default (conservative — preserve importance).

**Retrieval truncation logging:** Layer 2 (retrieval-time token budget) truncation is not recorded as a `compaction_event` because it is ephemeral (the originals are not modified). Should truncation events be logged at all? Light logging (count of truncated results per query, into an application metric rather than a database table) is probably sufficient.

**Reflector approval flow:** The Reflector emits recommendations as system-layer memories flagged for admin review. Is this the right UX? An alternative is a dedicated recommendations table or an admin API endpoint that surfaces pending recommendations. The memory-based approach is self-consistent but may be surprising to admins who don't expect policy recommendations to appear in the memory store.

**Purge of compaction_events audit rows:** The design retains `compaction_events` rows indefinitely (only cold-storage objects are purged). For GDPR jurisdictions where the audit row itself contains personal data (e.g., `source_memory_ids` references user-created content), the row may also need purging. Needs legal review before production deployment.
