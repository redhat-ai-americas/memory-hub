# Next Session -- Local

## Next: ONNX embeddings + Alembic cleanup (Phase 3)

Make search semantically meaningful by replacing MockEmbeddingService with
a real ONNX embedding model, add `memoryhub doctor` for diagnostics, and
backfill the Alembic batch-mode setup deferred from Phase 2.

1. **Alembic batch mode for SQLite** -- create `memoryhub-local/alembic.ini`,
   `migrations/env.py` with `render_as_batch=True`, and an initial squashed
   migration. Wire `alembic upgrade head` into server startup so future pip
   upgrades migrate the local DB automatically.

2. **OnnxEmbeddingService** -- implement `OnnxEmbeddingService(EmbeddingService)`
   using onnxruntime CPU. Model: granite-embedding-small-english-r2 ONNX int8,
   384-dim (same as cluster). First-run download to
   `~/.local/share/memoryhub/models/` with progress bar.

3. **Wire into server startup** -- replace MockEmbeddingService with
   OnnxEmbeddingService at startup. Fall back to MockEmbeddingService if model
   not yet downloaded (with a warning directing the user to `memoryhub doctor`).

4. **`memoryhub doctor` subcommand** -- add to memoryhub-cli. Reports: edition
   (personal/cluster), DB path and size, model present/absent and path,
   embedding dim, WAL mode status.

5. **Smoke test** -- verify fresh `pip install "memoryhub[local]"` produces
   working semantic search in under 2 minutes (including model download).

**Sequencing.** Alembic first (small, mechanical), then ONNX embedding service,
then wire into server, then doctor CLI, then smoke test.

**Session start protocol:**
- Premise checks: `git log --oneline feat/personal-edition` shows 23
  commits; Phase 2 complete (round-trip green); 24 local tests pass;
  627 service tests green; working tree clean
- What landed in Phase 2:
  - EmbeddingService ABC + MockEmbeddingService + identity module
  - Database module (SQLite WAL at XDG path)
  - Memory + thread service layer (self-contained, no memoryhub_core imports)
  - 4-tool compact profile: register_session, memory, thread, admin_memory
  - FastMCP stdio server with personal-edition instructions
  - `memoryhub mcp` CLI subcommand + SDK `[local]` extra
  - FTS5 sync triggers, transitive chain walk, message cascade fix
- Rules with history: all pushes through PRs; commit incrementally;
  stop-and-ask before modifying existing published packages (sdk/, memoryhub-cli/)
- Close ritual: session summary + NEXT_SESSION update; verify semantic
  search returns meaningfully different results than mock embeddings

**Exit predicate:**
- Fresh `pip install "memoryhub[local]"` produces working semantic search
  in under 2 minutes (including model download)
- `memoryhub doctor` reports edition, DB, model status
- Search results are semantically meaningful, not hash-based
- Alembic migration runs at startup without errors
- `pip install "memoryhub[local]"` still resolves from a clean venv

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

### Phase 2: Local MCP server + `memoryhub mcp` CLI (2 sessions) -- DONE

**Session 1:** Full vertical slice -- embedding service, database module,
service layer, tool wrappers, FastMCP server, CLI subcommand, SDK extra.
Round-trip verified (register/write/search/read/update/list/thread/delete).
Review fixes: FTS triggers, chain walk, message cascade.

**Commits:** `4006fc1`..`1149890` (9 commits on feat/personal-edition)

### Phase 3: Local ONNX embeddings (1 session) -- NEXT

Implement OnnxEmbeddingService, first-run model download, `memoryhub doctor`.

**Work:**
1. Implement `OnnxEmbeddingService(EmbeddingService)` via onnxruntime CPU
2. Model: granite-embedding-small-english-r2 ONNX int8, 384-dim (same as cluster)
3. First-run download to `~/.local/share/memoryhub/models/` with progress bar
4. Wire into `memoryhub mcp` startup (replace MockEmbeddingService)
5. Add `memoryhub doctor` subcommand (edition, DB path/size, model present/absent)
6. Add Alembic batch mode setup (deferred from Phase 2)

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

## What landed last session (2026-07-27, P2S1)

Phase 2 complete. 9 commits shipped the full local MCP server vertical slice:

1. EmbeddingService ABC + MockEmbeddingService + shared identity module
2. Database module: async SQLite engine at XDG path with WAL mode
3. Memory + thread service layer (self-contained, no memoryhub_core imports)
4. Personal-edition tool wrappers: register_session, memory (25+ actions),
   thread, admin_memory -- same interface as cluster edition
5. FastMCP stdio server with personal-edition instructions
6. `memoryhub mcp` CLI subcommand + SDK `[local]` extra
7. Round-trip integration test
8. Review fixes: FTS5 sync triggers, transitive forward chain walk in
   delete_memory, message cascade in thread soft-delete

**Session summary:** `session-summaries/2026-07-27-personal-edition-p2s1.md`

**Shipped commits:** `4006fc1` through `1149890` (9 commits on
feat/personal-edition). 24 local tests pass, 627 core tests pass.

## Watch out for

- **ONNX model provenance (P3):** RedHatAI internal ask pending for
  attested INT8 ONNX export of granite-embedding-small-english-r2.
  Fallback: export and publish under the project org.
- **sqlite-vec extension loading:** macOS Python doesn't ship with
  --enable-loadable-sqlite-extensions. pysqlite3 is the workaround.
  Brute-force cosine works at personal scale as fallback.
- **onnxruntime wheel size:** ~50MB for CPU-only. The `[local]` extra
  should document this so users aren't surprised by the download.
- **os.getlogin() in non-TTY:** can fail in cron/CI. Fallback to $USER
  is in place but not guaranteed on all platforms.

## If blocked

- If ONNX model isn't available: implement OnnxEmbeddingService with a
  smaller public model (all-MiniLM-L6-v2 ONNX is widely available, 384-dim)
  and swap to Granite when available.
- If onnxruntime has compatibility issues on the target platform: keep
  MockEmbeddingService as default and make ONNX opt-in via
  `pip install "memoryhub[local,embeddings]"`.
