# UI Architecture Options

Two approaches to integrating the MemoryHub UI with the RHOAI dashboard,
with different trade-offs in coupling, effort, and native feel.

## Option A: Standalone PatternFly App (recommended for demo)

A self-contained React + PatternFly application served from its own Route.
The OdhApplication tile links to this Route.

### Architecture

```
┌─────────────────────────────────────┐
│  RHOAI Dashboard                    │
│  ┌───────────────────────────────┐  │
│  │ OdhApplication tile           │  │
│  │ "Open application" ──────────────┼──► memoryhub-ui Route
│  └───────────────────────────────┘  │      │
└─────────────────────────────────────┘      ▼
                                     ┌──────────────┐
                                     │ MemoryHub UI │ (PatternFly React)
                                     │ nginx/caddy  │
                                     └──────┬───────┘
                                            │ REST API
                                            ▼
                                     ┌──────────────┐
                                     │ FastAPI      │
                                     │ Backend      │──► Auth service API (OAuth clients)
                                     └──────┬───────┘
                                            │ SQLAlchemy
                                            ▼
                                     ┌──────────────┐
                                     │ PostgreSQL   │◄── MemoryHub MCP Server
                                     │ + pgvector   │    (agent-facing, same DB)
                                     └──────────────┘
```

### Stack

| Layer | Technology |
|---|---|
| Framework | React 18+ |
| Component library | PatternFly 6 (matches odh-dashboard) |
| Build tool | Vite |
| Container | nginx on UBI 9 (static file serving) |
| API communication | FastAPI backend → PostgreSQL (shared DB with MCP server) |

### Authentication

Authentication is handled by a separate OAuth 2.1 authorization service that issues short-lived JWTs. Agents exchange API keys for tokens via the `client_credentials` grant; the MCP server validates JWTs using FastMCP's `JWTVerifier`. See [governance.md](../governance.md) for the full architecture.

Authorino or Istio Service Mesh can optionally validate JWTs at the infrastructure layer as defense-in-depth, rejecting invalid tokens before they reach the application. This is recommended for production but not required — the MCP server validates tokens independently.

The landing page UI itself is accessed by platform admins via the RHOAI dashboard, so it sits behind OpenShift OAuth (same as the dashboard). For the demo, we can use an `oauth-proxy` sidecar on the UI deployment, or simply rely on the cluster's network policy if all users are already authenticated to the console.

For client management (creating/deactivating clients), the UI talks to the auth service's client registry (`oauth_clients` table). Authorino can optionally validate JWTs at the infrastructure layer as defense-in-depth.

### API Layer

The UI backend is a FastAPI service that queries PostgreSQL directly
using SQLAlchemy async, sharing the same models from the `memoryhub-core`
library that the MCP server uses. This is not an MCP client — the UI
backend and the MCP server are peers that read from the same database.
The MCP server is not in the data path for the UI.

The FastAPI backend handles three concerns:

1. **Memory data** — SQL queries against `memory_nodes`, `memory_relationships`,
   and `curator_rules`. pgvector similarity queries for search. No MCP
   protocol involved.

2. **Auth service API** — Listing, creating, and deactivating OAuth clients
   for identity management. The React app proxies these calls through the
   FastAPI backend.

3. **MCP server health** — A simple HTTP health check against the MCP server
   pod to report liveness on the Status Overview panel. This is a plain
   HTTP GET, not an MCP protocol interaction.

### Data Architecture

The UI backend and MCP server are peers sharing the same PostgreSQL database.
Neither proxies through the other.

- The **MCP server** is the write path for agents: it receives tool calls
  (write_memory, update_memory, etc.) and commits changes to PostgreSQL.
- The **UI backend** is the read path for humans: it queries PostgreSQL
  directly for dashboards, graph visualization, and admin views.
- The only writes the UI backend makes are to the auth service (OAuth client
  management) and to `curator_rules` (admin curation rule management).
- Both services use the same SQLAlchemy models from `memoryhub-core`,
  so schema changes are reflected consistently.

This shared-database pattern is standard for platform UIs — the OpenShift
console reads from etcd, the same store the API server writes to, without
proxying through the API server for every read.

### Pros

- Full control over the UI — no coupling to dashboard internals
- Uses the same PatternFly version (6.x) as the RHOAI dashboard, so
  it looks native
- Independent release cycle — deploy UI updates without touching RHOAI
- Simpler to build and debug
- Can be developed and tested outside the cluster

### Cons

- Opens in a new browser tab (not inline in the dashboard)
- Needs its own oauth-proxy sidecar for admin auth (straightforward
  but an extra container)
- Doesn't appear in the dashboard's left sidebar navigation

### Deployment

```yaml
# Deployment for the UI (static files via nginx)
apiVersion: apps/v1
kind: Deployment
metadata:
  name: memoryhub-ui
  namespace: memory-hub-mcp
spec:
  replicas: 1
  selector:
    matchLabels:
      app: memoryhub-ui
  template:
    spec:
      containers:
      - name: ui
        image: quay.io/yourorg/memoryhub-ui:latest
        ports:
        - containerPort: 8080
---
# Route referenced by the OdhApplication CR
apiVersion: route.openshift.io/v1
kind: Route
metadata:
  name: memoryhub-ui
  namespace: memory-hub-mcp
spec:
  tls:
    termination: edge
  to:
    kind: Service
    name: memoryhub-ui
```

---

## Option B: ODH Dashboard Plugin (deeper integration)

Embed MemoryHub as a feature package inside the ODH dashboard, appearing
as a left-sidebar navigation item alongside Workbenches, Pipelines, etc.

### Architecture

```
┌────────────────────────────────────────────────────┐
│  RHOAI Dashboard                                   │
│                                                    │
│  ┌──────────┐  ┌────────────────────────────────┐  │
│  │ Sidebar  │  │ Main content area               │  │
│  │          │  │                                  │  │
│  │ Home     │  │  ┌────────────────────────────┐ │  │
│  │ Projects │  │  │ MemoryHub plugin           │ │  │
│  │ Models   │  │  │ (loaded via Module         │ │  │
│  │ Pipelines│  │  │  Federation at runtime)    │ │  │
│  │ MemoryHub│◄─┤  └────────────────────────────┘ │  │
│  │          │  │                                  │  │
│  └──────────┘  └────────────────────────────────┘  │
│                       │ API calls                   │
│                       ▼                             │
│               ┌──────────────┐                      │
│               │ FastAPI BFF  │  (queries PostgreSQL  │
│               │ /api/memory  │   directly, not MCP)  │
│               └──────┬───────┘                       │
│                      │                              │
└──────────────────────┼──────────────────────────────┘
                       ▼
                ┌──────────────┐
                │ PostgreSQL   │◄── MemoryHub MCP Server
                │ + pgvector   │    (agent-facing, same DB)
                └──────────────┘
```

### How the ODH dashboard extension model works

The ODH dashboard is a monorepo (~25 packages) using Webpack Module
Federation for runtime code sharing. Feature packages live under
`packages/` and are loaded dynamically. Key points:

- Each feature is a self-contained package with its own routes,
  components, and API layer
- The dashboard shell provides navigation registration, auth context,
  and PatternFly theme
- Some features use a BFF pattern (gen-ai, model-registry, maas) for
  backend communication
- There is no formal "install a third-party plugin" mechanism — today,
  features are added by contributing to the monorepo

### What this means for MemoryHub

To use Option B, we would either:

1. **Fork odh-dashboard** and add a `packages/memoryhub` feature
   package. This gives full integration but means maintaining a fork.

2. **Contribute upstream** — submit a PR to odh-dashboard adding
   MemoryHub as an optional feature package. This is the long-term
   path but requires alignment with the ODH community.

3. **Dynamic plugin loading** — the dashboard doesn't currently support
   loading external plugins at runtime without rebuilding. This may
   change in future versions, but it's not available today.

### Pros

- Fully inline — MemoryHub appears in the sidebar, no new tab
- Inherits dashboard auth (OpenShift OAuth) automatically
- Shares the dashboard's PatternFly theme and layout
- Feels like a first-class RHOAI component

### Cons

- Requires forking or contributing to odh-dashboard
- Tightly coupled to dashboard release cycle and build system
- Must track upstream dashboard changes to avoid merge conflicts
- More complex development setup (full dashboard monorepo)
- No formal third-party plugin loading mechanism yet

### Effort comparison

| Dimension | Option A (standalone) | Option B (plugin) |
|---|---|---|
| Time to demo-ready | Days | Weeks |
| Dashboard coupling | None | Tight |
| MCP auth | OAuth 2.1 JWT (both options) | OAuth 2.1 JWT (both options) |
| Admin auth | oauth-proxy sidecar | Inherited from dashboard |
| Release independence | Full | Tied to dashboard |
| "Native" feel | Very close (same PatternFly) | Identical |
| Long-term viability | Indefinite | Best if accepted upstream |

---

## Recommendation

**Start with Option A** for the demo and near-term use. It can be built
quickly, looks native thanks to PatternFly 6, and has no dependency on
the dashboard codebase.

**Plan for Option B** as the long-term target once MemoryHub is accepted
as an RHOAI component. At that point, the React components built for
Option A can be lifted into a dashboard feature package with minimal
rework — the PatternFly components and API layer are the same.
