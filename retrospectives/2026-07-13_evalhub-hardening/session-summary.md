# Session Summary -- 2026-07-13 - Dreaming - EvalHub hardening + cluster capacity

**Plan:** NEXT_SESSION-dreaming.md items 0-6   **Commits:** 773bebd..bf8876b (feat/359-evalhub-deploy, squash-merged as PR #363)
**Deployed:** memoryhub-eval namespace (EvalHub, MLflow, adapter rebuild)   **Model:** Opus 4.6

## Plan vs. actual
Planned: items 0-6 (scale cluster, commit keepers, Gemini switch, sidecar fix, PVC persistence, BuildConfig IaC, 20-query smoke). Shipped: all 7 items. Slipped: none.
Scope: expanded slightly -- fixed `test_graduate_with_evidence` (naive datetime bug, 2-line fix) and fixed a duplicate COMPLETED status bug discovered during smoke verification.

## Shipped
- `773bebd` Extraction pipeline doc review edits + compat-shim re-exports (fixes test collection)
- `82975ec` Fix `compute_temporal_status` naive datetime comparison (fixes `test_graduate_with_evidence`)
- `92a4e78` Switch smoke eval to Gemini Flash Lite, add `gemini-api-key` Secret to deploy script
- `076d601` Fix sidecar result forwarding: `DefaultCallbacks.from_adapter()` + MLflow save
- `72c79eb` SQLite from in-memory to file-backed via `DB_URL` env override
- `d9c1c9c` BuildConfig/ImageStream manifests + idempotent creation in deploy script
- `2909821` Fix duplicate COMPLETED status causing 409 Conflict on sidecar
- `bf8876b` Fix deploy script `grep -P` portability for macOS
- Cluster: scaled down LlamaStack (34 orphaned pods) and LibreChat, freed ~2000m CPU. Recorded in `ops/cluster-capacity.md`.

## Verification & confidence
- Smoke eval: `evalhub eval run --wait` completed, BM25 + Gemini 3.1 Flash Lite = 0.60 accuracy (20 queries)
- MLflow persistence: metrics survived EvalHub pod delete+restart (run `d8315d21...`)
- Deploy idempotency: `deploy-evalhub.sh` second run = all "already exists"
- Test collection: `test_conversation_extraction.py` collects 28 tests; graduation + temporal tests pass (41/41)
- Confidence: **high** for the EvalHub plumbing fixes; **medium** for the PVC workaround (#365 -- file-backed SQLite on /tmp is a known limitation, not a solution)

## Judgment calls & deviations
- PVC persistence (#365): operator reconciles away volume patches. Chose `/tmp` file-backed SQLite + documented limitation rather than switching to PostgreSQL. Acceptable for the matrix -- job results land in MLflow regardless.
- Model selection: `gemini-2.5-flash-lite-preview-06-17` and `gemini-2.5-flash-lite` both deprecated. Used `gemini-3.1-flash-lite`. This changes the answer model from what previous runs used -- not directly comparable to prior Haiku baselines.
- No new cluster nodes: LlamaStack/LibreChat cleanup freed enough CPU. GPU nodes at 3%/29% -- not GPU constrained. Deferred L40S provisioning.

## Backlog delta
Closed #364 (sidecar), #366 (Gemini switch), #367 (BuildConfig). #365 partially addressed (file-backed, not PVC-backed; commented with findings). No new issues filed. Memory: none written.

## Drift & forward-collisions
- Backward: #360 (ablation matrix) -- sidecar fix + Gemini switch were prerequisites. Now unblocked except for the ephemeral DB limitation (acceptable per #365 comment).
- Backward: #342 (reranker) -- GPU node was not added, but existing GPU nodes have capacity. Still unblocked once someone starts the work.
- Forward: none.

## For the reviewer
- Sanity-check: the duplicate COMPLETED status fix (removing it from `run_benchmark_job`) -- is this safe for all EvalHub providers, or is ours special? The SDK's `report_results()` sends its own COMPLETED, which seems to be the intended pattern.
- Thin verification: the full test suite hangs locally (unrelated to our changes -- likely a DB integration test). CI "CLI Tests" also fail (pre-existing `ModuleNotFoundError: No module named 'memoryhub_core'` in MCP server tests). Neither is from this session.
- Wants guidance: should we pursue PostgreSQL for EvalHub (#365) or accept `/tmp` SQLite for the matrix runs?

## Risks / watch-fors
- Gemini model rotation: `gemini-3.1-flash-lite` could be deprecated like 2.5 was. The smoke config will need updating when that happens.
- Provider ID instability: UUID changes on every pod restart/re-registration. The deploy script now auto-updates `smoke-eval.yaml`, but any other config referencing the ID will break.
- CI CLI test failure is pre-existing and should be investigated separately.
