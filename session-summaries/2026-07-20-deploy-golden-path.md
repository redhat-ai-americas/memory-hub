# Session Summary -- 2026-07-20 -- deploy -- Fix golden path for fresh cluster installs

**Plan:** Colleague unable to deploy on fresh cluster   **Commits:** 4705d05..96f1006 (main, via PRs #442-#446)
**Deployed:** memory-hub-fips (zks6c)   **Model:** Opus 4.6

## Plan vs. actual
Planned: analyze and fix why deploy-full.sh fails on fresh clusters, validate by redeploying. Shipped: all 7 identified issues fixed + self-contained install + smoke test. Scope expanded from "fix the breakages" to "make it a true single-command install."

## Shipped
- `4705d05` (#442) -- Dynamic URL resolution for auth/embedding/reranker, CPU model deployment added to deploy-full.sh, retention CronJob fixed, OAuthClient redirect URI dynamic, deploy order changed (auth before MCP), model namespaces in uninstall
- `0a0b9a2` (#443) -- Write-up of what was broken and fixed (docs/deploy-golden-path-fixes.md)
- `b4c53d8` (#444) -- README install guide rewritten with full deployment details, Makefile partial targets updated
- `db87703` (#445) -- Auto-venv, auto-generate users-configmap, auto-write API key, smoke test
- `96f1006` (#446) -- Default to current oc context (was hardcoded to mcp-rhoai)

## Verification & confidence
- Full teardown + fresh deploy on memory-hub-fips: all 7 pods running, 26 migrations applied, auth healthz OK, MCP responding, embedding/reranker URLs dynamically resolved, retention CronJob secret refs validated, zero hardcoded cluster URLs remain (grep verified).
- Confidence: **high** for the deploy fixes themselves; **medium** for the self-contained install flow (auto-venv, auto-configmap) -- not yet validated end-to-end from a clean clone.

## Judgment calls & deviations
- Chose CPU models (all-MiniLM-L6-v2, ms-marco-MiniLM-L12-v2) as default over GPU granite models. User confirmed "CPU default, GPU optional." Same 384-dim embeddings, code-compatible.
- Reordered deploy-full.sh (auth before MCP) to avoid chicken-and-egg on JWKS URL resolution. No functional impact since auth doesn't depend on MCP.
- Auto-generating users-configmap.yaml trades security for convenience -- random keys are generated but the file is gitignored and not rotated. Acceptable for dev/eval; production should use operator-managed keys.

## Backlog delta
Filed: none. Closed: none. Deferred: none.

## Drift & forward-collisions
- Backward -- none identified.
- Forward -- none identified.

## For the reviewer
- Sanity-check: the auto-generate-configmap behavior is a convenience trade-off; the generated keys are random hex but not operator-vetted.
- Thin verification: the self-contained flow (clone + make install with no manual steps) has not been tested end-to-end from a clean clone yet.
- Wants guidance: none.

## Risks / watch-fors
- The `tests/perf/test_cross_encoder.py` test has a hardcoded URL to the old n7pd5 cluster's embedding service. Pre-existing but should be parameterized.
- CI on main shows CLI Tests and Integration Tests failing (pre-existing, not from this session). Likely from the parallel session's changes.
