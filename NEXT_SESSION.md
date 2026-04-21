# Next Session Plan

## Completed this session (2026-04-20)

### #195 — RHOAI tile breaks on pod restart (closed)
- ExternalName Service tested first — does NOT work with OpenShift Routes
  (HAProxy resolves via Endpoints, not DNS)
- Fix: Endpoints now point at the memoryhub-ui Service's ClusterIP instead
  of the pod IP. ClusterIPs are stable across pod restarts, rollouts, and
  node migrations. Verified by restarting the pod (IP changed) and
  confirming the tile still returned HTTP 200.

### #170 Phase 1 — Graph-enhanced retrieval (closed, remaining work done)
- `collect_graph_neighbors` in services/graph.py: recursive CTE traversal
  from seed nodes, bounded by max_depth (hard cap 3), filters tenant/
  deleted/active edges/relationship types, returns {node_id: min_hop_distance}
- Wired into `search_memories_with_focus` as 4th RRF signal alongside
  query, focus, and domain. Configurable `graph_boost_weight` (default 0.2)
- `search_memory` MCP tool gains `graph_depth`, `graph_relationship_types`,
  `graph_boost_weight` parameters. Response gains `graph_neighbors_added`
  and `graph_fallback_reason` when graph_depth > 0
- `graph_depth=0` (default) is a complete no-op — zero behavior change
- 30 new tests (23 core + 7 MCP)

### #103 — resolve_contradiction + Tool consolidation 15 → 10
- Alembic migration 014: `resolution_action` and `resolved_by` columns on
  `contradiction_reports`
- `resolve_contradiction` service function gains `resolution_action` and
  `actor_id` parameters
- Tool consolidation motivated by Anthropic's "Writing effective tools
  for AI agents" guidance:
  - `manage_session` (status / set_focus / focus_history) replaces
    get_session + set_session_focus + get_focus_history
  - `manage_graph` (create_relationship / get_relationships / get_similar)
    replaces create_relationship + get_relationships + get_similar_memories
  - `manage_curation` (report_contradiction / resolve_contradiction / set_rule)
    replaces report_contradiction + set_curation_rule; adds resolve
  - `manage_project` stays separate (unchanged)
- 664 tests passing (347 core + 317 MCP), deployed as build 13

### #100 — Cross-encoder re-benchmark (deferred)
- 131 current memories, ~13% of the ~1000+ target
- Single user, no content diversity — not statistically meaningful
- Commented on issue with revisit criteria

## Priority items for next session

### 1. Quick fixes from retro
- Fix `register_session` tool description: still says "Check remaining
  time with get_session" — should reference `manage_session(action="status")`
- File issue for SDK update to reflect consolidated tool names (if SDK
  has tool-specific helpers that reference old names)

### 2. #170 Phase 2 — Entity extraction (next graph phase)
Design doc is at docs/graph-enhanced-memory.md Phase 2. Adds:
- Entity nodes (scope="entity", branch_type="entity:person" etc.)
- MENTIONS relationship type
- Multi-stage extraction pipeline (spaCy → GLiNER2 → LLM fallback)
- Entity-aware search (filter by entity names)
New dependencies: spaCy, GLiNER2

### 3. Design doc implementation roadmap (deferred per user request)
After #170 Phase 2, implementation proceeds in dependency order:
- #168 — Conversation persistence (3-5 sessions)
- #169 — Context compaction (5-7 sessions) — user wants to wait
- #171 — Knowledge compilation (6-8 sessions) — user wants to wait

## Context
- SDK v0.6.0 on PyPI
- CLI v0.4.0
- MCP server **v0.8.0**, 10 tools deployed (build 13), verified via mcp-test-mcp
- Alembic migrations through 014 applied
- Ruff: 0 errors
- All tests passing: 317 MCP + 347 core = 664 total

## Cluster state
- Cluster: **mcp-rhoai** context (n7pd5, sandbox5167)
- MCP server: memory-hub-mcp namespace (build 13, v0.8.0, 2026-04-21)
- DB: memoryhub-db namespace, migrations through 014 applied
- Auth: memoryhub-auth namespace
- UI: memoryhub-ui namespace (RHOAI tile now uses ClusterIP Endpoints)
- MinIO: memory-hub-mcp namespace
- Valkey: memory-hub-mcp namespace
