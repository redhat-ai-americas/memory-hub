# Conversation Thread Persistence

## Summary

This document specifies the design for first-class conversation thread persistence in MemoryHub (issue #168). The feature stores raw conversation transcripts — messages, tool calls, and tool results — under the same scope isolation, tenant isolation, RBAC, and retention policies that govern extracted memories. It also defines the auditable extraction pipeline that links conversations to the memory nodes derived from them, satisfying EU AI Act Article 12 provenance requirements for high-risk AI systems.

---

## Strategic Context

Every agent framework stores conversation history in some form. None governs it. LangGraph checkpoints are application-controlled with no access control. OpenAI's Conversations API retains indefinitely with no retention policies. A2A delegates persistence entirely to participating agents. MCP explicitly disclaims ownership of session state. Kagenti's `ContextStore` is append-only with no RBAC beyond Kubernetes namespace boundaries.

The whitespace is governed conversation persistence: thread-level access control, auditable extraction provenance, retention policy enforcement with cascade to derived memories, and cross-agent handoff with governance. This is not a differentiator that can be bolted on later — it requires a data model that treats threads as governed artifacts from the start.

The regulatory driver is EU AI Act Article 12, effective August 2, 2026 for high-risk systems. High-risk AI systems must maintain logs that link outputs to source data, model versions, and user prompts, and must produce a complete audit trail of every action. No existing framework satisfies this requirement end-to-end. MemoryHub's existing scope/tenant model, memory tree with provenance branches, and contradiction detection provide the substrate; this feature adds the missing first-class thread entity and auditable extraction pipeline.

---

## Data Model

### ConversationThread

`conversation_threads` is a new top-level table, not a memory node. Threads are governed objects with their own RBAC, retention, and lifecycle, distinct from the memory nodes they produce.

```sql
CREATE TABLE conversation_threads (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- Identity
    title           TEXT,                           -- optional human-readable name
    a2a_context_id  TEXT,                           -- maps to A2A contextId if originated from A2A

    -- Scope and tenant isolation (mirrors memory_nodes columns)
    scope           VARCHAR(20)  NOT NULL,          -- user | project | campaign | role | organizational | enterprise
    scope_id        VARCHAR(255),                   -- project_id or role_name, NULL for other scopes
    owner_id        VARCHAR(255) NOT NULL,          -- creating user/agent
    actor_id        VARCHAR(255),                   -- #65 authenticated principal who created the thread
    driver_id       VARCHAR(255),                   -- #65 upstream user/agent on whose behalf
    tenant_id       VARCHAR(255) NOT NULL DEFAULT 'default',

    -- Participants (agent and user identities present in this thread)
    participant_ids TEXT[]       NOT NULL DEFAULT '{}',

    -- Lifecycle
    status          VARCHAR(20)  NOT NULL DEFAULT 'active',   -- active | archived | deleted
    archived_at     TIMESTAMPTZ,
    deleted_at      TIMESTAMPTZ,
    expires_at      TIMESTAMPTZ,                    -- NULL = no retention expiry set

    -- Retention policy (resolved from scope/tenant hierarchy at creation time)
    retention_policy JSONB,
    legal_hold      BOOLEAN NOT NULL DEFAULT FALSE, -- blocks hard-delete when true (except spill response)

    -- Extraction state
    last_extracted_at TIMESTAMPTZ,                  -- timestamp of most recent extraction run
    extraction_cursor INTEGER NOT NULL DEFAULT 0,   -- message sequence_number up to which extraction has run

    -- Extensible metadata
    metadata        JSONB,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX ix_conv_threads_owner_scope      ON conversation_threads (owner_id, scope);
CREATE INDEX ix_conv_threads_tenant_scope     ON conversation_threads (tenant_id, scope);
CREATE INDEX ix_conv_threads_scope_id         ON conversation_threads (scope_id) WHERE scope_id IS NOT NULL;
CREATE INDEX ix_conv_threads_a2a_context_id   ON conversation_threads (a2a_context_id) WHERE a2a_context_id IS NOT NULL;
CREATE INDEX ix_conv_threads_status           ON conversation_threads (status);
CREATE INDEX ix_conv_threads_deleted_at       ON conversation_threads (deleted_at) WHERE deleted_at IS NOT NULL;
CREATE INDEX ix_conv_threads_expires_at       ON conversation_threads (expires_at) WHERE expires_at IS NOT NULL;
```

`status` values: `active` (in use), `archived` (readable, immutable, not subject to normal retention deletion unless explicitly purged), `deleted` (soft-deleted, invisible to all queries except audit).

Tenant isolation follows the existing `memory_nodes` pattern: cross-tenant queries filter by `tenant_id` before evaluating any other predicate. A thread that does not match the caller's `tenant_id` returns as not found, not as access denied.

### ConversationMessage

`conversation_messages` stores individual turns append-only. Once written, messages are never updated or deleted except as part of full thread retention enforcement.

```sql
CREATE TABLE conversation_messages (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    thread_id       UUID NOT NULL REFERENCES conversation_threads(id) ON DELETE CASCADE,

    -- Ordering within thread (monotonically increasing per thread, assigned by server)
    sequence_number INTEGER NOT NULL,

    -- Message classification
    role            VARCHAR(20) NOT NULL,   -- user | assistant | tool_call | tool_result | system
    actor_id        VARCHAR(255),           -- identity of the user or agent that produced this message

    -- Content storage
    storage_type    VARCHAR(10) NOT NULL DEFAULT 'inline',  -- inline | s3
    content         TEXT,                   -- populated when storage_type = 'inline'
    content_ref     VARCHAR(1024),          -- S3 object key when storage_type = 's3'
    content_size    INTEGER,                -- byte length; used to drive inline vs S3 routing

    -- Tool call/result correlation
    tool_call_id    VARCHAR(255),           -- present on tool_call and tool_result messages

    -- Handoff metadata (populated when this message carries a cross-agent handoff)
    handoff_from_agent_id  VARCHAR(255),
    handoff_authorized_by  VARCHAR(255),
    handoff_redacted       BOOLEAN NOT NULL DEFAULT FALSE,

    -- Tenant isolation (denormalized from thread for single-table queries)
    tenant_id       VARCHAR(255) NOT NULL DEFAULT 'default',

    metadata        JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX uq_conv_messages_thread_seq ON conversation_messages (thread_id, sequence_number);
CREATE INDEX ix_conv_messages_thread_id         ON conversation_messages (thread_id);
CREATE INDEX ix_conv_messages_tenant_id         ON conversation_messages (tenant_id);
CREATE INDEX ix_conv_messages_actor_id          ON conversation_messages (actor_id) WHERE actor_id IS NOT NULL;
CREATE INDEX ix_conv_messages_tool_call_id      ON conversation_messages (tool_call_id) WHERE tool_call_id IS NOT NULL;
```

Content size threshold for S3 routing: 8 KB. Messages at or below the threshold are stored inline in `content`. Larger messages write to S3 with `storage_type = 's3'` and `content_ref` holding the object key. The object key format is `threads/{tenant_id}/{thread_id}/{sequence_number}`. This is consistent with the S3 decoupling pattern already in the codebase (see `efe1df9`).

`role` values mirror standard LLM message roles. `tool_call` and `tool_result` are stored as discrete messages rather than embedded in an assistant message's content, which enables per-call extraction and per-call audit.

### Relationship to Memory Tree

Threads and messages connect to `memory_nodes` via a dedicated provenance table rather than `memory_relationships`. The `memory_relationships` table (and its `RelationshipType` enum — `derived_from`, `supersedes`, `conflicts_with`, `related_to`) is unchanged; no new enum value is added. A separate table is needed because `memory_relationships` uses UUID FKs to `memory_nodes` on both ends and cannot reference thread/message rows directly.

`conversation_extractions` records the provenance of each extraction event:

```sql
CREATE TABLE conversation_extractions (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    memory_node_id  UUID NOT NULL REFERENCES memory_nodes(id) ON DELETE CASCADE,
    thread_id       UUID NOT NULL REFERENCES conversation_threads(id) ON DELETE RESTRICT,

    -- Which messages contributed to this memory (ordered list of sequence_numbers)
    source_messages INTEGER[] NOT NULL DEFAULT '{}',

    -- Extraction metadata
    extracted_by    VARCHAR(255) NOT NULL,          -- agent/pipeline identity
    extraction_model VARCHAR(255),                  -- LLM model used for extraction, if any
    extraction_prompt_hash VARCHAR(64),             -- SHA-256 of the extraction prompt for auditability

    tenant_id       VARCHAR(255) NOT NULL DEFAULT 'default',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX ix_conv_extractions_memory_node ON conversation_extractions (memory_node_id);
CREATE INDEX ix_conv_extractions_thread_id   ON conversation_extractions (thread_id);
CREATE INDEX ix_conv_extractions_tenant      ON conversation_extractions (tenant_id);
```

This table makes the full chain auditable: given a memory node, find all conversation messages that contributed to it; given a thread, find all memory nodes produced from it. EU AI Act Article 12 compliance requires exactly this linkage.

The existing `branch_type` column on `memory_nodes` does not change. Extraction from conversation adds `extracted_from` records in `conversation_extractions`; it does not require a new `branch_type`.

---

## MCP Tool Surface

Thread operations are exposed as a single `thread(action=...)` tool following the `manage_session(action=...)` / `manage_project(action=...)` pattern. This adds one MCP tool to the server, not seven. The action-dispatch design keeps the tool list compact while giving the async extraction agent granular access to all operations.

All actions inherit MemoryHub's existing authorization flow: `get_claims_from_context()` resolves identity, and scope/tenant checks enforce isolation. Actions that operate on a specific thread verify that the caller's `tenant_id` matches the thread's `tenant_id` before evaluating any other predicate.

### Actions

| Action | Required params | Optional params | Description |
|--------|----------------|-----------------|-------------|
| `create` | scope | scope_id, title, participant_ids, a2a_context_id, metadata | Create a new thread. Retention policy inherited from scope/tenant. |
| `append` | thread_id, role, content | actor_id, tool_call_id, metadata | Append a message. turn number auto-incremented. S3-routed if content > 8 KB. |
| `get` | thread_id | limit (50), before_sequence, include_tool_messages (true) | Retrieve thread metadata + paginated messages. |
| `list` | | scope, scope_id, status (active), participant_id, limit (20), offset | List threads visible to caller. |
| `share` | thread_id, grantee_id, access_level | authorized_by | Grant read or read-write access. |
| `archive` | thread_id | reason | Set status to archived. Immutable thereafter. |
| `fork` | thread_id, from_sequence | title | Create a divergent copy from a fork point. |
| `extract` | thread_id | turn_range, method, model | Trigger extraction pipeline. Async by default. |

### Authorization

- `create` — caller must have write access to the specified scope.
- `append` — caller must be thread owner, listed participant, or hold `threads:write` on the scope. Archived threads reject appends.
- `get` / `list` — caller must match `tenant_id` and be owner, participant, or hold `threads:read` on the scope.
- `share` — caller must be thread owner or hold `threads:admin` on the scope.
- `archive` / `fork` — caller must be thread owner or hold `threads:admin`.
- `extract` — caller must have `threads:read` on the thread.

---

## Memory Extraction Pipeline

### Overview

Extraction is asynchronous by default. The extraction cursor (`extraction_cursor` on `conversation_threads`) tracks which messages have been processed. The pipeline runs after each `append_message` call by enqueuing a background task; it does not block the tool response.

For latency-sensitive use cases, `create_thread` accepts an `extraction_mode: sync` option that makes extraction blocking. The tradeoff (per Mem0 LOCOMO benchmarks: 17 s p95 for full-context vs 1.4 s for extracted facts) should be documented in the tool description so callers make an informed choice.

### Extraction Granularity

The default window is a sliding window of 4 messages (2 full turns), matching Zep's Graphiti architecture. This provides enough context for entity and relationship inference without requiring the full thread history per extraction call.

All three modes ship at launch:

- `per_turn` (default) — extract after each assistant turn. Balances freshness and cost.
- `per_session` — extract once at thread archive or explicit trigger. Lowest cost; delayed availability.
- `per_message` — extract after every append. Highest cost; use only for real-time pipelines.

The mode is configured at thread creation and stored in `retention_policy` JSON.

### Extraction Model Selection

The extraction LLM can differ from the model driving the agent's main conversation. This is configured via environment variables with per-request override support:

- `MH_EXTRACTION_MODEL` — default model for extraction (e.g., `claude-haiku-4-5`). Falls back to the deployment's default LLM if not set.
- `MH_EXTRACTION_MODEL_URL` — endpoint URL if the extraction model is hosted separately from the main LLM.
- The `extract` action accepts an optional `model` parameter for per-request override, allowing callers to use a more capable model for complex extractions.

The extraction prompt is loaded from `prompts/extraction.yaml` and is configurable without a code change.

### Extraction Failure Handling

Failed extraction windows (LLM error, timeout) do not advance `extraction_cursor`. The retry strategy:

1. Immediate retry (once).
2. Exponential backoff: 30s, 60s, 120s.
3. After 3 total failures, the window is written to a `conversation_extraction_failures` log table with the error details.
4. The cursor advances past the failed window to avoid blocking subsequent extractions. The failed window can be manually re-triggered via `extract` with an explicit `turn_range`.

### Pipeline Steps

For each extraction window:

1. Retrieve messages in the window from `conversation_messages`.
2. Fetch any previously extracted memories whose `conversation_extractions` records point to overlapping messages (for conflict checking).
3. Submit the window to the extraction LLM using the standard extraction prompt. The prompt hash (SHA-256) is recorded in `conversation_extractions` for auditability.
4. For each extracted fact, call the existing `write_memory` service path to create or update a `memory_node`. This reuses deduplication, embedding, and conflict detection.
5. Write a `conversation_extractions` record linking `memory_node_id` to `thread_id` and `source_messages`.
6. Advance `extraction_cursor` to the highest processed `sequence_number`.

### Integration with `write_memory`

The extraction pipeline calls `write_memory` with the same parameters an agent would use, plus an additional `extraction_source` field in `metadata_` carrying the `thread_id` and `source_messages`. This preserves backward compatibility with the existing `write_memory` API: callers who don't use conversation threads see no change.

### Provenance Tracking

`conversation_extractions` provides one direction of the audit chain (memory → thread → messages). The reverse direction (thread → memories) is available via a JOIN on `thread_id`. Both directions must be accessible without full table scans; the indexes on `memory_node_id` and `thread_id` cover the common query patterns.

### Conflict Resolution

When extracted content contradicts an existing memory, the pipeline calls the existing `manage_curation(action="report_contradiction", ...)` mechanism. The contradiction report's `metadata_` includes the `thread_id` and `source_messages` of the conflicting evidence, making the source of conflict auditable.

Temporal ordering is the tiebreaker for automatic resolution: the more recent extraction supersedes the older one. Conflicts that cannot be automatically resolved are flagged with `ConflictStatus.pending` and surface through the existing contradiction report query.

---

## Governance Model

### Thread-Level RBAC

Threads inherit the scope model from `memory_nodes` but add participant-level access on top:

- `threads:read` — read messages and metadata
- `threads:write` — append messages
- `threads:admin` — archive, fork, modify participants, change retention

The thread owner always has `threads:admin`. Listed `participant_ids` have `threads:write` by default. Scope-level permissions (e.g., project admins) can override participant-level permissions.

RBAC is enforced in the tool handlers using the same `get_claims_from_context()` path as memory operations. No separate RBAC table is introduced in this iteration; participant grants are stored in the `participant_ids` array plus a `participant_access` JSONB column (map of identity to access level) added to `conversation_threads`.

### Retention Policy Model

Retention is resolved by inheriting from the most specific applicable policy. The most restrictive policy wins at each level.

**Policy resolution order** (first match wins):
1. Thread-level override (if set on the thread itself)
2. Scope-level policy (e.g., "all project-scoped threads in project X")
3. Tenant-level default (configurable via admin API)
4. System default (90 days for user-scoped, 365 days for project-scoped)

New threads inherit their retention policy from their scope at creation time. The resolved policy is stored in the thread's `retention_policy` JSONB column for auditability and offline enforcement:

```json
{
  "ttl_days": 90,
  "cascade_to_memories": "delete",
  "min_retention_days": 30,
  "inherited_from": "scope:project:infrastructure"
}
```

**`cascade_to_memories`** controls what happens to extracted memories when a thread is deleted:
- `delete` (default) — extracted memories are soft-deleted if they have no other provenance source (i.e., `conversation_extractions` count = 1). This is the safest default for data minimization.
- `orphan` — extracted memories survive; their `conversation_extractions` records are soft-deleted so the provenance link is severed but the memory is retained.
- `preserve` — everything kept unchanged. Used under regulatory hold or when memories have independent value.

**`min_retention_days`** sets a floor on how long soft-deleted data must be retained before hard deletion. This supports corporate policies that require deleted data to remain recoverable for a minimum period (e.g., 30 days). The retention sweep will not hard-delete data until `deleted_at + min_retention_days` has passed.

A background retention job (Kubernetes CronJob) runs daily and is idempotent. It handles two phases:
1. **Soft-delete phase:** Find threads where `expires_at <= now() AND status = 'active'`, soft-delete them and cascade per policy.
2. **Hard-delete phase:** Find threads where `deleted_at + min_retention_days <= now() AND status = 'deleted'`, hard-delete rows (unless under legal hold).

### Legal Hold

A `legal_hold` flag on `conversation_threads` (and the tenant-level policy) blocks all deletion operations:

- When a legal hold is active on a thread, soft-delete is allowed but hard-delete is blocked. The thread transitions to `status = 'pending_deletion'` and waits for the hold to be lifted.
- When a legal hold is active at the tenant level, no threads in that tenant can be hard-deleted.
- Lifting a legal hold triggers the retention sweep to process any `pending_deletion` threads.
- Only `threads:admin` or higher can set/clear legal holds.

Legal hold does NOT block spill response (see Deletion Hierarchy below).

### Deletion Hierarchy

Four deletion levels, escalating in severity and authorization requirements:

| Level | Trigger | Respects holds? | Cascade | Audit record | Authorization |
|-------|---------|-----------------|---------|-------------|---------------|
| **Soft delete** | Agent, retention sweep | Yes | Per policy (default: `delete`) | Full audit entry | Thread owner or `threads:admin` |
| **Admin purge** | Operator | Overrides with justification | Hard-deletes thread + messages + extractions + cascade memories | Full audit entry with justification | `memory:admin` |
| **Spill response** | IA staff | Bypasses all holds | Atomic hard-delete: all content, embeddings, S3 objects | Tombstone only (ID + timestamp + actor + incident ref, no content) | `memory:admin:spill` |
| **Silent spill** | IA staff | Bypasses all holds | Same as spill response | No record created | `memory:admin:spill` + `memory:admin:silent` |

Spill response uses the admin hard-delete infrastructure designed in `docs/admin/content-moderation.md`. Thread-level spill response extends that design to cover `conversation_threads`, `conversation_messages`, `conversation_extractions`, and any S3 objects referenced by `content_ref`. All deletions happen in a single transaction.

The tombstone table (`purge_log`) records content-free deletion events:

```sql
CREATE TABLE purge_log (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    resource_type   VARCHAR(50)  NOT NULL,  -- 'thread', 'memory', 'message'
    resource_id     UUID         NOT NULL,
    purged_by       VARCHAR(255) NOT NULL,
    purged_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
    reason          VARCHAR(20)  NOT NULL,  -- 'retention', 'admin', 'gdpr', 'spill'
    incident_ref    VARCHAR(255)            -- external incident tracking ID
);
```

When `leave_tombstone=false` (silent spill), not even this record is created. The data ceases to exist with no forensic trace. This capability exists for classified environments where the existence of deleted data is itself sensitive.

### Thread Status Lifecycle

```
active → archived (immutable, readable, not subject to retention unless purge_archived=true)
active → deleted (soft-deleted, invisible to queries, subject to min_retention_days before hard-delete)
active → pending_deletion (deletion requested but legal hold active; processed when hold lifts)
deleted → (hard-deleted) (after min_retention_days, rows physically removed)
```

---

## Cross-Agent Handoff

### A2A Compatibility

When a conversation originates from an A2A-compatible client, the initiating message carries a `contextId`. `create_thread` accepts `a2a_context_id` and stores it. Subsequent A2A messages referencing the same `contextId` are appended to the matching thread by looking up `a2a_context_id`.

The `historyLength` A2A parameter maps to `get_thread`'s `limit` parameter.

### Governed Handoff

A cross-agent handoff occurs when Agent A writes a message to a thread owned in Agent A's scope and shares the thread with Agent B. The `share_thread` tool records the granting identity (`authorized_by`) in the thread's participant list. The handoff message (the last message Agent A appends before sharing) should carry `role = 'system'` with a structured handoff payload in `metadata`.

The receiving agent (Agent B) uses `get_thread` to load history. What the receiving agent can see is governed by its `access_level`: a `read` grant gives full thread history; a scope-restricted grant (configured in `retention_policy.handoff_redact_patterns`) can suppress messages matching specified patterns before returning them.

`handoff_redacted = TRUE` on a `conversation_message` marks a message as suppressed for the receiving agent. The message row is retained for the sending tenant's audit trail but is excluded from `get_thread` responses for the receiving agent.

---

## Session Identity

### Thread Identity vs. Transport Session

MCP transport sessions (`streamable-http` session IDs allocated by FastMCP) are transport convenience, not persistent identifiers. Issue #86 (landed) established per-conversation session IDs as server-minted UUIDs; issue #104 addresses making these durable across transport reconnections (persisted to Valkey).

Conversation threads are a layer above transport sessions. A single transport reconnection should not create a new thread. The mapping is:

```
MCP transport session  →  ephemeral (lifetime of one HTTP connection)
Application session    →  durable across reconnections (issue #86, landed; #104 for Valkey persistence)
Conversation thread    →  durable across sessions (this feature)
```

Agents using the MemoryHub MCP server should maintain the `thread_id` across reconnections and pass it to `append_message` after re-establishing their application session via `register_session`. The SDK will expose a `resume_thread(thread_id)` helper that combines `register_session` and initial `get_thread` in one call.

The `thread_id` is durable across MCP pod restarts. The Valkey-backed application session store described in [`planning/session-persistence.md`](https://github.com/redhat-ai-americas/memory-hub-scratchpad/blob/main/planning/session-persistence.md) (Fork A) makes `register_session` state persistent across pod restarts; `thread_id` as a database identity in PostgreSQL is unaffected by pod lifecycle. If the MCP pod restarts mid-extraction, the in-flight extraction task is lost but not unrecoverable: the `extraction_cursor` on `conversation_threads` records the last committed sequence number, so a restarted pod (or a re-queued background task) resumes from that point rather than reprocessing the full thread. No messages are extracted twice and no extraction window is permanently skipped.

### Relationship to Issue #86

Issue #86 (landed) established per-conversation session IDs as server-minted UUIDs, decoupling session identity from user identity (JWT sub claim). `thread_id` is the stable application-level identity (a database row that survives reconnections, pod restarts, and agent handoffs); the session_id from #86 is the per-connection identifier that ties a client to its push subscriber and broadcast exclusion. When #104 lands (Valkey persistence for session state), session_id will survive transport reconnections. The application session will carry a `thread_id` so agents need not track it client-side.

---

## Storage

### PostgreSQL

All thread metadata (`conversation_threads`) and messages up to 8 KB (`conversation_messages` with `storage_type = 'inline'`) live in PostgreSQL. This keeps transactional integrity, enables simple JOIN-based provenance queries, and avoids the S3 availability dependency for the common case.

### S3 for Large Payloads

Messages exceeding 8 KB use S3 with the object key pattern `threads/{tenant_id}/{thread_id}/{sequence_number}`. The `content_ref` column stores the key. Retrieval in `get_thread` fetches inline messages from PostgreSQL and S3 messages from MinIO in parallel, returning them merged in sequence order.

The 8 KB threshold is configurable via an environment variable `MH_CONV_INLINE_MAX_BYTES`. The S3 integration follows the pattern established in the storage decoupling work (commit `9ad20ba`): S3 unavailability causes writes to fail with a structured error rather than silently downgrading to inline; callers see an explicit storage error.

### Interaction with Context Compaction (#169)

Issue #169 (dual-track storage for context compaction) stores compacted conversation summaries. The design here and #169 share `conversation_threads` as the anchor: a compaction run reads messages up to the compaction cursor, writes a summary `conversation_message` with `role = 'system'` and `metadata.compaction = true`, and advances the thread's compaction cursor. The original messages are not deleted; they remain available for audit. This is distinct from extraction: compaction reduces the thread's active context window; extraction produces memory nodes.

---

## Migration

Migration `020_add_conversation_threads.py` creates four tables in order:

1. `conversation_threads` — no FK dependencies outside this feature
2. `conversation_messages` — FK to `conversation_threads`
3. `conversation_extractions` — FK to `memory_nodes` and `conversation_threads`
4. `purge_log` — no FK dependencies (content-free deletion audit trail)

All four tables are created in a single migration to keep the schema consistent. The migration is reversible: `downgrade()` drops the tables in reverse order.

No changes to existing tables. No backfill is required: existing memory nodes have no conversation provenance, and their `conversation_extractions` count is zero by definition.

After `020`, the `RelationshipType` enum in `schemas.py` does not need a new value. The extraction provenance link is stored in `conversation_extractions`, not in `memory_relationships`. This keeps `memory_relationships` clean and avoids the problem of FK constraints on `memory_relationships` pointing at a non-`memory_nodes` target.

Note: `purge_log` is placed in the conversation-threads migration for convenience but is a general-purpose table that also covers memory node purges. It has no FK dependencies on any other table by design (the referenced resources have been deleted by the time the log entry is written).

---

## Dependencies

This feature depends on:
- PostgreSQL + pgvector (existing)
- MinIO/S3 (existing, used for large message payloads)
- The S3 decoupling completed in `9ad20ba`/`efe1df9` (structured error path on S3 unavailability)
- Issue #86 (per-conversation session ID — landed) for clean client-side thread identity
- Issue #65 (actor_id/driver_id columns — landed) for identity model on thread and message entities

Features that depend on this:
- Issue #169 (context compaction) references `conversation_threads` as the anchor for compaction cursors
- EU AI Act audit trail reporting — any compliance reporting tooling will query `conversation_extractions` for provenance

---

## Resolved Decisions

**Extraction LLM selection.** Resolved: configurable via `MH_EXTRACTION_MODEL` and `MH_EXTRACTION_MODEL_URL` environment variables. Per-request override via the `extract` action's `model` parameter. Default prompt in `prompts/extraction.yaml`.

**Retention policy inheritance.** Resolved: scope-level inheritance. New threads inherit retention policy from their scope at creation time. Resolution order: thread override > scope policy > tenant default > system default.

**Extraction modes.** Resolved: all three modes (`per_turn`, `per_session`, `per_message`) ship at launch.

**Cascade default.** Resolved: `delete` (soft-delete extracted memories if no other provenance source). Configurable per policy.

**Extraction failure handling.** Resolved: exponential backoff (30s, 60s, 120s), max 3 retries. Failed windows logged to `conversation_extraction_failures` table. Cursor advances past failed window; manual re-trigger via `extract` with explicit `turn_range`.

**Hard deletion.** Resolved: four-level deletion hierarchy (soft delete, admin purge, spill response, silent spill). Extends existing `docs/admin/content-moderation.md` design. Tombstone table (`purge_log`) for audit. Silent spill leaves no forensic trace for classified environments.

## Open Questions

**Thread search.** Deferred to a separate issue. `list_threads` supports metadata filtering but not full-text or semantic search over message content. Adding message-level embeddings would enable semantic thread retrieval but doubles per-message storage cost. Will be refined separately.

**Participant access JSONB schema.** The `participant_access` column is described informally. Before implementation, define the schema explicitly (e.g., `{"agent-id-1": "read", "user-id-2": "write"}`) and add a CHECK constraint validating that all values are in `{'read', 'write', 'admin'}`.
