# Tool Error Response Standardization

Status: Design proposal — 2026-04-08
Tracks: redhat-ai-americas/memory-hub#97
Author: @rdwj (drafted with Claude Code Opus 4.6)

## Why this exists

The 15 MCP tools in `memory-hub-mcp/src/tools/` return errors in two incompatible shapes. Half raise `fastmcp.exceptions.ToolError`, which sets the `is_error` bit on the MCP wire-level response. The other half return a plain Python `{"error": True, "message": "..."}` dict as a successful response, which does **not** set `is_error`. SDK and agent consumers have to handle both.

This proposal picks one canonical pattern (`raise ToolError(...)`), documents the per-tool refactor work, and sequences the work into an umbrella tracking issue with one sub-issue per tool so each sub-PR can catch its own regressions independently.

No code changes in this document — it is a design note and a work-item enumeration.

## The bug in one paragraph

When a tool returns `{"error": True, "message": "..."}`, the MCP framework treats the call as successful at the protocol layer. The response body is a dict with an `error` key, but `result.is_error` is `False`. The SDK's `_call()` helper in `sdk/src/memoryhub/client.py:237-247` only checks `result.is_error`, so it treats the response as a successful result and returns the dict to the caller. **Every error from a dict-returning tool is silently swallowed by the SDK.** The caller either has to remember to `.get("error")` on every response (which no SDK consumer currently does) or gets `None` where data fields should be.

The tools that raise `ToolError` work correctly: `ToolError` sets `is_error` in FastMCP's `_handle_tool_error` path, the SDK sees it, and raises either `NotFoundError` (for messages containing "not found") or its SDK-side `ToolError` wrapper. The SDK's advertised behavior — *"Raises ToolError if the tool returns an error"* — holds for 7 of the 15 tools and silently lies for the other 8.

This is worse than a cosmetic inconsistency. It is a correctness bug in the 8 dict-returning tools.

## Audit of the current 15 tools

Results from grepping `memory-hub-mcp/src/tools/` for `ToolError`, `{"error": True`, and direct `raise` of stdlib exceptions.

### Canonical — raises `ToolError` (7 tools, no refactor needed)

| Tool | Error sites | Notes |
|---|---|---|
| `delete_memory` | 6 × `raise ToolError` | Covers invalid UUID, not found, access denied, already deleted. Good reference implementation. |
| `get_focus_history` | 5 × `raise ToolError` | Inverted date range, malformed date, no auth — all raised cleanly. |
| `get_memory_history` | 4 × `raise ToolError` | Invalid UUID, memory not found, authz denied. |
| `report_contradiction` | 6 × `raise ToolError` | Full coverage including authz branch. |
| `search_memory` | 3 × `raise ToolError` | Parameter validation, unknown scope, embedding service failure. |
| `set_session_focus` | 4 × `raise ToolError` | Empty focus, no session, invalid project. |
| `update_memory` | 7 × `raise ToolError` | Largest tool; covers not-found, not-current-version, authz, validation. |

### Non-conforming — returns `{"error": True, "message": ...}` (8 tools, refactor required)

| Tool | Error sites | Error categories returned | Approximate LOC |
|---|---|---|---|
| `create_relationship` | 11 | auth, validation, node not found, authz denied, relationship type validation, generic failure | ~80 |
| `get_relationships` | 6 | auth, validation (memory_id UUID), not found, authz denied, direction validation, generic failure | ~60 |
| `get_similar_memories` | 5 | auth, validation, memory not found, authz denied, generic failure | ~50 |
| `read_memory` | 5 | UUID parse, auth, authz denied, not found, generic failure | ~60 |
| `register_session` | 1 | Invalid API key | ~30 |
| `set_curation_rule` | 7 | auth, validation, empty name, unknown scope, authz, generic failure | ~110 |
| `suggest_merge` | 9 | auth, validation (UUID parse for each ID), not found for each memory, authz, same-memory, generic failure | ~75 |
| `write_memory` | 9 | auth, validation, scope validation, parent-without-branch, branch-without-parent, owner validation, weight out-of-range, authz, curation veto, generic failure | ~130 |

Total: **53 error-dict sites across 8 files** that need to become `raise ToolError(...)` calls.

### `register_session` is a special case

`register_session` is the only tool where a successful response can include a non-fatal warning (push subscriber failed to start, running under JWT auth so session registration is a no-op). It raises no errors today — it only has one failure case (invalid API key) that currently returns the error dict. The refactor should:

1. Convert the invalid-API-key branch to `raise ToolError("Invalid API key. ...")`
2. Leave the two successful-response shapes alone (the JWT-active response and the session-registered response).

It is the smallest refactor in the set and is a good first conversion to land as the reference pattern.

## Target shape

### Rule

**Every tool must raise `fastmcp.exceptions.ToolError` for every failure. No tool may ever return a dict with an `error` key as a successful MCP response.**

Enforcement:

- Tool authors import `from fastmcp.exceptions import ToolError` once at the top of the file.
- Every failure path becomes `raise ToolError(message)` where `message` is a human-readable string that begins with one of a short set of standardized prefixes (see below).
- Exception handlers that currently catch `MemoryNotFoundError`, `AuthorizationError`, etc. and convert to error dicts instead re-raise as `ToolError` with the category prefix preserved.
- A regression test at `memory-hub-mcp/tests/test_no_error_dicts.py` greps every tool file for the literal pattern `"error": True` and fails the suite if any match.

### Standard message prefixes for SDK classification

The SDK currently parses the substring `"not found"` out of `ToolError` messages to map to its typed `NotFoundError`. Extend this pattern — lightweight, explicit, matches FastMCP idioms — with a small set of prefixes the SDK can classify cleanly:

| Category | Message prefix (case-insensitive) | SDK exception to raise |
|---|---|---|
| Memory or entity not found | `"Memory <uuid> not found"` / `"... not found."` | `NotFoundError` (existing) |
| Caller is not authorized | `"Not authorized to"` / `"Access denied:"` | `PermissionDeniedError` (new) |
| Invalid parameter or shape | `"Invalid "` / `"... must be"` / `"... cannot be empty"` | `ValidationError` (new) |
| Authentication failed | `"Invalid API key"` / `"No authenticated session"` | `AuthenticationError` (existing) |
| Conflict with existing state | `"... already exists"` / `"... already deleted"` | `ConflictError` (new) |
| Curator vetoed write | `"Curation rule blocked"` | `CurationVetoError` (new) |
| Unknown / generic | anything else | `ToolError` (existing — the SDK's fallback bucket) |

The SDK exception hierarchy stays backwards-compatible: `MemoryHubError` ← `ToolError` ← the new specific subclasses. Existing consumers that `except ToolError` keep working.

Prefix-based classification is not ideal. The alternative is a structured message format (JSON-encoded error body inside the `ToolError` message), which is ugly to look at on the wire and in logs. Prefix classification is what the SDK already does for `not found`, so this extends a pattern the codebase already relies on. If prefix classification becomes fragile, the work to move to a structured format lives behind the SDK's `_call()` method and is a per-SDK change, not a per-tool change.

### The 6 prefixes are not arbitrary

Each maps to an actual error category already present in the current error-dict code. The audit above shows these are the only categories in use. If a future tool needs a seventh category, add it in the design doc first (update this document), then add it to the SDK, then use it in the tool.

## Per-tool refactor work items

Each of the 8 non-conforming tools becomes one sub-issue under the #97 umbrella. One tool per PR. The reason for one-per-PR: the changes are mechanical but wide, and each tool's tests live in a different file, so a single PR touching all 8 would make it hard to localize test regressions. One PR per tool means a failed CI run points directly at one tool.

Ordering is by risk and by how much existing test coverage the tool has. Start with the safest ones so the pattern gets established, then tackle the riskier ones.

### Sub-issue 1 — `register_session` (smallest, one error site)

- [ ] Replace the single `{"error": True, ...}` return at `register_session.py:170` with `raise ToolError("Invalid API key. Contact your system administrator for a valid key. Keys follow the format: mh-dev-<username>-<year>.")`
- [ ] Update `tests/test_register_session*.py` assertions from `.get("error")` to `pytest.raises(ToolError)`
- [ ] Verify SDK's `_call()` path surfaces this as `AuthenticationError` via the `"Invalid API key"` prefix (SDK change is part of sub-issue 9).

Rationale for going first: smallest conversion, establishes the pattern, proves the SDK prefix classifier on the smallest surface.

### Sub-issue 2 — `read_memory` (5 sites, already well-tested)

- [ ] Convert `read_memory.py:59-62, 72, 80-83, 102-108, 110` to `raise ToolError(...)`
- [ ] Preserve the "not found" message shape for SDK `NotFoundError` mapping — do not change the text of the not-found branch
- [ ] Update tests

### Sub-issue 3 — `get_similar_memories` (5 sites)

- [ ] Convert `get_similar_memories.py:69, 76, 95, 117, 121` to `raise ToolError(...)`
- [ ] Preserve not-found message text
- [ ] Update tests — #47 currently tracks a broken post-fetch RBAC filter in this tool; coordinate so this refactor does not accidentally mask or obscure the #47 bug

### Sub-issue 4 — `get_relationships` (6 sites)

- [ ] Convert `get_relationships.py:88, 95, 101, 110, 178, 185` to `raise ToolError(...)`
- [ ] Update tests

### Sub-issue 5 — `set_curation_rule` (7 sites)

- [ ] Convert `set_curation_rule.py:95, 107, 113, 118, 143, 204` to `raise ToolError(...)`
- [ ] Update tests — this tool has the most-varied error categories so it is a good test of the prefix classifier

### Sub-issue 6 — `suggest_merge` (9 sites)

- [ ] Convert `suggest_merge.py:61, 68, 76, 82, 88, 103, 105, 130, 134, 136` to `raise ToolError(...)`
- [ ] Preserve not-found message text
- [ ] Update tests

### Sub-issue 7 — `create_relationship` (11 sites)

- [ ] Convert `create_relationship.py:74, 79, 90, 98, 104, 121, 123, 137, 145, 152, 154` to `raise ToolError(...)`
- [ ] Update tests

### Sub-issue 8 — `write_memory` (9 sites, most complex)

- [ ] Convert `write_memory.py:117, 130, 141, 149, 164, 183, 204, 239, 246, 248` to `raise ToolError(...)`
- [ ] Preserve the curation-veto message shape so the SDK's new `CurationVetoError` classifier catches it (prefix: `"Curation rule blocked"`)
- [ ] Verify the cross-consumer audit: grep `memoryhub-ui/backend/`, `sdk/`, and `memoryhub-cli/` for any code that pattern-matches `write_memory`'s error dict shape (e.g., `result.get("error")`) and update those call sites to catch `ToolError` subclasses instead
- [ ] Update tests including the curation-veto path

### Sub-issue 9 — SDK update for prefix classification and new exception classes

- [ ] Add `PermissionDeniedError`, `ValidationError`, `ConflictError`, `CurationVetoError` to `sdk/src/memoryhub/exceptions.py` as subclasses of `ToolError`
- [ ] Update `sdk/src/memoryhub/client.py` `_call()` to classify by prefix (extend the existing `"not found"` branch)
- [ ] Update `sdk/src/memoryhub/__init__.py` exports
- [ ] Add unit tests exercising each classification path
- [ ] Update `sdk/README.md` with the new exception hierarchy and migration notes for existing SDK consumers (the base `ToolError` catch still works)

### Sub-issue 10 — Regression test + CI

- [ ] Add `memory-hub-mcp/tests/test_no_error_dicts.py` that walks `memory-hub-mcp/src/tools/*.py` and fails on any file containing the literal `"error": True` (excluding comments)
- [ ] Add a similar lint to the root `tests/` layer if the server-side library is also a source of error-dict returns
- [ ] Wire into the root `.github/workflows/test.yml` `mcp-tests` job (it already runs on every `memory-hub-mcp/**` PR, so no workflow change needed — just the new test file)

### Sub-issue 11 — Documentation update

- [ ] Update `memory-hub-mcp/TOOLS_PLAN.md` — each tool's "Error cases" section should describe the ToolError message shape and its SDK classification
- [ ] Update `memory-hub-mcp/README.md` — add a short "Error handling" section documenting the `raise ToolError` contract for future tool authors
- [ ] Update `docs/mcp-server.md` — reference the design note at `planning/tool-error-standardization.md`
- [ ] Link this design note from the #97 umbrella issue body

### Sub-issue 12 — Umbrella close-out

Close #97 only after sub-issues 1-11 are all merged and the test in sub-issue 10 is passing in CI.

## Sequencing

Sub-issues 1 and 9 can land first in either order (or in parallel — register_session and SDK don't touch the same files). Once 1 and 9 are both merged, the SDK has the classifier and one tool is proving the end-to-end shape.

Then sub-issues 2-8 can land in any order — they are independent of each other. In practice open them round-robin as reviewer bandwidth allows.

Sub-issue 10 (regression test) should land **after** at least one tool has been converted so the test does not start failing immediately against `main`. It can land in parallel with sub-issues 2-8 if it is scoped to only the already-converted tools and a TODO list of pending ones. Simpler is to land 10 after 8, when all 8 tools are converted.

Sub-issue 11 (docs) lands last, reflecting the final state.

Total work: 12 PRs, most of them small (10-50 line diffs). The SDK PR (sub-issue 9) is the only one with any design surface; the tool conversions are mechanical once 9 is merged.

## Risks and open questions

1. **Prefix classification fragility.** A future tool author writes an error message that happens to start with `"Not authorized"` in a context that is not actually a permission denial, and the SDK misclassifies. Mitigation: sub-issue 9 includes a unit test for each classifier branch, and the test in sub-issue 10 does not classify — it only forbids dict returns. A misclassification is a cosmetic bug in the SDK, not a correctness bug in the tool.

2. **Backwards compatibility for callers that depend on the error-dict shape.** None exist in the repo (the audit confirmed the SDK ignores these dicts entirely), but external consumers outside the repo might. Mitigation: the SDK's base `ToolError` catch still works, so any consumer that does `except ToolError` will catch all the new subclasses. Consumers that do `result.get("error")` against the MCP layer directly will need to catch `ToolError` instead — document this as a breaking change in the `sdk` changelog on the first SDK release after sub-issue 9 lands.

3. **Interaction with #47 (broken get_similar_memories RBAC filter).** #47 is an active bug in one of the tools being refactored. Land #47 first, or explicitly coordinate so sub-issue 3 does not mask or obscure the #47 fix. Prefer landing #47 first.

4. **`auth.py` internal helper raises `RuntimeError`.** `memory-hub-mcp/src/tools/auth.py:102` raises `RuntimeError`, not `ToolError`, for an internal assertion. It is not a tool itself (no `@mcp.tool` decorator) — it is a helper. Leave as is; stdlib exceptions from internal helpers are fine because they never reach the tool-return surface.

5. **Curation veto is not exactly an "error."** `write_memory` can veto a write because the curator blocked it — the caller asked for something the system refuses to do, which is closer to HTTP 403 than HTTP 400. Putting it under `CurationVetoError` (its own subclass) captures this correctly. Do not overload it under `PermissionDeniedError` because the curator veto is not about identity — it is about content policy.

6. **Error messages that leak internals.** Several current dict returns include `f"Failed to X: {exc}"` which propagates raw exception text (including SQL error fragments, stack traces, etc.) to the tool response. The refactor is a good opportunity to scrub these — wrap with a generic message and log the full exception at ERROR level. Flag in each sub-issue's acceptance criteria.

## Acceptance criteria for the umbrella issue

Close #97 when all of the following are true:

- [ ] Zero occurrences of `"error": True` as a return value in `memory-hub-mcp/src/tools/*.py`
- [ ] The regression test at `memory-hub-mcp/tests/test_no_error_dicts.py` passes in CI
- [ ] All 15 MCP tools raise `ToolError` for every failure path
- [ ] The SDK's `_call()` helper classifies errors into the 6 typed exception subclasses plus the generic `ToolError` fallback
- [ ] Every sub-issue 1-11 is closed
- [ ] `memory-hub-mcp/TOOLS_PLAN.md` reflects the new error contract for every tool
- [ ] `docs/mcp-server.md` references this design note

## What this proposal deliberately does not do

- **It does not add error codes.** The FastMCP `ToolError` wire format is a string. Adding structured error codes would require either a JSON-encoded message body or a FastMCP protocol change, both of which are out of scope for a cleanup task. If a future integration needs machine-readable codes, revisit then.
- **It does not change any MCP tool's success shape.** Only error paths are touched.
- **It does not refactor the service-layer exceptions in `memoryhub_core`.** `MemoryNotFoundError`, `AuthorizationError`, etc. stay as they are — the tool layer catches them and re-raises as `ToolError`. The service layer is allowed to have rich typed exceptions; the tool layer flattens them at the MCP boundary.
- **It does not touch `memoryhub-auth`.** Auth service error handling is a separate concern (HTTP/OAuth error responses, not MCP tool errors).
- **It does not change `register_session`'s success responses** — the JWT-active shape and the session-registered shape both stay as dicts with human-readable `message` fields. Only the one failure branch becomes a `ToolError`.
