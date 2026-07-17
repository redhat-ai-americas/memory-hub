# Session Summary -- 2026-07-17 -- Dreaming -- Pipeline validation

**Plan:** NEXT_SESSION-dreaming.md Parts 1-3   **Commits:** 873963a (PR #433), 21f2293 (PR #432)
**Deployed:** EvalHub adapter build #19   **Model:** Opus 4.6

## Plan vs. actual

Planned: diagnose 0% Flash Lite accuracy, fix bugs, validate with Pro on EvalHub.
Actual: diagnosed and fixed the 0%, validated at 70% (7/10) on EvalHub with Pro. All three parts completed. Root cause was different from initial hypothesis -- not a model quality issue but a `return_chunks` parameter causing empty search results.

## Shipped

- `873963a` (PR #433): Fix 0% accuracy -- removed `return_chunks` from dreaming eval configs, fixed adapter env-var clearing, switched answerer to Pro, added `dreaming-validate` config
- `21f2293` (PR #432): Track planning and research documents (issue maintenance)
- EvalHub adapter build #19 deployed with adapter env-var fix
- Cancelled 5 stuck eval jobs (4-5 hours old, ingestion loops)

## Root cause analysis

The 0% had two layers:

1. **Primary (0% on both local and cluster):** `return_chunks: "true"` in eval configs caused the SDK `SearchResult.model_validate()` to produce an empty `results.results` list. The harness saw 0-char context and short-circuited to `correct=False` without calling the answerer. The search itself returned data (visible in MCP server logs) but the response format with `return_chunks` wasn't being parsed into the results list the harness expected.

2. **Secondary (would cause 0% in some environments):** The adapter's param-to-env loop only cleared stale env vars for `disabled_signals`. If `MEMORYHUB_TENANT_ID` leaked from a `.env` file (via `load_dotenv(override=True)`), searches filtered to the wrong tenant and returned empty results. Fixed by clearing ALL stale env vars when a config param is absent.

3. **Red herring (was NOT the primary cause):** Flash Lite as answerer. The dreaming-smoke/tiny configs used Flash Lite as the MCQ answerer, but this was masked by the return_chunks bug -- Flash Lite never got to answer because context was empty. Switched to Pro for correctness regardless.

## Verification & confidence

- Pipeline validated on EvalHub: **70% accuracy (7/10)** with Pro answerer, dreaming-mode extracted facts, `amb-dreaming-tiny` project (3,620 memories, 37 personas). Score appears in EvalHub API with per-question-type breakdown.
- Local validation: 100% (2/2) and 66.7% (2/3) across multiple runs with correct env vars
- Confidence: **high** that the 589-query full run will complete without pipeline errors. Accuracy will likely land 60-75% given the small-sample variance.

## Judgment calls & deviations

- Diagnosed locally before touching the cluster -- saved ~4 rebuilds
- Identified that my earlier "90% local test" was querying the wrong project (library-mode `amb-granite-pro` instead of dreaming-mode `amb-dreaming-tiny`) due to `.env` override. This prevented a false-positive validation.

## Backlog delta

Closed: none (pipeline validation is a milestone toward #349, not a separate issue).
Created: #426-#431 (issue maintenance), PR #432 (docs tracking).
Branch protection configured (enforce_admins=true, required checks for MCP Server Tests + gitleaks).

## For the reviewer

- The `return_chunks` bug is a real SDK/server interaction issue -- `SearchResult` doesn't map chunked responses correctly. Worth a separate fix (#343-era work) but not blocking benchmarks since we don't need return_chunks for scoring.
- The adapter env-var fix is minimal (one line: clear all stale env vars, not just disabled_signals) but prevents a class of subtle bugs where prior env vars leak into new eval jobs.

## Risks / watch-fors

- 70% on 10 queries has high variance. The 589-query run may land anywhere from 55-75%. The library-mode baseline was 84.9% with full session transcripts; dreaming mode with extracted facts losing ~15pp is expected since single-sentence facts carry less context than full conversations.
- The `return_chunks` response format issue in the SDK should be filed as a separate bug -- other consumers may hit the same empty-results problem.
- The 3 EvalHub `dreaming-smoke` jobs that were stuck for 4-5 hours ingested data into `amb-granite-pro-dreaming-smoke`. That project may have partial/duplicate data.
