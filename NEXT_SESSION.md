# Next Session Plan

## Completed this session (2026-04-17, session 3)

### MCP server redeploy (progressive discovery)
- Verified deployed image was from build 8, predating progressive discovery
  commit 7b9ee93. Redeployed (build 9), verified via mcp-test-mcp that
  register_session returns projects and quick_start fields.

### #190 — Session TTL with auto-extend (closed)
- API-key sessions now have configurable TTL (default 1h via
  MEMORYHUB_SESSION_TTL_SECONDS) with auto-extend on every tool call
- register_session returns expires_at and session_ttl_seconds
- get_session returns expires_at, remaining_seconds, session_ttl_seconds
- Expired sessions raise clear errors directing re-registration
- JWT sessions unaffected (no TTL fields returned)
- 15 new tests, review caught and fixed stale-user-on-expiry bug

### #166 — Consolidated manage_project tool (closed)
- Replaced list_projects with manage_project: list, create, describe
  (with members + memory count), add_member, remove_member
- Follows Anthropic's tool design guidance on consolidation
- Security: add_member requires caller membership (admin for invite-only);
  remove_member requires admin or self-removal; creator auto-enrolled as admin
- Service layer gains create_project, get_project_members, add_project_member,
  remove_project_member; promoted _memory_counts to public API
- 28 tool tests; deployed as build 10; verified via mcp-test-mcp

### #170 Phase 1 prep — Temporal validity on relationships
- Alembic migration 013: valid_from (NOT NULL, default now(), backfilled from
  created_at) and valid_until (nullable) on memory_relationships
- Replaced absolute unique constraint with partial unique index on active
  edges only (WHERE valid_until IS NULL)
- ORM model updated with new columns and updated __table_args__
- Service layer: invalidate_relationship(), _active_edges_filter() helper
- get_relationships and trace_provenance accept as_of parameter
- find_related filters to active edges only
- RelationshipRead schema includes valid_from and valid_until
- Migration 013 applied to cluster DB, MCP server redeployed (build 11)
- Exercise-tools verified all 15 tools against live deployment
- DB credential drift discovered and fixed (openshift.yaml reverted to
  REPLACE-ME placeholder, cluster Secret patched directly)
- Version bumped to v0.7.0; docs updated (list_projects → manage_project)
- Filed #192 (deploy.sh should copy DB Secret instead of hardcoding)

## Priority items for next session

### 1. #170 Phase 1 — Graph-enhanced retrieval (remaining work)

Temporal validity infrastructure is done. The remaining work is the retrieval
enhancement itself:

**collect_graph_neighbors** — New function in services/graph.py:
- Recursive CTE bounded by max_depth (cap at 3)
- Takes seed_ids from vector search top-N results
- Returns {node_id: min_hop_distance} for all reachable neighbors
- Filters: tenant, not deleted, active edges, RBAC
- Design reference: docs/graph-enhanced-memory.md lines 121-134

**Wire into search_memories_with_focus** — Fourth RRF signal:
- After vector search returns top-k, call collect_graph_neighbors
- Graph proximity rank based on hop distance (1-hop > 2-hop)
- RRF blend with existing query, focus, and domain signals
- New graph_depth and graph_relationship_types parameters
- graph_depth=0 (default) skips traversal entirely — backward compatible
- FocusedSearchResult gains graph_neighbors_added field

**MCP tool changes** — search_memory gains two optional parameters:
- graph_depth (int, default 0, max 3)
- graph_relationship_types (list[str] | null)
- Response gains graph_neighbors_added and graph_fallback_reason fields

**Tests needed**:
- Unit tests for collect_graph_neighbors (varying depths, cycles, deleted nodes)
- Unit tests for RRF integration
- Integration test for full search path with graph enhancement

Design reference: docs/graph-enhanced-memory.md (Phase 1, "Graph-Enhanced
Retrieval" section)


### 2. #192 — deploy.sh credential drift fix

Standalone infrastructure fix. Remove hardcoded DB Secret from openshift.yaml,
add copy_secret step to deploy.sh. Third consecutive retro flagging this.

### 3. Design doc implementation roadmap (unchanged)

After #170 Phase 1 completes, implementation proceeds in dependency order:

**#168 — Conversation persistence (3-5 sessions)**
**#169 — Context compaction (5-7 sessions)**
**#171 — Knowledge compilation (6-8 sessions)**

See docs/ and planning/ for design references.

## Context
- SDK v0.6.0 on PyPI
- CLI v0.4.0
- MCP server **v0.7.0**, 15 tools deployed, exercised and verified
- Alembic migrations through 013 applied
- Ruff: 0 errors
- All tests passing: 304 MCP + 324 core = 628 total

## Cluster state
- Cluster: **mcp-rhoai** context (n7pd5, sandbox5167)
- MCP server: memory-hub-mcp namespace (build 11, v0.7.0, 2026-04-17)
- DB: memoryhub-db namespace, migrations through 013 applied
- Auth: memoryhub-auth namespace
- UI: memoryhub-ui namespace
- MinIO: memory-hub-mcp namespace
- Valkey: memory-hub-mcp namespace
- DB Secret: cluster Secret patched manually; openshift.yaml has REPLACE-ME
  placeholder (see #192 for permanent fix)
