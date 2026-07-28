# Next Session -- Local

## Next: Extraction + maintenance (Phase 4)

MCP sampling extraction, on-connect dreaming queue, `memoryhub dream` CLI.
Builds on the dreaming epic's stable extraction design (PRs #407, #412).

1. **MCP sampling extraction path** -- implement the extraction pipeline
   from `planning/eager-fact-extraction.md` for the personal edition.
   The server issues MCP sampling requests to extract facts from
   conversation threads.

2. **On-connect dreaming mode** -- pending extraction drains via sampling
   while an agent session is active. Threads with unextracted messages
   queue for processing on the next session start.

3. **`memoryhub dream` CLI command** -- add to memoryhub-cli with optional
   `--model ollama/...` for local LLM models. Runs extraction explicitly
   rather than waiting for on-connect mode.

4. **Deferred queue for no-sampling-support fallback** -- when the MCP
   client doesn't support sampling (e.g., non-Claude agents), queue
   threads for manual extraction via `memoryhub dream`.

**Sequencing.** MCP sampling extraction first (core), then on-connect mode,
then dream CLI, then deferred queue fallback.

**Session start protocol:**
- Premise checks: `git log --oneline feat/personal-edition` shows 27+
  commits; Phase 3 complete (ONNX green, 30 tests); working tree clean
- What landed in Phase 3:
  - Alembic batch-mode setup with auto-migrate at startup
  - OnnxEmbeddingService with granite-embedding-small-english-r2 INT8
  - Auto-download from HuggingFace Hub on first startup
  - `memoryhub doctor` subcommand
  - 6 ONNX embedding tests (semantic similarity verified)
- What landed in Phase 2:
  - Full local MCP server vertical slice (tools, services, server, CLI)
- Rules with history: all pushes through PRs; commit incrementally;
  stop-and-ask before modifying existing published packages (sdk/, memoryhub-cli/)
- Read `planning/eager-fact-extraction.md` before starting -- that's the
  extraction design this phase implements for the personal edition
- Close ritual: session summary + NEXT_SESSION update

**Exit predicate:**
- Live sampling round-trip: Claude Code writes a thread, extraction runs
  via sampling, extracted facts appear as searchable memories
- `memoryhub dream` works with local models (Ollama)
- On-connect mode drains pending work during active sessions
- 30+ tests pass (existing + new extraction tests)

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

### Phase 3: Local ONNX embeddings (1 session) -- DONE

**Session 1:** Alembic batch-mode migration setup (async bridge env.py,
auto-generated initial migration, pre-existing DB detection),
OnnxEmbeddingService with granite-embedding-small-english-r2 INT8,
auto-download from HuggingFace Hub, fallback to MockEmbeddingService,
`memoryhub doctor` subcommand, 6 ONNX tests.
Semantic similarity verified: cat-kitten 0.83 vs cat-database 0.70.

**Commits:** `2b8f5fc`..`450064b` (4 commits on feat/personal-edition)

### Phase 4: Extraction + maintenance (1 session) -- NEXT

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

**Dependencies:** Gated on Phase 3. Depends on dreaming epic's extraction design (stable, confirmed 2026-07-27).

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

## What landed last session (2026-07-28, P3S1)

Phase 3 complete. 4 commits shipped ONNX embeddings and Alembic:

1. Alembic batch-mode setup with async bridge, auto-generated initial
   migration, pre-existing DB detection, `auto_migrate()` replaces `create_tables()`
2. OnnxEmbeddingService with granite-embedding-small-english-r2 INT8,
   auto-download from HuggingFace Hub, fallback to MockEmbeddingService
3. `memoryhub doctor` subcommand (edition, DB, model, WAL, migration status)
4. 6 ONNX embedding tests including semantic similarity and search ranking

**Session summary:** `session-summaries/2026-07-28-personal-edition-p3s1.md`

**Shipped commits:** `2b8f5fc` through `450064b` (4 commits on
feat/personal-edition). 30 local tests pass.

## Watch out for

- **MCP sampling support:** not all MCP clients support sampling. Claude
  Code does, but other agents may not. The deferred queue fallback
  (Phase 4, item 4) handles this.
- **eager-fact-extraction.md:** the extraction design doc must be read
  before starting Phase 4. It defines the extraction pipeline, prompt
  format, and reconciliation flow.
- **transformers dependency size:** ~200MB+. If install size becomes a
  concern, consider switching to `tokenizers` library directly.
- **os.getlogin() in non-TTY:** can fail in cron/CI. Fallback to $USER
  is in place but not guaranteed on all platforms.

## If blocked

- If MCP sampling isn't supported by the target agent: implement
  `memoryhub dream` as the primary extraction path (direct LLM call)
  and make sampling the optimization, not the requirement.
- If the dreaming epic's extraction design changes: check
  `planning/eager-fact-extraction.md` and PRs #407, #412 for the latest.
