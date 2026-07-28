# Next Session -- Local

## Next: Local MCP server + `memoryhub mcp` CLI (Phase 2, session 1 of 2)

Add the `memoryhub mcp` subcommand, create personal-edition tool
wrappers, wire SQLite at XDG path, and make `pip install "memoryhub[local]"`
resolve. This is the session that makes the personal edition usable from
Claude Code.

1. **`memoryhub mcp` subcommand** -- add to `memoryhub-cli/src/memoryhub_cli/main.py`.
   Starts a stdio FastMCP server pointing at the SQLite backend.

2. **Personal-edition tool wrappers** -- bypass auth/authz, hardcode
   tenant_id="local", auto-register session. Same 4-tool compact
   profile: register_session, memory, admin_memory, thread.

3. **SQLite engine at XDG path** -- `~/.local/share/memoryhub/memoryhub.db`
   with WAL mode. Create DB directory on first run.

4. **Alembic batch mode** -- SQLite migrations via Alembic batch mode,
   run at startup.

5. **FastMCP instructions** -- personal-edition system prompt (no API
   key mention, no cluster references).

6. **`[local]` extra** -- add to `sdk/pyproject.toml` pulling in
   `memoryhub-local` + `memoryhub-cli`.

**Session start protocol:**
- Premise checks: `git log --oneline feat/personal-edition` shows 14
  commits (3 arch + 6 s1 + 5 s2); Phase 1 complete; cheese test (23
  tests) green; 627 service tests green; working tree clean
- What landed in Phase 1:
  - memoryhub-local package scaffold, RecallBackend protocol, dialect types
  - 8 portable model files
  - SQLiteBackend (all 4 methods) + PostgresBackend (all 4 methods)
  - Frozen conftest replaced with production dialect types
  - 23 cheese tests parameterized across backends
- Rules with history: all pushes through PRs; commit incrementally;
  stop-and-ask before modifying existing published packages (sdk/, memoryhub-cli/)
- Close ritual: session summary + NEXT_SESSION update; verify new MCP
  server starts and responds to tool calls

**Exit predicate:**
- `memoryhub mcp` starts a stdio FastMCP server
- Round-trip via Claude Code: register, write, search, read works
- Uses MockEmbeddingService (real embeddings are Phase 3)
- DB file at XDG path with WAL mode
- `pip install "memoryhub[local]"` resolves from a clean venv

## Remaining epic phases

A developer runs `pip install "memoryhub[local]"` +
`claude mcp add memoryhub -- memoryhub mcp` and has working, versioned,
searchable memory on their laptop with the same tool surface as the
cluster edition. No database server, no API keys, no background services.

Architecture doc: `planning/personal-edition.md` (grounded 2026-07-27).
Branch: `feat/personal-edition`.

### Phase 1: RecallBackend protocol + SQLiteBackend (2 sessions) -- DONE

**Session 1:** Package scaffold, protocol, dialect config, model port,
SQLiteBackend (3 recall methods), cheese test on SQLite. 13 tests green.

**Session 2:** PostgresBackend extraction, graph_neighbors for both
backends, frozen conftest replaced with production dialect types,
parameterized cheese test. 23 tests green, 627 service tests green.

**Commits:** `907602f`..`d88a86a` (14 commits on feat/personal-edition)

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

## What landed last session (2026-07-27, session 2)

Phase 1 complete. All 4 plan items shipped + review fixes:

1. PostgresBackend: vector_recall (pgvector <=> via literal_column),
   keyword_recall (plainto_tsquery + ts_rank), similarity_check, graph_neighbors
2. graph_neighbors for both backends: SQLite uses VALUES CTE, PostgreSQL
   uses unnest(uuid[]) CTE. Bidirectional traversal, depth cap, edge/node
   filtering.
3. Frozen conftest replaced: production dialect types (JsonEncodedVector,
   JsonEncodedList) from memoryhub_local. _sqlite_schema_patches() context
   manager replaces 147 lines of inline monkey-patching.
4. Parameterized cheese test: 23 tests on SQLite, PostgreSQL activates
   via MEMORYHUB_TEST_PG_URL env var.

**Shipped commits:** `9a6b5f7` through `d88a86a` (5 commits on
feat/personal-edition). 627 existing core tests pass with no regressions.

**Review findings (fixed):** Conftest index restoration guard, UUID
interpolation safety comment, stale docstring, added multi-seed/depth-cap/
disconnected-node tests.

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
