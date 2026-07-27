# MemoryHub Personal Edition: `pip install memoryhub`, Zero Infrastructure

**Status:** Architecture (grounded in codebase analysis and competitive research)
**Original design:** 2026-07-16, @rdwj (designed with Claude in Cowork)
**Architecture update:** 2026-07-27, @rdwj (codebase audit, package
layout decision, RecallBackend protocol, local MCP server design)
**Builds on:** existing `memoryhub` PyPI package (SDK, v0.14.0), `memoryhub-core`
(server-side library), `planning/eager-fact-extraction.md` (sampling),
`strategy/client-supplied-intelligence.md` (the zero-credential wedge)

---

## Changelog

- **2026-07-27:** Grounded architecture pass. Added package architecture
  (Section 3a), RecallBackend protocol with call-site analysis (Section 3
  rewrite), SQLite implementation details (Section 3b), local MCP server
  design (Section 7a), parity testing strategy (Section 7b). Updated
  product statement with competitive positioning and two-command install.
  Updated sequencing with codebase-grounded estimates. Resolved open
  questions Q1 (package layout) and Q4 (scope semantics).
- **2026-07-16:** Original design document.

---

## 1. The product statement

A developer runs:

```bash
pip install "memoryhub[local]"
claude mcp add memoryhub -- memoryhub mcp
```

and has persistent, versioned, searchable agent memory backed by a single
SQLite file, with **no database server, no object store, no GPU, no model
API key, no account, and no config init step**. The MCP server's
instructions tell the agent how to use the tools. First retrieval works
within a minute of install.

`memoryhub config init` remains available for power users who want to
customize loading patterns, focus sources, or hook behavior, but it is not
required for the basic experience.

### Why (adoption mechanics)

- Top-of-funnel: nobody evaluates a memory platform by provisioning an
  OpenShift cluster. They evaluate it in Claude Code in ten minutes.
- The community -> product ladder is the org's home motion. Local mode
  is the community edition; the cluster is the product; `memoryhub join`
  is the bridge.
- Competitive wedge (verified against primary sources 2026-07-16 and
  2026-07-27):

| | Install | API key? | Services | MCP |
|---|---|---|---|---|
| **MemoryHub Personal** | `pip install "memoryhub[local]"` | No | None (SQLite + ONNX) | `memoryhub mcp` (stdio) |
| **MemoryPalace** | `pip install mempalace` | No | None (SQLite + ChromaDB) | `mempalace-mcp` (stdio) |
| **Mem0** | `pip install mem0ai` | Yes (`OPENAI_API_KEY`) | None for lib, Docker for MCP | No official MCP server |
| **Letta** | `pip install letta` | No (hosted endpoint) | `letta server` (persistent FastAPI) | Not an MCP server (client only) |

MemoryHub Personal matches MemoryPalace on install simplicity. The
differentiator is the enterprise upgrade path: `memoryhub join <cluster>`
moves a developer onto the enterprise edition with the same tool surface,
version chains preserved, and an audit trail. No competitor in the
category has a governed join/leave story.

## 2. Substrate mapping

| Cluster | Personal | Notes |
|---------|----------|-------|
| PostgreSQL + pgvector | SQLite + sqlite-vec | vector recall; ANN adequate at personal scale (<100K memories) |
| tsvector + GIN | SQLite FTS5 (BM25) | keyword recall -- maps one-to-one |
| MinIO (S3 spill) | inline in SQLite | personal content stores inline (SQLite handles MB-scale TEXT fine) |
| TEI Granite embedding (GPU) | granite-embedding-small-english-r2, ONNX int8, CPU | Same model family -- embeddings are semantically continuous across editions |
| TEI Granite reranker (GPU) | optional extra `[reranker]`, ONNX CPU | k is small at personal scale; default off, honest flag when off |
| Valkey, auth service, OAuth | none | single user; tenant_id="local", owner = OS user |
| CronJob agents (curator etc.) | none in v1 | see maintenance model, Section 5 |
| Alembic migrations | Alembic, batch mode | pip upgrades must migrate the local DB |
| DB location | XDG path (`~/.local/share/memoryhub/memoryhub.db`) | one file; backup = copy the file |

**Kept in full, deliberately:** versioning + `is_current`, provenance,
extraction run IDs, honesty flags (`content_truncated`/`full_available`),
chunking + chunk-to-parent expansion, fact extraction + `retrieval_unit`,
simplified curation gates, graph relationships, temporal classification,
and a lightweight audit table. Governance is the differentiator.

**Dropped, deliberately:** RBAC, multi-tenancy, OAuth, cross-namespace
anything, SDC, leader election, push broadcast (Valkey), S3 spill,
entity extraction (GLiNER/spaCy -- too heavy for local install), campaign
scopes.

## 3. The load-bearing decision: a RecallBackend protocol

`memoryhub-core` services currently speak SQLAlchemy with
Postgres-specific constructs. The personal edition requires isolating
the PostgreSQL-specific **recall paths** behind a protocol. Everything
else -- CRUD, version chains, branch flags, filter construction -- uses
portable SQLAlchemy ORM and needs no abstraction.

### 3.1 Why a narrow protocol, not a full storage abstraction

Codebase audit (2026-07-27) found that PostgreSQL-specific query
operations are concentrated in three query shapes:

- **Vector recall** (pgvector's `cosine_distance`): 7 call sites across
  5 files. 6 of 7 already have try/except fallback to weight-based
  ordering.
- **Keyword recall** (tsvector/FTS): 2 call sites in
  `services/memory.py`, both guarded by try/except.
- **Graph traversal** (raw CTE with `unnest(CAST(:seed_ids AS uuid[]))`):
  1 call site in `services/graph.py`.

All other service operations -- `create_memory`, `read_memory`,
`update_memory`, `delete_memory`, `list_memories`, `get_memory_history`,
`report_contradiction`, `resolve_contradiction`, version chain walking,
branch flag queries -- use pure SQLAlchemy ORM and work on any dialect.

The model-level PostgreSQL constructs (UUID, ARRAY, TSVECTOR, Vector,
partial indexes, GIN indexes) are handled by dialect-conditional column
types (Section 3b), not by the recall protocol.

### 3.2 Call-site inventory

| File | Function | Line | Op | Fallback? |
|------|----------|------|----|-----------|
| `services/memory.py` | `search_memories` | 1118 | cosine_distance | Yes |
| `services/memory.py` | `search_memories_with_focus` | 1555 | cosine_distance | Yes |
| `services/memory.py` | `search_memories` | 1178 | plainto_tsquery/ts_rank | Yes |
| `services/memory.py` | `search_memories_with_focus` | 1726 | plainto_tsquery/ts_rank | Yes |
| `services/curation/similarity.py` | `check_similarity` | 66 | cosine_distance | Yes |
| `services/curation/similarity.py` | `get_similar_memories` | 135 | cosine_distance | **No** |
| `services/entity.py` | `find_or_create_entity` | 113 | cosine_distance | Yes |
| `services/pattern.py` | `detect_patterns` | 61 | cosine_distance | Yes |
| `services/admin.py` | `search_memory_admin` | 115 | cosine_distance | Yes |

Additionally, `services/graph.py` `collect_graph_neighbors` (line 103)
contains a raw PostgreSQL CTE with `unnest(CAST(:seed_ids AS uuid[]))`.

### 3.3 Protocol definition

The protocol lives in `memoryhub_core/storage/recall.py` (new file).

```python
from typing import Protocol, runtime_checkable

@runtime_checkable
class RecallBackend(Protocol):
    async def vector_recall(
        self,
        query_embedding: list[float],
        filters: list,
        limit: int,
        session: AsyncSession,
    ) -> list[tuple[MemoryNode, float]]:
        """Return (node, distance) pairs sorted by ascending distance."""
        ...

    async def keyword_recall(
        self,
        query_text: str,
        filters: list,
        limit: int,
        session: AsyncSession,
    ) -> list[tuple[MemoryNode, float]]:
        """Return (node, rank) pairs sorted by descending rank."""
        ...

    async def similarity_check(
        self,
        embedding: list[float],
        filters: list,
        max_distance: float,
        limit: int,
        session: AsyncSession,
    ) -> list[tuple[uuid.UUID, float]]:
        """Return (id, distance) pairs within max_distance.
        Used by curation similarity gate. The similar-memory API
        (get_similar_memories) uses this for ranked IDs, then does a
        follow-up ORM query for full node stubs and pagination."""
        ...

    async def graph_neighbors(
        self,
        seed_ids: list[uuid.UUID],
        max_depth: int,
        max_neighbors: int,
        session: AsyncSession,
    ) -> list[uuid.UUID]:
        """Return neighbor IDs within max_depth hops."""
        ...
```

### 3.4 Implementations

**`PostgresBackend`:** Extracted from existing code with zero behavior
change. `vector_recall` uses `MemoryNode.embedding.cosine_distance()`.
`keyword_recall` uses `plainto_tsquery`/`ts_rank`/`search_vector.op("@@")`.
`similarity_check` uses the existing `check_similarity` logic.
`graph_neighbors` uses the existing recursive CTE.

**`SQLiteBackend`:** `vector_recall` uses sqlite-vec's
`vec_distance_cosine()`. `keyword_recall` uses FTS5 `MATCH` with
`bm25()` ranking. `similarity_check` uses sqlite-vec distance with a
WHERE clause on distance. `graph_neighbors` rewrites the CTE to use a
VALUES clause for seed initialization instead of `unnest(CAST(... AS
uuid[]))`.

**The parity guarantee is mechanical:** the existing core/MCP test suites
get parameterized over both backends in CI. A tool behavior that differs
between editions is a failing test, not a docs footnote.

## 3a. Package architecture

### Current packages

| Package | Location | Version | Published | Provides |
|---------|----------|---------|-----------|----------|
| `memoryhub` | `sdk/` | 0.14.0 | Yes (PyPI) | SDK: MemoryHubClient, models, config. Pure MCP protocol client. |
| `memoryhub-cli` | `memoryhub-cli/` | 0.12.0 | Yes (PyPI) | CLI: `memoryhub` command (config, search, write, admin, etc.) |
| `memoryhub-core` | root `pyproject.toml` | 0.10.1 | No (internal) | Server-side: models, services, storage. PostgreSQL-bound. |
| MCP server | `memory-hub-mcp/` | n/a | No (container) | FastMCP tools, auth, deployed to OpenShift |

### Breaking change analysis (2026-07-27)

Adding `[local]` extras and the `memoryhub mcp` subcommand is purely
additive -- **zero breaking changes** to existing pip consumers.
`memoryhub-core` has never been published to PyPI; its refactoring
(RecallBackend protocol, dialect.py) only affects monorepo consumers
(MCP server, dashboard BFF, tests).

### Decision: SDK stays lean, new `memoryhub-local` package

`pip install memoryhub` continues to install only the SDK.

`pip install "memoryhub[local]"` pulls in a new `memoryhub-local`
package (published to PyPI) plus the CLI:

```
memoryhub[local]
  |-- memoryhub          (SDK: httpx, pyjwt, pydantic, pyyaml, fastmcp)
  |-- memoryhub-cli      (CLI: typer, rich -- provides `memoryhub` entry point)
  '-- memoryhub-local    (NEW, published to PyPI)
        |-- sqlalchemy[asyncio]>=2.0
        |-- aiosqlite
        |-- sqlite-vec
        |-- onnxruntime
        |-- pydantic>=2.0, pydantic-settings
        |-- alembic
        '-- pyyaml
```

**Why `memoryhub-local` instead of publishing `memoryhub-core`:**
`memoryhub-core` contains the full server-side surface (models,
services, admin, multi-tenant auth, curation, etc.) and is not
designed as a public API. Publishing it would create stability
guarantees we don't want to maintain. `memoryhub-local` has a
deliberately narrow public API: start the stdio MCP server and
that's it. Everything else is internal.

**Package structure:**

```
memoryhub-local/           (new top-level directory in monorepo)
  pyproject.toml           (published to PyPI as memoryhub-local)
  src/memoryhub_local/
    __init__.py            (version, public API: run_server())
    server.py              (FastMCP setup, stdio entry point)
    tools/                 (personal-edition tool wrappers)
    storage/
      backend.py           (RecallBackend protocol)
      sqlite.py            (SQLiteBackend: sqlite-vec + FTS5)
      postgres.py          (PostgresBackend: pgvector + tsvector)
    models/                (dialect-portable models)
      dialect.py           (configure_for_dialect())
      ...                  (portable subset of memoryhub_core models)
    services/              (portable subset of memoryhub_core services)
    embeddings/
      onnx.py              (OnnxEmbeddingService)
    migrations/            (Alembic, SQLite batch mode)
```

The portable service and model code lives once in the monorepo. The
`memoryhub-local` package includes the extracted portable subset
under its own `memoryhub_local` namespace. The cluster edition
(`memoryhub-core`, not published) continues to use its code from the
monorepo source tree.

The `PostgresBackend` ships in `memoryhub-local` alongside
`SQLiteBackend` so the same package can be used in both modes. This
also enables the parity test suite to run against both backends from
a single package install.

The exact extraction boundary -- how much of memoryhub-core's service
code gets ported into memoryhub-local vs. re-implemented -- is a P1
implementation detail. The RecallBackend protocol defines the
interface; the service layer above it should be maximally shared.

### pyproject.toml changes

**`sdk/pyproject.toml`** -- add `[local]` extra:
```toml
[project.optional-dependencies]
local = [
    "memoryhub-cli>=0.12.0",
    "memoryhub-local>=0.1.0",
]
```

**`memoryhub-local/pyproject.toml`** (new):
```toml
[project]
name = "memoryhub-local"
dependencies = [
    "sqlalchemy[asyncio]>=2.0",
    "pydantic>=2.0",
    "pydantic-settings",
    "alembic",
    "pyyaml",
    "aiosqlite",
    "sqlite-vec>=0.1.1",
    "onnxruntime>=1.16",
    "fastmcp>=2.11.3",
]
```

## 3b. SQLite implementation details

### Column type mapping

Dialect-conditional column types replace the frozen monkey-patches in
`tests/test_services/conftest.py` (lines 37-147, FREEZE NOTICE at
line 7). A new `memoryhub_core/models/dialect.py` module provides
`configure_for_dialect(dialect_name: str)` called once at engine
creation. The existing `_JsonEncodedVector` TypeDecorator from the
test conftest (lines 37-50) migrates into production code.

| PostgreSQL | SQLite | Files affected |
|-----------|--------|----------------|
| `Vector(384)` (pgvector) | `BLOB` via sqlite-vec / `JsonEncodedVector` | `models/memory.py:110` |
| `TSVECTOR` + `Computed(...)` | Separate FTS5 virtual table | `models/memory.py:112-119` |
| `UUID(as_uuid=True)` (~25 cols) | `TEXT` storing hex UUIDs | All 8 model files |
| `ARRAY(Text)` (3 cols) | `JSON` (TEXT) | `models/memory.py:71`, `models/conversation.py:65,235` |
| `ARRAY(Integer)` (1 col) | `JSON` (TEXT) | `models/conversation.py:235` |
| `Interval` (1 col) | `INTEGER` (seconds) | `models/campaign.py:41` |
| `JSON` from pg dialect (6 cols) | Standard SQLAlchemy `JSON` | Various |
| `server_default=text("uuid_generate_v4()")` | App-generated `uuid.uuid4()` | All model PKs |
| `server_default=text("'{}'::text[]")` | `server_default=None` | `models/memory.py:74`, `models/conversation.py:67,239` |
| `server_default=text("'{}'::jsonb")` | `server_default=None` | `models/memory.py:229`, `models/curation.py:45` |
| `postgresql_using="gin"` (2 indexes) | Dropped (FTS5 provides its own) | `models/memory.py:171-172` |
| `postgresql_where` (8 partial indexes) | `sqlite_where` equivalent or dropped | `models/memory.py:176-183`, `models/conversation.py:109-113,194-195`, `models/curation.py:90` |
| `CheckConstraint("jsonb_typeof(...)")` | Dropped | `models/conversation.py:114` |

### Specific portability fixes

**ARRAY.any() (1 call site):** `services/conversation.py` line 264 uses
`ConversationThread.participant_ids.any(participant_id)`. For SQLite
with JSON-stored arrays, this becomes a `json_each()` subquery or a
portable helper function.

**Raw CTE in graph.py (line 103):** The `unnest(CAST(:seed_ids AS
uuid[]))` initialization becomes a VALUES clause or IN-based seed.
The recursive CTE body (`WITH RECURSIVE`) is supported by SQLite.

### Alembic for SQLite

Alembic batch mode (`render_as_batch=True` in `env.py`) for SQLite,
since SQLite does not support `ALTER TABLE ... ADD COLUMN` with all
constraint types. Migrations maintain a separate branch for SQLite
schema initialization (single squashed migration creating all tables)
alongside the PostgreSQL incremental migrations.

## 4. Models without infrastructure

- **Embeddings (required):** granite-embedding-small-english-r2 exported
  to ONNX int8, run via onnxruntime (CPU). Same 384-dim space as the
  cluster edition (`EMBEDDING_DIM = 384` at
  `memoryhub_core/services/embeddings.py:19`).

  `OnnxEmbeddingService` implements the existing `EmbeddingService` ABC
  (`embeddings.py:22-33`) which defines exactly two methods:
  `embed(text) -> list[float]` and
  `embed_batch(texts) -> list[list[float]]`.

  Model location: `~/.local/share/memoryhub/models/granite-embedding-small-english-r2/`.
  First-run download: auto-download with progress bar on first `embed()` call.
  Install weight: ~50MB wheels (onnxruntime) + ~90MB model download.

- **Reranker (optional `[reranker]` extra):** Granite reranker ONNX.
  Default off; status visible via `memoryhub doctor`.

- **No LLM anywhere in the base install.** This is a hard product
  constraint. Extraction rides MCP sampling (the connected agent's own
  model).

## 5. Extraction and maintenance without a server LLM

- **Eager fact extraction:** MCP sampling, exactly as designed in
  `eager-fact-extraction.md`. The connected client (Claude Code/Desktop)
  IS the model. The "no-sampling-support" fallback is `deferred` -> a
  local queue.
- **Dreaming/maintenance (no cron, no agents):** three modes, user
  choice in `.memoryhub.yaml`:
  1. `on-connect` (default): pending extraction/curation work drains via
     sampling while a session is connected.
  2. `manual`: `memoryhub dream` CLI, optionally with `--model
     ollama/...` for users who have local models.
  3. `off`.
- **Reconciliation (#347), when it lands, runs identically.** Design
  reviews for Phase 5-7 features must state their personal-edition
  behavior.

## 6. Onboarding surface

- `memoryhub mcp` -- stdio MCP server (the Claude Code path). `uvx
  memoryhub mcp` works without a permanent install. See Section 7a.
- `memoryhub config init` -- optional power-user customization. Writes
  `.memoryhub.yaml` + hooks for advanced loading patterns. NOT required
  for basic use.
- `memoryhub doctor` -- shows edition, DB path/size, models present,
  signals active.
- `memoryhub join` / `memoryhub leave` -- membership flows, Section 6b.

## 6b. Membership: joining and leaving a team

(Unchanged from original design -- see git history for full text.)

**`memoryhub join <cluster-url>`:** Authenticates, writes connection
profile, offers curated promotion of local memories to cluster scopes.

**`memoryhub leave`:** Exports entitled memories (user scope in v1) to
local DB with version chains and provenance intact. Audit record on both
sides.

## 7. What this unlocks internally

- **Benchmark/CI:** retrieval tests run against the personal edition in
  GitHub Actions -- per-PR regression gates, no cluster.
- **The sampling round-trip test gap:** Claude Desktop + local stdio
  server is the missing test environment.
- **D5 benchmark tasks** become runnable by anyone.

## 7a. Local MCP server design

The `memoryhub mcp` subcommand starts a stdio MCP server with the SQLite
backend. No background process -- the server lives and dies with the
Claude Code session.

### Architecture

1. `memoryhub mcp` is a new Typer subcommand in
   `memoryhub-cli/src/memoryhub_cli/main.py`. When `memoryhub-core` is
   not installed, it prints a helpful error:
   `pip install "memoryhub[local]" to enable local mode`.

2. The subcommand creates a
   `FastMCP("MemoryHub", instructions=_PERSONAL_INSTRUCTIONS)` instance
   with personal-edition instructions that drop the API key requirement:
   > "MemoryHub provides persistent, versioned, searchable memory.
   > Use memory(action=...) for all operations. Use thread(action=...)
   > for conversation persistence. Session is auto-registered -- no API
   > key needed."

3. Tool functions are personal-edition wrappers that call
   `memoryhub_core` services directly, bypassing the remote MCP server's
   auth/authz layer (`memory-hub-mcp/src/tools/auth.py`,
   `src/core/authz.py`). Hardcoded: `tenant_id="local"`,
   `owner_id=os.getlogin()`, all scopes granted.

4. Database: `create_async_engine("sqlite+aiosqlite:///<xdg-path>")` with
   WAL mode (`PRAGMA journal_mode=WAL`). Alembic migrations run at
   startup (batch mode).

5. Embedding service: `OnnxEmbeddingService()` at startup. Falls back to
   `MockEmbeddingService()` if model not yet downloaded (with a warning
   telling the user to run `memoryhub doctor`).

6. No S3 adapter, no Valkey client, no reranker by default. All three
   already degrade gracefully in the existing codebase:
   - Valkey: `ValkeyUnavailableError` catches -> pull-only mode
   - S3: returns `None` when not configured -> inline storage
   - Reranker: `NoopRerankerService` with `is_configured=False`

7. Session management: `register_session` becomes a no-op returning
   `{"user_id": os_user, "session_id": "local", "scopes": ["user", "project"]}`.

### Tool surface

The same 4-tool compact profile: `register_session`, `memory`,
`admin_memory`, `thread`. Same action dispatch, same response format.
The agent cannot tell the difference between personal and cluster
editions from the tool interface.

### What the tool wrappers import from memoryhub-local

```
memoryhub_local.services.memory     -- search, create, read, update, delete, list, history
memoryhub_local.services.conversation -- thread CRUD, extraction
memoryhub_local.services.graph      -- relationships
memoryhub_local.services.curation   -- similarity gate, rules
memoryhub_local.services.checkpoint -- workflow state
memoryhub_local.services.promotion  -- scope promotion
memoryhub_local.services.graduation -- experiential -> knowledge
memoryhub_local.services.entity     -- entity management
memoryhub_local.embeddings.onnx     -- OnnxEmbeddingService
memoryhub_local.services.database   -- get_session (SQLite)
memoryhub_local.storage.sqlite      -- SQLiteBackend
```

## 7b. Parity testing strategy

### Replacing the test conftest patches

The existing `tests/test_services/conftest.py` (lines 37-147) patches
SQLAlchemy column types at runtime to make models work with SQLite. It
has a FREEZE NOTICE (line 7) prohibiting new patches. The personal
edition replaces this with `configure_for_dialect("sqlite")` from
`memoryhub_core/models/dialect.py`, which both the test suite and the
personal edition use.

### Parameterized test matrix

```python
@pytest.fixture(params=["sqlite", "postgresql"])
async def backend_session(request):
    if request.param == "sqlite":
        configure_for_dialect("sqlite")
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        ...
    else:
        pytest.importorskip("asyncpg")
        engine = create_async_engine(os.environ["TEST_PG_URL"])
        ...
```

- **SQLite always runs in CI** (GitHub Actions, no external services)
- **PostgreSQL runs behind `@pytest.mark.integration`** (requires real
  PostgreSQL + pgvector via compose)
- **Parity tests:** write/read/update/delete, version chain, search
  (vector + keyword), curation similarity gate, graph relationships
- **Backend-specific tests:** `graph_neighbors` has separate PostgreSQL
  and SQLite implementations tested independently

## 8. Sequencing (~8 sessions to alpha)

1. **P1 -- RecallBackend protocol + SQLite spike (2 sessions):**
   - Create `memoryhub_core/storage/recall.py` with protocol
   - Create `memoryhub_core/models/dialect.py` with `configure_for_dialect()`
   - Extract `PostgresBackend` from existing code (7 vector + 2 keyword
     + 1 similarity + 1 graph call sites)
   - Implement `SQLiteBackend` with sqlite-vec and FTS5
   - Replace test conftest monkey-patches
   - Exit: parameterized write/search/version/curation tests green on
     both backends

2. **P2 -- Local MCP server + stdio transport (2 sessions):**
   - Add `memoryhub mcp` subcommand to CLI
   - Create personal-edition tool wrappers (bypass auth/authz)
   - Auto-register session, hardcode `tenant_id="local"`
   - Wire SQLite database at XDG path with Alembic batch mode
   - Personal-edition FastMCP instructions
   - Exit: `claude mcp add memoryhub -- memoryhub mcp` round-trip on a
     laptop using MockEmbeddingService

3. **P3 -- Local ONNX embeddings (1 session):**
   - Implement `OnnxEmbeddingService(EmbeddingService)`
   - First-run model download with progress
   - Wire into `memoryhub mcp` startup
   - Add `memoryhub doctor` subcommand
   - Exit: fresh `pip install "memoryhub[local]"` -> working search in
     under 2 minutes on CPU

4. **P4 -- Extraction + maintenance (1 session):**
   - MCP sampling extraction path
   - On-connect dreaming queue
   - `memoryhub dream` CLI command
   - Exit: live sampling round-trip demonstrated

5. **P5 -- Onboarding + docs (1 session):**
   - README quickstart rewrite
   - Parity matrix published
   - Exit: the 10-minute story is reproducible by an outsider

6. **P6 -- Membership v1 (2 sessions):**
   - `memoryhub join <cluster-url>` and `memoryhub leave`
   - Connection profiles, curated promotion, entitlement-scoped export,
     identity mapping, audit records both directions
   - Exit: round-trip join/leave test with audit trail

## 9. Open questions

1. **Package layout:** RESOLVED -- Option B. `memoryhub` stays lean;
   `[local]` extra pulls in CLI + core[local] + onnxruntime.

2. **ONNX export provenance:** Still open. Internal ask pending for
   RedHatAI to publish attested INT8 ONNX of
   granite-embedding-small-english-r2.

3. **Windows:** Punt to post-v1. Target macOS/Linux with Windows
   explicitly untested.

4. **Scope semantics at n=1:** RESOLVED -- exist-but-empty for
   organizational/enterprise scopes so promoted memories don't change
   shape.

5. **Embedding continuity on transfer:** Deferred to P6. Local 384-dim
   Granite == cluster 384-dim Granite, so vectors could travel. Provenance
   records which embedder produced what either way.

6. **Dual-homing (post-v1):** One local MCP surface routing user-scope
   to local file and team scopes to cluster. Own design pass.

7. **Entitlement policy for `leave`:** Default v1 = user scope only.

8. **MCP tool layer architecture (NEW):** Do we create a thin
   `memoryhub_core/tools/local.py` that wraps service calls for local
   mode, or refactor `memory-hub-mcp/src/tools/` to support both? The
   former is simpler and avoids coupling the personal edition to the
   remote server's auth/authz dependencies. The latter reduces code
   duplication. Leaning: the former, with shared response formatting
   utilities extracted from the existing tools.
