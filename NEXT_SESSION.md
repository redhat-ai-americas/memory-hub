# Next Session Plan

## Completed this session (2026-04-16)

### Design docs
- Drafted, committed, and pushed design docs for 6 needs-design issues
  (commit 8bc7856): #166 project-governance, #109 ui/design, #168
  conversation-persistence, #169 context-compaction, #170
  graph-enhanced-memory, #171 knowledge-compilation.
- Ran parallel review sub-agents across all 6 docs. Found 2 critical
  design issues (#170 missing partial unique constraint migration, #169
  content_ref dual-use collision) and ~15 minor fixes. All resolved in
  commit c8fc3c6.
- Linked each design doc from its issue with a summary comment.
- Removed `needs-design` label from #168, #169, #170, #171.
- #102 already closed (confirmed fixed by #63).

### Agent ergonomics consult
- Consulted with sibling Claude Code session building demo-chat-agent:
  register_session is a tool call (not HTTP header), proposed
  BaseAgent.connect_mcp auth extension pattern, system prompt block
  for gpt-oss-20b memory tool usage.

### Red Hat managed indicator investigation
- Verified 2026-04-16: switching OdhApplication to Self-managed disables
  the launch link. Self-managed tiles require either a csvName (installed
  Operator CSV) or an enable block (hardcoded per-app validator in
  dashboard source). Neither applies. Reverted to Red Hat managed.
- Two forward paths: (1) submit odh-dashboard PR registering a
  MemoryHub validator, (2) bundle into RHOAI operator's reconciled set.
- Findings documented in odh-application.yaml comments and the retro.

### Install polish + migration
- Created `scripts/check-prereqs.sh` (8 checks), `scripts/uninstall-full.sh`
  (full teardown with --skip-db and --yes flags).
- Extended `scripts/deploy-full.sh` with UI deploy, RHOAI tile apply,
  prereq verification, and summary banner.
- Renamed root `make install` (was venv setup) to `make dev`. New
  `make install` is the cluster install entry point. Added `make uninstall`,
  `make check-prereqs`, `make deploy-ui`, `make deploy-tile`.
- Fixed UI namespace drift: `memoryhub-ui/deploy/deploy.sh` was hardcoded
  to `memory-hub-mcp`; fixed to `memoryhub-ui`. Stripped hardcoded
  namespace refs from openshift.yaml and oauth-proxy-sa.yaml.
- Ran live migration on workshop cluster (`make uninstall --skip-db`
  then manual install). Discovered 5 categories of drift debt: MinIO +
  Valkey deployment, SCC grants, cross-namespace Secrets, auth admin key,
  UI proxy/admin Secrets. All wired into deploy-full.sh (commit d67ec5e).
- CLAUDE.md updated with golden test rule, cross-namespace Secret rule,
  SCC grant rule.

## Priority items for next session

### 1. Golden test verification (blocking)

Run `make uninstall --skip-db && make install` end-to-end on the
workshop cluster to verify that deploy-full.sh is fully self-contained
after the d67ec5e fixes. The current cluster is working because we fixed
things manually during the migration — we haven't proven the script
works from scratch yet. This MUST pass before declaring the install
story complete.

### 2. Red Hat managed — read odh-dashboard source

Before committing to Path 1 (submit upstream PR) or Path 2 (bundle into
RHOAI operator), read the actual odh-dashboard source at
github.com/opendatahub-io/odh-dashboard to confirm the "validation is
hardcoded per-app" theory. If there IS a generic validator path, the fix
is simpler than we think.

### 3. Design doc implementation (from the design-docs retro)

The 6 design docs are candidates for implementation. In ascending scope:
- **#166** (project-governance) — smallest, good warm-up
- **#170** Phase 1 (graph-enhanced memory) — temporal validity + RRF
- **#168** (conversation-persistence) — new subsystem
- **#169** (context-compaction) — extends existing curator
- **#171** (knowledge-compilation) — composes all three, largest scope

### 4. Ruff lint cleanup

71 pre-existing errors (13 root + 58 MCP). Not blocking but increasingly
visible in session-close checks. Quick cleanup session.

### 5. CLAUDE.md pre-session modification

CLAUDE.md has been showing as modified pre-session for 3+ sessions.
Run `git diff CLAUDE.md` at next session start and commit or revert.

## Context
- SDK v0.6.0 on PyPI (v0.6.1 unreleased: project_id field in ProjectConfig)
- CLI v0.3.0 (unreleased: --project/--non-interactive flags)
- MCP server v0.5.1, build #27 (rebuilt during this session's migration),
  14 tools deployed
- MinIO deployed to memory-hub-mcp namespace (rebuilt during migration)
- Valkey deployed to memory-hub-mcp namespace (rebuilt during migration)
- Curation thresholds: exact_duplicate 0.98, near_duplicate gate 0.90,
  flag 0.80
- min_appendix=5 (was 1)

## Cluster state
- Cluster: workshop-cluster (n7pd5, sandbox5167). **Pass `--context
  workshop-cluster` on every `oc` / `kubectl` command.** The default
  kubeconfig context is currently workshop-cluster (may drift).
- `scripts/cluster-health-check.sh` uses the default context; its
  output may be misleading if context drifts.
- gpt-oss-20b: `gpt-oss-model-2` namespace, verified live
- MCP server: memory-hub-mcp namespace (rebuilt 2026-04-16)
- MinIO: memory-hub-mcp namespace (rebuilt 2026-04-16)
- Valkey: memory-hub-mcp namespace (rebuilt 2026-04-16)
- Auth: memoryhub-auth namespace (rebuilt 2026-04-16)
- UI: **memoryhub-ui** namespace (migrated from memory-hub-mcp, 2026-04-16)
- DB: memoryhub-db namespace, migrations through 012 in sync (preserved
  through migration with --skip-db)
- OdhApplication: `redhat-ods-applications/memoryhub` (category: Red Hat
  managed — hack, see investigation notes)
