# Session Summary -- 2026-07-27 -- CLI -- Defer low-signal topic search

**Plan:** User question about topic discovery mechanism, then fix.  **Commits:** 1943ab6 (`feat/defer-low-signal-search`)
**Deployed:** none  **Model:** Opus 4.6

## Plan vs. actual
Planned: Answer user's question about how `focus_source` topic discovery works. Shipped: answered the question, identified the low-signal first-turn gap, and rewrote the instruction templates. No scope expansion -- the fix was the natural follow-up.

## Shipped
- 1943ab6 -- Rewrote lazy and lazy_with_rebias template blocks (4 total: 2 claude-code, 2 universal) to defer memory search until the user provides actionable signal instead of mechanically searching after the first turn. Removed the separate "vague opening" fallback note since the primary instruction now covers it. Updated the test assertion to match.

## Verification & confidence
- 164/164 tests pass, lint clean, CI green on main, gitleaks clean.
- Confidence: high -- the change is purely instructional text in string templates, with a single test assertion update. No runtime code paths affected.

## Judgment calls & deviations
- Removed the "vague opening" fallback paragraph from lazy blocks entirely rather than keeping it alongside the new deferred-search instruction. The two would have been redundant and potentially confusing (one says "search then re-search if vague"; the other says "don't search until you have signal"). Single instruction is clearer.

## Backlog delta
Filed: none. Closed: none. Memory: none. Deferred: `focus_source` config field is still not wired into template selection (Q3 item per SDK comment at `client.py:528`).

## Drift & forward-collisions
- Backward: none
- Forward: none

## For the reviewer
- Sanity-check: read the four rewritten template blocks for instruction clarity -- does "enough detail to form a meaningful search query" give agents enough guidance, or should it enumerate what counts as signal?
- Thin verification: no live agent testing yet (branch exists for that purpose).
- Wants guidance: none

## Risks / watch-fors
- Agents may now over-defer and never search if the user drip-feeds context across many short turns without a single "meaty" message. Worth watching during testing.
