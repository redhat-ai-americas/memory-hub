# Session Summary -- 2026-07-27 -- personal-edition -- P1S1 RecallBackend + SQLiteBackend

**Plan:** NEXT_SESSION-local.md (Phase 1, session 1 of 2)   **Commits:** `907602f`..`2f1bba8` (feat/personal-edition)
**Deployed:** none   **Model:** Opus 4.6

## Plan vs. actual
Planned: bootstrap memoryhub-local package, define RecallBackend protocol, port models, implement SQLiteBackend, prove with cheese test. Shipped: all 6 items complete, 13 tests green. Slipped: none.
Scope: stayed in scope. Did not touch memoryhub-core as planned.

## Shipped
- `907602f` Package scaffold: memoryhub-local/ with pyproject.toml and directory structure
- `b680cae` RecallBackend protocol (4 methods), dialect type decorators (PortableUUID, JsonEncodedList, JsonEncodedVector, IntervalSeconds), 8 model files ported from memoryhub_core
- `0d757dd` SQLiteBackend: brute-force cosine for vector_recall/similarity_check, FTS5 for keyword_recall, graph_neighbors stubbed
- `6ce9b58` Cheese test suite: 13 tests covering write/update/version-chain/vector-search/keyword-search/similarity-check/graph-edges
- `3296772` Review fixes: IntervalSeconds impl type, sqlalchemy[asyncio] dep, dead code removal

## Verification & confidence
- memoryhub-local cheese tests: 13/13 green on SQLite (0.28s)
- Core regression: 627/627 existing service tests pass (1 skipped, pre-existing)
- Lint: ruff clean across memoryhub-local/ and src/
- Secrets: gitleaks clean (865 commits scanned)
- Table creation: 15 tables create on in-memory SQLite without errors
- Confidence: **high** -- every exit predicate met, no regressions, clean lint and secrets

## Judgment calls & deviations
- **Brute-force cosine over sqlite-vec:** macOS Python doesn't ship with `--enable-loadable-sqlite-extensions`. Used pure-Python cosine distance instead of sqlite-vec's `vec_distance_cosine()`. At personal scale (<100K memories) this is fast enough; sqlite-vec can be added when we control engine creation (Phase 2).
- **Separate DeclarativeBase:** memoryhub_local uses its own Base so table metadata registers independently of memoryhub_core. Zero import dependency on core.
- **No `configure_for_dialect()` function:** plan item 3 described a function; we went with direct type substitution in the models (cleaner, no runtime patching needed). Same outcome, better pattern.
- **Rebuilt Python:** pyenv rebuild with `--enable-loadable-sqlite-extensions` attempted but didn't take effect (existing install cached). pysqlite3 confirmed as the workaround path.

## Backlog delta
Filed: none. Closed: none. Deferred: graph_neighbors to session 2 (per plan).

## Drift & forward-collisions
- Backward: none -- new package, no existing issues affected.
- Forward: none -- no later issues reference memoryhub-local yet.

## For the reviewer
- Sanity-check: the FTS5 external content table does a full `rebuild` before every keyword search (O(n)). Acceptable at personal scale but should be replaced with triggers or a contentless table before Phase 2 ships.
- Thin verification: keyword_recall uses string-interpolated SQL for rowid IN clauses. Values are self-generated integers and UUIDs so injection isn't possible, but parameterized queries would be better practice.
- Wants guidance: none.

## Risks / watch-fors
- **FTS rebuild cost:** O(n) rebuild per keyword search. Not a problem at <1K memories but will degrade. Track for session 2.
- **sqlite-vec extension loading:** the pysqlite3 workaround works but adds a dependency. Phase 2/3 needs to decide whether to hard-depend on pysqlite3 or keep brute-force as default.
- **Model duplication:** memoryhub-local carries its own copy of all 8 model files. Any schema change in memoryhub_core needs to be mirrored. This is the intentional extraction pattern but creates drift risk over time.
