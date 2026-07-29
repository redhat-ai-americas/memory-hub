# Reconciliation -- 2026-07-28 -- dreaming-followon (epic close)

**Range:** 2026-07-28 (1 session)   **Plan:** NEXT_SESSION-dreaming-followon.md

## Backlog reconciled
| # | Was | Action | Why |
|---|-----|--------|-----|
| #429 | Unit tests for _run_dreaming_ingest | Closed | 16 tests shipped in `c23e05d` (PR #470) |
| #430 | Extraction model preflight probe | Closed | Probe shipped in `24f847d` (PR #470) |
| #447 | Retrieval-unit routing | Closed | Split routing shipped in `ce1a7a0`, +3.1pp validated in `de096cb` |
| #455 | LLM Stage 3 fallback extractor | Closed (pre-existing) | Already implemented at extraction.py:296-603; closed earlier this session |

## Forward-collisions banked
None. All work was harness-only (no server or SDK changes that overlap with other epics).

## Critique
On track: epic completed in a single session. All 3 phases shipped, all 4 issues closed,
benchmark target exceeded (+3.1pp vs +2pp target). No scope creep. No recurring friction
within this epic (Gemini model deprecation is a cross-epic friction, not specific to this arc).

## Guidance for next
Epic is done. Planning file archived to `archive/next-session/NEXT_SESSION-dreaming-followon-2026-07-28.md`.
PR #470 stays on branch per user direction; merge to main when ready.
