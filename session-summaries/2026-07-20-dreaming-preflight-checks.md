# Session Summary -- 2026-07-20 -- Dreaming -- Tenant mismatch root cause + preflight checks

**Plan:** NEXT_SESSION-dreaming.md (per-category analysis + ablation)   **Commits:** 6ab3c4e..33f5fe7 (feat/dreaming-analysis-ablation, PR #440)
**Deployed:** nothing   **Model:** Opus 4.6

## Plan vs. actual
Planned: per-category analysis comparing combined vs library-only results, two source ablation runs, write full analysis into RESULTS.md, close #349, scale GPU machineset. Shipped: per-category analysis (item 1), corrected RESULTS.md analysis (item 3 partially), GPU scale-down from 3 to 2 (item 4), plus unplanned preflight system. Slipped: ablation runs blocked by discovery that the combined result is invalid (tenant mismatch means dreaming memories were never searched). #349 remains open.
Scope: expanded to include root cause investigation of identical retrieval contexts, preflight smoke checks (new subsystem), and pressure testing of preflight against 5 failure scenarios.

## Shipped
- `6ab3c4e` Per-category analysis for combined vs library-only (#349) -- comparison table in RESULTS.md
- `c1ea531` Preflight smoke checks: new `preflight.py` with 4 checks (project exists, memories present, source distribution, search functional); integrated into `omb run` via `memoryhub.py`, `runner.py`, `cli.py`
- `33f5fe7` Corrected combined run analysis in RESULTS.md -- tenant mismatch root cause documented, previous "non-destructive baseline match" interpretation replaced with "dreaming memories invisible to search"
- GPU machineset scaled from 3 to 2 nodes

## Key finding
All 589 queries in the combined benchmark produced byte-identical retrieval context between library-only and combined runs. Root cause: `_run_dreaming_ingest()` ingests memories with `tenant_id='default'` while searches use `tenant_id='amb-benchmark'`. The dreaming memories exist in the database but are invisible to tenant-scoped search. The 84.9% combined result is therefore invalid -- it is the library-only result with unreachable dreaming memories alongside.

## Verification & confidence
- Per-category analysis: confirmed all deltas between runs are zero (byte-identical context proves they must be)
- Preflight smoke checks: pressure tested against 5 scenarios (source=dreaming on broken data -> ABORT, expect-sources on broken data -> ABORT, no filter on broken data -> WARN, no-preflight bypass, healthy baseline -> PASS) -- all correct
- CI: all 9 checks pass on PR #440
- Gitleaks: no secrets detected
- Confidence: **high** on the root cause diagnosis (byte-identical context is conclusive). **High** on the preflight system (5 scenarios tested, integrated into CLI flow).

## Judgment calls & deviations
- Did not attempt to fix the tenant_id bug in this session. The fix is in `_run_dreaming_ingest()` in the harness and requires re-ingestion + re-run. Correctly deferred to avoid scope creep.
- Built the preflight system as an unplanned addition. Rationale: the tenant mismatch would have been caught immediately by a preflight check. This prevents similar silent failures in future benchmark runs.
- Corrected RESULTS.md analysis rather than leaving the stale "non-destructive baseline" interpretation. The previous text was factually wrong -- dreaming was not tested, it was invisible.

## Backlog delta
Filed: none. Closed: none. #349 remains open -- the combined result is now known-invalid and requires a tenant fix + re-run before the ablation runs make sense. No new issues needed; the existing issue covers the remaining work.

## Drift & forward-collisions
- Backward: #349 is still open. The combined result is now known-invalid (dreaming memories ingested under wrong tenant). The per-category analysis and ablation runs described in the plan are blocked until the tenant_id bug is fixed and a clean combined run is executed.
- Forward: the preflight system will be used by all future benchmark runs, relevant to Phase 8 (full benchmark validation). Any run with dreaming memories will now fail-fast if the source distribution check finds zero dreaming-sourced memories in the search tenant.

## For the reviewer
- The key commit to scrutinize is `33f5fe7` -- verify the RESULTS.md corrections accurately describe the tenant mismatch and don't overclaim or underclaim the finding.
- The preflight system (`preflight.py`) is new code with no unit tests. Integration testing was done via the 5 pressure scenarios, but formal test coverage is zero. Acceptable for harness tooling but worth noting.
- The `research/prose-loses-to-urgency.md` file has an unstaged edit (adds a "stale fallback" observation). This is unrelated to the benchmark branch.

## Risks / watch-fors
- The tenant_id bug in `_run_dreaming_ingest()` needs fixing before any combined benchmark run can produce valid results. Until then, all combined results should be treated as library-only.
- 244 pre-existing ruff lint errors in `benchmarks/amb-harness/src/`. Not a regression from this session but worth a cleanup pass.
- amb-combined-pro project data (3,468 agent + 985 dreaming) will need re-ingestion after the tenant fix. The dreaming memories exist but under the wrong tenant.
- GPU machineset now at 2 nodes. Scale back to 3 when the re-run is ready.
