# Session Summary -- 2026-07-28 -- dreaming-followon -- Test, harden, and route

**Plan:** NEXT_SESSION-dreaming-followon.md / #429, #430, #447, #455
**Commits:** 4d34ac4..035a156 (feat/dreaming-followon/test-harden)
**Deployed:** memoryhub-install-gold (extraction model config only)
**Model:** Claude Opus 4.6

## Plan vs. actual
Planned: Phase 1 (test + harden #429, #430). Shipped: Phases 1-2 plus closed Phase 3. Slipped: nothing.
Scope: expanded from Phase 1 only to all 4 issues in the epic, because Phase 1 finished fast and Wes wanted to continue.

## Shipped
- `4d34ac4` Bootstrap pytest infrastructure for amb-harness (zero prior test coverage)
- `c23e05d` 16 unit tests for `_run_dreaming_ingest` covering 7 bug-prone paths (#429)
- `24f847d` Extraction model preflight probe -- Gemini verification + custom endpoint reachability (#430)
- `505ee5c` Design doc for retrieval-unit routing (skeleton -> design-complete)
- `ce1a7a0` Split routing, round-robin merge, token budget implementation (#447)
- `8613cb8` 12 routing tests + import fix in `_apply_token_budget`
- `de096cb` Benchmark results recorded in design doc (+3.1pp validated)
- Closed #455 as already-implemented (Stage 3 LLM fallback exists at extraction.py:296-603)
- Configured memoryhub-install-gold cluster for extraction (gemini-api-key secret, env vars)

## Verification & confidence
- 39 unit tests pass, zero network calls, zero failures
- Full PersonaMem 32k benchmark on memoryhub-install-gold cluster: pooled 72.3% vs split 75.4% (+3.1pp)
- Minimal E2E smoke test validated full pipeline (write, search, thread, extraction, answer, judge)
- CLI loads without regression (`uv run omb --help`)
- Confidence: **high** -- both unit tests and live cluster benchmark validate the changes

## Judgment calls & deviations
- Designed a blend of approaches A+C rather than pure A or C for routing (user-approved)
- Used `continue` (skip) in token budget rather than `break` -- allows smaller memories to fill remaining budget after a large one is skipped
- Switched from gemini-2.5-flash -> gemini-2.0-flash -> gemini-3.1-flash-lite after two model deprecations mid-session (exactly the scenario #430's preflight probe was built to catch)
- Closed #455 without code changes after discovering Stage 3 LLM fallback already exists in the codebase

## Backlog delta
Closed: #429, #430, #455. Refs: #447 (code + benchmark done, issue stays open until PR merges).
Deferred: token budget benchmark run (`max_context_tokens=20000`) -- low priority, can do anytime.
Memory: none new.

## Drift & forward-collisions
- Backward: none detected. The 4 issues addressed were self-contained.
- Forward: none. Routing is harness-only; no server changes that would overlap with other epics.

## For the reviewer
- Sanity-check: the round-robin interleave guarantees 1:1 transcript:fact ratio -- should we consider a configurable ratio (e.g., 3:1) for cases where facts are lower quality?
- Thin verification: `MEMORYHUB_MAX_CONTEXT_TOKENS` is unit-tested but not benchmarked on the cluster yet
- Wants guidance: none

## Risks / watch-fors
- Gemini model deprecation continues to be a recurring friction point. The preflight probe (#430) catches it, but we're now on gemini-3.1-flash-lite which may also deprecate. The memoryhub-install-gold cluster extraction model needs updating when this happens.
- The benchmark baseline (72.3% pooled with flash-lite) is slightly lower than the prior baseline (72.8% with flash-lite on the old cluster). Minor variance, but worth noting if comparing across clusters.
