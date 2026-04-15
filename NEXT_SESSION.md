# Next Session Plan

## Completed this session
- #188 project enrollment friction: auto-enrollment on project-scoped
  writes (open projects), list_projects MCP tool, CLI
  --project/--non-interactive flags, SDK project_id field in ProjectConfig
- Compiled-entry backfill in search pipeline (fixes displacement when
  high-similarity memories push compiled entries out of top-N)
- min_appendix raised from 1 to 5 (reduces recompilation frequency)
- Migration 012 (projects table) deployed
- MCP server rebuilt with 14 tools (build #26)
- Validation scripts updated (max_results workaround removed)

## Priority items for next session

### 1. Project-scoped delete_memory RBAC fix (HIGH)
delete_memory doesn't pass project_ids to authorize_write, so
project-scoped deletes fail even for the memory owner. Discovered during
validation. Should be a small fix in the delete tool to thread project_ids
through the authz call.

### 2. Cleanup from validation (LOW)
The enrollment-test project and its test memory created during validation
could be cleaned up.

### 3. #176 first 3 users (DEPRIORITIZED)
Still on the backlog but not blocking anything.

## Context
- SDK v0.6.0 on PyPI (v0.6.1 unreleased: project_id field in ProjectConfig)
- CLI v0.3.0 (unreleased: --project/--non-interactive flags)
- MCP server v0.5.0, build #26, 14 tools deployed
- Curation thresholds: exact_duplicate 0.98, near_duplicate gate 0.90,
  flag 0.80
- min_appendix=5 (was 1)

## Cluster state
- Cluster: sandbox5167
- Granite 3.3 8B: granite-model namespace, vLLM
- MCP server: memory-hub-mcp namespace
- DB: memoryhub-db namespace, migrations through 012 in sync
