# Next Session -- Dreaming Follow-on

## Next: <to be planned via /plan-next-session>

(No next-session focus selected yet. Run `/plan-next-session dreaming-followon` to
pick the first slice from the phases below.)

## Remaining epic phases

Close the gaps left by the completed dreaming epic: test coverage for the
extraction pipeline, preflight robustness, and making extracted facts
actually contribute to search results. The dreaming pipeline shipped and
benchmarked (84.9% AMB PersonaMem); this epic hardens it and unlocks the
value of extracted facts in retrieval.

### Phase 1: Test + harden (#429, #430) -- DONE

Unit tests for `_run_dreaming_ingest` and extraction model identity in
the preflight manifest. The dreaming code path has zero unit coverage
despite 7 bugs found via live cluster testing. The preflight gap bit us
twice when Gemini model names deprecated mid-session.

**Work:**
1. Unit tests for `_run_dreaming_ingest` covering: thread creation auth,
   extraction API key wiring, URL construction, model name validation,
   circuit breaker logic, thread ownership, append auth (#429)
2. Add extraction model name, URL, and reachability check to the
   preflight manifest (#430)
3. Verify tests pass against SQLite (no cluster needed)

**Definition of done:** `pytest tests/ -k dreaming` passes with coverage
on all 7 bug-prone code paths identified in #429. Preflight manifest
includes extraction model identity and a reachability probe that fails
fast on deprecated model names.

**Dependencies:** None.

**Parallel-ok:** Yes -- independent of Phase 2.

### Phase 2: Retrieval-unit routing (#447) -- DONE (+3.1pp validated)

Extracted dreaming facts don't contribute to search results when pooled
with full conversation transcripts (source ablation showed +0.1pp without
routing). Implement separate search pools for facts vs transcripts so
both memory types contribute to the LLM's context window.

**Work:**
1. Read the design doc (`planning/retrieval-unit-routing.md`)
2. Implement separate top-k pools for `source=agent` and `source=dreaming`
   in the search service
3. Merge results via RRF or interleaving (per design doc)
4. Add `source` filter to search API if not already exposed
5. Re-run source ablation benchmark to measure the delta

**Definition of done:** Combined search (library + dreaming) with
retrieval-unit routing shows a measurable accuracy improvement over
library-only in the PersonaMem benchmark. The delta is documented in
`benchmarks/RESULTS.md`.

**Dependencies:** None (Phase 1 is parallel-ok).

**Parallel-ok:** Yes -- independent of Phase 1. Needs worktree isolation
if running concurrently.

### Phase 3: LLM Stage 3 fallback extractor (#455)

LLM-based entity extraction fallback for entities missed by GLiNER
Stage 2. A prior implementation existed on a deleted branch. The
extraction pipeline has been restructured since then; reimplement
against the current architecture.

**Work:**
1. Implement LLM fallback extractor in the 3-stage cascade
   (`src/memoryhub_core/services/extraction.py`)
2. Trigger when GLiNER confidence is below threshold
3. Use structured prompt for entity extraction
4. Tests covering the cascade: spaCy -> GLiNER -> LLM fallback
5. Measure extraction recall improvement on a sample corpus

**Definition of done:** 3-stage extraction cascade runs end-to-end with
LLM fallback. Extraction recall measurably improves on a test corpus
compared to 2-stage (spaCy + GLiNER only). Tests cover all three stages
including fallback triggering.

**Dependencies:** None (independent of Phases 1-2, but lower priority).

**Parallel-ok:** Yes.

---

## What this covers (and what it doesn't)

**In scope:**
- #429 Unit tests for _run_dreaming_ingest
- #430 Add extraction model identity + reachability to preflight manifest
- #447 Implement retrieval-unit routing for dreaming facts
- #455 Reimplement LLM Stage 3 fallback extractor

**Out of scope (other epics own):**
- #350-353, #345 Curator scaffold and sweeps (`NEXT_SESSION-curation.md`)
- #370 Ablation Matrix B (backlog, unblocked by #349 closure)
- Retrieval polish issues (#306, #389, #397, #404, #453, #454) -- future `NEXT_SESSION-retrieval-polish.md`

## What landed last session (2026-07-28)

Phase 1 + Phase 2 code complete. PR #470 targeting main.

**Phase 1 (test + harden):**
- Bootstrapped pytest infrastructure for amb-harness (dev deps, conftest,
  asyncio_mode=auto)
- 16 unit tests for `_run_dreaming_ingest` covering all 7 bug-prone paths
- Extraction model preflight probe (Gemini + custom endpoint verification)
- 11 preflight tests
- Closes #429, #430

**Phase 2 (retrieval-unit routing):**
- Design doc fleshed out at `planning/retrieval-unit-routing.md`
- Split routing: two searches (transcripts + facts), round-robin merge
- Token budget: `MEMORYHUB_MAX_CONTEXT_TOKENS` for small-model deployments
- All env vars optional, backward compatible
- 12 routing tests (split, merge, budget, backward compat, integration)
- Benchmark validated on memoryhub-install-gold cluster:
  pooled 72.3% vs split 75.4% (+3.1pp, exceeds +2pp target)
- Closed #455 (Stage 3 LLM fallback already implemented in extraction.py)

39 tests total, zero network calls.

Prior work tracked in `archive/next-session/NEXT_SESSION-dreaming-2026-07-20.md`.

## Watch out for

- **Gemini model deprecation.** Model names expire without warning.
  Phase 1 (#430) addresses this. Until then, verify model names against
  `https://generativelanguage.googleapis.com/v1beta/models` before any
  extraction run.
- **Retrieval-unit routing design doc.** Read `planning/retrieval-unit-routing.md`
  before starting Phase 2. The design covers separate top-k pools and
  merge strategy.
- **Source ablation baseline.** The library-only baseline is 84.9%
  (granite-pro project). Do not modify that project.

## If blocked

- If cluster is unavailable: Phases 1 and 3 run locally against SQLite.
  Phase 2 needs cluster data for the benchmark re-run but the code
  changes can be developed locally.
- If Gemini API is down: Phase 2 benchmark and Phase 3 LLM calls need
  an API. Develop and test locally, defer the benchmark run.
