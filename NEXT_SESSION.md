# Next Session: Python SDK (`memoryhub` on PyPI)

## Goal

Ship a real `memoryhub` SDK (v0.1.0) that wraps MemoryHub's MCP tools as typed Python methods with transparent OAuth authentication. By end of session: a published package on PyPI that a developer can `pip install memoryhub` and use to search/read/write memories from any Python agent.

## What's deployed and working

- MCP server with 12 tools on OpenShift (`https://mcp-server-memory-hub-mcp.apps.cluster-n7pd5.n7pd5.sandbox5167.opentlc.com/mcp/`)
- **OAuth 2.1 auth service** on OpenShift (`https://auth-server-memoryhub-auth.apps.cluster-n7pd5.n7pd5.sandbox5167.opentlc.com`)
  - `client_credentials` + `refresh_token` grants
  - RSA-2048 JWT signing, JWKS endpoint
  - Seeded clients: wjackson (user), curator-agent (service)
- PostgreSQL + pgvector in `memoryhub-db` namespace
- Real embeddings via all-MiniLM-L6-v2
- MCP server has JWTVerifier loaded (validates tokens when present, doesn't reject unauthenticated yet)
- CI/CD: GH Actions test + release pipelines with trusted publishing
- `memoryhub` registered on PyPI (0.0.1 placeholder)
- 175 core + MCP tests, 51 auth tests — all passing

## What was completed last session

- Auth service built and deployed (memoryhub-auth/)
- Migration 006: oauth_clients + refresh_tokens tables
- MCP server wired with JWTVerifier via AUTH_JWKS_URI env var
- Key finding: FastMCP 3.2.0 JWTVerifier validates tokens when present but doesn't reject unauthenticated requests. Full enforcement needs RemoteAuthProvider or service-layer checks (planned for #7).
- Retro at `retrospectives/2026-04-05_oauth-auth-service/RETRO.md`

## Session plan

### 1. Design the SDK API surface

The SDK wraps MCP tools as typed Python methods. The developer never sees MCP protocol, JWT tokens, or transport details.

**Target API (from governance.md):**

```python
from memoryhub import MemoryHubClient

# API key auth (client_credentials grant under the hood)
client = MemoryHubClient(
    url="https://mcp-server-memory-hub-mcp.apps.example.com/mcp/",
    auth_url="https://auth-server-memoryhub-auth.apps.example.com",
    client_id="wjackson",
    client_secret="mh-dev-wjackson-2026",
)

# Or from environment variables
client = MemoryHubClient.from_env()

# Core operations — async
results = await client.search("deployment patterns", max_results=5)
memory = await client.read(memory_id="uuid-here")
created = await client.write("User prefers Podman over Docker", scope="user", weight=0.9)
updated = await client.update(memory_id="uuid-here", content="Updated content")

# Lifecycle
history = await client.get_history(memory_id="uuid-here")
await client.report_contradiction(memory_id="uuid-here", observed_behavior="...", confidence=0.8)

# Sync wrappers for non-async contexts
results = client.search_sync("deployment patterns")
```

**Decided:** Use FastMCP `Client` with `BearerAuth` over streamable-http. The server already speaks MCP — no reason to build a REST layer.

**Remaining design decisions to discuss:**
- Async-first with sync wrappers, or sync-first with async variants?
- How to handle `register_session` — the SDK should call it automatically after connecting, or skip it if JWT auth is active (it becomes a compatibility shim per governance.md).
- Environment variable naming: `MEMORYHUB_URL`, `MEMORYHUB_AUTH_URL`, `MEMORYHUB_CLIENT_ID`, `MEMORYHUB_CLIENT_SECRET`?

### 2. Implement the SDK

**Structure in `sdk/`:**

```
sdk/
├── src/memoryhub/
│   ├── __init__.py          # Exports MemoryHubClient, __version__
│   ├── client.py            # MemoryHubClient class
│   ├── auth.py              # Token management (fetch, cache, refresh, retry-on-401)
│   ├── models.py            # Pydantic models for Memory, SearchResult, etc.
│   └── exceptions.py        # MemoryHubError, AuthenticationError, NotFoundError
├── tests/
│   ├── conftest.py
│   ├── test_client.py
│   ├── test_auth.py
│   └── test_models.py
├── pyproject.toml           # Already exists (0.0.1 placeholder)
└── README.md                # Already exists
```

**Auth layer (auth.py):**
- Calls `POST /token` with `client_credentials` grant
- Caches the access token in memory
- Refreshes automatically when expired (checks `exp` claim, refreshes with ~30s buffer)
- Uses refresh token for seamless rotation
- Retry-on-401: if a tool call gets 401, refresh token and retry once

**Transport layer:**
- Uses FastMCP `Client` with `BearerAuth` for MCP protocol over streamable-http (decided)

**Dependencies to add to pyproject.toml:**
- `httpx` (HTTP client for token endpoint + optional REST transport)
- `pyjwt` (decode token to check expiry without verification)
- `pydantic>=2.0` (response models)
- If using MCP transport: `fastmcp>=2.11.3`

### 3. Write tests

- Unit tests for auth token management (mock the token endpoint)
- Unit tests for response model parsing
- Integration test: connect to the real deployed MCP server, search memories, verify response structure
- Test sync wrappers work correctly

### 4. Publish v0.1.0 to PyPI

- Bump version in pyproject.toml to 0.1.0
- Update README.md with real usage examples
- Use `/create-release` to tag and publish via GH Actions trusted publishing
- Verify: `pip install memoryhub` in a clean venv, run a quick smoke test

### 5. Smoke test: use the SDK from a script

Write a small example script that demonstrates the SDK end-to-end:
```python
from memoryhub import MemoryHubClient

client = MemoryHubClient.from_env()
results = await client.search("deployment patterns")
print(f"Found {len(results)} memories")
```

## What we're NOT building this session

- Sync wrappers can be deferred if time is short (async-first is fine for v0.1.0)
- `platform_token=True` (K8s SA token exchange) — needs token_exchange grant, not built yet
- CLI client (#25) — separate concern, can wrap the SDK later
- LlamaStack integration (#27) — depends on SDK being done first
- RBAC enforcement (#7) — next session after this

## MCP tool → SDK method mapping

| MCP Tool | SDK Method | Priority |
|----------|-----------|----------|
| `search_memory` | `client.search()` | Must have |
| `read_memory` | `client.read()` | Must have |
| `write_memory` | `client.write()` | Must have |
| `update_memory` | `client.update()` | Must have |
| `register_session` | Called internally by client | Must have |
| `get_memory_history` | `client.get_history()` | Should have |
| `report_contradiction` | `client.report_contradiction()` | Should have |
| `get_similar_memories` | `client.get_similar()` | Nice to have |
| `get_relationships` | `client.get_relationships()` | Nice to have |
| `create_relationship` | `client.create_relationship()` | Nice to have |
| `suggest_merge` | `client.suggest_merge()` | Nice to have |
| `set_curation_rule` | `client.set_curation_rule()` | Nice to have |

## Architecture reference

**FastMCP Python client with Bearer auth:**
```python
from fastmcp import Client
from fastmcp.client.auth import BearerAuth

client = Client(
    "https://mcp-server.apps.example.com/mcp/",
    auth=BearerAuth(access_token)
)

async with client:
    result = await client.call_tool("search_memory", {"query": "test", "max_results": 5})
```

**OAuth token endpoint:**
```
POST https://auth-server-memoryhub-auth.apps.cluster-n7pd5.n7pd5.sandbox5167.opentlc.com/token
Content-Type: application/x-www-form-urlencoded

grant_type=client_credentials&client_id=wjackson&client_secret=mh-dev-wjackson-2026
```

Returns: `{"access_token": "eyJ...", "token_type": "bearer", "expires_in": 900, "refresh_token": "...", "scope": "..."}`

## What comes after this session

- **#7 RBAC enforcement**: Wire RemoteAuthProvider or service-layer authorize_read/authorize_write. SDK already sends JWTs, so enforcement is transparent to SDK users.
- **#25 CLI client**: Thin wrapper around the SDK with click/typer.
- **#27 LlamaStack integration**: Use SDK as the memory provider.
- **#19 RHOAI dashboard**: Unblocked by auth, independent of SDK.

## Open backlog (for context, not this session)

- **#7** — RBAC enforcement (design done, auth service deployed, needs implementation)
- **#19** — RHOAI dashboard UI
- **#21** — Evaluate graph viz library
- **#24** — Write getStartedMarkDown for OdhApplication CR
- **#10** — Observability: Grafana dashboards + Prometheus metrics
- **#11** — Org-ingestion pipeline design
- **#5** — MinIO for S3 object storage

## Key conventions

- SDK lives in `sdk/` directory (already exists with placeholder)
- Package name is `memoryhub` (already registered on PyPI)
- Use hatchling for builds (already configured in pyproject.toml)
- MCP tools MUST be created via `/plan-tools` → `/create-tools` → `/exercise-tools` (not applicable for SDK, but noted)
- Run tests before committing
- Deploy and verify on cluster as part of implementation
