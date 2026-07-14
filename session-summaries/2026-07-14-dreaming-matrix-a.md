# Session Summary -- 2026-07-14 - Dreaming - Matrix A Execution + H6 Audit

**Plan:** NEXT_SESSION-dreaming.md / #365, #342, #360   **Commits:** e9c96c9..e99b18f (bench/matrix-a, fix/evalhub-pg-persistence, feat/reranker-upgrade)
**Deployed:** dev (EvalHub PG, GPU reranker, MCP server redeployed via golden test)   **Model:** Opus 4.6

## Plan vs. actual
Planned: #365 (EvalHub PVC) then #342 (reranker GPU) then #360 (Matrix A), strictly sequential. Shipped: all three plus the H6 context-delivery audit that was listed as "3b, if time permits." Slipped: none.
Scope: expanded to include H6 audit after Matrix A results pointed at content delivery as the root cause.

## Shipped
- `e9c96c9` EvalHub switched from SQLite to PostgreSQL for persistent state (#365, PR #384)
- `140490d` bge-reranker-v2-m3 deployed on L40S GPU, replacing ms-marco-MiniLM-L12-v2 (#342, PR #385)
- `bf489bc` Matrix A: 4 configs x 589 queries, all at 46.5% (274/589) (#360, PR #386)
- `14f9902` H6 audit: confirmed MCP delivers 5.2x less context than BM25-local
- `e99b18f` H6 audit report at benchmarks/results/h6-content-delivery-audit.md

## Verification and confidence
- EvalHub PG: provider survived pod deletion + restart (live verification)
- Reranker GPU: /info and /rerank endpoints verified, golden test (preserve-DB) passed in 7m7s
- Matrix A: all 4 runs completed (589 queries each, ~20 min each), preflight before first run
- H6 audit: side-by-side BM25 vs MCP context dump for 5 queries, DB content length verified
- Confidence: **high** on all findings. The 274/589 identity across all 4 configs is deterministic, not statistical.

## Judgment calls and deviations
- EvalHub: session plan said PVC for SQLite, but `pvcManaged`/`pvcName` are on the lmevaljob CRD (job outputs), not the evalhubs CRD (server DB). Switched to PostgreSQL instead -- correct per verify-before-propagating rule.
- deploy-full.sh: moved `prepare_auth_infra` before `deploy_mcp` to fix a pre-existing race where the MCP pod started before the auth secret existed.
- Added `amb-benchmark` tenant user to the MCP users.json configmap -- benchmark data is in that tenant but no API key existed for it.
- Installed local SDK editable in harness to get `disabled_signals` support (not yet published to PyPI). Reverted the pyproject.toml at session close.

## Backlog delta
- Closed (via PRs, pending merge): #365, #342, #360
- New finding (not yet filed): H6 content truncation defect -- `s3_prefix_chars=1000` truncates all memories >1024 bytes at write time; search never hydrates from S3. This is the single largest performance blocker.

## Drift and forward-collisions
- Backward: #343 (chunking fix) -- Matrix A confirms chunking cannot differentiate until H6 is fixed. The exit predicate ("chunked >= unchunked baseline") is unreachable while the baseline itself is truncated. Re-scope candidate.
- Forward: The H6 finding (search must hydrate from S3 or raise the inline threshold) is prerequisite for any retrieval quality work. It touches services/memory.py write + search paths.

## For the reviewer
- Sanity-check: the 46.5% vector-only number vs the 70.8% #332 baseline. What changed between #332 and now? Was #332 run before S3 spill was enabled, so memories were stored inline at full length?
- Thin verification: the perf/cross_encoder test now hits a 503 on the old reranker URL (scaled to 0). Not fixed -- it's a perf test with a hardcoded URL.
- Wants guidance: should H6 be fixed by raising the inline threshold (Option B, simple) or by adding S3 hydration to the search path (Option A, correct long-term)? Option B is a one-line config change; Option A is a feature.

## Risks / watch-fors
- The `disabled_signals` parameter is in the local SDK but not published to PyPI. The EvalHub adapter (K8s job path) will also need the published SDK before Matrix A can run via EvalHub jobs.
- Two docs reference the old reranker model name (ARCHITECTURE.md, SYSTEMS.md). Low priority but will confuse readers.
- The old ms-marco reranker is scaled to 0 but still deployed. Could be deleted to free namespace clutter.
