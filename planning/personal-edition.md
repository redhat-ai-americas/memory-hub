# MemoryHub Personal Edition: `pip install memoryhub`, Zero Infrastructure

**Status:** Design (new epic candidate — outside the dreaming epic)
**Date:** 2026-07-16
**Author:** @rdwj (designed with Claude in Cowork)
**Builds on:** existing `memoryhub` PyPI package (SDK, v0.14.0 — the name
is already ours, verified 2026-07-16), `memoryhub-core` (server-side
library), `planning/eager-fact-extraction.md` (sampling),
`strategy/client-supplied-intelligence.md` (the zero-credential wedge)

---

## 1. The product statement

A developer runs:

```bash
pip install "memoryhub[local]"
claude mcp add memoryhub -- memoryhub mcp   # or: uvx memoryhub mcp
```

and has persistent, versioned, searchable agent memory — with the same
14 MCP tools the enterprise cluster exposes — backed by a single SQLite
file, with **no database server, no object store, no GPU, no model API
key, and no account**. First retrieval works within a minute of install.

The existing `memoryhub` package is the client SDK; today
`MemoryHubClient()` requires a cluster URL. Personal edition is defined
as: **the zero-argument constructor works.** No URL -> embedded local
engine. Same import, same API, same tool surface. Not a fork, not a
"lite" product — a second deployment mode of the same product.

### Why (adoption mechanics)

- Top-of-funnel: nobody evaluates a memory platform by provisioning an
  OpenShift cluster. They evaluate it in Claude Code in ten minutes.
- The community -> product ladder is the org's home motion. Local mode
  is the community edition; the cluster is the product; `memoryhub push`
  is the bridge.
- Competitive wedge (verified against primary sources 2026-07-16):
  Hindsight's embedded mode requires `llm_api_key` in its constructor;
  Mem0 self-hosted requires `OPENAI_API_KEY` or a self-run Ollama
  endpoint. Personal MemoryHub requires **no credentials of any kind**:
  retrieval runs on local ONNX embeddings; extraction rides MCP sampling
  (the connected agent's own model). "No API key" is a category-unique
  sentence.

## 2. Substrate mapping

| Cluster | Personal | Notes |
|---------|----------|-------|
| PostgreSQL + pgvector | SQLite + sqlite-vec | vector recall; ANN adequate at personal scale (<100K memories) |
| tsvector + GIN | SQLite FTS5 (BM25) | keyword recall — maps one-to-one |
| MinIO (S3 spill) | inline in SQLite | threshold is 100KB now; personal content simply stores inline (SQLite handles MB-scale TEXT fine). No spill tier. |
| TEI Granite embedding (GPU) | granite-embedding-small-english-r2, ONNX int8, CPU | SAME model family as the cluster — embeddings are semantically continuous across editions. ~90MB one-time download on first run. |
| TEI Granite reranker (GPU) | optional extra `[reranker]`, ONNX CPU | k is small at personal scale; default off, honest flag when off |
| Valkey, auth service, OAuth | none | single user; tenant_id="local", owner = OS user |
| CronJob agents (curator etc.) | none in v1 | see maintenance model, Section 5 |
| Alembic migrations | Alembic, batch mode | pip upgrades must migrate the local DB — the cluster rule ("create_all cannot migrate") applies to laptops too |
| DB location | XDG path (`~/.local/share/memoryhub/memoryhub.db`) | one file; backup = copy the file |

**Kept in full, deliberately:** versioning + `is_current`, provenance,
extraction run IDs, honesty flags (`content_truncated`/`full_available`),
chunking + chunk-to-parent expansion, fact extraction + `retrieval_unit`,
simplified curation gates, and a lightweight audit table. Governance is
the differentiator; a personal memory with version history and an audit
trail is the demo of the enterprise value proposition, not a separate
product.

**Dropped, deliberately:** RBAC, multi-tenancy, OAuth, cross-namespace
anything, SDC, leader election. These are meaningless at n=1 and their
absence is not degradation.

## 3. The load-bearing decision: a storage backend protocol

`memoryhub-core` services currently speak SQLAlchemy with
Postgres-specific constructs (pgvector operators, the generated tsvector
column, dialect-specific recall SQL in `search_memories` /
`curation/similarity.py`). The personal edition requires isolating a
**StorageBackend protocol** covering the hot paths:

- vector recall (top-k by cosine over candidate filters)
- keyword recall (ranked text match)
- filtered CRUD + version-chain read/write
- similarity search for curation/reconciliation
- chunk/fact/branch child queries

Everything above that line (services, curation logic, extraction,
MCP tools, honesty flags, retrieval_unit policy) is portable and MUST
NOT fork. Two implementations: `PostgresBackend` (extracted from
current code, zero behavior change) and `SQLiteBackend`
(sqlite-vec + FTS5).

**The parity guarantee is mechanical, not aspirational:** the existing
core/MCP test suites get parameterized over both backends in CI. A tool
behavior that differs between editions is a failing test, not a docs
footnote. This is also the forcing function that keeps future features
(reconciliation #347, reflection #345) edition-portable by default.

**Accepted costs:** permanent two-backend maintenance; sqlite-vec is
younger than pgvector (pin + vendor-watch); SQLite single-writer
concurrency (fine for personal use; WAL mode; documented boundary —
"multi-agent concurrent writes is what the cluster is for").

## 4. Models without infrastructure

- **Embeddings (required):** granite-embedding-small-english-r2 exported
  to ONNX int8, run via onnxruntime (CPU). Avoids the torch/GPU
  dependency cliff — target install weight is tens of MB of wheels plus
  a ~90MB one-time model download with a clear first-run message.
  Same 384-dim space as the cluster edition.
- **Reranker (optional `[reranker]` extra):** Granite reranker ONNX.
  Default off; preflight-style status visible via a `memoryhub doctor`
  command.
- **No LLM anywhere in the base install.** This is a hard product
  constraint, not an implementation preference — it is the wedge.

## 5. Extraction and maintenance without a server LLM

- **Eager fact extraction:** MCP sampling, exactly as designed in
  `eager-fact-extraction.md` — and personal edition is its natural home:
  the connected client (Claude Code/Desktop) IS the model. The
  "no-sampling-support" fallback here is `deferred` -> a local queue.
- **Dreaming/maintenance (no cron, no agents):** three modes, user
  choice in `.memoryhub.yaml`:
  1. `on-connect` (default): pending extraction/curation work drains via
     sampling while a session is connected — "dreams while you work."
  2. `manual`: `memoryhub dream` CLI, optionally with `--model
     ollama/...` for users who have local models and want offline
     maintenance.
  3. `off`.
- **Reconciliation (#347), when it lands, runs identically** — it is
  deterministic-plus-tiebreaker, and the tiebreaker uses the same
  sampling/queue path. Design reviews for Phase 5-7 features must state
  their personal-edition behavior (the parity CI will enforce it anyway).

## 6. Onboarding surface

- `memoryhub mcp` — stdio MCP server (the Claude Code path). `uvx
  memoryhub mcp` works without a permanent install.
- `memoryhub init` — writes `.memoryhub.yaml` + the SessionStart hook
  into a project (reuses the existing `memoryhub config init` machinery;
  local vs cluster is just the connection block).
- `memoryhub doctor` — shows edition, DB path/size, models present,
  signals active (the personal cousin of the benchmark preflight).
- `memoryhub join` / `memoryhub leave` — membership flows, Section 6b.
  (Replaces an earlier bare push/pull sketch: transfer is one mechanism
  inside membership, not the feature itself.)

## 6b. Membership: joining and leaving a team

Requirement (Wes, 2026-07-16): a local user joining a team on the
enterprise edition, and the reverse, must both be easy. Design
principles:

1. **Membership is a governed operation, not a sync.** What crosses the
   local/cluster boundary is explicit, reviewed, and audited — in both
   directions. No silent bulk upload of a laptop's memory into an org
   tenant; no silent bulk download on the way out.
2. **Scopes are the homing rule.** The scope hierarchy already encodes
   ownership: `user` memories are yours; `project`/`organizational`/
   `enterprise` are the team's. Join and leave are defined per-scope,
   which makes the semantics obvious instead of negotiated.

**`memoryhub join <cluster-url>`:**
- Authenticates (API key or OAuth device flow), verifies granted scopes,
  writes the connection profile (`~/.config/memoryhub/config.json`) —
  the local DB is untouched by default.
- Offers **curated promotion**: an interactive (or `--from-file`) review
  of local memories worth contributing — project-relevant items promote
  into cluster scopes with version chains and provenance preserved, and
  a record that they originated from a personal edition (identity
  mapping: local OS-user owner_id -> corporate identity, recorded in
  metadata, both auditable).
- Default posture after joining: **user scope can stay local** (private
  by default), team scopes live on the cluster. v1 implements this as a
  connection switch with curated promotion; full dual-homing (one MCP
  surface routing user-scope queries to the local file and team-scope
  queries to the cluster simultaneously) is the architectural north
  star — flagged as its own design pass, not improvised (open question
  6).

**`memoryhub leave`:**
- The reverse, and the differentiator: offboarding as a governed
  operation. Exports what the user is *entitled* to take — their
  user-scope memories always; project/org memories only as RBAC
  permits — into the local DB, version chains and provenance intact,
  with the export recorded in the cluster audit trail.
- The pitch sentence: "joining and leaving are governed memory
  operations — what an employee takes when they leave is exactly what
  policy says, and there's an audit record either way." No competitor
  in the category has an offboarding story at all.
- Embeddings on transfer (both directions): re-embed on import by
  default; provenance records which embedder produced what (see open
  question 5).

## 7. What this unlocks internally

- **Benchmark/CI:** the AMB harness and retrieval tests run against the
  personal edition in GitHub Actions — per-PR retrieval regression
  gates, no cluster, no port-forwards. This alone may pay for the
  backend work.
- **The sampling round-trip test gap** (ctx.sample() never exercised
  end-to-end): Claude Desktop + local stdio server is the missing test
  environment.
- **D5 benchmark tasks** (restraint/escalation classes) become runnable
  by anyone — the platform benchmark's reproducibility story improves.

## 8. Sequencing (new epic, ~6 sessions to alpha)

1. **P1 — Backend protocol + SQLite spike:** extract StorageBackend;
   SQLiteBackend passing the core search/CRUD test subset. Exit: cheese
   test (write/update/version/search) green on SQLite.
2. **P2 — Embedded server + stdio MCP:** zero-URL client path; 14 tools
   over stdio; parameterized test suite in CI. Exit: Claude Code
   round-trip on a laptop.
3. **P3 — Local models:** ONNX Granite embeddings, first-run download,
   `doctor`. Exit: fresh venv -> working search in <2 min on CPU.
4. **P4 — Extraction + maintenance:** sampling extraction on by default,
   on-connect dreaming queue, `memoryhub dream`. Exit: live sampling
   round-trip demonstrated (closes the known test gap).
5. **P5 — Onboarding + docs:** `init`, README quickstart rewrite,
   parity matrix published. Exit: the 10-minute story is reproducible by
   an outsider.
6. **P6 — Membership v1 (join + leave):** connection profiles, curated
   promotion, entitlement-scoped export, identity mapping, audit records
   both directions. Exit: round-trip test — a local memory promoted via
   `join` retains version chain + provenance on the cluster; a
   user-scope memory exported via `leave` is intact and searchable
   locally, and the cluster audit trail shows both operations. Dual-home
   routing is explicitly NOT in v1 (own design pass).

## 9. Open questions

1. **Package layout:** does `[local]` live as an extra of `memoryhub`
   (SDK) pulling `memoryhub-local`, or does `memoryhub-core` get
   published with the backend split? Constraint: `pip install
   "memoryhub[local]"` must be the only command a user learns.
   (docs/package-layout.md is the reference; decide in P1.)
2. **ONNX export provenance — verified 2026-07-16, now an ask not a
   question.** The RedHatAI HuggingFace org publishes quantized models
   and has INT8 ONNX embedding precedent (bge family), but no Granite
   *embedding* quantizations yet (its Granite entries are LLMs in
   vLLM-targeted formats). A community INT8 ONNX of
   granite-embedding-english-r2 exists (yasserrmd/) but is unattested
   and the wrong size variant — do NOT ship on it. Action: internal ask
   to get granite-embedding-small-english-r2 (and the reranker) INT8
   ONNX published under RedHatAI with attestation — the ideal outcome
   for our provenance story (models pulled from our own org's attested
   account). Fallback: we export and publish under the project org via
   the same attested release workflow we use for PyPI.
3. **Windows:** sqlite-vec + onnxruntime support it in principle; decide
   whether v1 claims it or targets macOS/Linux with Windows explicitly
   untested.
4. **Scope semantics at n=1:** user scope = default; project scope from
   `.memoryhub.yaml`/git root. Do organizational/enterprise scopes exist
   locally (empty), or are they rejected? Leaning: exist-but-empty, so
   promoted memories don't change shape.
5. **Embedding continuity on transfer:** local 384-dim Granite ==
   cluster 384-dim Granite, so vectors COULD travel — but re-embedding
   on import is safer (model version drift). Decide in P6; provenance
   records which embedder produced what either way.
6. **Dual-homing (post-v1 design pass):** one local MCP surface routing
   user-scope operations to the local file and team scopes to the
   cluster, with merged search results. The scope model makes this
   coherent; result merging, latency, offline behavior, and
   conflict-on-reconnect make it a real design, not a feature flag.
   Membership v1's connection-switch semantics must not paint this into
   a corner (e.g., keep the local DB alive after join rather than
   migrating-and-deleting).
7. **Entitlement policy for `leave`:** who defines what project/org
   memories a departing user may export — RBAC roles as-is, or a
   dedicated export policy? Needs enterprise-admin input; default v1 =
   user scope only, everything else stays.
