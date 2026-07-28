# Next Session -- Dreaming

## Next: Fix tenant bug, re-run combined benchmark, close #349

The 2026-07-19 combined benchmark (84.9%) is invalid. Dreaming
memories were ingested under `tenant_id='default'` while searches
use `tenant_id='amb-benchmark'`. The two populations were never
visible to the same search. This session fixes the bug, re-runs
the combined benchmark with preflight validation, and closes #349.

1. **Fix `_run_dreaming_ingest()` tenant propagation** (harness bug)
   The library ingest path passes `self._tenant_id` on each `write()`
   call (memoryhub.py:173-174). The dreaming path creates threads and
   extracts facts via `create_thread()` / `extract_thread()` without
   passing tenant_id. Fix: propagate `self._tenant_id` through the
   dreaming pipeline. ~10 lines of code.

2. **Fix existing data via SQL update** (fast path, avoids re-extraction)
   ```sql
   UPDATE memory_nodes SET tenant_id = 'amb-benchmark'
   WHERE scope_id = 'amb-combined-pro' AND source = 'dreaming';
   ```
   This makes the 985 existing dreaming memories visible to the
   benchmark search. Verify with preflight.

3. **Run preflight to confirm both sources are visible**
   ```bash
   MEMORYHUB_PROJECT_ID=amb-combined-pro uv run omb run \
     --dataset personamem --split 32k --memory memoryhub \
     --skip-ingestion --expect-sources agent,dreaming \
     --name combined-pro-v2 -q 3
   ```
   This MUST show both `agent` and `dreaming` in the smoke results
   before proceeding. If dreaming still doesn't appear, investigate
   (embedding missing? search filter bug?).

4. **Smoke-test the code fix** (verify, don't just fix)
   Re-ingest 3-5 personas in dreaming mode with the fixed code.
   Confirm the extracted memories land under `tenant_id='amb-benchmark'`
   in the DB. This proves the code fix works without re-extracting
   all 985 memories.

5. **Run the full 589-query combined benchmark**
   With `--expect-sources agent,dreaming` and `--skip-ingestion`.
   This is the real combined run. The result will tell us whether
   dreaming facts actually contribute to accuracy.

6. **Per-category analysis** (if the result differs from 84.9%)
   Build the comparison table. This time the deltas will reflect
   real retrieval differences, not LLM noise.

7. **Source ablation runs** (2 runs, 589 queries each)
   - `MEMORYHUB_EXCLUDE_SOURCE=dreaming` -- library-only, should
     match the granite-pro baseline (~84.9%)
   - `MEMORYHUB_SOURCE=dreaming` -- dreaming-only, expected ~60-70%

8. **Write the final RESULTS.md analysis, close #349**

**Sequencing.** Items 1-4 are the fix-and-verify phase (no Gemini
calls). Item 5 is the main benchmark run (~90 min if API is stable).
Items 6-7 depend on item 5's result. Item 8 is the write-up.

**Constraints for the session:**
- Do NOT modify `amb-granite-pro` (library-only baseline, 84.9%).
- Gemini Pro API may be unstable. If down, complete items 1-4 (all
  local/cluster, no Gemini needed) and defer items 5-8.
- All pushes through PRs (branch protection enforced).
- Deploy scripts in main context only (2026-05-19 incident).
- The SQL update (item 2) modifies live benchmark data. Verify the
  WHERE clause before executing.

**Session start protocol:**
- Premise checks: `oc whoami --context mcp-rhoai`; verify MCP pod
  running; verify `amb-combined-pro` has 3,468 agent + 985 dreaming
  in memory_nodes (check tenant_id distribution); source `~/.secrets`
  for GEMINI_API_KEY; merge PR #440 (preflight + analysis) first
- Rules with history: all pushes through PRs (enforced since
  2026-07-17); deploy scripts in main context only; preflight
  required before any full run (2026-07-20 lesson)
- Stop-and-ask before: SQL updates to memory_nodes; modifying
  baseline project data; any fresh extraction (uses Gemini credits)
- Close ritual: session summary + NEXT_SESSION update; record
  combined result against the 84.9% library-only baseline

**Exit predicate:**
- Tenant bug fixed in harness code (committed)
- SQL fix applied and verified via preflight
- Code fix smoke-tested (3-5 personas, correct tenant in DB)
- Full 589-query combined run completed with both sources in retrieval
- Per-category analysis in RESULTS.md (if result differs from baseline)
- Both ablation runs completed
- #349 closed on GitHub

## Remaining epic phases

MemoryHub should be the obvious memory system for anyone deploying agents
on OpenShift at scale. No capability gap should exist between MemoryHub
and any competitor for users who need governed, multi-tenant,
platform-level memory. Governance features (versioning, RBAC, audit
trails, multi-tenancy) are additive, not a tax on retrieval or
extraction quality.

This epic closes that gap across three fronts: retrieval performance
(match or beat competitors on standard benchmarks), memory management
(dreaming, reconciliation, reflection), and measurement (prove the
compound value with benchmarks nobody else runs).

### Phase 3: Layer 1 -- reranker + chunking fix (DONE)

- **3a (#342): Reranker upgrade.** DONE -- granite-embedding-reranker-english-r2
  deployed on L40S via TEI 1.9 GPU image (2026-07-15).
- **3b (#343): Chunk-to-parent expansion + tuning.** DONE -- expansion shipped
  (PR #399). Per-request chunk params shipped (PR #401). Tuning investigation
  complete: 21-config sweep proves chunk size irrelevant for PersonaMem.

### Phase 4: Benchmark remediation + fact extraction (DONE)

- **4r5 (#360 re-scoped): Matrix A.** DONE -- signal ablation complete,
  retrieval-saturated at 4-7 parents.
- **Fact extraction prototype:** DONE -- 63.3% at k=70, 1,256 ctx tokens.
- **Fact extraction pipeline:** DONE -- PR #407 (write-time extraction via
  MCP sampling), PR #412 (extract_facts parameter wiring). Deployed build #19.
- **Extraction model comparison:** DONE -- Flash Lite wins over Flash (-5.6pp).
- **Matrix B (#370): focus/domain/graph -- deferred post-#349.** Domain
  tags and graph edges only exist after dreaming-mode extraction.

### Phase 4.5: Pro benchmark validation (DONE)

- **Full Pro run:** 589-query PersonaMem with Granite embeddings + reranker +
  gemini-3.1-pro-preview. Result: **84.9%** (500/589). Up from 81.2% with
  MiniLM. Passes Cognee (81.8%) and hybrid-search (84.4%), 1.7pp behind
  Hindsight (86.6%). Result file: `outputs/personamem/granite-pro/rag/32k.json`.

### Phase 5: Layer 2 -- reconciliation + rollback (DONE)

- **5a (#347): Stage contracts + reconciliation with decision log.** DONE --
  PR #414 merged. Migration 025 deployed to cluster (2026-07-17).
- **5b (#348): Run provenance + rollback.** DONE -- PR #415 merged.
  Consistent run IDs, rollback_extraction_run(), dry-run mode, circuit
  breaker. 9 tests covering all exit predicates.
- **5c (#349): Layer 2 benchmark run.** Combined result 84.9% (500/589)
  INVALIDATED (2026-07-20): tenant mismatch meant dreaming memories were
  never searched. PRs #436-#438 shipped but result must be re-run after
  tenant fix. PR #440 adds preflight checks + corrected analysis.
- **5d (#418): Session-close capture hook.** DONE -- PR #419.

### Phase 5.5: Pipeline validation (DONE)

- **EvalHub infrastructure.** DONE -- PRs #422, #423, #424.
- **Pipeline validation.** DONE -- PR #433. Validated at 70% (7/10).
- **Combined mode.** PRs #436, #437, #438 shipped. Result INVALIDATED
  (tenant mismatch). PR #440 adds preflight + corrected analysis.

### Phase 6-7: Curator Agent + Layer 3 reflection -- MOVED

Moved to `NEXT_SESSION-curation.md` as a standalone epic. Issues #350-353
(Curator scaffold through staleness sweep) and #345 (provenance-driven
reflection) are tracked there.

### Phase 8: Full benchmark validation (deferred)

Re-run all benchmarks with full pipeline active after curation epic ships.
Depends on `NEXT_SESSION-curation.md` completing.

**Reporting rule:** the Flash Lite competitor table and the Pro >= 85%
headline are SEPARATE tables -- never mixed in one comparison.

## What landed last session (2026-07-20)

Discovered the combined benchmark result (84.9%) was invalid due to a
tenant mismatch. Built preflight smoke checks into the harness to
prevent this class of bug from reaching full runs. Scaled GPU from 3
to 2 nodes.

**Closed:** none. #349 remains open pending the tenant fix + re-run.

**Shipped:** PR #440 (preflight checks + corrected RESULTS.md analysis +
per-category comparison table + session summary).

**Key finding:** `_run_dreaming_ingest()` writes memories under
`tenant_id='default'` while searches use `tenant_id='amb-benchmark'`.
All 589 queries had byte-identical context between library-only and
combined runs. The dreaming memories were never searched.

**Follow-ups filed:** none. Memories captured:
`feedback_preflight_before_expensive_runs` (smoke test before full runs).

## Watch out for

- **Tenant mismatch is the known bug.** The 985 dreaming memories in
  `amb-combined-pro` have `tenant_id='default'`. The SQL update (item 2)
  fixes this. Double-check the WHERE clause before executing.
- **Gemini Pro 504s.** The API was unstable 2026-07-18/19/20. The runner
  retries 504/DEADLINE_EXCEEDED/ConnectError. Use Mac with nohup for
  long runs (cluster egress IP triggers stricter rate limits).
- **amb-granite-pro project**: 84.9% baseline. Do not modify.
- **GPU machineset at 2 nodes.** Scale to 3 if embedding/reranker
  throughput is insufficient for the full run.
- **Preflight is now mandatory.** `omb run --skip-ingestion` runs
  3 smoke queries before the main loop. Use `--expect-sources
  agent,dreaming` for combined runs. This is the gate that would
  have caught the tenant bug.
- **PR #440 must be merged before starting.** The preflight code
  and corrected RESULTS.md are on that branch.

## If blocked

- If Gemini API is down: complete items 1-4 (tenant fix, SQL update,
  preflight verification, code smoke test). None require Gemini.
  Defer items 5-8 (the actual benchmark runs).
- If cluster DB is inaccessible: the SQL update (item 2) needs DB
  access via port-forward. The code fix (item 1) and preflight (item 3)
  only need the MCP server route (public).
