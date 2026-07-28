# Next Session -- Local

## Next: PostgresBackend extraction + parameterized tests (Phase 1, session 2 of 2)

Extract the PostgresBackend from existing memoryhub_core service code,
implement graph_neighbors for both backends, replace the frozen conftest
patches with the production dialect abstraction, and run the full
parameterized test suite across BOTH backends.

1. **PostgresBackend** -- extract from existing memoryhub_core services
   into `memoryhub_local/storage/postgres.py`. Wrap the 7 vector + 2
   keyword + 1 similarity call sites from `src/memoryhub_core/services/`
   into the RecallBackend protocol methods. Zero behavior change.

2. **graph_neighbors for both backends** -- port the recursive CTE from
   `services/graph.py:103` into PostgresBackend. Write the SQLite
   equivalent using VALUES clause for seed initialization instead of
   `unnest(CAST(... AS uuid[]))`.

3. **Replace frozen conftest patches** -- the monkey-patching in
   `tests/test_services/conftest.py` (lines 37-147) should be replaced
   by importing `memoryhub_local.models` with the portable types. This
   eliminates the FREEZE NOTICE pattern and makes the test infra
   maintainable.

4. **Parameterized test suite** -- extend the cheese test to run across
   BOTH SQLite and PostgreSQL backends via pytest parameterize. Verify
   existing 627 unit tests still pass with no regressions.

**Session start protocol:**
- Premise checks: `git log --oneline feat/personal-edition` shows 9
  commits (3 from architecture session + 6 from session 1); working tree
  clean; `memoryhub-local/` exists and `pip install -e .` works; cheese
  test (13 tests) green on SQLite
- What landed in session 1:
  - Package scaffold (pyproject.toml, directory structure)
  - RecallBackend protocol (4 methods in storage/recall.py)
  - Dialect type decorators (PortableUUID, JsonEncodedList,
    JsonEncodedVector, IntervalSeconds in models/dialect.py)
  - 8 model files ported with PG-specific types swapped
  - SQLiteBackend (3 of 4 methods: vector_recall with brute-force
    cosine, keyword_recall with FTS5, similarity_check)
  - 13 cheese tests green on SQLite
- Design notes from session 1 review:
  - FTS5 external content table does a full rebuild before every
    keyword search (O(n)); replace with triggers or contentless FTS
  - String-interpolated SQL in keyword_recall is safe (self-generated
    values) but parameterized queries are better practice
  - sqlite-vec requires Python built with --enable-loadable-sqlite-extensions;
    brute-force cosine works fine at personal scale as fallback
  - pysqlite3 package provides extension support on macOS
- Rules with history: all pushes through PRs; commit incrementally;
  don't modify memoryhub-core (except replacing conftest patches)
- Stop-and-ask before: any changes to existing published packages
  (sdk/, memoryhub-cli/)
- Close ritual: session summary + NEXT_SESSION update; verify 627+
  existing tests + parameterized cheese tests all green

**Exit predicate:**
- PostgresBackend in `memoryhub_local/storage/postgres.py` implements
  all 4 RecallBackend methods
- graph_neighbors works on both SQLite and PostgreSQL backends
- Frozen conftest patches replaced by production dialect abstraction
- Cheese test parameterized across both backends, all green
- Existing 627 unit tests pass with no regressions

## Remaining epic phases

A developer runs `pip install "memoryhub[local]"` +
`claude mcp add memoryhub -- memoryhub mcp` and has working, versioned,
searchable memory on their laptop with the same tool surface as the
cluster edition. No database server, no API keys, no background services.

Architecture doc: `planning/personal-edition.md` (grounded 2026-07-27).
Branch: `feat/personal-edition`.

### Phase 1: RecallBackend protocol + SQLiteBackend (2 sessions)

Extract the recall protocol, implement both backends, create the
`memoryhub-local` package scaffold, and replace the frozen test conftest
patches with a production-quality dialect abstraction.

**Session 1 (done):** Package scaffold, protocol, dialect config, model
port, SQLiteBackend (3 recall methods), cheese test on SQLite. All 6
items complete, 13 tests green.

**Session 2 (next):** PostgresBackend extraction from existing code (7 vector +
2 keyword + 1 similarity call sites), graph_neighbors for both backends
(CTE port), replace frozen conftest patches, parameterized test suite
across BOTH backends, verify existing 627 unit tests still pass.

**Definition of done (full phase):**
- `memoryhub-local/` exists as a package, passes `pip install -e .`
- "Cheese test" green on both SQLite and PostgreSQL backends
- Frozen conftest patches replaced by `configure_for_dialect("sqlite")`
- Existing 627 unit tests pass with no regressions

**Dependencies:** None -- entry point.

**Parallel-ok:** No. Everything depends on this.

### Phase 2: Local MCP server + `memoryhub mcp` CLI (2 sessions)

Add the `memoryhub mcp` subcommand, create personal-edition tool
wrappers, wire SQLite at XDG path, and make `pip install "memoryhub[local]"`
resolve.

**Work:**
1. Add `memoryhub mcp` subcommand to `memoryhub-cli/src/memoryhub_cli/main.py`
2. Create personal-edition tool wrappers (bypass auth/authz, hardcode tenant_id="local", auto-register session)
3. Wire SQLite engine at `~/.local/share/memoryhub/memoryhub.db` with WAL mode
4. Alembic batch mode for SQLite migrations, run at startup
5. Write personal-edition FastMCP instructions (no API key mention)
6. Add `[local]` extra to `sdk/pyproject.toml` pulling in `memoryhub-local` + `memoryhub-cli`
7. Same 4-tool compact profile: register_session, memory, admin_memory, thread

**Definition of done:**
- `pip install "memoryhub[local]"` resolves from a clean venv
- `claude mcp add memoryhub -- memoryhub mcp` starts a stdio MCP server
- Round-trip via Claude Code: register, write, search, read, update, version history -- all working
- Uses MockEmbeddingService (real embeddings are Phase 3)
- DB file at XDG path with WAL mode

**Dependencies:** Gated on Phase 1.

**Parallel-ok:** No.

### Phase 3: Local ONNX embeddings (1 session)

Implement OnnxEmbeddingService, first-run model download, `memoryhub doctor`.

**Work:**
1. Implement `OnnxEmbeddingService(EmbeddingService)` -- `embed()` and `embed_batch()` via onnxruntime CPU
2. Model: granite-embedding-small-english-r2 ONNX int8, 384-dim (same as cluster)
3. First-run download to `~/.local/share/memoryhub/models/` with progress bar
4. Wire into `memoryhub mcp` startup (replace MockEmbeddingService)
5. Add `memoryhub doctor` subcommand (edition, DB path/size, model present/absent)

**Definition of done:**
- Fresh `pip install "memoryhub[local]"` -> working semantic search in under 2 minutes (including model download)
- `memoryhub doctor` reports edition, DB, model status
- Search results are semantically meaningful, not hash-based

**Dependencies:** Gated on Phase 2.

**Parallel-ok:** No.

### Phase 4: Extraction + maintenance (1 session)

MCP sampling extraction, on-connect dreaming queue, `memoryhub dream` CLI.
Builds on the dreaming epic's stable extraction design (PRs #407, #412).

**Work:**
1. MCP sampling extraction path (from `planning/eager-fact-extraction.md`)
2. On-connect dreaming mode: pending extraction drains via sampling while a session is active
3. `memoryhub dream` CLI command with optional `--model ollama/...` for local models
4. Deferred queue for no-sampling-support fallback

**Definition of done:**
- Live sampling round-trip: Claude Code writes a thread, extraction runs via sampling, extracted facts appear as searchable memories
- `memoryhub dream` works with local models (Ollama)
- On-connect mode drains pending work during active sessions

**Dependencies:** Gated on Phase 3 (needs real embeddings). Depends on dreaming epic's extraction design (stable, confirmed 2026-07-27).

**Parallel-ok:** Yes -- Phase 5 can run concurrently.

### Phase 5: Onboarding + docs (1 session)

README quickstart, parity matrix, reproducible 10-minute story.

**Work:**
1. README quickstart rewrite with the two-command install path
2. Parity matrix: personal vs cluster feature table
3. Test the quickstart on a clean venv + fresh user directory
4. Document `memoryhub doctor`, `memoryhub dream`, `memoryhub config init` (optional)

**Definition of done:**
- An outsider follows the README and has working memory in 10 minutes
- Parity matrix published
- Quickstart tested on clean environment

**Dependencies:** Gated on Phase 3 (needs real embeddings for the demo). Does NOT require Phase 4 -- docs can note extraction as available with sampling-capable agents.

**Parallel-ok:** Yes -- can run concurrently with Phase 4.

---

## What this covers (and what it doesn't)

**In scope:**
- RecallBackend protocol + SQLite/PostgreSQL dual-backend
- `memoryhub-local` package (new, published to PyPI)
- `memoryhub mcp` stdio server for Claude Code
- Local ONNX embeddings (Granite, same 384-dim as cluster)
- MCP sampling extraction + on-connect dreaming
- Onboarding docs + parity matrix

**Out of scope (other epics own):**
- Membership join/leave (`memoryhub join <cluster>`) -- future epic
- Kubernetes-general / Helm chart -- `planning/kubernetes-general.md`
- Curator agent + reflection -- `NEXT_SESSION-curation.md`
- Full benchmark re-validation -- `NEXT_SESSION-dreaming.md` Phase 8

## What landed last session (2026-07-27, session 1)

Phase 1, session 1 complete. All 6 plan items shipped:

1. Package scaffold: `memoryhub-local/` with pyproject.toml, directory
   structure, verified `pip install -e .`
2. RecallBackend protocol: 4 methods (vector_recall, keyword_recall,
   similarity_check, graph_neighbors) in `storage/recall.py`
3. Dialect type decorators: PortableUUID, JsonEncodedList,
   JsonEncodedVector, IntervalSeconds in `models/dialect.py`
4. 8 model files ported from memoryhub_core with all PG-specific types
   replaced. Fixed stale embedding comment (all-MiniLM-L6-v2 -> Granite).
5. SQLiteBackend: 3 of 4 methods implemented (brute-force cosine for
   vector, FTS5 for keyword, brute-force for similarity). graph_neighbors
   deferred.
6. Cheese test: 13 tests green on SQLite (write, update, version chain,
   vector search, keyword search, similarity check, graph edges).

**Shipped commits:** `907602f` through `1aae645` (6 commits on
feat/personal-edition). 627 existing core tests pass with no regressions.

**Review findings (fixed):** IntervalSeconds.impl was String(20) instead
of Integer, sqlalchemy missing [asyncio] extra, dead code in
keyword_recall.

## Watch out for

- **FTS rebuild cost:** current FTS5 external content table does a full
  rebuild before every keyword search. Replace with triggers or
  contentless FTS in session 2 or Phase 2.
- **sqlite-vec extension loading:** macOS Python doesn't ship with
  --enable-loadable-sqlite-extensions. pysqlite3 is the workaround.
  Brute-force cosine works at personal scale as fallback.
- **ONNX model provenance (P3):** RedHatAI internal ask pending for
  attested INT8 ONNX export of granite-embedding-small-english-r2.
  Fallback: export and publish under the project org.

## If blocked

- If PostgreSQL test infra isn't available (session 2): parameterize
  cheese test with SQLite-only and defer PG to a follow-up.
- If ONNX model isn't available (P3): use MockEmbeddingService and
  defer P3. P2 is fully functional without real embeddings.
- If sqlite-vec has compatibility issues: brute-force approach already
  works (proven in session 1).
