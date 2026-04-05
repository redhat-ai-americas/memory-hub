# Next Session: OAuth Auth Service + Python SDK

## Goal

Begin implementing the OAuth 2.1 auth service and the `memoryhub` Python SDK. These are the two new components that emerged from the RBAC design session. The auth service is the foundation — nothing else can enforce scopes without it.

## What's deployed and working

- MCP server with 12 tools on OpenShift (route: `https://mcp-server-memory-hub-mcp.apps.cluster-n7pd5.n7pd5.sandbox5167.opentlc.com/mcp/`)
- PostgreSQL + pgvector in `memoryhub-db` namespace
- Real embeddings via all-MiniLM-L6-v2
- API key auth with users configmap (to be replaced by OAuth)
- Deterministic curation pipeline (secrets scan, PII detection, embedding dedup)
- Contradiction tracking with `contradiction_reports` table + `resolve_contradiction` service function
- Lazy rule seeding, one-command deployment (`make deploy-all`)
- 175 tests (106 unit + 69 MCP), all passing
- Authorino installed on cluster (v1beta2, defense-in-depth role)
- RBAC design complete in `docs/governance.md` — enforcement architecture, scope model, audit trail schema, auth architecture

## What was completed last session

- **#7** governance design — enforcement gaps documented, authorize_read/authorize_write designed, operational scope model (memory:read:user etc.), JWT token model with tenant_id, audit_log table schema with RLS
- **#13** closed as duplicate of #7
- **#22** Authorino verified — v1beta2 on cluster, landing-page-design.md fixed
- Auth architecture pivoted: OAuth 2.1 AS as separate service, three grant types, FastMCP JWTVerifier on MCP server
- memoryhub-integration.md rules fixed (hardcoded API key)
- Retro at `retrospectives/2026-04-05_rbac-governance-design/RETRO.md`

## Session plan

### 1. Register `memoryhub` on PyPI

The name is available. Create a minimal placeholder package to reserve it:
- `memoryhub/` package with `__init__.py` and version
- `pyproject.toml` with metadata
- Publish to PyPI

This is time-sensitive — someone else could register it.

### 2. Decide: same repo or separate repo for auth service?

Arguments for same repo:
- Shared models (user identity, scopes, tenant)
- Easier to keep in sync during rapid development
- Single CI pipeline

Arguments for separate repo:
- Independent deployment lifecycle
- Auth service is a general capability, not MCP-specific
- Cleaner separation of concerns

Discuss and decide before starting implementation.

### 3. Design the auth service

If same repo: `memoryhub-auth/` directory alongside `memory-hub-mcp/`
If separate repo: new repo with FastAPI

Key components:
- `/token` endpoint (all three grant types)
- `/register` endpoint (dynamic client registration)
- `/.well-known/oauth-authorization-server` metadata
- JWKS endpoint for public key distribution
- Client registry (PostgreSQL — can share the existing DB)
- Trust configuration (YAML or CRD)
- Token issuance (short-lived JWT + refresh token)

### 4. Design the Python SDK

The `memoryhub` package that agents import:
- `MemoryHubClient` with api_key and platform_token auth modes
- Token caching, refresh, retry-on-401
- search, read, write, update operations
- Async-first (with sync wrapper)

### 5. Wire FastMCP JWTVerifier into MCP server

Update `memory-hub-mcp/src/core/app.py` to pass `auth=JWTVerifier(...)` to FastMCP constructor. This replaces the custom `register_session` / `require_auth()` pattern.

## Architecture decisions (from governance.md)

- OAuth 2.1 AS as a **separate service**
- Three grants: client_credentials, authorization_code+PKCE, token exchange (RFC 8693)
- Operational scopes: `memory:read`, `memory:write:user`, `memory:write:organizational`, `memory:admin`
- TenantID in JWT claims
- MCP server is a resource server (JWTVerifier only)
- `register_session` retained as compatibility shim
- Expandable trust config, start with local cluster
- `memoryhub` SDK on PyPI

## Open backlog (for context, not this session)

- **#7** — Implementation of the RBAC enforcement (design done)
- **#19** — RHOAI dashboard UI (blocked on auth)
- **#21** — Evaluate graph viz library
- **#24** — Write getStartedMarkDown for OdhApplication CR
- **#10** — Observability: Grafana dashboards + Prometheus metrics
- **#11** — Org-ingestion pipeline design
- **#5** — MinIO for S3 object storage
- **#25, #26, #27** — CLI, SDK, LlamaStack integration

## Key conventions

- MCP tools MUST be created via `/plan-tools` → `/create-tools` → `/exercise-tools`
- Delete existing deployment before redeploying (`make clean-mcp` then `make deploy-mcp`)
- Use `-n namespace` flags, never `oc project`
- Run `make test` before committing
- Deploy and verify on cluster as part of implementation
