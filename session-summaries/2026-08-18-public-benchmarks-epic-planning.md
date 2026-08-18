# Session Summary — 2026-08-18 · public-benchmarks · Epic planning for AMB and AML leaderboard submissions

**Plan:** New epic (no prior plan)   **Commits:** ee20b17 (`feat/soc-demo-openshell`)
**Deployed:** none   **Model:** Claude Code (Opus 4.6)

## Plan vs. actual
Planned: Research how to submit MemoryHub benchmark results to AMB PersonaMem leaderboard. Shipped: full epic plan covering both AMB and AML submission venues, with next-session file ready for Phase 1. Slipped: none.
Scope: expanded from "how do we submit" to a full 5-phase epic covering both leaderboards — user-directed expansion.

## Shipped
- `ee20b17` — Epic plan file `NEXT_SESSION-public-benchmarks.md` with 5 phases, execution order, and next-session focus on AMB upstream provider adapter

## Verification & confidence
- Smoke-checked upstream AMB repo state: confirmed no existing MemoryHub provider, confirmed 3 memory systems already on PersonaMem board (Hindsight 86.6%, hybrid-search 84.4%, Cognee 81.8%), confirmed no existing fork
- Verified our adapter exists at `benchmarks/amb-harness/src/memory_bench/memory/memoryhub.py` (503 lines)
- Verified our result file exists at `benchmarks/amb-harness/outputs/personamem/granite-pro/rag/32k.json.gz`
- Confidence: high — this is planning, not code; the factual claims about both venues were verified against live repo state and web research

## Judgment calls & deviations
- Corrected an initial assumption from web research that AMB PersonaMem only had LLM baselines — the upstream manifest shows 3 memory systems already. The epic file was updated before committing.
- Combined Phases 1+2 (adapter + PR) into one session focus since the adapter work is mostly trimming an existing 503-line file, not building from scratch.
- Scoped AML as "build adapter now, park submission until November" rather than waiting entirely — the HTTP adapter work is independent and worth doing while AMB context is fresh.

## Backlog delta
Filed: none. Closed: none. Deferred: none.
Memory: none written (the epic file carries the context).

## Drift & forward-collisions
- Backward — none. This session was pure planning, no code changes that affect existing issues.
- Forward — #370 (Ablation Matrix B), #389 (S3 hydration), #453 (disabled_signals) identified as Phase 5 score-improvement candidates. No comments posted (these are our own repo issues and the connection is already documented in the epic file).

## For the reviewer
- Sanity-check: Is combining Phase 1+2 into one session realistic? The adapter cleanup should be straightforward (trim env vars, match upstream conventions), but reproduction against the cluster adds uncertainty (cluster must be healthy, network accessible).
- Thin verification: AML submission window timing (~November 2026) is inferred from "1 attempt per 3 months" and the Aug 7 deadline. Not confirmed with AML directly.
- Wants guidance: none

## Risks / watch-fors
- The upstream AMB repo is run by Vectorize (makers of Hindsight, the #1 entry). PR review dynamics may be slow or have competitive considerations.
- Our 84.9% was measured with Gemini 3.1 Pro Preview as answer LLM. If the upstream harness pins a different answer LLM, our score could shift.
- AML's next submission window is unconfirmed — set a reminder to check in late October.
