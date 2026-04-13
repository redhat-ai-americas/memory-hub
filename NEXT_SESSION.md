# Next session: MCP tool consolidation (#173, #174)

## What was completed (2026-04-13)

- Deployed TLS hardening to memoryhub-auth (combined CA bundle, init container, internal service URLs, TLS verify enabled)
- Implemented and deployed #179 (openshift_allowed_group enforcement) with b64-encoded username handling
- Validated all three e2e scenarios on the live cluster: user in group, user not in group (403), no group configured (allow all)
- Closed #81 (e2e test) and #179 (group enforcement, PR #180 merged)
- Added e2e-mandatory rule to memoryhub-auth/CLAUDE.md
- Retro written: `retrospectives/2026-04-13_tls-hardening-and-group-enforcement/`

## #173: Consolidate suggest_merge into create_relationship

`suggest_merge` is a thin wrapper around `create_relationship` that hardcodes `relationship_type=conflicts_with` with merge metadata. Removing it reduces the tool count from 15 to 14.

### Steps
1. Update `create_relationship` tool description to mention the merge-suggestion pattern: `relationship_type="conflicts_with"` with `metadata={"merge_suggested": true, "reasoning": "..."}`
2. Remove `memory-hub-mcp/src/tools/suggest_merge.py`
3. Remove suggest_merge from tool registration in `__init__.py`
4. Remove suggest_merge tests, add test for merge-via-relationship pattern
5. Update SYSTEM_PROMPT.md and any docs referencing suggest_merge
6. Update SDK (`sdk/src/memoryhub/client.py`) — remove or deprecate `suggest_merge` method
7. Update the MemoryHub MCP integration rule in `.claude/rules/memoryhub-integration.md` if it references suggest_merge

### Key files
- `memory-hub-mcp/src/tools/suggest_merge.py` (remove)
- `memory-hub-mcp/src/tools/create_relationship.py` (update description)
- `memory-hub-mcp/src/tools/__init__.py` (update registration)
- `sdk/src/memoryhub/client.py` (remove/deprecate wrapper)
- `sdk/tests/test_client.py` (update)

## #174: Consolidate get_memory_history into read_memory

`read_memory` already supports `include_versions=True` for inline version history but without pagination. `get_memory_history` adds pagination (`offset`, `max_versions`) as a standalone tool. Merging them reduces tools from 14 to 13.

### Steps
1. Add `history_offset: int = 0` and `history_max_versions: int = 10` parameters to `read_memory`
2. When `include_versions=True`, paginate the version history using those params
3. Deprecate `get_memory_history` — add deprecation notice to its description pointing to `read_memory`
4. Update SDK: add pagination params to `read_memory`, deprecate `get_memory_history`
5. Update SYSTEM_PROMPT.md and docs
6. Update the MemoryHub MCP integration rule if it references get_memory_history

### Key files
- `memory-hub-mcp/src/tools/read_memory.py` (add pagination params)
- `memory-hub-mcp/src/tools/get_memory_history.py` (deprecation notice, eventual removal)
- `memory-hub-mcp/src/tools/__init__.py` (registration update after removal)
- `sdk/src/memoryhub/client.py` (update read_memory, deprecate get_memory_history)
- `sdk/tests/test_client.py` (update)

### Migration note
The issue says to use a deprecation period for #174 since agents may call `get_memory_history`. Keep the tool with a deprecation notice for one release cycle, then remove. For #173, `suggest_merge` has no external consumers — clean removal.

## Approach

Both changes follow the same pattern: update the surviving tool, remove or deprecate the absorbed tool, update SDK + docs + tests. Do #173 first (simpler — pure removal) then #174 (requires adding pagination params).

**Important:** These are MCP tool changes. Per CLAUDE.md, read `memory-hub-mcp/CLAUDE.md` before making changes. However, since these are modifications to existing tools (not new tools), the `/plan-tools` -> `/create-tools` workflow is not needed — these are refactoring operations.

## Cluster state

- Auth server: Running in `memoryhub-auth`, TLS hardened, group enforcement active (`memoryhub-users`)
- DB: `memoryhub-pg-0` in `memoryhub-db`
- MCP: Running in `memory-hub-mcp` (15 tools currently)
- `memoryhub-users` group on cluster: `kube:admin` (b64-encoded), `rdwj`

## After the tool consolidation

Deploy the updated MCP server and verify the tool count dropped (15 -> 13). Use `mcp-test-mcp` to verify remaining tools still work.
