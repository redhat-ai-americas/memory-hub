# Session Summary -- 2026-07-16 - Dreaming - Extraction model comparison + pipeline

**Plan:** NEXT_SESSION-dreaming.md   **Commits:** 96273d2..53b2df2 (feat/eager-fact-extraction)
**Deployed:** none   **Model:** Opus 4.6

## Plan vs. actual

Planned: Part 1 (extraction model comparison) then Part 2 (permanent write-time extraction pipeline).
Shipped: both parts, plus #406 filed for SDK/CLI extraction gap.
Slipped: deployment of sampling-enabled MCP server (stop-and-ask gate; intentional).
Scope: stayed in scope.

## Shipped

- 96273d2 extraction prompt at `prompts/fact_extraction.yaml` + `create_fact_children()` in memory service
- 2a79e5c `retrieval_unit` search preference (`facts|chunks|parents|auto`) with pool discipline
- d5f4ea5 MCP sampling integration in `write_memory` with 15s timeout and deferred fallback
- 53b2df2 SDK `extract_facts` and `retrieval_unit` parameters + `_WRITE_OPTS`/`_SEARCH_OPTS` whitelist updates
- Merged PR #402 (design docs), PR #407 (pipeline), PR #408 (session summary)
- Closed #403 (eager fact extraction shipped)
- Filed #406 (SDK/CLI extraction gap)

## Extraction model comparison results

| Extraction model | Facts in DB | Accuracy | Avg memories/query | Avg ctx chars | Empty contexts |
|---|---|---|---|---|---|
| gemini-3.1-flash-lite | 6,697 | **63.3%** | 70.0 | 6,030 | 0 |
| gemini-3.5-flash | 6,522 | 57.7% | 64.3 | 6,949 | 43 |

Delta: -5.6pp. gemini-2.5-flash was the originally planned model but is deprecated. gemini-3.5-flash had 35 JSON parse errors (18% of docs), produced wordier facts, and scored worse. Extraction model quality is not the lever; cheapest viable model wins. Haiku ceiling test skipped per plan (only if Flash beat Flash Lite meaningfully).

## Verification & confidence

- Unit tests: 702 passed, 8 failed (pre-existing in test_conversation_extraction), 1 skipped
- Syntax: all modified files compile cleanly
- Lint: clean after fixing UP041 (asyncio.TimeoutError -> TimeoutError)
- Benchmark: extraction comparison run complete with stored results
- Confidence: **medium** -- pipeline code is sound, but not integration-tested with live MCP sampling (requires deployed server)

## Judgment calls & deviations

- Used gemini-3.5-flash instead of gemini-2.5-flash (deprecated). Bigger capability step up than planned, which made the negative result more conclusive.
- `retrieval_unit` filtering happens post-RRF rather than pre-recall. Pre-recall filtering would reduce the candidate pool size; post-RRF is simpler and matches the existing `return_chunks` pattern.
- `create_fact_children()` is a public function (not underscore-prefixed like `_create_chunk_children`) because it's called from the MCP tool layer, not from within `create_memory()`. The sampling call can only happen at the tool level where `ctx` is available.

## Backlog delta

Filed #406 (SDK/CLI extraction gap, design, Backlog). Closed #403 (eager extraction, Done). Merged PR #402 (design docs from docs/facts-pipeline-designs branch).

## Drift & forward-collisions

- Backward -- #347 (reconciliation): still valid, now more urgent since facts are being created. Cross-write fact dedup is explicitly deferred to #347 per the design doc.
- Backward -- #348 (run provenance): `extraction_run_id` metadata is carried on every fact node, implementing the pattern #348 requires. #348 may be partly done.
- Forward -- none identified.

## For the reviewer

- Sanity-check: the `retrieval_unit=auto` logic (facts-first with parent fallback) may need tuning. The current implementation checks if ANY fact nodes appear in the RRF-scored candidate pool. If only a few low-scoring facts exist, this could be worse than parent expansion. A threshold or minimum-count might be needed.
- Thin verification: no live MCP sampling test. The `ctx.sample()` integration is structurally correct (matches FastMCP 3.4.2 docs) but hasn't been exercised end-to-end.
- Wants guidance: should the `retrieval_unit=auto` policy be adjusted before the next benchmark run, or should we measure first and adjust based on data?

## Risks / watch-fors

- Containerfile does not COPY `prompts/` -- deployment will fail to load the extraction prompt until this is added.
- `extract_facts` parameter is accepted by the SDK but ignored by the MCP write tool (it always extracts if oversized). The opt-in/opt-out dispatch needs wiring.
- 15 sweep projects (`amb-c32-o0-k10`, etc.) + `amb-facts-flash` still in the database, consuming storage.
