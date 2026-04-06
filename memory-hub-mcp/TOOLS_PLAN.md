# Tools Plan

## Overview

MemoryHub MCP server provides 6 tools for AI agents to read, write, search, and manage memories in a centralized, governed memory system. Agents connect via streamable-http MCP transport. Every operation flows through a governance layer for access control and audit logging.

The tools are designed around the tree-based memory model: memories are nodes with optional branches (rationale, provenance, etc.), weighted for injection priority, versioned for forensics, and embedded for semantic search.

## Design Principles Applied

**Fewer, powerful tools.** We consolidated get_branches into read_memory (via a depth parameter) and dropped the speculative get_context tool. 6 tools cover the full agent workflow: write → search → read (with depth) → update → history → report contradictions.

**Tool descriptions as steering mechanisms.** Each tool description explains the tree model concepts (stubs, branches, weight) so agents understand how to use MemoryHub effectively. An agent that's never seen MemoryHub before should be able to use it correctly from the descriptions alone.

**Composable, not monolithic.** Rather than a single "get me everything relevant" tool, agents compose search_memory (find relevant memories) + read_memory (expand interesting ones) + get_memory_history (check evolution). This gives agents control over their context budget.

**Actionable errors.** Every error tells the agent what went wrong AND what to do about it. "Write to organizational scope requires curator approval — memory has been queued for review" not just "403 Forbidden".

**Weight-aware responses.** search_memory returns a mix of full content (high-weight matches) and stubs (lower-weight matches). Agents see stubs with indicators like "rationale available" and decide whether to expand, keeping context lean.

## Tools

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
  - "Access denied: you cannot write to [scope] scope. Your identity allows writes to: [list of allowed scopes]." — Agent tried to write to a scope it doesn't have permission for.
  - "Parent memory [id] not found. Check the parent_id — it may have been deleted or you may not have access to it." — Invalid parent_id for branch creation.
  - "branch_type is required when parent_id is set. Common types: rationale, provenance, description, evidence." — Missing branch_type on a branch write.
  - "Content flagged by security scan: [reason]. The memory was not stored. Remove sensitive content and retry." — Secrets/PII detected in content.
- **Example Usage**: An agent recording a user preference:
  ```
  write_memory(content="prefers Podman over Docker for container builds", scope="user", owner_id="wjackson", weight=0.9)
  ```
  Adding rationale to that preference:
  ```
  write_memory(content="works for Red Hat where Podman is the standard runtime", scope="user", owner_id="wjackson", parent_id="<id from above>", branch_type="rationale")
  ```

### read_memory

- **Purpose**: Retrieve a specific memory by ID, with optional depth expansion into branches. At depth 0, returns just the node. At depth 1, includes all direct child branches (rationale, provenance, etc.) with their full content. This is how agents "crawl deeper" after seeing a stub in search results.
- **Parameters**:
  - `memory_id` (string/UUID, required): The ID of the memory to read.
  - `depth` (integer, optional, default 0): How many levels of branches to include. 0 = just this node. 1 = this node + direct children. 2 = children + grandchildren. Rarely need more than 1.
  - `include_versions` (boolean, optional, default false): If true, includes a summary of the version history alongside the current content. Useful when an agent needs to understand how a memory evolved.
- **Returns**: The memory node with full content, metadata, version info, and (if depth > 0) an array of branch nodes with their content and types. Each branch includes its own has_children flag so the agent knows if there's more depth available.
- **Error Cases**:
  - "Memory [id] not found. It may have been deleted, or you may not have access to this memory's scope." — Memory doesn't exist or is inaccessible.
  - "Memory [id] is not current (version [N] superseded by version [M]). Returning the current version instead. Pass include_versions=true to see the full history." — Agent requested a superseded version; returns current by default with a note.
- **Example Usage**: Reading a memory and its rationale:
  ```
  read_memory(memory_id="abc-123", depth=1)
  ```
  Returns: the memory content + any branches (rationale, provenance, etc.) as nested objects.

### update_memory

- **Purpose**: Create a new version of an existing memory. The old version is preserved with isCurrent=false; the new version becomes current. This is how memories evolve over time while maintaining full history for forensics. Use this when a preference changes, information is corrected, or a memory needs refinement.
- **Parameters**:
  - `memory_id` (string/UUID, required): The ID of the current memory to update. Must be a current (isCurrent=true) memory.
  - `content` (string, optional): New content text. If omitted, content stays the same (useful for weight-only updates).
  - `weight` (float, optional): New weight. If omitted, inherits from the previous version.
  - `metadata` (object, optional): New metadata. Merged with existing metadata (not replaced).
- **Returns**: The new version of the memory with its new ID, version number, and the previous_version_id linking back to the old version. The old version's isCurrent is now false.
- **Error Cases**:
  - "Memory [id] is not the current version. The current version is [current_id] (version [N]). Update that instead." — Agent tried to update a superseded version.
  - "Access denied: only the memory owner can update user-scope memories. This memory belongs to [owner]." — Attribution protection: can't edit someone else's memories.
  - "No changes provided. Include at least one of: content, weight, metadata." — Empty update.
- **Example Usage**: Updating a preference:
  ```
  update_memory(memory_id="abc-123", content="prefers Rust for systems work, Python for scripting and ML")
  ```

### search_memory

- **Purpose**: Semantic search across all memories the agent has access to. This is the primary discovery mechanism — agents don't need to know memory IDs upfront. The query is embedded via pgvector and compared against stored memory embeddings. Results are a mix of full content (for high-weight matches) and stubs (for lower-weight matches), keeping the response token-efficient.
- **Parameters**:
  - `query` (string, required): Natural language search query. Be specific — "container runtime preferences" works better than "containers". The query is embedded and compared via cosine similarity.
  - `scope` (string, optional): Filter to a specific scope (user, project, role, organizational, enterprise). Omit to search all accessible scopes.
  - `owner_id` (string, optional): Filter to a specific owner's memories. Useful for searching within a particular user's or project's context.
  - `max_results` (integer, optional, default 10): Maximum number of results to return. Results are ranked by relevance. Keep low (5-15) to avoid context bloat.
  - `weight_threshold` (float, optional, default 0.0): Only return memories with weight >= this value. Set to 0.8 to see only high-priority memories.
  - `current_only` (boolean, optional, default true): If true, only returns current versions. Set to false for forensic searches across all versions.
- **Returns**: An array of results ranked by relevance. Each result includes:
  - For high-weight memories (weight >= deployment threshold): full content, scope, weight, branch indicators
  - For lower-weight memories: stub text, scope, weight, branch indicators (has_rationale, has_children)
  - A `result_type` field ("full" or "stub") so the agent knows what it's looking at
  - A `relevance_score` (0-1) from the vector similarity search
  The response also includes a `total_accessible` count so the agent knows if there are more results beyond max_results.
- **Error Cases**:
  - "No memories found matching your query. Try broader search terms or remove scope/owner filters." — Empty results with guidance.
  - "Invalid scope filter: [value]. Valid scopes: user, project, role, organizational, enterprise." — Bad scope parameter.
- **Example Usage**: Finding relevant context for a container build task:
  ```
  search_memory(query="container runtime preferences and build requirements", scope="user", owner_id="wjackson", max_results=5)
  ```
  Returns: "prefers Podman" (full, weight 0.9, has_rationale=true), "current project: memory-hub" (stub, weight 0.8), etc.

### get_memory_history

- **Purpose**: Retrieve the full version history of a specific memory. Shows how the memory evolved: what changed, when, and what the previous content was. Supports forensics ("what did the agent believe on March 15th?") and helps agents understand context drift.
- **Parameters**:
  - `memory_id` (string/UUID, required): The ID of any version of the memory (current or historical). The tool traces the full chain regardless of which version ID you provide.
- **Returns**: An ordered list (newest first) of all versions of this memory. Each entry includes: version number, content stub, is_current flag, created_at timestamp, and the full content. The current version is marked.
- **Error Cases**:
  - "Memory [id] not found." — Invalid ID.
  - "This memory has no version history (version 1, never updated)." — Not an error per se, but a clear response that there's only one version.
- **Example Usage**: Checking if a preference changed:
  ```
  get_memory_history(memory_id="abc-123")
  ```
  Returns: [v2: "prefers Rust for systems, Python for scripting" (current), v1: "prefers Python" (superseded 2026-03-01)]

### report_contradiction

- **Purpose**: Signal that observed behavior contradicts a stored memory. This feeds the staleness detection system. When an agent notices the user doing something that conflicts with a stored preference (e.g., using Docker when the memory says "prefers Podman"), it reports the contradiction. The curator agent aggregates these signals and may trigger a memory revision prompt.
- **Parameters**:
  - `memory_id` (string/UUID, required): The memory that appears to be contradicted.
  - `observed_behavior` (string, required): Description of what was observed that conflicts with the memory. Be specific: "User created a Docker Compose project with 12 services" not just "used Docker".
  - `confidence` (float, optional, default 0.7): How confident the agent is that this is a real contradiction (0.0-1.0). Temporary exceptions (e.g., using Docker for a specific client requirement) warrant lower confidence. Repeated, consistent contradictions warrant higher.
- **Returns**: Acknowledgment with the current contradiction count for this memory. If enough contradictions have accumulated, indicates that a revision prompt will be triggered: "Contradiction recorded (3 of 5 threshold). The user will be prompted to review this memory."
- **Error Cases**:
  - "Memory [id] not found." — Invalid memory ID.
  - "Memory [id] is not current. Contradictions can only be reported against current memories." — Can't contradict a superseded version.
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

**Curation tools let agents self-manage.** Rather than relying on a background curator for everything, agents can tune their own dedup thresholds via `set_curation_rule` and suggest merges via `suggest_merge`. This follows the "context-aware tools" principle — tools that consolidate what would otherwise require multiple steps.

### create_relationship

- **Purpose**: Create a directed edge between two memory nodes. Use this to link memories that are semantically connected — marking that an organizational memory was `derived_from` several user memories, that one memory `supersedes` another, that two memories `conflicts_with` each other, or that they are `related_to` one another. Relationships are immutable — create or delete them, never update.
- **Parameters**:
  - `source_id` (string/UUID, required): UUID of the source memory node — the "from" end of the directed edge.
  - `target_id` (string/UUID, required): UUID of the target memory node — the "to" end. Must differ from source_id.
  - `relationship_type` (string, required): One of: `derived_from` (provenance — source was derived from target), `supersedes` (source replaces target), `conflicts_with` (semantic conflict between source and target), `related_to` (general association).
  - `metadata` (object, optional): Key-value context about the relationship — reasoning, confidence, curator notes.
- **Returns**: The created relationship with its UUID, timestamps, `created_by` identity, and stub text from both the source and target nodes for context.
- **Error Cases**:
  - "Memory node [id] not found. Verify both source_id and target_id refer to existing, current memory nodes." — One or both nodes missing.
  - "Relationship ([source] --[type]--> [target]) already exists." — Duplicate edge. The agent should use the existing relationship.
  - "source_id and target_id must be different — self-referential edges are not allowed."
  - "Invalid relationship_type '[value]'. Must be one of: derived_from, supersedes, conflicts_with, related_to."
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
  - "Memory node [id] not found. Verify the node_id refers to an existing memory node."
  - "Invalid direction '[value]'. Must be one of: outgoing, incoming, both."
  - "Invalid relationship_type '[value]'. Must be one of: derived_from, supersedes, conflicts_with, related_to."
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
  - "Memory [id] not found." — Invalid or inaccessible memory ID.
  - "Memory [id] has no embedding — similarity search unavailable." — Memory was stored without an embedding (shouldn't happen in normal operation).
- **Example Usage**: After `write_memory` returns `similar_count: 3`:
  ```
  get_similar_memories(memory_id="<new-memory-id>", max_results=3)
  ```
  If the results look redundant, call `update_memory` on the existing one or `suggest_merge` to link them.

### suggest_merge

- **Purpose**: Suggest that two memories should be merged into one. Records the suggestion as a `conflicts_with` relationship between the two memories with merge reasoning in the metadata. This is how agents flag redundancy for review — the merge suggestion can be found later via `get_relationships`. RBAC-scoped: you can only suggest merges for memories you can read.
- **Parameters**:
  - `memory_a_id` (string/UUID, required): UUID of the first memory.
  - `memory_b_id` (string/UUID, required): UUID of the second memory. Must differ from memory_a_id.
  - `reasoning` (string, required): Why these memories should be merged. Be specific — "Both describe Podman preference but with different wording" is better than "duplicates".
- **Returns**: The created `conflicts_with` relationship with merge metadata (`merge_suggested: true`, `reasoning`, `suggested_by`), plus a confirmation message.
- **Error Cases**:
  - "Memory node [id] not found." — One or both memories don't exist.
  - "memory_a_id and memory_b_id must be different."
  - "reasoning cannot be empty."
  - "A merge suggestion already exists between these memories." — Duplicate suggestion.
- **Example Usage**: After finding two similar container preference memories:
  ```
  suggest_merge(memory_a_id="<older-memory>", memory_b_id="<newer-memory>", reasoning="Both describe Podman preference. The newer version includes Containerfile guidance that should be consolidated.")
  ```

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
  - "Cannot override system rule '[name]' — it is protected by the platform administrator." — Agent tried to create a user rule with the same name as a protected system rule.
  - "Invalid tier '[value]'. Must be one of: regex, embedding."
  - "Invalid action '[value]'. Must be one of: flag, block, quarantine, reject_with_pointer, decay_weight."
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
  - "Memory [id] not found. It may have already been deleted, or you may not have read access to its scope." — The memory doesn't exist OR the caller's claims don't include `memory:read` for the memory's scope. We don't distinguish these to avoid leaking the existence of memories the caller can't see.
  - "Memory [id] has already been deleted. Use get_memory_history to see when it was deleted." — Returned when the memory exists but its `deleted_at` is already set. This is a 409-equivalent: idempotent retries are safe but the agent should know the second call did nothing.
  - "Not authorized to delete this [scope]-scope memory. You need either ownership of the memory or the memory:admin scope." — Caller has read access but not write access to this memory's scope, and is not a memory:admin. Tells the agent exactly what would unblock the call.
  - "Invalid memory_id format: '[value]'. Expected a UUID string." — The memory_id parameter wasn't a valid UUID. Standard format error.
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

## Implementation Order

### Phase 1 (complete)

1. **register_session** — Authentication and session setup.
2. **write_memory** — Foundation. Now includes curation pipeline integration (secrets scanning, embedding dedup, similar_count feedback).
3. **read_memory** — Depth expansion and branch traversal.
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

### Phase 3 (current)

13. **delete_memory** — Depends on the `deleted_at` column (Alembic 007), the `delete_memory()` service-layer function in `memoryhub.services.memory`, and the `MemoryAlreadyDeletedError` exception. The tool itself is a thin authorization + service-layer wrapper. Refs #42.

## Dependencies

### Phase 1 (resolved)

- **PostgreSQL + pgvector**: Deployed in memoryhub-db namespace.
- **memoryhub core library**: SQLAlchemy models, Pydantic schemas, service layer.
- **Embedding service**: all-MiniLM-L6-v2 deployed on OpenShift AI (384-dim embeddings).
- **API key auth**: ConfigMap-based user authentication.

### Phase 2 (resolved)

- **Graph service** (`memoryhub.services.graph`): 6 async functions for creating/querying relationships and traversals. Built in #4.
- **Curation service** (`memoryhub.services.curation`): Pipeline, scanner, similarity, and rules modules. Built in #6 Phase 2a.
- **`memory_relationships` table**: Migration 003, deployed.
- **`curator_rules` table**: Migration 004, deployed. Default system rules seeded.

### Phase 3 (resolved)

- **`deleted_at` column on `memory_nodes`**: Alembic migration 007, applied to dev DB.
- **`delete_memory()` service function** (`memoryhub.services.memory`): Walks the version chain (both directions), collects child branches, and bulk soft-deletes via `UPDATE`. Returns a count summary.
- **`MemoryAlreadyDeletedError` exception** (`memoryhub.services.exceptions`): Distinguishes "already deleted" from "not found" so the tool can return a 409-equivalent message.
- **All read paths filter `deleted_at IS NULL`**: `read_memory`, `search_memories`, `_bulk_branch_flags`, `_compute_branch_flags`, and the BFF queries (graph, search, stats, users).

## Open Questions (Phase 1 — Resolved)

- **Embedding strategy**: all-MiniLM-L6-v2 on OpenShift AI via HTTP API. MockEmbeddingService for tests.
- **Contradiction threshold**: Default of 5, configurable via curator rules.
- **Concurrent write handling**: Blocking for user-scope, queued for above-user-scope.
