# Retrospective: Infrastructure Automation + Integration Tests

**Date:** 2026-04-04
**Effort:** Curation rule seeding, deployment automation, manifest consolidation, integration tests
**Issues:** #18 (closed), #14 (closed), #15 (closed — de-scoped), #17 (closed)
**Commits:** 4e44cb2..a3cdc4c (10 commits)

## What We Set Out To Do

Three items: automate curation rule seeding (#18), close #4 on GitHub (retro action item), and create one-command deployment automation (#14). These were the quick-win infra items from the Phase 2 backlog.

## What Changed

| Change | Type | Rationale |
|--------|------|-----------|
| Alembic migration approach → port-forward + local alembic (not K8s Job) | Good decision | K8s Job requires either putting alembic in the MCP container or building a separate migration image. Port-forward is simpler and already proven. Job is the upgrade path for CI. |
| Discovered deploy.sh build context was missing memoryhub-core/ | Found during live verification | The Containerfile expected it but deploy.sh's inline build context never included it. build-context.sh handled it correctly but deploy.sh had diverged. |
| Consolidated two openshift.yaml files into one | Cleanup | deploy/openshift.yaml had production-quality settings (probe tuning, image-resolve annotation, DB credentials) but was unused. Template openshift.yaml was what deploy.sh actually used but was incomplete. Merged and deleted the unused copy. |

## What Went Well

- **Review sub-agents caught real bugs.** The `((WAITED++))` arithmetic bug under `set -e` would have broken every fresh deployment. The `$?` always-zero diagnostic message was also caught. The two-manifest divergence was found by a comparison sub-agent.
- **Live verification caught the build context gap.** The memoryhub-core/ missing from the build context would not have been found by any local test. Deploying to the cluster found it immediately.
- **Integration tests found a real service bug.** Cosine similarity scores could go negative because pgvector distance ranges [0, 2] and the service did `1.0 - distance` without clamping. This bug was invisible in SQLite tests — exactly the kind of thing #17 was meant to catch.
- **Clean commit separation.** Prep commits (manifest hardening, deploy.sh fixes) separated from feature commits (#18, #14), making each individually reviewable and revertable.
- **Lazy seeding design was simple and correct.** 8 lines of production code, idempotent, no event loop issues, self-healing on table wipe.
- **Fixture consolidation reduced 198 lines of duplication** across 3 test files down to a single shared conftest.

## Gaps Identified

| Gap | Severity | Resolution |
|-----|----------|------------|
| Port-forward migration approach won't work in CI or multi-developer setups | Accept for now | Fine for single-developer dev. Kubernetes Job or init container is the upgrade path when CI pipeline is built (#17). |
| deploy.sh and build-context.sh still have parallel build-context logic | Minor | deploy.sh now includes memoryhub-core but the two scripts could diverge again. Consider having deploy.sh call build-context.sh instead of inlining. |
| Hardcoded embedding URL is cluster-specific | Accept for now | The sandbox cluster URL is baked into the Secret. Documented with a warning comment. Will need parameterization for multi-cluster. |
| No `shellcheck` available locally | Minor | Several bash issues were caught by review sub-agents, but automated linting would catch more. |

## Action Items

- [x] Fix `((WAITED++))` bug in run-migrations.sh
- [x] Fix misleading `$?` in deploy-full.sh error message
- [x] Consolidate two openshift.yaml files
- [x] Include memoryhub-core/ in deploy.sh build context
- [x] Live-verify deployment against cluster (12 tools loaded, server healthy)
- [x] Integration tests against real PostgreSQL + pgvector (14 tests, all passing)
- [x] Fix cosine similarity score clamping bug found by integration tests
- [x] De-scope #15 (UBI pgvector image — not cost-effective for demo)
- [ ] Consider having deploy.sh delegate to build-context.sh to avoid parallel context logic

## Patterns

**Start:**
- Live-verifying deployment changes against the real cluster before closing the session. Found the memoryhub-core build context gap that no local test would have caught.
- Running comparison sub-agents on config files before deleting — the two-manifest comparison surfaced 6 production settings that would have been lost.

**Stop:**
- Nothing new this session.

**Continue:**
- Review sub-agents after implementation. Caught 2 real bugs in bash scripts this session (4e44cb2 session total: `((WAITED++))`, `$?` message, deploy.sh quoting, missing `-uo pipefail`).
- Discussing the plan before implementing. The port-forward vs K8s Job decision was made upfront, saving wasted effort.
- Filing clean prep commits separate from feature commits.
