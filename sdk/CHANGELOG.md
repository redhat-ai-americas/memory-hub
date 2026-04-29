# Changelog — memoryhub (SDK)

All notable changes to the `memoryhub` SDK package.

## [0.7.0] — 2026-04-29

- **BREAKING (wire format)**: `MemoryHubClient` now dispatches every
  operation through the unified `memory(action=..., options={...})` MCP
  tool introduced by the server-side consolidation in #198/#202.
  Per-action tool names (`search_memory`, `read_memory`, `write_memory`,
  `update_memory`, `delete_memory`, `report_contradiction`,
  `get_similar_memories`, `get_relationships`, `create_relationship`,
  `set_curation_rule`, `manage_session`, `manage_project`,
  `set_session_focus`, `get_focus_history`) are no longer called.
  This release **cannot** talk to a server that only exposes the legacy
  per-action tools; older releases (≤ 0.6.0) **cannot** talk to the
  primary `memory-hub-mcp` deployment. The Python API is unchanged —
  consumers only need to update the dependency pin. Tracks #210, closes
  the alias gap left by #202.

- **Stub result compatibility**: Default `content` and `owner_id` fields to
  empty strings in the `Memory` model so cache-optimized search responses
  containing stub results parse without Pydantic validation errors. Fixes
  SDK failures when used with the fipsagents framework memory connector
  (#205).

## [0.5.1] — 2026-04-14

- **Edge-case fix**: Normalize empty URL string (`""`) to `None` to avoid
  transport errors when only `api_key` is provided.

## [0.5.0] — 2026-04-12

- **API key backward-compat shim (#184)**: `api_key` and `server_url`
  constructor arguments accepted alongside the canonical `url` parameter.
- **Cache-optimized assembly (#175)**: `search()` returns results in a
  stable order that maximizes KV cache hit rates when injected into prompts.
- **Tool consolidation (#173, #174)**: `suggest_merge` and
  `get_memory_history` merged into existing tools.

## [0.4.0] — 2026-04-09

- **Campaign & domain parameter support (#164)**: Added `project_id` to all 11
  client methods for campaign enrollment verification. Added `domains` and
  `domain_boost_weight` to `search()`, and `domains` to `write()` and
  `update()` for crosscutting knowledge tagging. All parameters are optional
  with `None` defaults — existing callers are unaffected.

## [0.3.0] — 2026-04-09

- Added session focus support (#61): `set_session_focus()` and
  `get_focus_history()` methods. Two-vector retrieval via `focus` and
  `session_focus_weight` parameters on `search()`.
- Push notification support (#62): `on_memory_updated()` for Pattern E
  live subscription when enabled in `.memoryhub.yaml`.

## [0.2.0] — 2026-04-09

- **Error handling overhaul (#97)**: All MCP tools now raise `ToolError` instead
  of returning error dicts. The SDK classifies error messages by prefix into
  typed exceptions: `AuthenticationError`, `CurationVetoError`, `NotFoundError`,
  `PermissionDeniedError`, `ConflictError`, `ValidationError`.
- Prefix classifier in `_call()` with ordered matching (most specific first).

## [0.1.0] — 2026-04-05

- Initial SDK release. Typed async client wrapping the MCP tool catalog,
  OAuth 2.1 token management, `.memoryhub.yaml` auto-discovery for
  project-level retrieval defaults.

## [0.0.1] — 2026-04-05

- Release pipeline bring-up. Published scaffold package.
