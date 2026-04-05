# MCP Server Interface

The MCP server is the sole external interface to MemoryHub. Every agent interaction -- reading, writing, searching, versioning -- goes through MCP tools. There is no REST API, no direct database access, no alternative path. This simplifies security (one interface to secure) and governance (one interface to audit).

**Status: implemented.** 12 tools deployed on OpenShift via streamable-http transport. See `memory-hub-mcp/TOOLS_PLAN.md` for the full tool specifications.

## Transport and Deployment

The MCP server uses streamable-http transport (SSE is deprecated). It's built with FastMCP 3 (not v2), deployed as a single-replica Deployment on OpenShift behind a Route with TLS edge termination. The pod is stateless -- all state lives in PostgreSQL.

Authentication uses API key auth via a ConfigMap-mounted `users.json`. Each key maps to a user identity with scoped access. Full OpenShift OAuth/OIDC integration is a future concern (see [governance.md](governance.md)).

Deployment is automated via `deploy/deploy.sh` which stages a build context, triggers an OpenShift BuildConfig (binary strategy), and waits for rollout. The Deployment spec includes `imagePullPolicy: Always` to prevent stale image caching.

## Implemented Tool Surface

### Phase 1: Core Memory Operations (7 tools)

| Tool | Purpose | Read/Write |
|------|---------|------------|
| `register_session` | API key authentication, establishes user identity | Setup |
| `write_memory` | Create memory nodes and branches, with inline curation feedback | Write |
| `read_memory` | Retrieve memory by ID with optional branch depth expansion | Read |
| `update_memory` | Create new version of a memory, preserving history | Write |
| `search_memory` | Semantic search via pgvector embeddings | Read |
| `get_memory_history` | Version chain traversal with pagination | Read |
| `report_contradiction` | Accumulate staleness signals against a memory | Write |

### Phase 2: Graph Relationships & Curation (5 tools)

| Tool | Purpose | Read/Write |
|------|---------|------------|
| `create_relationship` | Create directed edges between memories (derived_from, supersedes, conflicts_with, related_to) | Write |
| `get_relationships` | Query edges for a node with optional provenance tracing | Read |
| `get_similar_memories` | Paged similar memory lookup by embedding similarity | Read |
| `suggest_merge` | Record merge suggestion as a conflicts_with relationship | Write |
| `set_curation_rule` | Create/update user-layer curation rules (dedup thresholds, custom regex) | Write |

### Curation Pipeline

`write_memory` runs an inline curation pipeline before persisting:

1. **Tier 1 (regex)**: Secrets detection (AWS keys, GitHub tokens, private key headers) and PII detection (SSN, email, phone). Blocks or flags based on curation rules.
2. **Tier 2 (embedding)**: Cosine similarity against existing memories in the same (owner_id, scope). Rejects exact duplicates (>0.95), flags possible duplicates (0.80-0.95).

The write response includes curation feedback: `similar_count`, `nearest_id`, `nearest_score`, and `flags`. The calling agent's LLM decides what to do with ambiguous cases -- no MCP sampling is used, avoiding the HITL approval friction.

### Curation Rules Engine

Three-layer rules (system > organizational > user) with override protection. System rules for secrets scanning are marked `override=true` and cannot be weakened by user rules. Users tune their own dedup thresholds via `set_curation_rule`.

## Authentication

Current: API key auth via `register_session`. Keys are stored in a ConfigMap-mounted JSON file. Each key maps to a user_id, name, and list of accessible scopes.

Future: OpenShift OAuth/OIDC with per-agent identity. See #7 (governance design) and #13 (RBAC).

## Error Handling

MCP tools return clear, actionable errors as `{"error": true, "message": "..."}` dicts. Error messages explain what went wrong AND how to fix it:

- "Invalid relationship_type 'friends_with'. Must be one of: derived_from, supersedes, conflicts_with, related_to."
- "Write blocked by curation rule: secrets_scan. Content matches aws_access_key pattern (AKIA...MPLE)."
- "Memory node abc-123 not found. Verify both source_id and target_id refer to existing, current memory nodes."

## Design Questions (Resolved)

- **Should `get_context` exist?** No. Agents compose `search_memory` + `read_memory` themselves. This gives agents control over their context budget and avoids a monolithic tool.
- **Should `get_branches` be a separate tool?** No. `read_memory(depth=1)` returns branches inline. One tool, fewer round-trips.
- **How does write_memory handle concurrent writes?** Blocking for user-scope (direct write). Above-user-scope queued for curator review (not yet implemented).
- **How do agents without OpenShift identity connect?** API keys via `register_session`. Works for Claude Code and other external clients.
- **Max results granularity for search?** `max_results` parameter (default 10, max 50) plus weight-based stub/full split. Agents control page size.
- **Should curation use LLM sampling?** No. MCP spec requires HITL approval for sampling, which is unacceptable friction on write operations. Instead, `write_memory` returns similarity counts and the calling agent's existing LLM handles judgment calls.

## Design Questions (Open)

- Rate limiting: should the MCP server enforce per-agent rate limits? Not needed at current scale (single user), but relevant for multi-tenant deployment.
- Should there be an `import_memory` tool for bulk ingestion from Claude Code's local memory files? Useful for onboarding but adds complexity.
- Connection pooling: the MCP server creates a new SQLAlchemy session per tool call. At scale, connection pooling (PgBouncer) may be needed.
