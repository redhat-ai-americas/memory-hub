# Next Session: Dashboard Admin — Client Management, Users/Agents, oauth-proxy

## Goal

Add admin functionality to the MemoryHub dashboard: self-service OAuth client management (Panel 7), a Users/Agents roster (Panel 3), and oauth-proxy to secure the UI Route. By end of session: platform admins can create/deactivate OAuth clients for agents, see who's using MemoryHub, and the dashboard is behind OpenShift auth.

## What's deployed and working

- MCP server with RBAC enforcement on OpenShift (`mcp-server` in `memory-hub-mcp` namespace)
- OAuth 2.1 auth service (`auth-server` in `memoryhub-auth` namespace) — POST /token, /.well-known/*, /healthz
- PostgreSQL + pgvector in `memoryhub-db` namespace
- SDK v0.1.0 on PyPI with JWT auth
- **Dashboard with Memory Graph + Status Overview** (`memoryhub-ui` in `memory-hub-mcp` namespace)
  - Interactive force-directed graph (cytoscape.js/fcose), scope coloring, edge click relationship view
  - Status cards: total memories, donut chart, activity feed, MCP health
  - OdhApplication tile registered in RHOAI
- `noCache: true` on all BuildConfigs (no more stale layer issues)

## Design references

- `docs/RHOAI-DEMO/landing-page-design.md` — Panels 3 and 7 specs
- `docs/RHOAI-DEMO/ui-architecture.md` — oauth-proxy sidecar, auth service admin API
- `memoryhub-auth/src/models.py` — OAuthClient and RefreshToken SQLAlchemy models

## Session scope

### 1. Auth service admin API (`memoryhub-auth/`)

The auth service currently only has token issuance. Add client management endpoints:

```
GET    /admin/clients              → list all clients
POST   /admin/clients              → create client (returns client_secret once)
GET    /admin/clients/{client_id}  → get client detail
PATCH  /admin/clients/{client_id}  → update (deactivate, change scopes)
POST   /admin/clients/{client_id}/rotate-secret → generate new secret
```

**OAuthClient model** (already exists in `memoryhub-auth/src/models.py`):
- client_id (String, unique), client_secret_hash (String), client_name (String)
- identity_type (String: user/service), tenant_id (String), default_scopes (JSON)
- active (Boolean), created_at, updated_at

These endpoints are admin-only. For this session, protect them with a shared admin secret header (`X-Admin-Key`). In production, they'd be behind the oauth-proxy.

### 2. Panel 7: Client Management (frontend + BFF)

Self-service OAuth client provisioning.

**Table columns:** client_id, client_name, identity_type (user/service badge), scopes, tenant_id, active status, created date

**Actions:**
- Create client via modal: client_id, client_name, identity_type dropdown, scopes checkboxes, tenant_id
- Secret shown once in a confirmation modal after creation (with copy button)
- Deactivate: toggle active status (soft delete, no hard delete)
- Rotate secret: generates new secret, invalidates old, shows new secret once

**BFF endpoints to add:**
```
GET    /api/clients              → proxy to auth service /admin/clients
POST   /api/clients              → proxy to auth service
PATCH  /api/clients/{client_id}  → proxy to auth service
POST   /api/clients/{client_id}/rotate-secret → proxy to auth service
```

### 3. Panel 3: Users and Agents

Read-only roster of all identities using MemoryHub.

**Data sources:**
- Primary: `oauth_clients` table via auth service admin API (authoritative identity list)
- Enrichment: `SELECT owner_id, COUNT(*), MAX(updated_at) FROM memory_nodes WHERE is_current = true GROUP BY owner_id` for memory counts and last active time

**Table columns:** name, type (user/service badge), use case (from client_name), memory count, last active

**Interaction:** Click a row to filter the Memory Graph by that owner_id (navigate to graph panel with owner filter pre-set).

### 4. oauth-proxy sidecar

Add OpenShift oauth-proxy to the memoryhub-ui Deployment so the dashboard requires OpenShift login.

**Changes:**
- Add `oauth-proxy` sidecar container to the Deployment
- Create ServiceAccount with `serviceaccounts.openshift.io/oauth-redirectreference` annotation
- Route terminates TLS at oauth-proxy (port 4180), which proxies to the app (port 8080)
- Update Route to point to oauth-proxy port
- Update Service to expose both ports

The oauth-proxy authenticates users via OpenShift OAuth and passes the authenticated identity downstream. The dashboard itself doesn't need to validate tokens — it's behind the proxy.

## Architecture

```
RHOAI Dashboard
  └─ OdhApplication tile → memoryhub-ui Route (TLS)
                                │
                    ┌───────────┴────────────┐
                    │   oauth-proxy :4180     │ ← OpenShift OAuth login
                    └───────────┬────────────┘
                                │ (authenticated)
                    ┌───────────┴────────────┐
                    │   memoryhub-ui :8080    │
                    │   React + FastAPI BFF   │
                    └───────────┬────────────┘
                          │           │
              ┌───────────┘           └───────────┐
              │ SQLAlchemy                        │ HTTP
    ┌─────────┴──────────┐            ┌───────────┴────────────┐
    │ PostgreSQL+pgvector │            │ auth-server :8081      │
    └────────────────────┘            │ /admin/clients/*       │
                                      └────────────────────────┘
```

## Implementation plan

### Step 1: Auth service admin API

Add `memoryhub-auth/src/routes/admin.py`:
- CRUD endpoints for oauth_clients
- Pydantic schemas for client creation (input) and client detail (output)
- Client secret generation: `secrets.token_urlsafe(32)`, hash with bcrypt, return plaintext once
- Admin auth: `X-Admin-Key` header checked against `ADMIN_KEY` env var
- Tests for all endpoints

Redeploy auth service to `memoryhub-auth` namespace.

### Step 2: BFF proxy endpoints

Add to `memoryhub-ui/backend/src/routes.py`:
- `/api/clients` endpoints that proxy to the auth service admin API
- BFF adds the `X-Admin-Key` header from its own env var (frontend never sees the admin key)
- Auth service URL from `MEMORYHUB_AUTH_SERVICE_URL` env var

### Step 3: Frontend panels

- `ClientManagement.tsx` — Table with create modal, deactivate toggle, rotate secret action
- `UsersAgents.tsx` — Read-only roster with memory counts, click-to-filter
- Wire into App.tsx sidebar nav (replace placeholder items)
- Add `SecretRevealModal.tsx` — one-time secret display with copy button

### Step 4: oauth-proxy sidecar

- Update `memoryhub-ui/openshift.yaml` with sidecar container, ServiceAccount, updated Route
- Create `memoryhub-ui/openshift/oauth-proxy-sa.yaml` for the ServiceAccount
- Test that unauthenticated requests redirect to OpenShift login

### Step 5: Redeploy everything

- Auth service with admin API
- memoryhub-ui with new panels + oauth-proxy
- Verify end-to-end: login → dashboard → create client → see in roster

## What we're NOT building this session

- Panels 4-6 (Curation Rules, Contradiction Log, Observability Links)
- Role-based access control on the admin API (all authenticated users are admins for now)
- Client secret rotation notifications
- Audit logging for client management operations

## What comes after

- **Panels 4+5** — Curation Rules and Contradiction Log
- **#10 Grafana dashboards** — observability metrics for Panel 6
- **RBAC on admin API** — restrict client management to specific users/groups
- **#25 CLI client** — typer/click wrapper around the SDK
- **#36 Frontend component tests** — Vitest + React Testing Library
