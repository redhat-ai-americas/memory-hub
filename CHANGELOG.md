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

- FastMCP 3 server exposing the 13 MemoryHub tools over streamable-HTTP.

## memoryhub-core (server-side library)

Lives at the repo root in [`src/memoryhub/`](src/memoryhub/). Consumed by
memory-hub-mcp and memoryhub-auth; not published as a standalone package.

### [Unreleased]

- Models, services, storage, and RBAC. See
  [docs/package-layout.md](docs/package-layout.md) for the split between
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
