# Session Summary -- 2026-07-16 -- Dreaming -- Granite Pro benchmark + reconciliation kickoff

**Plan:** NEXT_SESSION-dreaming.md (Phase 4.5 Pro validation + #347 kickoff)
**Commits:** 3fd31f1..51bf3a1 (feat/347-reconciliation)
**Deployed:** none   **Model:** Claude Opus 4.6

## Plan vs. actual
Planned: 25-query Pro spot-test, then full 589-query run, then #347 reconciliation kickoff.
Shipped: Full 589-query Granite Pro benchmark (84.9%) + complete #347 reconciliation implementation.
Slipped: none. Scope stayed in plan.

## Shipped
- `3fd31f1` reconciliation: stage contracts, decision log migration (025), threshold-based reconciliation with LLM tiebreaker, cheese test
- `9048855` test: updated extraction test mocks for reconciliation integration (28 tests passing)
- `ab54cba` benchmark: wired extract_facts env var through MemoryHub provider
- `51bf3a1` benchmark: recorded Granite Pro run (84.9%), added 120s request timeout to Gemini client

## Verification & confidence
- Reconciliation: 8 unit tests covering all threshold bands + cheese test + negative case (content_type mismatch) + decision log completeness. All pass on SQLite with mocked similarity.
- Existing extraction tests: 28 passing after mock target update.
- Benchmark: full 589-query PersonaMem run against live Granite + Pro. Result file at `outputs/personamem/granite-pro/rag/32k.json`.
- Confidence: **high** for reconciliation logic (well-tested threshold bands). **Medium** for benchmark -- run required 4 kill/resume cycles due to Pro API hangs and credit exhaustion.

## Judgment calls & deviations
- Skipped the spot-test entirely after discovering the .env `load_dotenv(override=True)` footgun would have given false Flash Lite results. Went straight to fresh Granite ingest + full Pro run.
- Used `amb-granite-pro` project (not `amb-benchmark`) to preserve the old MiniLM-embedded data for comparison.
- Did not enable `extract_facts` during ingestion -- MCP sampling not proven end-to-end, and the focus was on measuring Granite + Pro without confounding variables.
- Added 120s HTTP timeout to Gemini client mid-run after discovering Pro hangs indefinitely on certain long-context queries.

## Backlog delta
Filed: none. Closed: none.
PR #414 opened for #347 reconciliation (ready for review).
Memory: `project_benchmark_on_cluster` -- future benchmark runs must use KubeFlow/K8s jobs.
Deferred: fact extraction re-run with Granite embeddings (offline script, separate project).

## Drift & forward-collisions
- Backward: #347 is now substantially implemented (was Backlog). PR #414 covers stage contracts + reconciliation + decision log. #348 (rollback) and #349 (Layer 2 benchmark) remain blocked on merge.
- Forward: none.

## For the reviewer
- Sanity-check: the reconciliation threshold logic (>= 0.80 band) runs the LLM tiebreaker even when no tiebreaker_fn is provided, defaulting to "create." Is that the right safe default, or should it gate on having a tiebreaker?
- Thin verification: reconciliation is unit-tested with mocked similarity, not integration-tested against PostgreSQL with real embeddings. The cheese test validates the update path but through mocked cosine scores.
- Wants guidance: none.

## Risks / watch-fors
- **CI integration test flaky**: `test_focus_zero_weight_matches_plain_search` fails with float tolerance too tight (0.0004 difference). Pre-existing, not caused by this session. Should widen tolerance or use `pytest.approx(rel=1e-2)`.
- **Pro API reliability**: 4 kill/resume cycles in one run. Future runs must be K8s jobs with the 120s timeout active. The credit exhaustion was not detected until the process had been hanging silently for 2+ hours.
- **GPU machineset at 3 nodes**: still scaled up from 2. Verify both Granite models fit on 2 nodes and scale back.
