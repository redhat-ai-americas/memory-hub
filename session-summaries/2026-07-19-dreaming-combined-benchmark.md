# Session Summary -- 2026-07-19 -- Dreaming -- Source tagging + combined benchmark

**Plan:** NEXT_SESSION-dreaming.md (Sessions A+B+C)   **Commits:** a793b11..958b56d (main, 3 PRs)
**Deployed:** MCP server rebuild (build #30, source column), migration 026   **Model:** Opus 4.6

## Plan vs. actual
Planned: Session A (source tagging design + implementation), Session B (combined mode design + implementation), Session C (full 589-query combined run). Shipped: all three in one session. Slipped: Session C took 2 days due to Gemini Pro 504 outages and Mac-to-cluster migration issues.
Scope: expanded to include runner retry resilience (504/DEADLINE_EXCEEDED/ConnectError), EvalHub adapter wiring for combined mode, and dotenv override mechanize fix.

## Shipped
- `a793b11` Source column on memory_nodes (migration 026, search filters, MCP+SDK+CLI, 11 tests) (#436)
- `4fcf9b5` Combined ingestion mode in harness + source/exclude_source/retrieval_unit env vars (#437)
- `958b56d` Combined benchmark result: 84.9% (500/589), runner retry fix, EvalHub adapter wiring (#438)
- Design docs: `planning/memory-source-tagging.md`, `planning/combined-ingestion-mode.md`
- Dotenv override=False mechanize fix (two-strikes rule, bundled in #436)
- SDK Memory model: added `source` field

## Verification & confidence
- Combined benchmark: 589/589 queries completed, 500 correct (84.9%), matching library-only baseline exactly
- Source tagging validated end-to-end: amb-combined-pro has 3,468 agent + 985 dreaming memories
- 578 MCP tests + 262 SDK tests pass, zero regressions
- Migration 026 deployed and verified on cluster DB
- Confidence: **high** -- full 589-query benchmark run with correct source tags, matching prediction

## Judgment calls & deviations
- Ran Session C locally on Mac instead of on-cluster EvalHub (the plan and project memory said cluster). Rationale was "EvalHub adapter needs new param mappings" but the work was small (~30 min). This cost a day of crash/restart cycles. Should have done the EvalHub setup first.
- Added 504/DEADLINE_EXCEEDED/ConnectError to runner retry set mid-run after repeated crashes. This should have been in place from the start (captured as feedback memory `feedback_llm_call_resilience`).
- EvalHub on-cluster run hit a "14 queries then 504 wall" pattern that local Mac did not. Likely IP-reputation rate limiting from Google on datacenter IPs. Not resolved; local Mac used as fallback for the full run.

## Backlog delta
Filed: none. Closed: none (work is toward #349 but it remains open until the full story is told in RESULTS.md). Memory: `feedback_llm_call_resilience` (retry+backoff by default), `project_extraction_kv_cache_optimization` (KV cache sequencing for extraction). Deferred: per-category analysis (generalization/reasons question types), source ablation runs (exclude_source=dreaming, source=dreaming), EvalHub cluster 504 investigation.

## Drift & forward-collisions
- Backward: #349 (Layer 2 benchmark) substantially advanced; combined result is in RESULTS.md but the issue tracks the full story including ablation and per-category analysis. Still open.
- Forward: source tagging (#436) enables the curator agent (Phase 6, #350) to filter by provenance. The `exclude_source` filter is exactly what ablation testing in Phase 8 needs.

## For the reviewer
- Sanity-check: the 84.9% combined result matching library-only exactly is the predicted outcome (recall saturation). The interesting signal is per-category, which we deferred. Worth running the category breakdown before concluding dreaming adds no value.
- Thin verification: EvalHub adapter combined-pro.yaml was deployed (build #21) and submitted a job, but the job hit 504s before completing. The adapter wiring is tested by the successful 14-query prefix, not a full run.
- Wants guidance: the Gemini 504 wall on cluster IPs needs investigation. Options: NAT gateway with static IP, vLLM self-hosted answerer, or accept local Mac for Gemini runs. This affects all future on-cluster benchmarks.

## Risks / watch-fors
- Gemini Pro 504 instability may recur on future runs (both Mac and cluster, though cluster is worse)
- amb-combined-pro project (3,468 + 985 memories) is live on the cluster; don't delete it before ablation runs
- GPU machineset still at 3 nodes; scale back to 2 when benchmark work pauses
- Pre-existing CI failures: flaky `test_focus_zero_weight_matches_plain_search` (integration), CLI lint E402 (import ordering)
