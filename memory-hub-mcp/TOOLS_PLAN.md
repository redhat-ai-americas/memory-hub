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

## Implementation Order

1. **write_memory** — Foundation. Can't test anything else without the ability to create memories. Also validates the governance pipeline.
2. **read_memory** — Immediate follow-up. Write + read is the minimal useful pair. Tests depth expansion and branch traversal.
3. **search_memory** — The most important tool for agent UX. Requires pgvector embeddings, so depends on an embedding service/function being available.
4. **update_memory** — Versioning is a core differentiator. Tests the isCurrent model and version chain.
5. **get_memory_history** — Builds on the version chain from update_memory. Straightforward once versioning works.
6. **report_contradiction** — Can be implemented last since it feeds the curator agent (which is a Phase 2 concern). But the MCP interface should exist so agents can start reporting.

## Dependencies

- **PostgreSQL + pgvector**: Deployed in memoryhub-db namespace (done — issue #3).
- **memoryhub core library**: SQLAlchemy models, Pydantic schemas, and a service layer for CRUD operations. The models exist; the service layer (database session management, query functions) needs to be built as part of tool implementation.
- **Embedding function**: search_memory needs to embed query strings into vectors. Options: call an external embedding API (OpenAI, vLLM-served model), or use a local model. For Phase 1, we can use a mock embedding or a lightweight local model. The embedding strategy is a deferred decision — the MCP tool just needs a function it can call.
- **Governance engine**: Access control and audit logging. For Phase 1, we can implement a simplified version (check scope permissions, log to PostgreSQL) without the full governance system from Phase 3.

## Open Questions

- **Embedding strategy**: What embedding model/service do we use? This affects search_memory quality significantly. For demo, a mock or small local model may suffice. For production, needs a vLLM-compatible model on OpenShift AI.
- **Contradiction threshold**: How many contradictions trigger a revision prompt? Configurable per deployment? Default of 5 seems reasonable.
- **Concurrent write handling**: Does write_memory block until the write completes, or return immediately with a "pending" status? For user-scope (direct write), blocking is fine. For above-user-scope (curator queue), async with status makes more sense.
