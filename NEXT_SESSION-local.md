# Next Session -- Local

## Next: RecallBackend protocol + SQLiteBackend (Phase 1, session 1 of 2)

Bootstrap the `memoryhub-local` package, define the RecallBackend
protocol, port the SQLAlchemy models to be dialect-portable, implement
the SQLiteBackend, and prove it with a parameterized cheese test.

1. **Package scaffold** -- create `memoryhub-local/` with `pyproject.toml`
   (`memoryhub-local` package name, deps: sqlalchemy, aiosqlite,
   sqlite-vec, pydantic, pydantic-settings, alembic, fastmcp),
   `src/memoryhub_local/` directory structure (storage/, models/,
   services/, embeddings/). Verify `pip install -e .` works.

2. **RecallBackend protocol** -- define in
   `memoryhub_local/storage/recall.py`. Four methods: `vector_recall`,
   `keyword_recall`, `similarity_check`, `graph_neighbors`. See
   `planning/personal-edition.md` Section 3.3 for the protocol spec.

3. **`configure_for_dialect()`** -- create
   `memoryhub_local/models/dialect.py`. Handles UUID->TEXT,
   ARRAY(Text)->JSON, Vector(384)->BLOB/JsonEncodedVector,
   TSVECTOR+Computed->dropped (FTS5 is a separate virtual table),
   Interval->INTEGER, partial index portability, server_default cleanup.
   The `_JsonEncodedVector` TypeDecorator from
   `tests/test_services/conftest.py:37-50` migrates into production code.

4. **Port the models** -- dialect-portable versions of the models from
   `src/memoryhub_core/models/` (memory.py, conversation.py, campaign.py,
   contradiction.py, curation.py, project.py, role.py, reconciliation.py).
   These live in `memoryhub_local/models/`. Fix the stale model comment
   at `models/memory.py:109` (references all-MiniLM-L6-v2, should be
   Granite).

5. **SQLiteBackend** -- implement in `memoryhub_local/storage/sqlite.py`:
   - `vector_recall`: sqlite-vec `vec_distance_cosine()`
   - `keyword_recall`: FTS5 virtual table with `MATCH` and `bm25()`
   - `similarity_check`: sqlite-vec distance with max_distance filter
   - `graph_neighbors`: deferred to session 2 (PostgresBackend + graph
     CTE port)

6. **Cheese test** -- parameterized pytest fixture across SQLite backend:
   write a memory, update it, read version chain, search by vector,
   search by keyword, check curation similarity gate. All green on
   SQLite. PostgreSQL backend parameterization is session 2.

**Sequencing.** Items 1-3 are scaffolding (do first, in order). Items 4-5
are the bulk work (can interleave). Item 6 validates everything.

**Constraints for the session:**
- All work on `feat/personal-edition` branch
- Do not modify `src/memoryhub_core/` in this session -- the portable
  code is extracted INTO `memoryhub_local`, not refactored in place.
  Core stays untouched so the cluster edition isn't affected.
- Commit incrementally (not batched at end)
- `graph_neighbors` deferred to session 2 -- focus on the three recall
  methods that cover the hot search path

**Session start protocol:**
- Premise checks: `git log --oneline feat/personal-edition` shows 2
  commits (architecture doc + session summary); working tree clean;
  `planning/personal-edition.md` Section 3 has the grounded protocol
  spec; `tests/test_services/conftest.py` has the frozen patches to
  reference (not modify yet -- that's session 2 when PostgresBackend
  is also ready)
- Rules with history: all pushes through PRs; commit incrementally;
  don't modify memoryhub-core
- Stop-and-ask before: any changes to existing published packages
  (sdk/, memoryhub-cli/); any changes to src/memoryhub_core/
- Close ritual: session summary + NEXT_SESSION update; record which
  models ported and which cheese tests pass

**Exit predicate:**
- `memoryhub-local/` installable via `pip install -e .`
- RecallBackend protocol defined with 4 methods
- `configure_for_dialect("sqlite")` exists and handles all 8 model files'
  PostgreSQL-specific types
- SQLiteBackend implements vector_recall, keyword_recall, similarity_check
- Cheese test (write/update/version/vector-search/keyword-search/similarity)
  green on SQLite

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

**Session 1 (next):** Package scaffold, protocol, dialect config, model
port, SQLiteBackend (3 recall methods), cheese test on SQLite.

**Session 2:** PostgresBackend extraction from existing code (7 vector +
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

## What landed last session (2026-07-27)

Architecture grounding session. Competitive research (MemoryPalace, Mem0,
Letta), codebase audit (10 PG-specific call sites, 8 model files), package
layout decision (memoryhub-local), two-command install design.

**Shipped:** `4130f45` (architecture doc), `593710d` (session summary)

## Watch out for

- **Code duplication risk:** memoryhub-local extracts portable service code
  from memoryhub-core under its own namespace. Establish the extraction
  pattern early in P1 to minimize drift.
- **Stale model comment:** `models/memory.py:109` references all-MiniLM-L6-v2
  instead of Granite. Fix during P1.
- **ONNX model provenance (P3):** RedHatAI internal ask pending for attested
  INT8 ONNX export of granite-embedding-small-english-r2. Fallback: export
  and publish under the project org.

## If blocked

- If ONNX model isn't available (P3): use MockEmbeddingService and
  defer P3. P2 is fully functional without real embeddings.
- If sqlite-vec has compatibility issues: the `sqlite_exact` brute-force
  approach (compute cosine in Python) works at personal scale (<100K
  memories) as a fallback.
