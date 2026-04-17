# Next Session Plan

## Completed this session (2026-04-17, session 2)

### Ruff lint cleanup (439 → 0)
- Added per-file-ignores for perf fixture data (E501), SQLAlchemy forward
  refs (F821), and FastAPI Depends() idiom (B008)
- Fixed E402 across MCP tools (moved logger below imports) and integration
  tests (moved pytestmark below imports)
- Fixed SIM103/SIM102/SIM108/SIM117, B904, N817, UP038, F841
- Auto-fixed: unsorted imports, unused imports, datetime.timezone.utc,
  deprecated imports
- 694 unit tests pass across all three components after fixes

### Issue triage
- Closed #188 (project membership friction) — auto-enrollment shipped in
  v0.6.0, remaining structural items tracked in #166 and DX backlog
- Created #189 (progressive discovery in register_session)
- Created #190 (session TTL / explicit expiry)
- Updated #166 with DX context (project management tools as DX blocker)

### Progressive discovery (#189)
- register_session now returns project memberships (with memory_count)
  and quick_start hints in the response
- get_session also returns project memberships
- SDK SessionInfo uses extra="allow", so new fields are backward-compatible
- All 268 MCP server tests pass

### OdhApplication investigation (item #1)
- Read odh-dashboard source: validation is fully generic, no hardcoded
  app allowlist. "Red Hat managed" category gets a convenience shortcut.
  No upstream PR needed — the existing CR approach is confirmed correct.
- Finding saved to MemoryHub memory for future reference.

### Housekeeping
- Cleaned up 7 stale worktrees from previous sessions
- Updated CLAUDE.md cluster context: workshop-cluster → mcp-rhoai

## Priority items for next session

### 0. Redeploy MCP server

register_session and get_session were enhanced with progressive discovery
(#189) but the deployed image is still v0.6.0. Rebuild and redeploy to
memory-hub-mcp namespace before starting new work. Verify with
mcp-test-mcp that the new response fields appear.

### 1. Close DX backlog: #166 (project governance) + #190 (session TTL)

These are the two remaining items blocking a 5/5 DX rating. Both are
small enough to land in one session together.

**#166 — Project governance (1-2 sessions)**
The scope-isolation infrastructure (#46) already shipped. Remaining work:
- Add `projects` table (id, name, description, tenant_id, invite_only,
  created_at, created_by) — the implicit string IDs in
  project_memberships work but lack discoverability
- MCP tools: create_project, describe_project, list_members
- Admin API endpoints for the dashboard
- Use `/plan-tools` → `/create-tools` → `/exercise-tools` workflow for
  the new MCP tools
- Design reference: `planning/scope-isolation-project-role.md` (Open
  Question 3)

**#190 — Session TTL (1 session)**
- Add configurable TTL to register_session (default 1h)
- Return `expires_at` in response
- get_session includes remaining TTL
- Expired sessions return clear error directing re-registration
- Decide: auto-extend on activity vs explicit renewal?

### 2. Design doc implementation roadmap

After the DX backlog is closed, implementation proceeds in dependency
order. Each item is standalone except #171 which composes the others.

**#170 Phase 1 — Graph-enhanced retrieval (2-3 sessions)**
- Temporal validity columns on relationships (valid_from, valid_to)
- `collect_graph_neighbors` for graph-aware context injection
- RRF blending of vector similarity + graph traversal scores
- Standalone — no dependencies on other design docs
- Design reference: `docs/graph-enhanced-retrieval.md`

**#168 — Conversation persistence (3-5 sessions)**
- New subsystem: ConversationThread + ConversationMessage tables
- Thread-level RBAC, retention policies, S3 offload for large messages
- MCP tools: create/append/get/list threads, archive, fork, share
- Extraction provenance (conversation_extractions) links to memories
- Foundation that #169, #170 P2, and #171 all build on
- Design reference: `planning/session-persistence.md`

**#169 — Context compaction (5-7 sessions)**
- Four-layer policy-driven compression (memory store, retrieval-time
  token budget, conversation threads, cross-agent coordination)
- Extends existing curator with compaction tier and ACE pattern
- Hot/cold storage with MinIO, compaction provenance branches
- Benefits from #168 (conversation threads to compact)
- Design reference: `docs/context-compaction.md`

**#171 — Knowledge compilation (6-8 sessions)**
- LLM-driven pipeline: threads + memories + entities → versioned
  knowledge articles
- Distributed workers with HPA, compilation epochs (#175 already shipped)
- Depends on #168 + #170 Phase 2 + #169. Last in the sequence.
- Design reference: `docs/knowledge-compilation.md`

## Context
- SDK v0.6.0 on PyPI (v0.6.1 unreleased: project_id field in ProjectConfig)
- CLI v0.4.0
- MCP server **v0.6.0**, 15 tools deployed (register_session + get_session
  enhanced locally, not yet redeployed)
- Curation thresholds: exact_duplicate 0.98, near_duplicate gate 0.90,
  flag 0.80
- min_appendix=5
- Ruff: 0 errors (was 439 at start of session)

## Cluster state
- Cluster: **mcp-rhoai** context (n7pd5, sandbox5167)
- DB password was reset last session (golden test recovery). All
  namespace Secrets are in sync.
- MCP server: memory-hub-mcp namespace (rebuilt 2026-04-17)
- MinIO: memory-hub-mcp namespace
- Valkey: memory-hub-mcp namespace
- Auth: memoryhub-auth namespace (rebuilt 2026-04-17)
- UI: memoryhub-ui namespace (rebuilt 2026-04-17)
- DB: memoryhub-db namespace, migrations through 012 in sync
- OdhApplication: `redhat-ods-applications/memoryhub` (category: Red Hat
  managed — confirmed valid, no upstream PR needed)
