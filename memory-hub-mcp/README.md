# memory-hub-mcp

The MCP server for MemoryHub. Exposes the memory layer as 14 tools over
streamable-HTTP so any MCP-speaking agent framework can read and write
governed, tenant-scoped memories.

This package lives in the MemoryHub monorepo and is deployed to OpenShift;
it is **not** published to PyPI or a container registry. For the SDK on
PyPI, see [`sdk/`](../sdk/). For the CLI, see
[`memoryhub-cli/`](../memoryhub-cli/). For the full architecture, see
[`docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md) and
[`docs/mcp-server.md`](../docs/mcp-server.md).

## Tools

Fourteen tools grouped by purpose. Every tool is authenticated (via
`register_session` for API-key sessions, or a JWT when the server is
deployed behind the OAuth 2.1 authorization server), every write is
governed by the curator pipeline, and every row is tenant-isolated.

| Tool | Purpose |
|------|---------|
| `register_session` | Authenticate the session with an API key and start the #62 push subscriber |
| `write_memory` | Create a new memory node or a branch (rationale, provenance, etc.). Project-scoped writes auto-enroll the caller in open projects |
| `read_memory` | Fetch a memory by UUID, optionally with version history (consolidated from `get_memory_history`) |
| `update_memory` | Create a new version of an existing memory, preserving the old one |
| `delete_memory` | Soft-delete a memory and its entire version chain (destructive) |
| `search_memory` | Semantic search across accessible memories via pgvector, with focus bias |
| `manage_project` | Discover, create, and manage projects and memberships |
| `report_contradiction` | Signal that observed behavior contradicts a stored memory |
| `create_relationship` | Create a directed edge between two memory nodes (also handles merge suggestions, consolidated from `suggest_merge`) |
| `get_relationships` | Query relationships for a node, optionally tracing provenance |
| `get_similar_memories` | Find near-duplicates of a memory with cosine similarity scores |
| `set_curation_rule` | Create or update a user-layer curation rule (regex or embedding tier) |
| `set_session_focus` | Declare the session's focus topic for #61 history and #62 broadcast filter |
| `get_focus_history` | Aggregated per-project histogram of session focus declarations |

### Tool reference

#### Core memory CRUD

##### `register_session`

Authenticate the session with your API key. Call this once at the start of
every conversation to establish identity; `write_memory` and `search_memory`
then default to your authenticated `user_id`. Also wires the session into
the #62 Pattern E push pipeline so the client receives broadcast
notifications without polling. Push wiring is non-fatal — if Valkey is
unreachable, registration still succeeds and the agent falls back to
pull-only loading.

When the server is deployed behind a JWT-issuing auth server, session
registration is a no-op: the JWT's `sub` claim is used directly and the
push subscriber starts automatically.

**Parameters:** `api_key` (str, required — format `mh-dev-<username>-<year>`)

##### `write_memory`

Create a new memory node or a branch. Records preferences, facts, project
context, rationale, and other knowledge. User-scope writes land
immediately; higher-scope writes (organizational, enterprise) are queued
for curator review. The return value includes curation metadata — if
`curation.similar_count > 0`, inspect the near-duplicates with
`get_similar_memories` and consider `update_memory` instead of creating
duplicates. If a curation rule blocks the write, a `ToolError` is raised with the reason
(SDK maps to `CurationVetoError`).

When `scope="project"`, the caller is auto-enrolled in open projects on
first write. Invite-only projects reject non-members. Use `manage_project(action="list")`
to discover available projects before writing.

**Parameters:** `content` (str), `scope` (`user` | `project` | `role` |
`organizational` | `enterprise`), `owner_id` (str, optional — defaults to
authenticated user), `weight` (float 0.0-1.0, default 0.7), `parent_id`
(UUID, optional), `branch_type` (str, required when `parent_id` is set —
common values: `rationale`, `provenance`, `description`, `evidence`,
`approval`), `metadata` (dict, optional).

##### `read_memory`

Retrieve a memory by UUID. Returns the node with `branch_count` set to the
number of direct child branches — branch contents are not loaded inline.
Pass `include_versions=true` to also return the full version history.

**Parameters:** `memory_id` (UUID str), `include_versions` (bool, default false).

##### `update_memory`

Create a new version of an existing memory. The old version stays
accessible via `read_memory(include_versions=true)`. Use when a
preference changes, information is corrected, or a memory needs
refinement. At least one of `content`, `weight`, or `metadata` must be
provided.

**Parameters:** `memory_id` (UUID str — must be the current version),
`content` (str, optional), `weight` (float 0.0-1.0, optional), `metadata`
(dict, optional).

##### `delete_memory`

**Destructive.** Soft-delete a memory and its entire version chain — every
node in the chain plus all child branches are marked deleted via
`deleted_at`. From an agent's perspective the deletion is final; only
admin tooling can recover. Only the memory owner or `memory:admin` can
delete. You can pass any version ID in the chain; the tool walks forward
and backward.

**Parameters:** `memory_id` (UUID str).

##### `search_memory`

The primary discovery mechanism. Semantic search across accessible
memories via pgvector. Results are a ranked mix of full content
(high-weight matches) and lightweight stubs (lower-weight matches) to keep
responses token-efficient.

Supports session-focus bias: pass `focus` (e.g., `"OAuth token
validation"`) to bias retrieval toward memories matching the focus in
addition to the query. The focus vector is combined with the query vector
via reciprocal-rank fusion. When `focus` is set, the response may include
`pivot_suggested: true` indicating the user has pivoted off-topic.

**Parameters:** `query` (str, required), `scope` (str, optional),
`owner_id` (str, optional — empty string searches all owners),
`max_results` (int 1-50, default 10), `weight_threshold` (float 0.0-1.0,
default 0.0), `current_only` (bool, default true), `mode` (`full` |
`index` | `full_only`, default `full`), `max_response_tokens` (int
100-20000, default 4000), `include_branches` (bool, default false),
`focus` (str, optional), `session_focus_weight` (float 0.0-1.0, default
0.4).

##### `manage_project`

Discover, create, and manage projects. The `action` parameter selects
the operation: `list` returns projects the caller is a member of (filter
`mine`) or all projects visible in the tenant (filter `all`); `create`
creates a new project; `update` changes description or enrollment policy;
`manage_membership` adds or removes a member.

**Parameters:** `action` (`list` | `create` | `update` | `manage_membership`),
plus action-specific parameters: `filter` (`mine` | `all`, default `mine`)
for listing; `project_id`, `description`, `invite_only` for create/update;
`project_id`, `user_id`, `membership_action` (`add` | `remove`), `role`
(`member` | `admin`) for membership management.

##### `report_contradiction`

Record that observed behavior conflicts with a stored memory. For example,
the user running Docker when a memory says *"prefers Podman"*. The curator
agent aggregates these signals and may trigger a revision prompt after
enough contradictions accumulate (default threshold: 5). Temporary
exceptions warrant lower confidence; repeated contradictions warrant
higher.

**Parameters:** `memory_id` (UUID str), `observed_behavior` (str, be
specific), `confidence` (float 0.0-1.0, default 0.7).

#### Graph and curation

##### `create_relationship`

Create a directed edge between two memory nodes. Use to link semantically
connected memories — marking that an organizational memory was
`derived_from` user memories, or that one memory `supersedes` another.
Relationships are immutable (create or delete, never update).

**Parameters:** `source_id` (UUID str), `target_id` (UUID str),
`relationship_type` (`derived_from` | `supersedes` | `conflicts_with` |
`related_to`), `metadata` (dict, optional).

##### `get_relationships`

Query the graph edges for a node. Supports filtering by relationship type
and direction; `include_provenance=true` follows `derived_from` edges
backward to build a provenance chain showing which source memories a
given node was derived from.

**Parameters:** `node_id` (UUID str), `relationship_type` (str, optional
filter), `direction` (`outgoing` | `incoming` | `both`, default `both`),
`include_provenance` (bool, default false).

##### `get_similar_memories`

Find memories similar to a given one with cosine similarity scores. Use
this to investigate when `write_memory` reports `similar_count > 0`.
Results are paged to avoid context bloat.

**Parameters:** `memory_id` (UUID str), `threshold` (float 0.0-1.0,
default 0.80), `max_results` (int 1-50, default 10), `offset` (int,
default 0).

##### `set_curation_rule`

Create or update a user-layer curation rule. Rules either flag, block,
quarantine, reject, or decay-weight matching writes. Two tiers: `regex`
(pattern match) and `embedding` (cosine-similarity threshold against
existing memories).

**Parameters:** `name` (str, unique per user), `tier` (`regex` |
`embedding`, default `embedding`), `action` (`flag` | `block` |
`quarantine` | `reject_with_pointer` | `decay_weight`, default `flag`),
`config` (dict — `{"threshold": float}` for embedding,
`{"pattern": str}` for regex), `scope_filter` (str, optional),
`enabled` (bool, default true), `priority` (int ≥ 0, default 10).

#### Session focus

##### `set_session_focus`

Declare the session's focus topic. Writes two records to Valkey: an
active-session hash with the focus string and its 384-dim embedding (TTL
matches the JWT lifetime, consumed by the #62 broadcast filter for
per-session cosine-ranked push), and an append-only per-project per-day
history entry consumed by `get_focus_history`. A short natural-language
topic (5–10 words) works best. Current session ID is the authenticated
`sub`; multi-concurrent-sessions-per-user will switch to JWT `jti` when
needed.

**Parameters:** `focus` (str), `project` (str — matches the `project`
field on project-scope memories and `.memoryhub.yaml`).

##### `get_focus_history`

Aggregated per-project histogram of session focus declarations over a
date range. Advisory only — does not feed retrieval ranking. Consumed by
humans and agents to see which topics are most active on a project and
spot recent coverage gaps.

**Parameters:** `project` (str), `start_date` (ISO `YYYY-MM-DD`, optional
— defaults to 30 days before `end_date`), `end_date` (ISO `YYYY-MM-DD`,
optional — defaults to today UTC).

## Entry point

The canonical entry point is `src.main`. The server imports each tool
module statically and registers it with a `FastMCP` instance via
`mcp.add_tool()` — see `src/main.py`. **Do not** use the template's
dynamic `UnifiedMCPServer` / `load_all` loader; it was designed for
FastMCP 2 and silently fails to register tools under v3. An earlier
`src.server_v3` entry point existed briefly during the FastMCP 2→3 pivot
and was consolidated away in commit `6aa2b28`; it no longer exists.

Every script, Containerfile, and workflow in this repo uses `src.main`:

- `memory-hub-mcp/Containerfile` — `CMD ["python", "-m", "src.main"]`
- `memory-hub-mcp/Makefile` — `make run-local` → `python -m src.main`
- `memory-hub-mcp/run-local.sh` and `run_local.py`
- `memory-hub-mcp/pyproject.toml` — `fastmcp-unified = "src.main:main"`

When you add a new tool, you must import it into `src/main.py` and add
it to the `mcp.add_tool()` list — see `memory-hub-mcp/CLAUDE.md` for the
full instructions.

## Running the server

### Local (STDIO)

```bash
make install          # create .venv and install
make run-local        # run with hot-reload in STDIO mode
```

In a second terminal:

```bash
cmcp ".venv/bin/python -m src.main" tools/list
cmcp ".venv/bin/python -m src.main" tools/call register_session '{"api_key": "mh-dev-<you>-2026"}'
```

### OpenShift (streamable-HTTP)

```bash
make deploy PROJECT=<openshift-project>
```

See [`docs/build-deploy-hardening.md`](../docs/build-deploy-hardening.md)
for the deployment invariants that apply across all MemoryHub components
(base image, file permissions, FIPS posture, health checks).

### Environment

| Variable | Default | Purpose |
|---|---|---|
| `MCP_TRANSPORT` | `stdio` | `stdio` for local, `http` for OpenShift |
| `MCP_HTTP_HOST` | `0.0.0.0` | HTTP bind address |
| `MCP_HTTP_PORT` | `8080` | HTTP port |
| `MCP_HTTP_PATH` | `/mcp/` | HTTP endpoint path |
| `MCP_LOG_LEVEL` | `INFO` | Logging level |

## Testing

```bash
make test                                       # full suite
.venv/bin/pytest tests/ -k "search_memory" -v   # targeted
.venv/bin/pytest --cov=src --cov-report=html    # with coverage
```

The FastMCP decorators wrap tool functions in tool objects; tests access
the underlying function via the `.fn` attribute:

```python
from src.tools.search_memory import search_memory

@pytest.mark.asyncio
async def test_search():
    result = await search_memory.fn(query="container preferences")
    assert "results" in result
```

See [`memory-hub-mcp/CLAUDE.md`](CLAUDE.md) for the full test patterns,
import conventions, and the reason this server registers tools directly
in `main.py` instead of using the template's dynamic loader (short version:
the loader was designed for FastMCP 2 and doesn't register tools correctly
under v3).

## Error handling

All tools raise `fastmcp.exceptions.ToolError` for failures. This sets the
`is_error` flag on the MCP wire response, which well-behaved clients surface
as a tool-level error rather than a protocol error.

**Contract**: no tool returns `{"error": True}` dicts. A regression test
(`tests/test_no_error_dicts.py`) enforces this.

**For tool authors**: import `ToolError` from `fastmcp.exceptions`, raise it
for all failures, and add an `except ToolError: raise` guard before any
broad `except Exception` handler to prevent re-wrapping:

```python
from fastmcp.exceptions import ToolError

try:
    result = await service.do_thing(...)
except ToolError:
    raise  # let it propagate unchanged
except Exception as e:
    logger.error("Unexpected error in my_tool: %s", e)
    raise ToolError("Internal error; check server logs") from None
```

The SDK classifies errors by message prefix into typed exceptions:

| Message pattern (case-insensitive) | SDK exception |
|--------|--------------|
| contains `"invalid api key"` or `"no authenticated session"` | `AuthenticationError` |
| starts with `"curation rule blocked"` | `CurationVetoError` |
| contains `"not found"` | `NotFoundError` |
| contains `"not authorized"` or starts with `"access denied:"` | `PermissionDeniedError` |
| contains `"already exists"` or `"already deleted"` | `ConflictError` |
| starts with `"invalid "`, or contains `" must be "` or `"cannot be empty"` | `ValidationError` |

See [`planning/tool-error-standardization.md`](../planning/tool-error-standardization.md)
for the full design note.

## Further reading

- [Architecture](../docs/ARCHITECTURE.md) — system design, deployment topology, data flow
- [MCP server design](../docs/mcp-server.md) — FastMCP 3 bring-up, tool catalog history, transport decisions
- [Memory tree](../docs/memory-tree.md) — the tree/branch data model these tools operate on
- [Agent memory ergonomics](../docs/agent-memory-ergonomics/design.md) — the design behind `search_memory`'s parameters
- [Governance](../docs/governance.md) — scopes, ownership, tenant isolation, audit
- [Curator agent](../docs/curator-agent.md) — the pipeline behind curation rules, similarity checks, and merge suggestions
- [Package layout](../docs/package-layout.md) — how `memory-hub-mcp`, `memoryhub-core`, and the SDK fit together
