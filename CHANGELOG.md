# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
This is a monorepo — each published package has its own section so releases
can be tracked independently. Packages that have not yet cut a tagged release
are tracked under "Unreleased" until they do.

For the full commit history, see `git log` or the
[GitHub commit view](https://github.com/redhat-ai-americas/memory-hub/commits/main).

## memoryhub (SDK)

Published to PyPI as [`memoryhub`](https://pypi.org/project/memoryhub/). Lives in [`sdk/`](sdk/).

### [Unreleased]

- **Procedural graph content type (#552)**: `content_type` accepts `"procedural"` for directed-graph runbooks (procedure root + `procedure_step` children). `create_relationship()` accepts three new topology edge types: `precedes`, `requires`, `alternative_to`. Docstrings for `search()`/`list()`/`write()` corrected from the stale `"declarative"` label to the actual `"knowledge"` value.
- **Localized procedural guidance (#553)**: `search()` accepts `current_step_id` and `max_hops`. When the step id is set, the server skips ranking and `SearchResult.query_ignored` is true. `get_guidance()` calls `memory(action="guidance")`.
- **Fixed (#553)**: `get_injection_block()` rendered a `result_type="guidance"` result as an empty string, silently dropping localized guidance from the SDK's prompt-injection path. It now injects `guidance_text`; the neighborhood that produced it is not injected.

### [0.6.0] — 2026-04-23

- **Stub result compatibility (#205)**: Default `content` and `owner_id` to
  empty strings in `Memory` model. Fixes Pydantic validation failures when
  cache-optimized search returns stub results.

### [0.5.1] — 2026-04-14

- **Edge-case fix**: Normalize empty URL string to `None` to avoid transport
  errors when only `api_key` is provided.

### [0.5.0] — 2026-04-12

- **API key backward-compat shim (#184)**: `api_key` and `server_url`
  constructor arguments accepted alongside the canonical `url` parameter.
- **Cache-optimized assembly (#175)**: `search()` returns results in a
  stable order that maximizes KV cache hit rates when injected into prompts.
- **Tool consolidation (#173, #174)**: `suggest_merge` and
  `get_memory_history` merged into existing tools.

### [0.4.0] — 2026-04-09

- **Campaign & domain parameter support (#164)**: Added `project_id` to all 11
  client methods for campaign enrollment verification. Added `domains` and
  `domain_boost_weight` to `search()`, and `domains` to `write()`/`update()`.
- All parameters are optional — existing callers are unaffected.

### [0.3.0] — 2026-04-09

- Session focus support (#61): `set_session_focus()`, `get_focus_history()`,
  two-vector retrieval via `focus`/`session_focus_weight` on `search()`.
- Push notification support (#62): `on_memory_updated()` for Pattern E.

### [0.2.0] — 2026-04-09

- **Error handling overhaul (#97)**: All MCP tools now raise `ToolError` instead
  of returning error dicts. SDK classifies error messages by prefix into typed
  exceptions: `AuthenticationError`, `CurationVetoError`, `NotFoundError`,
  `PermissionDeniedError`, `ConflictError`, `ValidationError`.

### [0.1.0] — 2026-04-05

- Initial SDK release. Typed async client wrapping the MCP tool catalog,
  OAuth 2.1 token management, `.memoryhub.yaml` auto-discovery for
  project-level retrieval defaults.
- Tag: `sdk/v0.1.0`

### [0.0.1] — 2026-04-05

- Release pipeline bring-up. Added `LICENSE`, published scaffold package.
- Tag: `sdk/v0.0.1`

## memoryhub-cli

Published to PyPI as [`memoryhub-cli`](https://pypi.org/project/memoryhub-cli/). Lives in [`memoryhub-cli/`](memoryhub-cli/).

### [Unreleased]

- **Procedural content type (#552)**: `--content-type` on `search`, `list`, and `write` now documents `procedural` alongside `experiential`/`knowledge`/`behavioral`. `memoryhub graph relate` lists the three new edge types (`precedes`, `requires`, `alternative_to`) in its help text.
- **Localized procedural guidance (#553)**: `search --current-step-id` requests localized guidance and prints it instead of a ranked table. `memoryhub graph guidance` prints the generated text and hop count.
- **Trajectory recording (#554)**: `memoryhub thread record` reads a Claude Code hook payload from stdin and appends it to the session's thread. `UserPromptSubmit` becomes `user`; `PostToolUse` and `PostToolUseFailure` become `tool_call` + `tool_result`; `Stop` becomes `assistant`. MemoryHub's own tools are skipped, common secrets are redacted and output is clipped. It always exits 0. `memoryhub config init --record-trajectories` installs `.claude/hooks/record-trajectory.sh` as async hooks. Off by default; `MEMORYHUB_RECORD_TRAJECTORY=0` pauses it. `memoryhub thread outcome success|failure|partial` writes the explicit outcome marker the procedural pass reads.
- **Local procedural extraction (#554)**: `memoryhub dream --procedures` runs the procedural pass of the personal edition after fact extraction. Off by default.

### [0.3.0] — 2026-04-09

- **Campaign & domain parameter support (#164)**: Added `--project-id` to
  search, read, write, delete, and history commands. Added `--domain` to
  search and write. Auto-loads `project_id` from `.memoryhub.yaml` campaigns.

### [0.2.0] — 2026-04-09

- Campaign enrollment prompt in `memoryhub config init` (#160).
- API key check after config init (#153).

### [0.1.0] — 2026-04-09

- Initial release. Terminal client with search, read, write, delete, and
  history commands.
- `memoryhub config init` for generating `.memoryhub.yaml` and
  `.claude/rules/memoryhub-loading.md`.
- `memoryhub config regenerate` for re-rendering rule files.
- Tag: `memoryhub-cli/v0.1.0`

## memory-hub-mcp

MCP server. Lives in [`memory-hub-mcp/`](memory-hub-mcp/). Deployed to
OpenShift; not published as a package.

### [Unreleased]

- **Project membership authorization (#514)**: `list_memory` and `search_memory` verify membership in the resolved tenant before serving an explicit `project_id`, regardless of the project-isolation setting. For requests without an explicit project, when isolation is enabled and membership claims are empty, both tools use tenant-scoped database memberships for retrieval and authorization filters.

- **Procedural graph content type, Phase 1 (#552)**: `write`/`list`/`search` accept `content_type="procedural"`; `relate` accepts `precedes`/`requires`/`alternative_to` edge types (`mentions` remains system-managed). `reconstruct` is unchanged and still scoped to `behavioral` only — procedural graphs are not returned by it. Retrieval/traversal support is #553, not this change.
- **Changed (#553)**: the `search_memory` guidance entry now carries a compact neighborhood (ids, stubs, typed edges; `neighborhood_detail: "compact"`) instead of the full subgraph, which was dozens of times the size of the guidance prose it accompanied. `manage_graph(action="get_guidance")` still returns the full neighborhood, marked `neighborhood_detail: "full"`.
- **Localized procedural guidance (#553)**: `search_memory` accepts optional `current_step_id`. When it is set, ranking is skipped and the response is one `result_type: "guidance"` entry with `query_ignored: true`. When it is absent, search is unchanged, including `content_type="procedural"`. `manage_graph(action="get_guidance")` and `memory(action="guidance")` return the same neighborhood and prose. Signed off 2026-09-21: short-circuit with a loudly ignored query; no auto-localization without `current_step_id`.

- **Changed (#554)**: `search_memory(current_step_id=...)` and `manage_graph(action="get_guidance")` return a `ToolError` for a step of an extracted procedure that is still a candidate (one session of evidence). Flat search is unchanged.
- **Procedural extraction options (#554)**: `thread(action="extract")` accepts optional `procedures` (bool), `procedure_mode` (`off`/`propose`/`apply`) and `dry_run`. The caller can only lower the server's `MEMORYHUB_PROCEDURAL_EXTRACTION_MODE` (default `off`). When the procedural pass runs or is requested, the result carries a `procedures` report (`detected`, `created`, `matched`, `edits_proposed`, `edits_applied`, `edits_rejected`, `procedure_ids`, `rejections`, …). No new tool and no required-parameter change.

- FastMCP 3 server exposing the 13 MemoryHub tools over streamable-HTTP.

## memoryhub-core (server-side library)

Lives at the repo root in [`src/memoryhub_core/`](src/memoryhub_core/). Consumed by
memory-hub-mcp and memoryhub-auth; not published as a standalone package.

### [Unreleased]

- **Procedural graph extraction from dreaming (#554)**: an opt-in pass in `extract_from_thread`, after the fact windows, detects a multi-step procedure in a session (`prompts/procedural_extraction.yaml`, strict pydantic schema, observed vs inferred evidence on every item), writes it as a candidate procedural graph in one transaction, and refines matching procedures from later sessions instead of duplicating them. Off by default: `AppSettings.procedural_extraction_mode` (`MEMORYHUB_PROCEDURAL_EXTRACTION_MODE`) = `off`/`propose`/`apply`, plus `procedural_*` gate thresholds. Evidence is accounted once per session in a ledger on the root; structural edits need two supporting sessions; hand-authored procedures are never structurally changed. Every rejected detection or edit goes through `record_procedural_decision` into `reconciliation_decisions` (seam for #555), and `rollback_extraction_run` undoes procedural runs. New modules: `services/procedure_extraction.py`, `services/procedure_evolution.py`. Its outbound LLM client keeps TLS verification on (#604). Design: [planning/procedural-graph-extraction.md](planning/procedural-graph-extraction.md).
- **Procedural extraction, second review (#554)**:
  - Rolling back a `proc_create` refuses (`skipped_modified`) once later sessions or edits changed the graph.
  - Promotion to `established` happens only in `apply` mode.
  - `update_memory` on a procedure root keeps its graph: step copies keep `scope_id` and `content_type`, edges and the entry follow the copies, and deleted steps stay deleted.
  - In a project, matching includes other members' procedures. A match on someone else's procedure is recorded as a proposal (`foreign_owner`) and writes nothing to it.
  - New optional validation gate for structural edits in `apply` mode, off by default and failing closed (`MEMORYHUB_PROCEDURAL_VALIDATION_URL`, `_API_KEY`, `_TIMEOUT`, `_CA_BUNDLE`; `services/procedure_validation.py`).
  - The pure detection contract moved to `services/procedure_contract.py`, shared byte for byte with memoryhub-local.
- **Procedural extraction hardening (#554 review)**: tool output alone is never observed evidence (prompt v1.1 fences the transcript as data); refinement locks the procedure root and creation takes an owner-scope advisory lock, so concurrent runs no longer lose evidence or duplicate roots; no transaction is held during model calls; rollback of a procedural decision is all-or-nothing; deprecating a middle step rewires its neighbours. New settings: `MEMORYHUB_PROCEDURAL_SERVE_CANDIDATES` (default `false`) and `MEMORYHUB_PROCEDURAL_LLM_CA_BUNDLE`.
- **Changed (#553 retrieval, #554)**: `localized_guidance` refuses guidance for an automatically extracted procedure that is still `candidate` (`ProcedureNotEstablishedError`) unless `MEMORYHUB_PROCEDURAL_SERVE_CANDIDATES=true`. Hand-authored procedures are unaffected.
- **Transaction-aware writes (#554)**: `create_memory(..., commit=False)` and `create_relationship(..., commit=False)` flush inside the caller's transaction instead of committing. Existing callers are unchanged. `create_memory(commit=False)` requires `skip_curation=True` and refuses content that would need chunking or S3.
- **Fixed (#553)**: `find_related` wrote each neighbor's stub to the opposite end of the edge, so `RelationshipRead.source_stub` and `target_stub` were inverted in the returned paths. Pre-existing; only observable once #553 began returning these edges through the API.
- **Procedural retrieval (#553)**: `find_related` requires `tenant_id` and applies it in SQL on the start node, every edge, and every neighbor. Each result hop carries direction and role. `resolve_procedure_entry` uses `metadata_.procedure.entry_step_id` when it names a live in-tenant step, and otherwise the single step with no incoming `precedes` edge.
- **Procedural guidance (#553)**: `build_localized_subgraph`, `generate_guidance`, and `localized_guidance` turn that neighborhood into prose via the Stage-3 LLM settings (`llm_extraction_url` / `llm_extraction_model` / `llm_extraction_timeout`) and `prompts/procedural_guidance.yaml`. `localized_guidance` is what `search_memory` and `manage_graph` both call. Decisions 5a and 5b were signed off on 2026-09-21: short-circuit when `current_step_id` is set, flat ranked list when it is absent. See [planning/procedural-graph-retrieval.md](planning/procedural-graph-retrieval.md).
- **Procedural graph schema, Phase 1 (#552)**: Added `ContentType.PROCEDURAL` and `RelationshipType.precedes`/`.requires`/`.alternative_to`. `ck_memory_nodes_content_type` recreated via Alembic migration 030 and mirrored on the `MemoryNode` ORM model so SQLite test schemas enforce it too. See [planning/procedural-graphs.md](planning/procedural-graphs.md) for the design (adjacency-list membership + `memory_relationships` topology; no new tables).

- Models, services, storage, and RBAC. See
  [planning/archive/package-layout.md](planning/archive/package-layout.md) for the split between
  `memoryhub-core` (server) and `memoryhub` (SDK on PyPI).

## memoryhub-auth

OAuth 2.1 authorization server. Lives in [`memoryhub-auth/`](memoryhub-auth/).
Not yet published.

### [Unreleased]

- OAuth 2.1 authorization server with PKCE, JWT issuance, LibreChat-compatible
  metadata endpoints.

## memoryhub-ui

Dashboard UI (React frontend + FastAPI backend). Lives in
[`memoryhub-ui/`](memoryhub-ui/). Not yet published.

### [Unreleased]

- BFF walker, dashboard views, memory inspector.
