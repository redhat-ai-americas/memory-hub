# Session Summary -- 2026-07-17 -- Dreaming -- Run provenance and rollback

**Plan:** NEXT_SESSION-dreaming.md / #348   **Commits:** cd5fa88..1661538 (main, via PRs #414, #415)
**Deployed:** migration 025 to cluster; MCP rebuild blocked by registry.redhat.io outage   **Model:** Opus 4.6

## Plan vs. actual

Planned: merge PR #414, deploy migration 025, implement #348 (run provenance, rollback, dry-run, circuit breaker). Shipped: all four deliverables plus test updates for signature changes. Slipped: MCP server redeploy blocked by registry.redhat.io 503 outage (filed #416).
Scope: stayed in scope.

## Shipped

- `cd5fa88` PR #414 merged (reconciliation from prior session); migration 025 deployed, `reconciliation_decisions` table verified on cluster
- `1661538` PR #415: fix extraction_run_id consistency (was per-candidate, now per-invocation); `rollback_extraction_run()` reverses creates/updates from a run using decision log; dry-run mode on `reconcile_candidate()` and `extract_from_thread()`; circuit breaker halts on anomalous create:update ratio; `_extract_window()` returns `list[ReconciliationResult]` instead of `list[UUID]`; 9 new tests, 6 existing tests updated for new signature

## Verification & confidence

- All 3 exit predicates from #348 verified by dedicated tests: rollback restores exact prior state (create soft-deleted, update reverted to v1), dry-run produces decisions with zero writes, circuit breaker trips on all-creates anomaly
- 45 directly-related tests pass; 610/614 full service suite pass (4 pre-existing Valkey failures, 1 pre-existing flaky integration test)
- Confidence: high -- core logic is tested against real SQLite DB (not mocks), rollback safety check for post-run modifications verified

## Judgment calls & deviations

- No alembic migration for `ConversationExtraction.extraction_run_id` -- the `ReconciliationDecision` table already indexes run IDs and serves as the rollback surface; adding a column to `ConversationExtraction` is unnecessary overhead for rollback
- Used direct ORM manipulation in rollback rather than calling `delete_memory()`/`update_memory()` to avoid side effects (entity extraction, curation, re-embedding)
- Circuit breaker default threshold set at 20:1 create:update ratio with min 5 decisions before arming -- conservative, can be tuned from decision log data

## Backlog delta

Filed #416 (MCP redeploy, blocked by registry outage). Closed: #348 needs admin close (code shipped, tests pass). No re-scoped issues.

## Drift & forward-collisions

- Backward -- #349 (dreaming benchmark): unblocked by #347 merge + #348 ship. #350-353 (curator agent): unblocked by #347 merge. #345 (reflection): unblocked by #347/#348.
- Forward -- none.

## For the reviewer

- Sanity-check: the rollback safety check (skip if post-run modification exists) is the right trade-off vs. trying to rebase the version chain. Worth confirming this matches the design intent.
- Thin verification: circuit breaker is tested as a pure function but not yet exercised end-to-end through `extract_from_thread()` with a real LLM (would need integration test or benchmark run).
- Wants guidance: none.

## Risks / watch-fors

- MCP redeploy (#416) is blocked by Red Hat registry outage. The running pod (build #19) has the #347 reconciliation code but not #348's rollback/dry-run. The dreaming pipeline won't use rollback/dry-run until a new build deploys.
- The `_extract_window()` return type change is a breaking internal API change. The `conversation_extraction.py` shim re-exports everything, so any external consumer importing `_extract_window` would need updating. No external consumers known.
