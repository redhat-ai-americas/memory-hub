# Next Session Plan

## Completed this session
- Fixed project-scoped read/update/delete RBAC: `node_to_read()` was
  dropping `scope_id` and `domains` when converting ORM to Pydantic,
  so `authorize_read`/`authorize_write` always saw `scope_id=None`.
  Root cause was one layer deeper than the NEXT_SESSION.md description
  suggested -- the #167 tool-layer wiring was correct but inert.
- Regression test added: `test_read_memory_preserves_scope_id_and_domains`
- Cleaned up enrollment-test project and membership from DB
- MCP server v0.5.1 deployed (build #27), verified end-to-end:
  write -> read -> delete all pass for project-scoped memories

## Priority items for next session: Bugs

### 1. #119 Translate upstream embedder errors into structured tool responses
Embedding service errors (e.g., connection failures, timeouts) currently
propagate as unstructured exceptions. Agents can't distinguish "embedder
down" from "bad input" and can't recover gracefully.

### 2. #102 ui: BFF /api/memory/{id}/history backward-only walker follow-up
The history walker in the BFF only walks backward through the version
chain. Needs to also walk forward to find the current version from any
arbitrary version ID.

### 3. #84 storage: Handle embedding service 413 on long memory content
When memory content exceeds the embedding model's token limit, the
embedding service returns a 413. Currently this surfaces as an opaque
error. Should truncate or chunk gracefully with a clear message.

## Session after next: Design docs
Review and flesh out the 6 design docs tagged `needs-design`:
#171 (knowledge compilation), #170 (graph-enhanced retrieval),
#169 (context compaction / ACE), #168 (conversation thread persistence),
#166 (projects table governance), #109 (UI design doc).

## Context
- SDK v0.6.0 on PyPI (v0.6.1 unreleased: project_id field in ProjectConfig)
- CLI v0.3.0 (unreleased: --project/--non-interactive flags)
- MCP server v0.5.1, build #27, 14 tools deployed
- Curation thresholds: exact_duplicate 0.98, near_duplicate gate 0.90,
  flag 0.80
- min_appendix=5 (was 1)

## Cluster state
- Cluster: sandbox5167
- Granite 3.3 8B: granite-model namespace, vLLM
- MCP server: memory-hub-mcp namespace
- DB: memoryhub-db namespace, migrations through 012 in sync
