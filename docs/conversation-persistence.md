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
    tenant_id       VARCHAR(255) NOT NULL DEFAULT 'default',

    -- Participants (agent and user identities present in this thread)
    participant_ids TEXT[]       NOT NULL DEFAULT '{}',

    -- Lifecycle
    status          VARCHAR(20)  NOT NULL DEFAULT 'active',   -- active | archived | deleted
    archived_at     TIMESTAMPTZ,
    deleted_at      TIMESTAMPTZ,
    expires_at      TIMESTAMPTZ,                    -- NULL = no retention expiry set

    -- Retention policy reference (FK to retention_policies if/when that table exists; JSON inline for now)
    retention_policy JSONB,

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

Threads and messages connect to `memory_nodes` via `memory_relationships` using a new relationship type: `extracted_from`. This is a directed edge pointing from the memory node (source) to the conversation message or thread that produced it (target). Because `memory_relationships` already uses UUID FKs to `memory_nodes`, a new table is needed to represent the thread/message side of extraction provenance.

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

## MCP Tools

All tools inherit MemoryHub's existing authorization flow: `get_claims_from_context()` resolves identity, and scope/tenant checks enforce isolation. Tools that operate on a specific thread verify that the caller's `tenant_id` matches the thread's `tenant_id` before evaluating any other predicate.

### `create_thread`

Create a new conversation thread.

Input:
- `scope` (required) — one of the `MemoryScope` values
- `scope_id` (optional) — project or role identifier for project/role-scoped threads
- `title` (optional) — human-readable label
- `participant_ids` (optional, list) — additional agent/user identities sharing this thread
- `a2a_context_id` (optional) — A2A contextId to associate with this thread
- `retention_days` (optional) — thread expires after N days; NULL means no automatic expiry
- `metadata` (optional) — arbitrary key-value pairs

Output: thread ID, created timestamp.

Authorization: caller must have write access to the specified scope. Tenant is inferred from the caller's JWT/session claims; caller cannot specify a different tenant.

### `append_message`

Append one message to an existing thread.

Input:
- `thread_id` (required)
- `role` (required) — `user | assistant | tool_call | tool_result | system`
- `content` (required) — message body; the server routes to S3 if content exceeds 8 KB
- `actor_id` (optional) — identity of the producing agent or user
- `tool_call_id` (optional) — correlates `tool_call` and `tool_result` pairs
- `metadata` (optional)

Output: message ID, sequence number, storage type.

Authorization: caller must be the thread owner, a listed participant, or have the `threads:write` RBAC permission on the thread's scope. A `status = 'archived'` thread rejects appends.

### `get_thread`

Retrieve thread metadata and a window of messages.

Input:
- `thread_id` (required)
- `limit` (optional, default 50) — number of messages to return
- `before_sequence` (optional) — return messages with sequence_number < N (pagination)
- `include_tool_messages` (optional, default true) — omit `tool_call`/`tool_result` for summarized views

Output: thread metadata, messages list (in sequence order), has_more flag.

Authorization: caller must match `tenant_id` and must be the thread owner, a participant, or have `threads:read` on the scope.

### `list_threads`

List threads visible to the caller.

Input:
- `scope` (optional) — filter by scope
- `scope_id` (optional) — filter by project or role
- `status` (optional, default `active`) — `active | archived | all`
- `participant_id` (optional) — filter to threads where this identity is a participant
- `limit` (optional, default 20, max 100)
- `offset` (optional)

Output: list of thread summaries (id, title, scope, status, message count, last message timestamp, extraction cursor).

Authorization: returns only threads matching the caller's `tenant_id`. Cross-scope visibility follows the caller's RBAC permissions.

### `share_thread`

Grant another agent or user read (or read-write) access to a thread.

Input:
- `thread_id` (required)
- `grantee_id` (required) — identity to grant access to
- `access_level` (required) — `read | write`
- `authorized_by` (optional) — identity authorizing the grant; defaults to the caller

Output: updated participant list.

Authorization: caller must be the thread owner or have `threads:admin` on the scope.

### `archive_thread`

Move a thread to `archived` status. Archived threads are readable but immutable.

Input:
- `thread_id` (required)
- `reason` (optional)

Output: thread ID, archived_at timestamp.

Authorization: caller must be the thread owner or have `threads:admin` on the scope. Archive is reversible only by a caller with `threads:admin`.

### `fork_thread`

Create a divergent copy of a thread starting from a specific sequence number.

Input:
- `thread_id` (required) — source thread
- `from_sequence` (required) — fork point; the new thread includes messages with sequence_number <= N
- `title` (optional) — title for the forked thread

Output: new thread ID, message count copied.

Authorization: caller must have `threads:read` on the source thread. The fork inherits the source thread's `scope` and `tenant_id`. The caller becomes the owner of the fork.

---

## Memory Extraction Pipeline

### Overview

Extraction is asynchronous by default. The extraction cursor (`extraction_cursor` on `conversation_threads`) tracks which messages have been processed. The pipeline runs after each `append_message` call by enqueuing a background task; it does not block the tool response.

For latency-sensitive use cases, `create_thread` accepts an `extraction_mode: sync` option that makes extraction blocking. The tradeoff (per Mem0 LOCOMO benchmarks: 17 s p95 for full-context vs 1.4 s for extracted facts) should be documented in the tool description so callers make an informed choice.

### Extraction Granularity

The default window is a sliding window of 4 messages (2 full turns), matching Zep's Graphiti architecture. This provides enough context for entity and relationship inference without requiring the full thread history per extraction call.

Three modes are supported:

- `per_turn` (default) — extract after each assistant turn. Balances freshness and cost.
- `per_session` — extract once at thread archive or explicit trigger. Lowest cost; delayed availability.
- `per_message` — extract after every append. Highest cost; use only for real-time pipelines.

The mode is configured at thread creation and stored in `retention_policy` JSON.

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

When extracted content contradicts an existing memory, the pipeline calls the existing `report_contradiction` mechanism. The contradiction report's `metadata_` includes the `thread_id` and `source_messages` of the conflicting evidence, making the source of conflict auditable.

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

### Retention Policies

Each thread's `retention_policy` JSONB column stores the policy that governs it:

```json
{
  "ttl_days": 90,
  "archive_on_expiry": false,
  "cascade_to_memories": "keep"
}
```

`cascade_to_memories` controls what happens to extracted memories when a thread expires:
- `keep` (default) — extracted memories survive; their `conversation_extractions` records are soft-deleted so the provenance link is no longer queryable but the memory is not affected
- `anonymize` — extracted memories survive; their `conversation_extractions` records are deleted and the memories' `owner_id` is replaced with a sentinel value indicating the source is no longer available
- `delete` — extracted memories are also soft-deleted if they have no other provenance source (i.e., `conversation_extractions` count = 1)

A background retention job runs daily. It queries `conversation_threads WHERE expires_at <= now() AND status = 'active'` and applies the policy. The job is idempotent: processing an already-expired thread is a no-op.

### Archive vs. Delete Semantics

`archived` threads are immutable and readable. They are not subject to retention-based deletion unless the policy explicitly sets `purge_archived: true`. Archive is the appropriate disposition for completed conversations that must remain available for audit.

`deleted` (soft-deleted) threads set `deleted_at` and `status = 'deleted'`. All tool queries filter these out. Hard deletion (removing rows) is performed only by the GDPR right-to-erasure process, which requires an operator-level invocation.

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

MCP transport sessions (`streamable-http` session IDs allocated by FastMCP) are transport convenience, not persistent identifiers. Issue #86 addresses making the application-level session ID durable across transport reconnections (persisted to Valkey).

Conversation threads are a layer above transport sessions. A single transport reconnection should not create a new thread. The mapping is:

```
MCP transport session  →  ephemeral (lifetime of one HTTP connection)
Application session    →  durable across reconnections (issue #86)
Conversation thread    →  durable across sessions (this feature)
```

Agents using the MemoryHub MCP server should maintain the `thread_id` across reconnections and pass it to `append_message` after re-establishing their application session via `register_session`. The SDK will expose a `resume_thread(thread_id)` helper that combines `register_session` and initial `get_thread` in one call.

### Relationship to Issue #86

Issue #86's per-conversation session ID maps to `conversation_threads.id`. When #86 lands, the application session will carry a `thread_id` claim that survives transport reconnections. Until #86 ships, the `thread_id` must be tracked client-side.

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

Migration `013_add_conversation_threads.py` creates three tables in order:

1. `conversation_threads` — no FK dependencies outside this feature
2. `conversation_messages` — FK to `conversation_threads`
3. `conversation_extractions` — FK to `memory_nodes` and `conversation_threads`

All three tables are created in a single migration to keep the schema consistent. The migration is reversible: `downgrade()` drops the tables in reverse order.

No changes to existing tables. No backfill is required: existing memory nodes have no conversation provenance, and their `conversation_extractions` count is zero by definition.

After `013`, the `RelationshipType` enum in `schemas.py` does not need a new value. The extraction provenance link is stored in `conversation_extractions`, not in `memory_relationships`. This keeps `memory_relationships` clean and avoids the problem of FK constraints on `memory_relationships` pointing at a non-`memory_nodes` target.

---

## Dependencies

This feature depends on:
- PostgreSQL + pgvector (existing)
- MinIO/S3 (existing, used for large message payloads)
- The S3 decoupling completed in `9ad20ba`/`efe1df9` (structured error path on S3 unavailability)
- Issue #86 (per-conversation session ID) for clean client-side thread identity — this feature can ship before #86, but the SDK `resume_thread` helper requires #86 to be self-contained

Features that depend on this:
- Issue #169 (context compaction) references `conversation_threads` as the anchor for compaction cursors
- Kagenti Phase 3 (`MemoryHubContextStore`) will use `create_thread` + `append_message` as the persistence backend, replacing the planned `memory_node` branch approach documented in `planning/kagenti-integration/architecture.md`
- EU AI Act audit trail reporting — any compliance reporting tooling will query `conversation_extractions` for provenance

---

## Open Questions

**Extraction LLM selection.** The extraction pipeline needs an LLM to identify discrete facts from a message window. Which model and prompt are used is a deployment concern, not a schema concern, but the pipeline must be configurable without a code change. Resolution: make the model and prompt path configurable via environment variables; provide a default prompt in `prompts/extraction.yaml`.

**Retention policy inheritance.** Should scope-level retention policies (e.g., "all project-scoped threads in project X expire after 180 days") propagate automatically to new threads in that scope, or must each thread specify its own policy? Automatic inheritance is more correct but requires a policy resolution layer. Manual specification is simpler but creates admin burden. Recommendation: start with manual per-thread specification and add scope-level inheritance as a follow-on.

**Thread search.** `list_threads` supports metadata filtering but not full-text or semantic search over message content. Adding message-level embeddings (similar to `memory_nodes.embedding`) would enable semantic thread retrieval but doubles the per-message storage cost. Defer until there is a demonstrated use case.

**Hard deletion and GDPR right to erasure.** Soft deletion is specified; hard deletion is described as an operator process. The exact API surface for right-to-erasure requests (which tables, in what order, with what audit record of the deletion itself) is not specified here. This should be a follow-on issue.

**Participant access JSONB schema.** The `participant_access` column is described informally. Before implementation, define the schema explicitly (e.g., `{"agent-id-1": "read", "user-id-2": "write"}`) and add a CHECK constraint validating that all values are in `{'read', 'write', 'admin'}`.

**Extraction failure handling.** If extraction fails for a window (LLM error, timeout), the `extraction_cursor` must not advance. The retry strategy (immediate, exponential backoff, dead-letter) is unspecified. Recommendation: use a background task queue with exponential backoff; failed windows are retried up to 3 times before being written to a `conversation_extraction_failures` log table.
