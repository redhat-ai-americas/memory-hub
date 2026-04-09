# Changelog — memoryhub (SDK)

All notable changes to the `memoryhub` SDK package.

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
