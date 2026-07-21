# Session Summary -- 2026-07-21 -- Install testing & docs

**Plan:** Ad-hoc install validation on fresh clusters   **Commits:** 5fed05d..248fdc2 (feat/dreaming-ablation-results)
**Deployed:** Two fresh test clusters (memory-hub-install-test-2, memory-hub-install-test-3)   **Model:** Opus 4.6

## Plan vs. actual
Planned: Test `make install` end-to-end on fresh clusters, fix docs. Shipped: Full install validated on two clusters, README post-install guide added, workshop-setup scripts hardened, seed script created. Scope stayed tight.

## Shipped
- `248fdc2` docs: Post-install guide (API key retrieval, CLI install, Claude Code connection, RHOAI dashboard walkthrough), fixed `claude mcp add` syntax, fixed `make uninstall` flag syntax, added `scripts/seed-sample-data.py`
- workshop-setup `4c64bd9` fix: Removed duplicate OperatorGroup that silently blocked RHOAI InstallPlan
- workshop-setup `613df1e` fix: Added `--context` flag to setup.sh and setup-rhoai.sh, removed hardcoded CSV versions
- workshop-setup `15db9c8` fix: Phased operand application to avoid CRD race condition on fresh clusters

## Verification & confidence
- Both clusters installed end-to-end: prereq check, full deploy, MCP roundtrip (register + write + search)
- Seed script tested on cluster 2 with real data (10 memories, 2 relationships)
- Confidence: high -- two independent fresh-cluster runs, zero manual intervention on cluster 3

## Judgment calls & deviations
- Used Python SDK for seed script instead of raw curl -- cleaner, more maintainable, SDK is already a documented dependency
- Changed `make uninstall` docs to show direct script invocation rather than adding Makefile passthrough targets -- simpler and honest about how Make works

## Backlog delta
Filed: none. Closed: none. Pre-existing: CI Secret Scanning false positive on example ConfigMap (not new).

## Drift & forward-collisions
- Backward: none
- Forward: none

## For the reviewer
- Sanity-check: the seed script's memory content is reasonable/realistic for a demo
- Thin verification: local test suite hangs (CI passes); root cause not investigated
- Wants guidance: none

## Risks / watch-fors
- Local pytest hangs may indicate a venv or import issue worth investigating in a future session
- The `users-configmap.example.yaml` false positive in CI Secret Scanning should get a gitleaks allowlist entry eventually
