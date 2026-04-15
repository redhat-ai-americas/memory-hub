# Tools Plan

## Overview

MemoryHub MCP server provides 6 tools for AI agents to read, write, search, and manage memories in a centralized, governed memory system. Agents connect via streamable-http MCP transport. Every operation flows through a governance layer for access control and audit logging.

The tools are designed around the tree-based memory model: memories are nodes with optional branches (rationale, provenance, etc.), weighted for injection priority, versioned for forensics, and embedded for semantic search.

## Design Principles Applied

**Fewer, powerful tools.** We dropped the speculative get_context and get_branches tools. 6 tools cover the full agent workflow: write → search → read → update → history → report contradictions. `read_memory` returns a `branch_count` summary; agents fetch specific branches via `search_memory` or follow-up `read_memory` calls rather than via a `depth` parameter.

**Tool descriptions as steering mechanisms.** Each tool description explains the tree model concepts (stubs, branches, weight) so agents understand how to use MemoryHub effectively. An agent that's never seen MemoryHub before should be able to use it correctly from the descriptions alone.

**Composable, not monolithic.** Rather than a single "get me everything relevant" tool, agents compose search_memory (find relevant memories) + read_memory (expand interesting ones, with optional paginated version history). This gives agents control over their context budget.

**Actionable errors.** Every error tells the agent what went wrong AND what to do about it. "Write to organizational scope requires curator approval — memory has been queued for review" not just "403 Forbidden".

**Weight-aware responses.** search_memory returns a mix of full content (high-weight matches) and stubs (lower-weight matches). Agents see stubs with indicators like "rationale available" and decide whether to expand, keeping context lean.

## Error Handling Contract

All 15 tools raise `fastmcp.exceptions.ToolError` for every failure. No tool returns `{"error": True}` dicts — errors always set `is_error` on the MCP wire so the consuming agent's harness knows the call failed.

The SDK classifies `ToolError` messages into typed exceptions by prefix:

| Category | Message prefix patterns | SDK exception |
|---|---|---|
| Not found | "Memory \<uuid\> not found" / "... not found." | `NotFoundError` |
| Not authorized | "Not authorized to" / "Access denied:" | `PermissionDeniedError` |
| Invalid parameter | "Invalid " / "... must be" / "... cannot be empty" | `ValidationError` |
| Authentication | "Invalid API key" / "No authenticated session" | `AuthenticationError` |
| Conflict | "... already exists" / "... already deleted" | `ConflictError` |
| Curation veto | "Curation rule blocked" | `CurationVetoError` |
| Generic | anything else | `ToolError` |

Generic `except Exception` handlers log at ERROR level and scrub internal details before raising `ToolError`. Tool authors must include an `except ToolError: raise` guard before the generic handler to avoid double-wrapping expected errors.

Full design note: `planning/tool-error-standardization.md`

## Tools

### register_session

- **Purpose**: Authenticate the session with an API key. Call this once at the start of every conversation to establish identity. After registration, `write_memory` and `search_memory` default to the authenticated `user_id`. Also wires the session into the #62 Pattern E push pipeline so the client receives broadcast notifications without polling. When the server is deployed behind a JWT-issuing auth server, session registration is a no-op: the JWT's `sub` claim is used directly.
- **Parameters**:
  - `api_key` (string, required): Your MemoryHub API key. Format: `mh-dev-<username>-<year>`.
- **Returns**: The authenticated identity with `user_id`, `name`, accessible `scopes`, and a confirmation message. If push subscriber wiring fails, the response still succeeds with a non-fatal warning.
- **Error Cases**:
  - "Invalid API key. Contact your system administrator for a valid key. Keys follow the format: mh-dev-\<username\>-\<year\>." — The API key is not recognized. → SDK: `AuthenticationError`
- **Example Usage**:
  ```
  register_session(api_key="mh-dev-wjackson-2026")
  ```

### write_memory

- **Purpose**: Create a new memory node or a branch on an existing memory. This is how agents record preferences, facts, project context, rationale, and other knowledge. For user-scope memories, the write happens immediately. For scopes above user level (organizational, enterprise), the write is queued for curator review.
- **Parameters**:
  - `content` (string, required): The memory text. Should be clear and self-contained — another agent should understand it without additional context. Keep concise; detailed context belongs in branches.
  - `scope` (string, required): One of: user, project, role, organizational, enterprise. Determines access control and governance rules. Most agent-created memories are "user" scope.
  - `owner_id` (string, required): The user, project, or org this memory belongs to. For user-scope, this is the user ID. For project-scope, the project identifier.
  - `weight` (float, optional, default 0.7): Injection priority from 0.0 to 1.0. High-weight memories (0.8-1.0) get full content injected into agent context. Lower weights produce stubs. Enterprise policies should be 1.0. Casual preferences are fine at 0.5-0.7.
  - `parent_id` (string/UUID, optional): If creating a branch (rationale, provenance, etc.), the ID of the parent memory node. Omit for root-level memories.
  - `branch_type` (string, optional): Required when parent_id is set. Common types: "rationale" (why this memory exists), "provenance" (where it came from), "description" (elaboration), "evidence" (supporting data), "approval" (who approved it). Free-form string — use descriptive types.
  - `metadata` (object, optional): Arbitrary key-value pairs for extensibility. Use for tags, source references, tool context, etc.
- **Returns**: The created memory node with its generated ID, stub text, and timestamp. If the write was queued (above user scope), returns a status indicating "queued_for_review" with the queue position.
- **Error Cases**:
  - "Access denied: you cannot write to [scope] scope. Your identity allows writes to: [list of allowed scopes]." — Agent tried to write to a scope it doesn't have permission for. → SDK: `PermissionDeniedError`
  - "Parent memory [id] not found. Check the parent_id — it may have been deleted or you may not have access to it." — Invalid parent_id for branch creation. → SDK: `NotFoundError`
  - "branch_type is required when parent_id is set. Common types: rationale, provenance, description, evidence." — Missing branch_type on a branch write. → SDK: `ValidationError`
  - "Content flagged by security scan: [reason]. The memory was not stored. Remove sensitive content and retry." — Secrets/PII detected in content. → SDK: `CurationVetoError`
  - "No authenticated session. Call register_session first." — No auth context available for the write. → SDK: `AuthenticationError`
  - "Curation rule blocked: [reason]." — A user or system curation rule rejected the content. → SDK: `CurationVetoError`
- **Example Usage**: An agent recording a user preference:
  ```
  write_memory(content="prefers Podman over Docker for container builds", scope="user", owner_id="wjackson", weight=0.9)
  ```
  Adding rationale to that preference:
  ```
  write_memory(content="works for Red Hat where Podman is the standard runtime", scope="user", owner_id="wjackson", parent_id="<id from above>", branch_type="rationale")
  ```

### read_memory

- **Purpose**: Retrieve a specific memory by ID. Returns the node with a `branch_count` summary of its direct children; branch contents are not loaded inline. Agents that want to inspect specific branches issue follow-up `search_memory` or `read_memory` calls. When a historical (non-current) version is requested, the response carries a `current_version_id` pointer so the caller can pivot to the live version in one round-trip.
- **Parameters**:
  - `memory_id` (string/UUID, required): The ID of the memory to read.
  - `include_versions` (boolean, optional, default false): If true, includes the full version history (paginated) alongside the current content. Useful when an agent needs to understand how a memory evolved.
- **Returns**: The memory node with full content, metadata, version info, and:
  - `branch_count` (integer): Number of direct child branches under this node. Computed via a single COUNT query — branch rows are not fetched.
  - `has_children` / `has_rationale` (booleans): Convenience flags for the common "are there branches" / "is there a rationale branch" checks.
  - `current_version_id` (string/UUID or null): When `is_current` is false, points at the live version of this memory's chain. Null when the requested node is itself current. Lets agents pivot to the current version in one extra `read_memory` call.
  - When `include_versions=true`, an additional `version_history` object: `{versions, total_versions, has_more, offset}` matching the `get_memory_history` shape.
- **Error Cases**:
  - "Memory [id] not found. It may have been deleted, or you may not have access to this memory's scope." — Memory doesn't exist or is inaccessible. → SDK: `NotFoundError`
  - "Not authorized to read memory [id]." — Caller is authenticated but doesn't have read access to this memory's scope. → SDK: `PermissionDeniedError`

  Historical reads do **not** error: they return the historical row plus a `current_version_id` pointer (see #51). Earlier spec drafts described an "is not current — returning the current version instead" warning; that design was replaced with the pointer field so agents can choose whether to follow the link.
- **Example Usage**: Reading a memory and discovering it's superseded:
  ```
  read_memory(memory_id="abc-123")
  ```
  Returns the v1 row with `is_current=false`, `current_version_id="def-456"`. The agent reads `def-456` if it wants the live content.

### update_memory

- **Purpose**: Create a new version of an existing memory. The old version is preserved with isCurrent=false; the new version becomes current. This is how memories evolve over time while maintaining full history for forensics. Use this when a preference changes, information is corrected, or a memory needs refinement.
- **Parameters**:
  - `memory_id` (string/UUID, required): The ID of the current memory to update. Must be a current (isCurrent=true) memory.
  - `content` (string, optional): New content text. If omitted, content stays the same (useful for weight-only updates).
  - `weight` (float, optional): New weight. If omitted, inherits from the previous version.
  - `metadata` (object, optional): New metadata. Merged with existing metadata (not replaced).
- **Returns**: The new version of the memory with its new ID, version number, and the previous_version_id linking back to the old version. The old version's isCurrent is now false.
- **Error Cases**:
  - "Memory [id] is not the current version. The current version is [current_id] (version [N]). Update that instead." — Agent tried to update a superseded version. → SDK: `ConflictError`
  - "Access denied: only the memory owner can update user-scope memories. This memory belongs to [owner]." — Attribution protection: can't edit someone else's memories. → SDK: `PermissionDeniedError`
  - "No changes provided. Include at least one of: content, weight, metadata." — Empty update. → SDK: `ValidationError`
- **Example Usage**: Updating a preference:
  ```
  update_memory(memory_id="abc-123", content="prefers Rust for systems work, Python for scripting and ML")
  ```

### search_memory

- **Purpose**: Semantic search across all memories the agent has access to. This is the primary discovery mechanism — agents don't need to know memory IDs upfront. The query is embedded via pgvector and compared against stored memory embeddings. Results are a mix of full content (for high-weight matches) and stubs (for lower-weight matches), keeping the response token-efficient. The response shape is tunable via three sizing controls: `mode`, `max_response_tokens`, and `include_branches` (see below).
- **Parameters**:
  - `query` (string, required): Natural language search query. Be specific — "container runtime preferences" works better than "containers". The query is embedded and compared via cosine similarity.
  - `scope` (string, optional): Filter to a specific scope (user, project, role, organizational, enterprise). Omit to search all accessible scopes.
  - `owner_id` (string, optional): Filter to a specific owner's memories. Useful for searching within a particular user's or project's context.
  - `max_results` (integer, optional, default 10): Maximum number of results to return. Results are ranked by relevance. Keep low (5-15) to avoid context bloat. Branch handling may reduce the page below this value when `include_branches=false` (the default).
  - `weight_threshold` (float, optional, default 0.0): Memories with weight below this value return as stubs instead of full content. Set to 0.8 to stub low-priority matches. Ignored when `mode='full_only'`.
  - `current_only` (boolean, optional, default true): If true, only returns current versions. Set to false for forensic searches across all versions.
  - `mode` (string, optional, default `"full"`): Result detail mode. Issue #57.
    - `"full"` — current behavior. Full content for `weight >= weight_threshold`, stubs below.
    - `"index"` — stubs everything regardless of weight. Use for exploratory "what's in here?" or audit/cleanup workflows when topic-level coverage matters more than content depth.
    - `"full_only"` — never stubs, ignoring `weight_threshold`. Use for specific-question answering when zero round-trips matters.
  - `max_response_tokens` (integer, optional, default 4000, range 100-20000): Soft cap on the response payload. Results are packed in similarity order; once the running cost exceeds the cap, the offending entry and every subsequent entry are degraded to stub form. Stubs are always included even past the cap so the agent never silently misses a ranked match. Issue #57.
  - `include_branches` (boolean, optional, default false): Branch handling. Issue #56.
    - `false` (default) — branches (rationale, provenance, etc.) whose parent is also in the result set are dropped from the page. The agent uses the parent's `has_rationale` / `has_children` flags to drill in via `read_memory`.
    - `true` — branches whose parent is in the result set are returned nested under the parent in a `branches` field rather than ranked as siblings. Forensic and audit workflows that want full depth use this.
    - Branches whose parent is **not** in the result set are always returned as top-level entries with `parent_id` populated regardless of this flag.
- **Returns**: An object with three top-level fields:
  - `results`: Array ranked by relevance. Each entry includes:
    - For high-weight memories (weight >= `weight_threshold`): full content, scope, weight, branch indicators
    - For lower-weight memories or budget-degraded entries: stub text, scope, weight, branch indicators (`has_rationale`, `has_children`), `parent_id`
    - A `result_type` field (`"full"` or `"stub"`) so the agent knows what it's looking at
    - A `relevance_score` (0-1) from the vector similarity search
    - When `include_branches=true`: an optional `branches` list of nested branch entries (each with the same shape as a top-level entry, including `result_type` and `relevance_score`)
  - `total_matching` (integer): Count of all memories matching the filter set (scope/owner/current_only/RBAC), independent of `max_results` and of the branch-omission rule. Useful for "showing N of M" displays and for deciding whether to broaden the query.
  - `has_more` (boolean): True when `total_matching > len(results)`. Indicates that narrowing filters or paginating would reveal additional matches.

  Earlier spec drafts described a single `total_accessible` field that conflated "page size" and "total matches"; that field was replaced with the unambiguous `total_matching` + `has_more` pair (see #53).
- **Error Cases**:
  - "No memories found matching your query. Try broader search terms or remove scope/owner filters." — Not an error; returns empty results with guidance. The tool succeeds with an empty result set.
  - "Invalid scope filter: [value]. Valid scopes: user, project, role, organizational, enterprise." — Bad scope parameter. → SDK: `ValidationError`
- **Example Usage**: Finding relevant context for a container build task:
  ```
  search_memory(query="container runtime preferences and build requirements", scope="user", owner_id="wjackson", max_results=5)
  ```
  Returns: "prefers Podman" (full, weight 0.9, has_rationale=true), "current project: memory-hub" (stub, weight 0.8), etc. By default the rationale branch is omitted; the agent calls `read_memory` to expand it on demand.

  Exploring an unfamiliar memory store with cheap topic coverage:
  ```
  search_memory(query="anything project-related", mode="index", max_results=30)
  ```
  Returns 30 stubs regardless of weight — useful for getting your bearings before drilling into specifics.

  Forensic walk that needs every branch nested under its parent:
  ```
  search_memory(query="auth decisions", include_branches=true, max_response_tokens=8000)
  ```

### get_memory_history (CONSOLIDATED into read_memory — #174)

> **Removed.** Version history is now accessed via `read_memory(include_versions=True, history_offset=..., history_max_versions=...)`. The pagination params are forwarded to the same service-layer function.

- **Original purpose**: Retrieve the full version history of a specific memory with pagination.
- **Migration**: `get_memory_history(memory_id="abc-123", offset=0, max_versions=20)` → `read_memory(memory_id="abc-123", include_versions=True, history_offset=0, history_max_versions=20)`

### report_contradiction

- **Purpose**: Signal that observed behavior contradicts a stored memory. This feeds the staleness detection system. When an agent notices the user doing something that conflicts with a stored preference (e.g., using Docker when the memory says "prefers Podman"), it reports the contradiction. The curator agent aggregates these signals and may trigger a memory revision prompt.
- **Parameters**:
  - `memory_id` (string/UUID, required): The memory that appears to be contradicted.
  - `observed_behavior` (string, required): Description of what was observed that conflicts with the memory. Be specific: "User created a Docker Compose project with 12 services" not just "used Docker".
  - `confidence` (float, optional, default 0.7): How confident the agent is that this is a real contradiction (0.0-1.0). Temporary exceptions (e.g., using Docker for a specific client requirement) warrant lower confidence. Repeated, consistent contradictions warrant higher.
- **Returns**: Acknowledgment with the current contradiction count for this memory. If enough contradictions have accumulated, indicates that a revision prompt will be triggered: "Contradiction recorded (3 of 5 threshold). The user will be prompted to review this memory."
- **Error Cases**:
  - "Memory [id] not found." — Invalid memory ID. → SDK: `NotFoundError`
  - "Memory [id] is not current. Contradictions can only be reported against current memories." — Can't contradict a superseded version. → SDK: `ValidationError`
- **Example Usage**:
  ```
  report_contradiction(memory_id="abc-123", observed_behavior="User ran 'docker build' and created a docker-compose.yml in the last 3 projects", confidence=0.8)
  ```

---

## Phase 2 Tools: Graph Relationships & Curation

Phase 2 adds 5 tools covering two capabilities: graph relationships between memories (provenance, supersession, conflict) and curation self-service (similarity inspection, merge suggestions, rule tuning).

### Design Principles for Phase 2

**Token-efficient similarity feedback.** write_memory already returns `similar_count` — a count, not a payload. The agent decides whether to investigate. `get_similar_memories` provides paged drill-down so agents control their context budget. This follows Anthropic's guidance to implement pagination and sensible defaults rather than returning massive datasets.

**Graph tools expose the relationship model, not raw queries.** Rather than a generic "run graph query" tool, we expose specific workflows: create a typed edge, query edges for a node, trace provenance. The relationship_type enum (`derived_from`, `supersedes`, `conflicts_with`, `related_to`) constrains the agent to valid edge types — reducing hallucination risk per Anthropic's guidance on semantic names over freeform strings.

**Curation tools let agents self-manage.** Rather than relying on a background curator for everything, agents can tune their own dedup thresholds via `set_curation_rule` and suggest merges via `create_relationship` (with `conflicts_with` type and merge metadata). This follows the "context-aware tools" principle — tools that consolidate what would otherwise require multiple steps.

### create_relationship

- **Purpose**: Create a directed edge between two memory nodes. Use this to link memories that are semantically connected — marking that an organizational memory was `derived_from` several user memories, that one memory `supersedes` another, that two memories `conflicts_with` each other, or that they are `related_to` one another. Relationships are immutable — create or delete them, never update.
- **Parameters**:
  - `source_id` (string/UUID, required): UUID of the source memory node — the "from" end of the directed edge.
  - `target_id` (string/UUID, required): UUID of the target memory node — the "to" end. Must differ from source_id.
  - `relationship_type` (string, required): One of: `derived_from` (provenance — source was derived from target), `supersedes` (source replaces target), `conflicts_with` (semantic conflict between source and target), `related_to` (general association).
  - `metadata` (object, optional): Key-value context about the relationship — reasoning, confidence, curator notes.
- **Returns**: The created relationship with its UUID, timestamps, `created_by` identity, and stub text from both the source and target nodes for context.
- **Error Cases**:
  - "Memory node [id] not found. Verify both source_id and target_id refer to existing, current memory nodes." — One or both nodes missing. → SDK: `NotFoundError`
  - "Relationship ([source] --[type]--> [target]) already exists." — Duplicate edge. The agent should use the existing relationship. → SDK: `ConflictError`
  - "source_id and target_id must be different — self-referential edges are not allowed." → SDK: `ValidationError`
  - "Invalid relationship_type '[value]'. Must be one of: derived_from, supersedes, conflicts_with, related_to." → SDK: `ValidationError`
- **Example Usage**: Marking provenance for a promoted memory:
  ```
  create_relationship(source_id="<org-memory-id>", target_id="<user-memory-id>", relationship_type="derived_from", metadata={"promoted_by": "curator"})
  ```

### get_relationships

- **Purpose**: Get all graph relationships for a memory node. Use this to understand how memories are connected — trace provenance chains, find conflicts, discover related memories. Supports directional filtering and optional provenance chain tracing.
- **Parameters**:
  - `node_id` (string/UUID, required): UUID of the memory node to query.
  - `relationship_type` (string, optional): Filter by type. One of: `derived_from`, `supersedes`, `conflicts_with`, `related_to`. Omit for all types.
  - `direction` (string, optional, default "both"): Which edges to return: `outgoing` (this node is the source), `incoming` (this node is the target), or `both`.
  - `include_provenance` (boolean, optional, default false): If true, additionally traces `derived_from` edges backward from this node to build a provenance chain showing where this memory originated. Useful for organizational memories that were promoted from user memories.
- **Returns**: A dict with `relationships` (list of edges with source/target stubs), `count`, and optionally `provenance_chain` (list of `{hop, node, relationship}` entries tracing back to the origin).
- **Error Cases**:
  - "Memory node [id] not found. Verify the node_id refers to an existing memory node." → SDK: `NotFoundError`
  - "Invalid direction '[value]'. Must be one of: outgoing, incoming, both." → SDK: `ValidationError`
  - "Invalid relationship_type '[value]'. Must be one of: derived_from, supersedes, conflicts_with, related_to." → SDK: `ValidationError`
- **Example Usage**: Tracing the origin of an organizational memory:
  ```
  get_relationships(node_id="<org-memory>", include_provenance=true)
  ```

### get_similar_memories

- **Purpose**: Get memories similar to a given memory, with similarity scores. Use this to investigate when `write_memory` reports `similar_count > 0`. Returns paged results to avoid context bloat — start with a small page and increase if needed. Each result includes the memory stub and a cosine similarity score.
- **Parameters**:
  - `memory_id` (string/UUID, required): UUID of the memory to find similar memories for. Uses the stored embedding from this memory.
  - `threshold` (float, optional, default 0.80): Minimum cosine similarity (0.0-1.0). Lower values return more results but include less-relevant matches.
  - `max_results` (integer, optional, default 10): Maximum results per page (1-50).
  - `offset` (integer, optional, default 0): Pagination offset. Use with `has_more` from the response.
- **Returns**: `{"results": [{id, stub, score}], "total": int, "has_more": bool}`. Results are ordered by similarity (highest first). The `total` is the full count of memories above the threshold, not just the page.
- **Error Cases**:
  - "Memory [id] not found." — Invalid or inaccessible memory ID. → SDK: `NotFoundError`
  - "Memory [id] has no embedding — similarity search unavailable." — Memory was stored without an embedding (shouldn't happen in normal operation). → SDK: `ToolError`
- **Example Usage**: After `write_memory` returns `similar_count: 3`:
  ```
  get_similar_memories(memory_id="<new-memory-id>", max_results=3)
  ```
  If the results look redundant, call `update_memory` on the existing one or `create_relationship` with `conflicts_with` type to suggest a merge.

### suggest_merge (CONSOLIDATED into create_relationship — #173)

> **Removed.** Merge suggestions are now expressed via `create_relationship(source_id=..., target_id=..., relationship_type="conflicts_with", metadata={"merge_suggested": true, "reasoning": "..."})`. The underlying service call was always `create_relationship`; the standalone tool was a thin wrapper.

- **Migration**: `suggest_merge(memory_a_id="a", memory_b_id="b", reasoning="duplicates")` → `create_relationship(source_id="a", target_id="b", relationship_type="conflicts_with", metadata={"merge_suggested": true, "reasoning": "duplicates"})`

### set_curation_rule

- **Purpose**: Create or update a user-layer curation rule. Use this to tune curation preferences — for example, raising the duplicate detection threshold if you're getting false positives. Rules created here only affect your own memories. Cannot override system rules marked as protected (like secrets scanning). Upserts by name: if a rule with the given name exists for your user, it's updated; otherwise created.
- **Parameters**:
  - `name` (string, required): Rule name. This is the unique identifier within your user rules.
  - `tier` (string, optional, default "embedding"): Rule tier: `regex` (pattern matching) or `embedding` (similarity threshold).
  - `action` (string, optional, default "flag"): Action on match: `flag`, `block`, `quarantine`, `reject_with_pointer`, `decay_weight`.
  - `config` (object, optional): Tier-specific configuration. For embedding: `{"threshold": 0.98}` to raise the dedup threshold. For regex: `{"pattern": "regex-string"}` for custom pattern matching.
  - `scope_filter` (string, optional): Limit this rule to a specific scope (user, project, etc.). Null applies to all scopes.
  - `enabled` (boolean, optional, default true): Whether this rule is active.
  - `priority` (integer, optional, default 10): Evaluation priority within the tier (lower = higher priority).
- **Returns**: The created or updated rule with its UUID and all fields. Includes `"created": true` or `"updated": true` to indicate which action was taken.
- **Error Cases**:
  - "Cannot override system rule '[name]' — it is protected by the platform administrator." — Agent tried to create a user rule with the same name as a protected system rule. → SDK: `PermissionDeniedError`
  - "Invalid tier '[value]'. Must be one of: regex, embedding." → SDK: `ValidationError`
  - "Invalid action '[value]'. Must be one of: flag, block, quarantine, reject_with_pointer, decay_weight." → SDK: `ValidationError`
- **Example Usage**: Raising the dedup threshold because dataset memories are intentionally similar:
  ```
  set_curation_rule(name="my_dedup_threshold", tier="embedding", action="reject_with_pointer", config={"threshold": 0.98})
  ```

---

## Phase 3 Tools: Memory Lifecycle

Phase 3 adds memory deletion. The need surfaced from the dashboard work in Phase 2c — admins viewing memories in the dashboard needed a way to remove ones that shouldn't be there (sensitive content that slipped past curation, stale test data, etc.). The deletion model is **soft-delete**: a `deleted_at` timestamp marks the memory and its entire version chain as gone, all queries filter it out, but the row stays in the database for audit/recovery. Hard delete is intentionally NOT exposed via MCP — it's reserved for a future admin agent (#45).

### Design Principles for Phase 3

**Destructive operations are annotated, not gated.** Following Anthropic's guidance: tools that make destructive changes should disclose this via tool annotations (`destructiveHint: True`) so the consuming agent's harness can warn the user, but the tool itself doesn't gate behind a confirmation parameter. Confirmation is the consuming agent's job; gating it in the tool would create friction for legitimate batch operations and wouldn't actually prevent a misbehaving agent from confirming its own destructive call.

**Soft-delete is the right primitive for an MCP tool.** Hard delete (physical row removal) is irreversible and dangerous in an agentic context where a single bad tool call could destroy user data. Soft-delete is recoverable, audit-friendly, and consistent with how the rest of the memory tree handles state changes (versioning never destroys, only supersedes). If a privileged actor needs hard delete, that's an admin workflow with elevated authorization, not a routine MCP tool.

**The whole version chain goes together.** Memories have version chains via `previous_version_id`. Deleting only the current version would leave orphaned older versions visible in forensic searches — confusing and useless. Deleting only an old version would leave a "current" pointer to a deleted node — broken. The clean semantics: delete the memory, and the entire chain (plus any child branches) goes with it. Return counts so the agent knows how much was affected.

**Authorization is owner OR admin.** Routine deletions are owner-driven (an agent cleaning up its own user-scope memories). Admin override exists for incident response (the curator agent finds sensitive content, deletes it on behalf of the user). Both paths flow through `memory:write:<scope>` for the routine case and the `memory:admin` scope for the override.

### delete_memory

- **Purpose**: Soft-delete a memory and its entire version chain. The memory and all of its prior versions are marked as deleted via a `deleted_at` timestamp; child branches (rationale, provenance, etc.) attached to any version in the chain are also deleted. Deleted memories are excluded from `search_memory`, `read_memory`, and graph traversal queries. The data remains in the database for audit and potential recovery, but is not visible via any standard read path. Use this when a memory is wrong, sensitive content slipped past curation, or test data needs cleanup. **This is a destructive operation** — there is no MCP-exposed undelete.
- **Parameters**:
  - `memory_id` (string/UUID, required): The ID of any version of the memory to delete. The tool walks the version chain in both directions (older via `previous_version_id`, newer via forward search) so passing an old version ID still deletes the entire chain. This matches the behavior of `get_memory_history`, which also accepts any version ID.
- **Returns**: A summary dict with the count of deleted nodes:
  - `deleted_id` (string): The memory_id that was passed in (echoed back for confirmation).
  - `versions_deleted` (integer): How many version-chain nodes were soft-deleted (will be ≥ 1).
  - `branches_deleted` (integer): How many child branch nodes (rationale, provenance, etc.) were also deleted.
  - `total_deleted` (integer): Sum of versions + branches. This is the total number of rows the tool affected.
  The agent uses this to confirm the scope of the deletion: if the agent expected to delete a single memory but `total_deleted` is 8, it knows the memory had a deep history or many branches and can mention this to the user.
- **Error Cases**:
  - "Memory [id] not found. It may have already been deleted, or you may not have read access to its scope." — The memory doesn't exist, has already been soft-deleted, OR the caller doesn't have `memory:read` for the memory's scope. **All three of these collapse to a single not-found error.** → SDK: `NotFoundError`

    Earlier spec drafts proposed a distinct "Memory [id] has already been deleted. Use get_memory_history to see when it was deleted." 409-equivalent for the already-deleted case. The implementation deliberately rejects that distinction because it would leak the *existence* of memories the caller can't read: a non-reader could probe IDs and infer "this UUID once existed and is now deleted" from the differentiated error. Folding all three causes into "not found" preserves the deleted state's invisibility to non-readers. See `src/tools/delete_memory.py` for the well-commented rationale; this is by design and should not be reverted.
  - "Not authorized to delete this [scope]-scope memory. You need either ownership of the memory or the memory:admin scope." — Caller has read access but not write access to this memory's scope, and is not a memory:admin. Tells the agent exactly what would unblock the call. → SDK: `PermissionDeniedError`
  - "Invalid memory_id format: '[value]'. Expected a UUID string." — The memory_id parameter wasn't a valid UUID. Standard format error. → SDK: `ValidationError`
- **Tool Annotations**:
  - `readOnlyHint: false` — Modifies state.
  - `destructiveHint: true` — **This is the key annotation for delete_memory.** Tells the consuming agent's harness that this operation removes data and should be surfaced to the user (e.g., shown in a confirmation prompt or marked in transcripts).
  - `idempotentHint: false` — A retry returns "already deleted" rather than the same result. Idempotent in effect (no double-deletion) but not in response.
  - `openWorldHint: false` — Only affects the local database, no external side effects.
- **Example Usage**: An agent cleaning up a stale preference:
  ```
  delete_memory(memory_id="0fcc6790-957d-4f2a-a398-99a028065005")
  ```
  Returns: `{"deleted_id": "0fcc6790-...", "versions_deleted": 3, "branches_deleted": 1, "total_deleted": 4}`. Agent reports to user: "Deleted the 'prefers Vim' preference along with 2 prior versions and its rationale branch (4 records total)."

  An admin agent removing sensitive content via memory:admin scope:
  ```
  delete_memory(memory_id="abc-123-leaked-secret")
  ```
  Returns the same shape; the agent's authorization to delete came from `memory:admin` rather than ownership.

---

## Phase 4 Tools: Session Focus History (#61)

Phase 4 adds two tools that make session focus a stored, analyzable signal rather than a per-call parameter that vanishes after each `search_memory`. Issue #61 tracks the feature. The complementary #62 (Pattern E push-side broadcast filter) reuses the same Valkey schema; #62's tools land in a later phase.

### Design Principles for Phase 4

**Stateless per-call focus on `search_memory` stays as-is; stateful declaration is separate.** Layer 2 (#58) deliberately made `search_memory`'s `focus` parameter stateless to sidestep the coordination/scaling questions around stored focus state. That decision was correct for retrieval — per-call focus is cheap and avoids every coordination issue. For the usage-signal and broadcast-filter use cases (#61 / #62), though, we need the focus to be stored somewhere both history aggregation and broadcast code can read. A new tool `set_session_focus` writes to that stored place without changing `search_memory`'s contract.

**Advisory-only feedback.** The histogram from `get_focus_history` is a readable signal, not a weight-tuning input. Humans and agents consume it informationally. Auto-nudging weights based on the histogram, or blending the histogram as a third retrieval vector, are explicitly out of scope for this phase — they would compound the complexity of the two-vector work #58 just landed without empirical justification.

**Valkey is the store of record for transient focus state.** Per the team-wide Valkey-first infrastructure rule, session state lives in Valkey, not PostgreSQL. Two key prefixes:
- `memoryhub:sessions:<session_id>` — active-session hash (focus, focus_vector, user_id, project, created_at, expires_at) with TTL matching JWT lifetime. Used by both #61 (write side) and #62 (broadcast-filter read side, when it lands).
- `memoryhub:session_focus_history:<project>:<yyyy-mm-dd>` — append-only JSON entries per project per day. 30-day retention via key TTL.

### set_session_focus

- **Purpose**: Declare the current session's focus topic — the narrow area the conversation is about, such as "deployment" or "MCP tool design". Writes the focus to two Valkey records simultaneously: (a) an active-session hash keyed by `session_id` carrying the focus string and its 384-dim embedded vector with a TTL matching the JWT lifetime, and (b) an append-only JSON entry in a per-project per-day history list. The SDK usually infers the focus from the working directory or the first user turn per `.memoryhub.yaml`, but agents can declare focus explicitly or update it mid-session when the conversation pivots.
- **Parameters**:
  - `focus` (string, required): A short natural-language topic describing the session's current focus. 5-10 words work best. Examples: "deployment", "MCP tool design for session focus", "UI panel for curation rules".
  - `project` (string, required): The project identifier this session belongs to. Typically matches the `project` field of project-scope memories and the `project` value in `.memoryhub.yaml`. Required so the history aggregation can scope per-project.
- **Returns**: A dict with:
  - `session_id` (string): The authenticated session_id the focus was recorded under. Same session_id that `register_session` surfaces.
  - `user_id` (string): The authenticated user_id from the JWT or session-fallback.
  - `project` (string): The project identifier derived from the authenticated identity.
  - `focus` (string): Echo of the declared focus.
  - `expires_at` (string, ISO datetime): When the active-session record will auto-expire from Valkey.
  - `message` (string): Human-readable confirmation.
- **Error Cases**:
  - "focus must not be empty. Provide a 5-10 word topic describing the session's current focus." — Empty or whitespace-only focus. → SDK: `ValidationError`
  - "No authenticated session found. Call register_session first, or provide a JWT in the Authorization header." — No auth context available. → SDK: `AuthenticationError`
  - "Session focus store is unavailable: [reason]. Focus was not recorded; retry after the backend recovers." — Valkey unreachable. Surfaces as an MCP error so the agent knows the write didn't land. → SDK: `ToolError`
- **Tool Annotations**:
  - `readOnlyHint: false` — Writes Valkey state.
  - `destructiveHint: false` — Doesn't destroy prior state; the TTL handles eviction.
  - `idempotentHint: false` — A retry creates an additional history entry; it is not a no-op.
  - `openWorldHint: false` — Only affects the Valkey instance co-located with the MCP server.
- **Example Usage**: Declaring the session's focus at the start of a deployment work session:
  ```
  set_session_focus(focus="MCP server deployment to OpenShift", project="memory-hub")
  ```
  Updating focus mid-session when the conversation pivots:
  ```
  set_session_focus(focus="debugging the OAuth token exchange flow", project="memory-hub")
  ```

### get_focus_history

- **Purpose**: Retrieve an aggregated per-project histogram of session focus declarations across a date range. Answers the question "what has this project actually been working on recently?" by aggregating the append-only history log from `set_session_focus` calls. Advisory-only — the histogram is a readable signal that humans and agents can consume to inform their own decisions (e.g., an agent declaring focus for a new session can check what topics are most active; a human can spot coverage gaps). It does NOT auto-tune memory weights or blend into retrieval ranking.
- **Parameters**:
  - `project` (string, required): The project identifier to query. Typically matches the `project` field of project-scope memories and the `.memoryhub.yaml` project identifier.
  - `start_date` (string, optional, ISO date YYYY-MM-DD): Start of the date range, inclusive. Defaults to 30 days before `end_date`.
  - `end_date` (string, optional, ISO date YYYY-MM-DD): End of the date range, inclusive. Defaults to today (UTC).
- **Returns**: A dict with:
  - `project` (string): Echo of the input.
  - `start_date` / `end_date` (strings): The window that was actually queried (useful when defaults were applied).
  - `total_sessions` (integer): Number of focus declarations in the window.
  - `histogram` (list of dicts): Sorted by count descending, ties broken by focus string. Each entry: `{"focus": str, "count": int}`. Empty list if `total_sessions` is 0.
- **Error Cases**:
  - "start_date (X) is after end_date (Y). Provide dates as YYYY-MM-DD where start_date <= end_date." — Inverted range. → SDK: `ValidationError`
  - "Invalid date format: 'X'. Expected ISO format YYYY-MM-DD." — Malformed date string. → SDK: `ValidationError`
  - "Session focus store is unavailable: [reason]. Histogram data cannot be retrieved until the backend recovers." — Valkey unreachable. → SDK: `ToolError`
- **Tool Annotations**:
  - `readOnlyHint: true` — Pure read from Valkey.
  - `destructiveHint: false`
  - `idempotentHint: true` — Repeat calls return the same result for the same window (ignoring intervening writes).
  - `openWorldHint: false`
- **Example Usage**: Checking what a project has been working on over the last two weeks:
  ```
  get_focus_history(project="memory-hub", start_date="2026-03-25", end_date="2026-04-07")
  ```
  Returns: `{"project": "memory-hub", "total_sessions": 18, "histogram": [{"focus": "deployment", "count": 8}, {"focus": "MCP tool design", "count": 5}, {"focus": "auth", "count": 3}, {"focus": "UI", "count": 2}]}`. A new-session agent reads this to decide whether to default its focus to "deployment" or ask the user.

---

## Implementation Order

### Phase 1 (complete)

1. **register_session** — Authentication and session setup.
2. **write_memory** — Foundation. Now includes curation pipeline integration (secrets scanning, embedding dedup, similar_count feedback).
3. **read_memory** — Single-node read with branch_count summary; historical-version reads include a current_version_id pointer.
4. **search_memory** — Semantic search via pgvector.
5. **update_memory** — Versioning with deep copy of branches.
6. **get_memory_history** — Version chain traversal.
7. **report_contradiction** — Staleness signal accumulation.

### Phase 2 (complete)

8. **create_relationship** — Depends on graph service layer (done in #4). Foundation for provenance and merge suggestions.
9. **get_relationships** — Depends on create_relationship. Read-only query tool.
10. **get_similar_memories** — Depends on curation similarity service (done in #6 Phase 2a). Read-only drill-down.
11. **suggest_merge** — Depends on create_relationship (uses it under the hood to create a `conflicts_with` edge).
12. **set_curation_rule** — Depends on curation rules service (done in #6 Phase 2a). Most independent of the Phase 2 tools.

### Phase 3 (complete)

13. **delete_memory** — Depends on the `deleted_at` column (Alembic 007), the `delete_memory()` service-layer function in `memoryhub_core.services.memory`, and the `MemoryAlreadyDeletedError` exception. The tool itself is a thin authorization + service-layer wrapper. Refs #42.

### Phase 4 (current)

14. **set_session_focus** — Depends on the Valkey deployment (`deploy/valkey/`), the `memoryhub_core.services.valkey_client.ValkeyClient` wrapper, and the existing embedding service (reused to compute the focus vector). Writes to both the active-session hash and the per-project per-day history list in one pipeline. Refs #61.
15. **get_focus_history** — Depends on `ValkeyClient.read_focus_history`. Pure read aggregator that counts focus string occurrences across the date range. Refs #61.

## Dependencies

### Phase 1 (resolved)

- **PostgreSQL + pgvector**: Deployed in memoryhub-db namespace.
- **memoryhub core library**: SQLAlchemy models, Pydantic schemas, service layer.
- **Embedding service**: all-MiniLM-L6-v2 deployed on OpenShift AI (384-dim embeddings).
- **API key auth**: ConfigMap-based user authentication.

### Phase 2 (resolved)

- **Graph service** (`memoryhub_core.services.graph`): 6 async functions for creating/querying relationships and traversals. Built in #4.
- **Curation service** (`memoryhub_core.services.curation`): Pipeline, scanner, similarity, and rules modules. Built in #6 Phase 2a.
- **`memory_relationships` table**: Migration 003, deployed.
- **`curator_rules` table**: Migration 004, deployed. Default system rules seeded.

### Phase 3 (resolved)

- **`deleted_at` column on `memory_nodes`**: Alembic migration 007, applied to dev DB.
- **`delete_memory()` service function** (`memoryhub_core.services.memory`): Walks the version chain (both directions), collects child branches, and bulk soft-deletes via `UPDATE`. Returns a count summary.
- **`MemoryAlreadyDeletedError` exception** (`memoryhub_core.services.exceptions`): Distinguishes "already deleted" from "not found" so the tool can return a 409-equivalent message.
- **All read paths filter `deleted_at IS NULL`**: `read_memory`, `search_memories`, `_bulk_branch_flags`, `_compute_branch_flags`, and the BFF queries (graph, search, stats, users).

### Phase 4 (resolved)

- **Valkey 8.x deployment** (`deploy/valkey/`): Single-pod Deployment + Service + PVC in `memory-hub-mcp` namespace. Dedicated `memoryhub-valkey` ServiceAccount with `anyuid` SCC grant scoped to just this workload.
- **`ValkeyClient` wrapper** (`memoryhub_core.services.valkey_client`): Async client over `redis.asyncio` (Valkey is protocol-compatible). Provides `write_session_focus`, `read_focus_history`, `ping`, and vector base64 codec helpers. Tests use `fakeredis` for in-memory Valkey emulation.
- **`MEMORYHUB_VALKEY_URL` env var**: Connection string passed to the MCP server pod, e.g. `redis://memoryhub-valkey.memory-hub-mcp.svc.cluster.local:6379/0`.

### Phase 5 (current)

16. **list_projects** — Depends on the `projects` table (Alembic 012) and the `list_projects_for_tenant()` service function in `memoryhub_core.services.project`. Read-only project discovery tool. Refs #188.

### Phase 5 (resolved when shipped)

- **`projects` table**: Alembic migration 012, creates `projects(name PK, description, invite_only, tenant_id, created_at, created_by)` with FK from `project_memberships.project_id`.
- **`ensure_project_membership()`**: Service function that auto-enrolls users in open projects on first project-scoped write. Called by `write_memory` instead of the old hard-reject check.
- **`list_projects_for_tenant()`**: Service function returning project dicts with `is_member` flag. Supports `include_all_open` filter mode.

---

## Phase 5 Tools: Project Discovery (#188)

Phase 5 adds project discovery for agents. The companion change (auto-enrollment via `ensure_project_membership`) is wired directly into the existing `write_memory` tool rather than as a separate tool — the agent doesn't need a `join_project` tool because the act of writing creates the membership.

### Design Principles for Phase 5

**Don't add tools where existing tools suffice.** Auto-enrollment is wired into `write_memory` because that's where the agent hits the friction. Adding `create_project` / `join_project` / `leave_project` tools would bloat the tool surface for operations that either happen automatically (join on write) or rarely (admin-only project creation). A single `list_projects` tool covers the remaining gap: discoverability.

**Filter, don't gate.** The `filter` parameter defaults to `"mine"` (only the user's projects) but supports `"all"` (all open projects in the tenant with an `is_member` flag). Invite-only projects that the user is NOT a member of are excluded from `"all"` results — they should not be discoverable.

### list_projects

- **Purpose**: List projects you belong to or that are available to join. Use this to discover which projects exist and which you're a member of before writing project-scoped memories. Projects you are not yet a member of can be joined automatically by writing a project-scoped memory with that `project_id` (auto-enrollment).
- **Parameters**:
  - `filter` (string, optional, default "mine"): Which projects to return. `"mine"` returns only projects you're a member of. `"all"` also includes open projects you could join, with an `is_member` flag on each.
- **Returns**: A dict with:
  - `projects` (list of dicts): Each entry has `name`, `description`, `invite_only`, `created_at`, `created_by`, and `is_member` (boolean).
  - `total` (integer): Number of projects returned.
- **Error Cases**:
  - "No authenticated session found. Call register_session first, or provide a JWT in the Authorization header." — No auth context. → SDK: `AuthenticationError`
  - "Invalid filter value '[value]'. Must be one of: mine, all." → SDK: `ValidationError`
- **Tool Annotations**:
  - `readOnlyHint: true` — Pure read.
  - `destructiveHint: false`
  - `idempotentHint: true` — Repeat calls return the same result (ignoring intervening writes).
  - `openWorldHint: false`
- **Example Usage**: Discovering projects before a first write:
  ```
  list_projects(filter="all")
  ```
  Returns: `{"projects": [{"name": "memory-hub", "description": null, "invite_only": false, "created_at": "2026-04-01T...", "created_by": "admin", "is_member": true}, {"name": "agent-template", "description": null, "invite_only": false, "created_at": "2026-04-15T...", "created_by": "wjackson", "is_member": false}], "total": 2}`. The agent sees it's not a member of `agent-template` yet; a `write_memory(scope="project", project_id="agent-template", ...)` call will auto-enroll.

## Open Questions (Phase 1 — Resolved)

- **Embedding strategy**: all-MiniLM-L6-v2 on OpenShift AI via HTTP API. MockEmbeddingService for tests.
- **Contradiction threshold**: Default of 5, configurable via curator rules.
- **Concurrent write handling**: Blocking for user-scope, queued for above-user-scope.
