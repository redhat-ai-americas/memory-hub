# Next Session: OAuth 2.1 Auth Service

## Goal

Build and deploy the OAuth 2.1 authorization service — the foundation for MemoryHub's auth architecture. Focus on `client_credentials` grant (the workhorse for agents/SDKs). By end of session: a deployed service that accepts API keys and returns short-lived JWTs, verified on the cluster.

## What's deployed and working

- MCP server with 12 tools on OpenShift (route: `https://mcp-server-memory-hub-mcp.apps.cluster-n7pd5.n7pd5.sandbox5167.opentlc.com/mcp/`)
- PostgreSQL + pgvector in `memoryhub-db` namespace
- Real embeddings via all-MiniLM-L6-v2
- API key auth with users configmap (to be replaced by OAuth)
- Deterministic curation pipeline (secrets scan, PII detection, embedding dedup)
- Contradiction tracking with `contradiction_reports` table + `resolve_contradiction` service function
- Lazy rule seeding, one-command deployment (`make deploy-all`)
- 175 tests (106 unit + 69 MCP), all passing locally
- Authorino installed on cluster (v1beta2, defense-in-depth role)
- RBAC design complete in `docs/governance.md` — enforcement architecture, scope model, audit trail schema, auth architecture
- `memoryhub` Python SDK on PyPI (placeholder 0.0.1)
- CI/CD: GH Actions test + release pipelines with trusted publishing
- Apache 2.0 license

## What was completed last session

- **#7** governance design — enforcement gaps documented, authorize_read/authorize_write designed, operational scope model (memory:read:user etc.), JWT token model with tenant_id, audit_log table schema with RLS
- **#13** closed as duplicate of #7
- **#22** Authorino verified — v1beta2 on cluster, landing-page-design.md fixed
- Auth architecture pivoted: OAuth 2.1 AS as separate service, three grant types, FastMCP JWTVerifier on MCP server. Istio identified as preferred defense-in-depth over Authorino.
- All design docs updated for new auth model (governance.md, mcp-server.md, ui-architecture.md, landing-page-design.md)
- `memoryhub` registered on PyPI (0.0.1 placeholder): https://pypi.org/project/memoryhub/
- CI/CD release pipeline: `scripts/release.sh`, GH Actions (test.yml + release.yml), trusted publishing, `/create-release` slash command. Verified end-to-end with sdk/v0.0.1 tag.
- Apache 2.0 LICENSE file added
- Retro at `retrospectives/2026-04-05_rbac-governance-design/RETRO.md`

## Session plan

### 1. Decide: same repo or separate repo?

Arguments for same repo (`memoryhub-auth/` alongside `memory-hub-mcp/`):
- Shared models (user identity, scopes, tenant)
- Easier to keep in sync during rapid development
- Single CI pipeline (already set up for monorepo)

Arguments for separate repo:
- Independent deployment lifecycle
- Auth service is a general capability, not MCP-specific
- Cleaner separation of concerns

Discuss and decide before writing code.

### 2. Build the auth service — `client_credentials` grant only

This is the minimum viable auth service. One grant type, one token endpoint.

**Endpoints to implement:**
- `POST /token` — accepts `grant_type=client_credentials`, `client_id`, `client_secret`, returns JWT + refresh token
- `GET /.well-known/oauth-authorization-server` — server metadata (RFC 8414)
- `GET /.well-known/jwks.json` — public key for JWT verification

**Internals:**
- Client registry backed by PostgreSQL (can share the existing DB or use a new table)
- RSA key pair for JWT signing (generated on first start, or from a K8s Secret)
- JWT claims: `sub`, `identity_type`, `tenant_id`, `scopes`, `exp`, `iss`, `aud`
- Short TTL (5–15 min), refresh token for long sessions
- FastAPI service on UBI9

**What we're NOT building this session:**
- `authorization_code` + PKCE grant (browser auth — needed for dashboard, not for agents)
- Token exchange / RFC 8693 (platform integration — needed for RHOAI, not for MVP)
- `/register` endpoint (dynamic client registration — can add later)
- Istio integration (defense-in-depth — separate concern)

### 3. Deploy to OpenShift and verify

- Deploy auth service to its own namespace or alongside the MCP server
- Verify: `curl -X POST /token` with a valid client_id/secret returns a JWT
- Verify: JWT can be decoded and has the expected claims
- Verify: JWKS endpoint returns the public key

### 4. Smoke test: MCP server validates the JWT

Wire `JWTVerifier` into the MCP server's FastMCP constructor, pointing at the auth service's JWKS endpoint. Verify that a tool call with a valid JWT succeeds and one without fails. This doesn't need to be the full enforcement rollout — just proof that the two services talk to each other.

## Architecture reference (from governance.md)

**JWT claims:**
```json
{
  "sub": "wjackson",
  "identity_type": "user",
  "tenant_id": "org-acme-healthcare",
  "scopes": ["memory:read", "memory:write:user"],
  "iat": 1743879600,
  "exp": 1743880500,
  "iss": "https://memoryhub-auth.apps.example.com",
  "aud": "memoryhub"
}
```

**Operational scopes:** `memory:read`, `memory:write:user`, `memory:write:organizational`, `memory:admin`

**FastMCP integration:**
```python
from fastmcp import FastMCP
from fastmcp.server.auth import JWTVerifier

auth = JWTVerifier(
    jwks_uri="https://memoryhub-auth.apps.example.com/.well-known/jwks.json",
    issuer="https://memoryhub-auth.apps.example.com",
    audience="memoryhub",
)
mcp = FastMCP("MemoryHub", auth=auth)
```

## What comes after this session

- **SDK (`memoryhub` on PyPI):** `MemoryHubClient` wrapping the token exchange + memory operations. Depends on having a real `/token` endpoint to code against.
- **Full MCP enforcement:** Roll out `authorize_read`/`authorize_write` across all tools, backed by JWT scopes.
- **Additional grant types:** `authorization_code` + PKCE for the dashboard, token exchange for RHOAI agents.
- **#19** RHOAI dashboard UI (blocked on auth being real)

## Open backlog (for context, not this session)

- **#7** — Implementation of RBAC enforcement (design done, auth service is prerequisite)
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
- Run tests before committing
- Deploy and verify on cluster as part of implementation, not as an afterthought
- After architectural changes, check ALL design docs for stale references (lesson from this session's retro)
