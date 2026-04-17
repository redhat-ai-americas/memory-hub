# Next Session Plan

## Completed this session (2026-04-17)

### Golden test — found and fixed
- Ran `scripts/uninstall-full.sh --skip-db --yes && scripts/deploy-full.sh`.
  Failed at seed-oauth-clients: deploy-full.sh was overwriting the DB
  credentials Secret with a placeholder from `deploy/postgresql/secret.yaml`.
- Fix: removed secret.yaml from kustomization, added idempotent Secret
  generation to `deploy_postgresql()` (openssl rand on first install,
  skip-if-exists). Created `scripts/run-seed-oauth-clients.sh` wrapper
  (port-forward pattern matching run-migrations.sh).
- Second bug found during test: MCP namespace `memoryhub-db-credentials`
  Secret had a hardcoded placeholder in `openshift.yaml`. Added post-deploy
  password sync step to `deploy_mcp()`.
- Re-ran golden test (preserve-DB variant): full pass, all services up.
- CLAUDE.md updated: golden test rule now documents both variants
  (preserve-DB and full-fresh) with correct script invocations.

### Agent DX improvements (MCP server v0.5.1 → v0.6.0)
- Ran agent usability test (sub-agent self-enrollment). Initial DX rating: 4/5.
- Fix 1: Corrected API key format hint (`mh-dev-<hex>` not `mh-dev-<username>-<year>`).
- Fix 2: `search_memory` with `project_id` now filters to that project only
  (was returning results from all member projects).
- Fix 3: Added "Quick start" section to `search_memory` docstring.
- Fix 4: New `get_session` tool (lightweight whoami, 15th tool).
- Fix 5: `list_projects` now returns `memory_count` per project.
- Fix 6: Labeled 11 search_memory params as "(Advanced)" to reduce
  cognitive load for first-time users.
- Fix 7: Added `project_description` param to `write_memory` for auto-create.
- Final DX rating: 4.5/5.
- Wrote `docs/agent-integration-guide.md` for onboarding other agent sessions.

### Resolved from prior session
- CLAUDE.md pre-session modification (item #5): was already clean, no action needed.

## Priority items for next session

### 1. Red Hat managed — read odh-dashboard source

Before committing to Path 1 (submit upstream PR) or Path 2 (bundle into
RHOAI operator), read the actual odh-dashboard source at
github.com/opendatahub-io/odh-dashboard to confirm the "validation is
hardcoded per-app" theory. If there IS a generic validator path, the fix
is simpler than we think.

### 2. Close #188 (project membership friction)

The auto-enrollment flow works end-to-end (verified this session). The
remaining structural items from #188 (explicit project management tools,
guided discovery, session TTL) should be triaged: close the issue with
a comment documenting what shipped, or file new issues for the structural
items and close #188 as the auto-enrollment fix.

### 3. Design doc implementation

The 6 design docs are candidates for implementation. In ascending scope:
- **#166** (project-governance) — smallest, good warm-up
- **#170** Phase 1 (graph-enhanced memory) — temporal validity + RRF
- **#168** (conversation-persistence) — new subsystem
- **#169** (context-compaction) — extends existing curator
- **#171** (knowledge-compilation) — composes all three, largest scope

### 4. Ruff lint cleanup

434 errors (was 71 last session — growth is from new code + ruff version
changes). Not blocking but increasingly visible in session-close checks.

### 5. DX push to 5/5

Remaining structural items from the usability test:
- Explicit project management tools (create, describe, list members)
- Progressive discovery in register_session response
- Session TTL / explicit expiry for predictable auth lifecycle
These are the "second category" items deferred from this session.

## Context
- SDK v0.6.0 on PyPI (v0.6.1 unreleased: project_id field in ProjectConfig)
- CLI v0.4.0
- MCP server **v0.6.0**, 15 tools deployed
- Curation thresholds: exact_duplicate 0.98, near_duplicate gate 0.90,
  flag 0.80
- min_appendix=5

## Cluster state
- Cluster: **mcp-rhoai** context (n7pd5, sandbox5167). The old
  "workshop-cluster" context name no longer exists — it was renamed
  to `mcp-rhoai`. **Pass `--context mcp-rhoai` on every `oc` / `kubectl`
  command.**
- `scripts/cluster-health-check.sh` uses the default context; its
  output may be misleading if context drifts.
- DB password was reset this session (golden test recovery). All
  namespace Secrets are in sync. The password is NOT the original
  `memoryhub-dev-password` — it was regenerated.
- gpt-oss-20b: `gpt-oss-model-2` namespace
- MCP server: memory-hub-mcp namespace (rebuilt 2026-04-17)
- MinIO: memory-hub-mcp namespace
- Valkey: memory-hub-mcp namespace
- Auth: memoryhub-auth namespace (rebuilt 2026-04-17)
- UI: memoryhub-ui namespace (rebuilt 2026-04-17)
- DB: memoryhub-db namespace, migrations through 012 in sync
- OdhApplication: `redhat-ods-applications/memoryhub` (category: Red Hat
  managed — hack, see investigation notes)
