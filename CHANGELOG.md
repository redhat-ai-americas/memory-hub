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

- **Procedural graph content type, Phase 1 (#552)**: `write`/`list`/`search` accept `content_type="procedural"`; `relate` accepts `precedes`/`requires`/`alternative_to` edge types (`mentions` remains system-managed). `reconstruct` is unchanged and still scoped to `behavioral` only — procedural graphs are not returned by it. Retrieval/traversal support is #553, not this change.
- **Changed (#553)**: the `search_memory` guidance entry now carries a compact neighborhood (ids, stubs, typed edges; `neighborhood_detail: "compact"`) instead of the full subgraph, which was dozens of times the size of the guidance prose it accompanied. `manage_graph(action="get_guidance")` still returns the full neighborhood, marked `neighborhood_detail: "full"`.
- **Localized procedural guidance (#553)**: `search_memory` accepts optional `current_step_id`. When it is set, ranking is skipped and the response is one `result_type: "guidance"` entry with `query_ignored: true`. When it is absent, search is unchanged, including `content_type="procedural"`. `manage_graph(action="get_guidance")` and `memory(action="guidance")` return the same neighborhood and prose. Signed off 2026-09-21: short-circuit with a loudly ignored query; no auto-localization without `current_step_id`.

- FastMCP 3 server exposing the 13 MemoryHub tools over streamable-HTTP.

## memoryhub-core (server-side library)

Lives at the repo root in [`src/memoryhub_core/`](src/memoryhub_core/). Consumed by
memory-hub-mcp and memoryhub-auth; not published as a standalone package.

### [Unreleased]

- **Fixed (#553)**: `find_related` wrote each neighbor's stub to the opposite end of the edge, so `RelationshipRead.source_stub` and `target_stub` were inverted in the returned paths. Pre-existing; only observable once #553 began returning these edges through the API.
- **Procedural retrieval (#553)**: `find_related` requires `tenant_id` and applies it in SQL on the start node, every edge, and every neighbor. Each result hop carries direction and role. `resolve_procedure_entry` uses `metadata_.procedure.entry_step_id` when it names a live in-tenant step, and otherwise the single step with no incoming `precedes` edge.
- **Procedural guidance (#553)**: `build_localized_subgraph`, `generate_guidance`, and `localized_guidance` turn that neighborhood into prose via the Stage-3 LLM settings (`llm_extraction_url` / `llm_extraction_model` / `llm_extraction_timeout`) and `prompts/procedural_guidance.yaml`. `localized_guidance` is what `search_memory` and `manage_graph` both call. Decisions 5a and 5b were signed off on 2026-09-21: short-circuit when `current_step_id` is set, flat ranked list when it is absent. See [planning/procedural-graph-retrieval.md](planning/procedural-graph-retrieval.md).

- **Procedural graph schema, Phase 1 (#552)**: Added `ContentType.PROCEDURAL` and `RelationshipType.precedes`/`.requires`/`.alternative_to`. `ck_memory_nodes_content_type` recreated via Alembic migration 028 and mirrored on the `MemoryNode` ORM model so SQLite test schemas enforce it too. See [planning/procedural-graphs.md](planning/procedural-graphs.md) for the design (adjacency-list membership + `memory_relationships` topology; no new tables).

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
