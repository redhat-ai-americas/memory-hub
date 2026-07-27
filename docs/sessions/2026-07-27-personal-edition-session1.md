# Session Summary: Personal Edition Phase 1, Session 1

**Date:** 2026-07-27
**Branch:** feat/personal-edition
**Epic:** Personal Edition (memoryhub-local)
**Phase:** 1 -- RecallBackend protocol + SQLiteBackend
**Session:** 1 of 2

## What shipped

All 6 planned items complete. 5 commits on feat/personal-edition.

### 1. Package scaffold (`907602f`)
- `memoryhub-local/` with pyproject.toml (hatch build, deps: sqlalchemy[asyncio], aiosqlite, sqlite-vec, pydantic, pydantic-settings, alembic, fastmcp)
- Directory structure: storage/, models/, services/, embeddings/
- Verified: `pip install -e .` succeeds

### 2. RecallBackend protocol + dialect types + model port (`b680cae`)
- `storage/recall.py`: runtime_checkable Protocol with 4 methods (vector_recall, keyword_recall, similarity_check, graph_neighbors)
- `models/dialect.py`: 4 TypeDecorators (PortableUUID, JsonEncodedList, JsonEncodedVector, IntervalSeconds)
- 8 model files ported from memoryhub_core with all PG-specific types replaced
- Fixed stale embedding comment (all-MiniLM-L6-v2 -> granite-embedding-30m-english)
- Verified: 15 tables create cleanly on in-memory SQLite

### 3. SQLiteBackend (`0d757dd`)
- `vector_recall`: brute-force cosine distance in Python (O(n) but sufficient at <100K scale)
- `keyword_recall`: FTS5 virtual table with bm25() ranking
- `similarity_check`: brute-force cosine with max_distance filter
- `graph_neighbors`: stubbed (returns empty list, deferred to session 2)

### 4. Cheese test suite (`6ce9b58`)
- 13 tests green on SQLite: write, read, update, version chain walkback, vector search (similar/limit/filters), keyword search (match/no-match), similarity check (threshold/empty/limit), graph edge creation

### 5. Review fixes (`3296772`)
- IntervalSeconds.impl: String(20) -> Integer
- pyproject.toml: sqlalchemy -> sqlalchemy[asyncio]
- Removed dead code in keyword_recall

## Validation

- 13/13 cheese tests pass on SQLite (0.27s)
- 627/627 existing core service tests pass (no regressions)
- Lint clean (ruff)

## Design decisions

- **Brute-force over sqlite-vec:** macOS Python doesn't ship with `--enable-loadable-sqlite-extensions`. Rather than require pysqlite3 as a hard dependency, we use pure-Python cosine distance. At personal scale (<100K memories) this is fast enough. sqlite-vec can be added as an optimization in Phase 2/3 when we control engine creation.
- **Separate Base class:** memoryhub_local uses its own DeclarativeBase so local and core tables register independently. No import dependency on memoryhub_core.
- **No conftest changes yet:** The frozen test patches in tests/test_services/conftest.py are untouched this session. Replacing them is session 2 work (needs PostgresBackend to parameterize).

## Next session (session 2)

PostgresBackend extraction from existing core code, graph_neighbors for both backends, replace frozen conftest patches, parameterized test suite across both backends.
