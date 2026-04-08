# MCP Server Interface

The MCP server is the sole external interface to MemoryHub. Every agent interaction -- reading, writing, searching, versioning -- goes through MCP tools. There is no REST API, no direct database access, no alternative path. This simplifies security (one interface to secure) and governance (one interface to audit).

**Status: implemented.** 13 tools deployed on OpenShift via streamable-http transport. Layer 1 (response shape, #56/#57) and Layer 2 (session focus retrieval, #58) of the agent-memory-ergonomics work are both shipped. See `memory-hub-mcp/TOOLS_PLAN.md` for the full tool specifications and [`agent-memory-ergonomics/design.md`](agent-memory-ergonomics/design.md) for the design behind the search-memory parameters.

## Transport and Deployment

The MCP server uses streamable-http transport (SSE is deprecated). It's built with FastMCP 3 (not v2), deployed as a single-replica Deployment on OpenShift behind a Route with TLS edge termination. The pod is stateless -- all state lives in PostgreSQL.

Authentication uses OAuth 2.1 with short-lived JWTs. A separate auth service issues tokens; the MCP server validates them via FastMCP's `JWTVerifier`. API keys are exchanged for JWTs via the `client_credentials` grant. See [governance.md](governance.md) for the full auth architecture.

Deployment is automated via `deploy/deploy.sh` which stages a build context, triggers an OpenShift BuildConfig (binary strategy), and waits for rollout. The Deployment spec includes `imagePullPolicy: Always` to prevent stale image caching.

## Implemented Tool Surface

### Phase 1: Core Memory Operations (7 tools)

| Tool | Purpose | Read/Write |
|------|---------|------------|
| `register_session` | Compatibility shim for clients that can't send HTTP auth headers; primary auth is via JWT bearer tokens | Setup |
| `write_memory` | Create memory nodes and branches, with inline curation feedback | Write |
| `read_memory` | Retrieve memory by ID, with optional version history | Read |
| `update_memory` | Create new version of a memory, preserving history | Write |
| `search_memory` | Semantic search via pgvector embeddings, with optional session focus / two-vector retrieval (Layer 2, #58) | Read |
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

### Phase 3: Lifecycle (1 tool)

| Tool | Purpose | Read/Write |
|------|---------|------------|
| `delete_memory` | Soft-delete a memory and its entire version chain (#42) | Write |

### Curation Pipeline

`write_memory` runs an inline curation pipeline before persisting:

1. **Tier 1 (regex)**: Secrets detection (AWS keys, GitHub tokens, private key headers) and PII detection (SSN, email, phone). Blocks or flags based on curation rules.
2. **Tier 2 (embedding)**: Cosine similarity against existing memories in the same (owner_id, scope). Rejects exact duplicates (>0.95), flags possible duplicates (0.80-0.95).

The write response includes curation feedback: `similar_count`, `nearest_id`, `nearest_score`, and `flags`. The calling agent's LLM decides what to do with ambiguous cases -- no MCP sampling is used, avoiding the HITL approval friction.

### Curation Rules Engine

Three-layer rules (system > organizational > user) with override protection. System rules for secrets scanning are marked `override=true` and cannot be weakened by user rules. Users tune their own dedup thresholds via `set_curation_rule`.

## Search response shape (Layer 1, #56/#57)

`search_memory` returns a mix of full content and lightweight stubs, with three knobs that callers can use to control how much detail comes back:

- **`mode`** — `"full"` (default) returns full content for weight ≥ `weight_threshold` and stubs below it; `"index"` returns stubs for everything regardless of weight (for exploratory or audit searches); `"full_only"` ignores `weight_threshold` so weight alone never causes stubbing.
- **`max_response_tokens`** — soft cap on the entire response (default 4000). Results are packed in similarity order; once the cap is reached, remaining matches degrade to stubs but are still included so the agent never silently misses a ranked match.
- **`include_branches`** — by default, branches whose parent is also in the result set are dropped (the agent can drill in via `read_memory` using the parent's `has_rationale` / `has_children` flags). Set `True` to nest them under the parent in a `branches` field instead. Branches whose parent is not in the result set are always returned as top-level entries.

Every result entry includes a `result_type` (`"full"` or `"stub"`) and a `relevance_score`. Pagination metadata in the response (`total_matching`, `has_more`) lets callers tell when more matches exist beyond `max_results`.

## Session focus retrieval (Layer 2, #58)

When the caller passes a `focus` string to `search_memory`, retrieval routes through `search_memories_with_focus` instead of plain pgvector cosine. The pipeline is:

1. **Recall.** pgvector cosine top-K=32 by query embedding (no change from the no-focus path).
2. **Rerank.** Cross-encoder rerank by query against the candidate set, using a `ms-marco-MiniLM-L12-v2` model deployed on RHOAI vLLM serving. The reranker URL is configured via `MEMORYHUB_RERANKER_URL`.
3. **Blend.** Reciprocal-rank fusion of the rerank ranks with focus cosine ranks, weighted by `session_focus_weight` (default 0.4 from the schema; benchmark suggests 0.2-0.4 is the sweet spot).
4. **Pivot signal.** Cosine distance from query to focus is computed; when it exceeds `pivot_threshold` (default 0.55), the response carries `pivot_suggested: true` and a human-readable `pivot_reason`.

The focus path is **stateless** — `focus` is passed per call rather than stored on a session. This avoided every coordination question about session state and Valkey. The cost is one re-embed of the focus string per call (~50ms with a warm vLLM); the benefit is horizontal scalability without coordination.

Focus is fully optional. When `focus` is omitted (or `session_focus_weight ≤ 0`), the entire focus path short-circuits and `search_memory` falls through to plain Layer 1 cosine retrieval — no rerank latency, no pivot computation, no behavior change from the no-focus path.

The cross-encoder is graceful-fallback: if `MEMORYHUB_RERANKER_URL` is unset or unreachable, the response carries a `focus_fallback_reason` field documenting the fallback and ranking falls back to pure cosine. The system stays usable even when the reranker pod is unhealthy.

Empirical benchmark methodology and the four-way comparison (NEW-1 RRF blend vs NEW-2 focus-augmented query vs NEW-3 rerank-only vs cosine baseline) live in [`research/agent-memory-ergonomics/two-vector-retrieval.md`](../research/agent-memory-ergonomics/two-vector-retrieval.md). NEW-1 won; NEW-2 was eliminated for catastrophic cross-topic recall collapse; NEW-3 alone was neutral on the synthetic corpus.

## Authentication

The MCP server is a **resource server** in OAuth 2.1 terms — it validates JWTs but does not issue them. A separate OAuth 2.1 authorization service ([`memoryhub-auth/`](../memoryhub-auth/)) handles token issuance via three grant types: `client_credentials` (agents/SDKs, shipped), `authorization_code` + PKCE (browser-based humans, used by the dashboard via the OpenShift OAuth proxy), and token exchange / RFC 8693 (platform-integrated agents on RHOAI/K8s, designed but not yet wired).

FastMCP's `JWTVerifier` validates tokens at the transport layer before any tool code executes. Tools access the authenticated identity via `get_claims_from_context()` in `core/authz.py`, which prefers JWT claims when present and falls back to a session shim when the dev-path API key flow is in use. The claims provide `sub` (user ID), `identity_type` (user/service), `tenant_id` (multi-tenant isolation), and `scopes` (operational permissions like `memory:read:user`, `memory:write:project`).

Service-layer RBAC enforcement shipped with the auth work: every tool calls `authorize_read()` or `authorize_write()` from `core/authz.py` before any service-layer call. `search_memory` builds the authorized-scopes filter at the SQL level so RBAC violations are impossible by construction. Cross-reference tools (`get_similar_memories`, `get_relationships`) do post-fetch filtering and report an `omitted_count` so callers know when something was hidden. See [governance.md](governance.md) for the full enforcement architecture.

The `register_session` tool is retained as a compatibility shim for MCP clients that cannot send HTTP Authorization headers (due to client bugs or limitations). It accepts an API key and writes a session shim that produces the same claim structure as a real JWT. It is not the primary auth path and is intended to be removed once all consumers move to OAuth.

## Error Handling

MCP tools return clear, actionable errors as `{"error": true, "message": "..."}` dicts. Error messages explain what went wrong AND how to fix it:

- "Invalid relationship_type 'friends_with'. Must be one of: derived_from, supersedes, conflicts_with, related_to."
- "Write blocked by curation rule: secrets_scan. Content matches aws_access_key pattern (AKIA...MPLE)."
- "Memory node abc-123 not found. Verify both source_id and target_id refer to existing, current memory nodes."

## Design Questions (Resolved)

- **Should `get_context` exist?** No. Agents compose `search_memory` + `read_memory` themselves. This gives agents control over their context budget and avoids a monolithic tool.
- **Should `get_branches` be a separate tool?** No. `read_memory(depth=1)` returns branches inline. One tool, fewer round-trips.
- **How does write_memory handle concurrent writes?** Blocking for user-scope (direct write). Above-user-scope queued for curator review (not yet implemented).
- **How do agents without OpenShift identity connect?** API keys exchanged for JWTs via the `client_credentials` OAuth grant. The `memoryhub` Python SDK handles this transparently. `register_session` remains as a fallback for MCP clients with header limitations.
- **Max results granularity for search?** `max_results` parameter (default 10, max 50) plus weight-based stub/full split. Agents control page size. Issue #57 added a `mode` parameter (`full` / `index` / `full_only`) and a `max_response_tokens` soft cap (default 4000) so agents can ask for index-only previews or zero-round-trip full content explicitly. See `agent-memory-ergonomics/design.md` for the rationale on why size-based stubbing was rejected in favor of weight + token budget.
- **How should `search_memory` handle branches relative to their parent?** Default behavior (Issue #56) drops branches whose parent is also in the result set — agents drill in via `read_memory` using the parent's `has_rationale` / `has_children` flags. Set `include_branches=true` to receive those branches nested under their parent in a `branches` field rather than ranked as siblings. Branches whose parent is **not** in the result set always surface as top-level entries with `parent_id` populated.
- **Should focus state be stored on a session or passed per call?** Stateless per-call (Issue #58). Storing focus on `register_session` would have introduced coordination/scaling questions about pod-local state vs Valkey vs database; per-call avoids them entirely. The cost is one re-embed of the focus string per call, which is negligible against the rerank latency. When #62 (Pattern E push) needs a stored session vector for broadcast filtering, Valkey is the right home and that change is additive rather than blocking.
- **Should curation use LLM sampling?** No. MCP spec requires HITL approval for sampling, which is unacceptable friction on write operations. Instead, `write_memory` returns similarity counts and the calling agent's existing LLM handles judgment calls.

## Design Questions (Open)

- Rate limiting: should the MCP server enforce per-agent rate limits? Not needed at current scale (single user), but relevant for multi-tenant deployment.
- Should there be an `import_memory` tool for bulk ingestion from Claude Code's local memory files? Useful for onboarding but adds complexity.
- Connection pooling: the MCP server creates a new SQLAlchemy session per tool call. At scale, connection pooling (PgBouncer) may be needed.
