# Next Session: RBAC Enforcement (#7)

## Goal

Enforce authorization on every MCP tool so that the deployed MemoryHub server rejects unauthorized access. By end of session: unauthenticated requests are rejected, JWT claims drive all read/write access decisions, and the SDK's transparent auth is verified end-to-end against the live server.

## What's deployed and working

- MCP server with 12 tools on OpenShift (`https://mcp-server-memory-hub-mcp.apps.cluster-n7pd5.n7pd5.sandbox5167.opentlc.com/mcp/`)
- OAuth 2.1 auth service on OpenShift (`https://auth-server-memoryhub-auth.apps.cluster-n7pd5.n7pd5.sandbox5167.opentlc.com`)
- JWTVerifier wired in `memory-hub-mcp/src/core/app.py` but **env-var gated** — `AUTH_JWKS_URI` and `AUTH_ISSUER` are not set in deployment, so it's currently inactive
- SDK v0.1.0 on PyPI — sends JWTs via OAuth 2.1 client_credentials
- PostgreSQL + pgvector in `memoryhub-db` namespace
- 175 core + MCP tests, 51 auth tests, 38 SDK tests — all passing
- Seeded OAuth clients: `wjackson` (user), `curator-agent` (service)

## What was completed last session

- SDK v0.1.0 published to PyPI with transparent OAuth auth
- SDK has MemoryHubAuth (custom httpx.Auth) that handles client_credentials + auto-refresh
- All 12 MCP tools wrapped with typed methods
- 38 SDK tests, 88% coverage

## The problem

Today, the MCP server has **no effective authorization**:
- `JWTVerifier` is wired but not activated (env vars not set)
- Most tools have zero auth checks (`read_memory`, `update_memory`, `get_memory_history`)
- Tools that check auth use `register_session`-based identity, which is process-local and doesn't read JWT claims
- `search_memory` accepts arbitrary `owner_id` without validation
- Cross-reference tools (`get_similar_memories`, `get_relationships`) don't filter results by caller's accessible scopes
- No tenant isolation in any query

## Session plan

### 1. Implement `authorize_read` and `authorize_write` (core/authz.py)

Create `memory-hub-mcp/src/core/authz.py` with the two shared authorization functions from `governance.md` (lines 154-190):

```python
def authorize_read(user_claims: dict, memory) -> bool:
    """Can this JWT bearer read this memory?"""
    # Tenant isolation → scope-level policy → ownership check

def authorize_write(user_claims: dict, scope: str, owner_id: str) -> bool:
    """Can this JWT bearer write a memory at this scope for this owner?"""
    # Operational scope check → tier policy → ownership check
```

Also implement a `get_claims_from_context(ctx: Context) -> dict` helper that:
- Extracts JWT claims from FastMCP's `get_access_token()` (when JWTVerifier is active)
- Falls back to `register_session` identity (compatibility shim for Claude Code MCP transport that can't send Authorization headers)
- Raises `ToolError` if neither is available (unauthenticated)

### 2. Wire authorization into every tool

**Per-tool enforcement based on governance.md:**

| Tool | Enforcement needed |
|------|-------------------|
| `search_memory` | SQL-level scope filtering: user-scope → `owner_id = caller`, broader scopes → check `has_scope` |
| `read_memory` | `authorize_read(claims, memory)` after fetch |
| `write_memory` | `authorize_write(claims, scope, owner_id)` before insert |
| `update_memory` | Fetch memory, `authorize_write(claims, memory.scope, memory.owner_id)` |
| `get_memory_history` | Fetch current memory, `authorize_read` check |
| `report_contradiction` | `authorize_read` on target memory (must be able to see it to contradict it) |
| `get_similar_memories` | Filter results through `authorize_read` |
| `get_relationships` | Filter both source node and related nodes through `authorize_read` |
| `register_session` | Keep as compatibility shim — stores identity for non-JWT clients |
| `suggest_merge` | `authorize_read` on both memories |
| `set_curation_rule` | Require `memory:admin` scope or `identity_type: service` |
| `create_relationship` | `authorize_read` on both source and target |

### 3. Activate JWTVerifier in deployment

- Set `AUTH_JWKS_URI` and `AUTH_ISSUER` env vars in the MCP server's OpenShift deployment
- Verify that unauthenticated MCP requests are rejected at transport level
- Verify that SDK auth (JWT bearer) passes through

### 4. Bridge `register_session` with JWT identity

When JWTVerifier is active, `register_session` becomes a compatibility shim:
- If the request already has a JWT (from transport auth), `register_session` is a no-op that returns the JWT identity
- If no JWT, `register_session` performs a client_credentials exchange internally and caches the identity
- Tools always go through `get_claims_from_context()` which checks JWT first, then session fallback

### 5. Write tests

**Unit tests for authz.py:**
- `test_authorize_read_user_scope_own_memory` — owner can read own user-scope memory
- `test_authorize_read_user_scope_other_user` — can't read another user's memory
- `test_authorize_read_organizational_scope` — all authenticated users can read org-scope
- `test_authorize_read_tenant_isolation` — different tenant always denied
- `test_authorize_write_user_scope` — can write own user-scope
- `test_authorize_write_organizational_requires_service` — only service agents write org-scope
- `test_authorize_write_enterprise_always_rejected` — enterprise writes need HITL

**Integration tests (against live server using SDK):**
- Unauthenticated request → rejected
- Authenticated search → returns only accessible memories
- Write user-scope memory → succeeds
- Read another user's memory → rejected
- Update own memory → succeeds
- Update another user's memory → rejected

### 6. Update `register_session` shim mode

- Detect when JWT is already present in request context
- Return JWT identity instead of requiring API key lookup
- Preserve backwards compat for API-key-only clients

## What we're NOT building this session

- Audit trail logging (designed in governance.md but can be a separate PR)
- HITL approval flow for enterprise-scope writes
- Project membership checks (governance.md has TBD for these)
- Role-scope matching (governance.md has TODO)
- Tenant management UI/API
- `memory:admin` scope operations beyond `set_curation_rule`

## Architecture reference

**JWT claims structure (from auth service):**
```json
{
  "sub": "wjackson",
  "identity_type": "user",
  "tenant_id": "default",
  "scopes": ["memory:read", "memory:write:user"],
  "iat": 1743904000,
  "exp": 1743904300,
  "iss": "https://auth-server-memoryhub-auth.apps.cluster-n7pd5...",
  "aud": "memoryhub"
}
```

**FastMCP access token extraction:**
```python
from fastmcp import Context

async def get_claims(ctx: Context) -> dict:
    token = ctx.get_access_token()  # Returns decoded JWT claims when JWTVerifier active
```

**Scope hierarchy (from governance.md):**
| Scope | `memory:read` | `memory:write` |
|-------|:---:|:---:|
| `memory:read` | All readable scopes | — |
| `memory:read:user` | User-scope only | — |
| `memory:write` | — | All writable scopes |
| `memory:write:user` | — | User-scope only |
| `memory:write:organizational` | — | Org-scope (service agents) |
| `memory:admin` | — | Admin operations |

**Seeded OAuth clients:**
- `wjackson`: identity_type=user, scopes=[memory:read, memory:write:user]
- `curator-agent`: identity_type=service, scopes=[memory:read, memory:write, memory:admin]

## Key files to modify

- `memory-hub-mcp/src/core/authz.py` — NEW: authorize_read, authorize_write, get_claims_from_context
- `memory-hub-mcp/src/core/auth.py` — UPDATE: bridge with JWT identity
- `memory-hub-mcp/src/tools/*.py` — UPDATE: wire authorization into each tool
- `memory-hub-mcp/src/core/app.py` — VERIFY: JWTVerifier activation
- `memory-hub-mcp/tests/test_authz.py` — NEW: authorization unit tests
- `memory-hub-mcp/tests/test_tools_auth.py` — NEW: per-tool auth enforcement tests

## What comes after this session

- **Audit trail**: `governance.md` has the full schema, just needs migration + logging calls
- **#25 CLI client**: Thin wrapper around SDK with typer/click
- **#27 LlamaStack integration**: SDK as memory provider
- **#19 RHOAI dashboard**: Independent, unblocked
- **HITL approval flow**: For enterprise-scope writes (deferred from RBAC)
