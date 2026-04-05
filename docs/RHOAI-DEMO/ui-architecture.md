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
                                      │ MemoryHub UI │  (PatternFly React)
                                      │ nginx/caddy  │
                                      └──────┬───────┘
                                             │ API calls
                                             ▼
                                      ┌──────────────┐
                                      │ MemoryHub    │
                                      │ MCP Server   │
                                      └──────────────┘
```

### Stack

| Layer | Technology |
|---|---|
| Framework | React 18+ |
| Component library | PatternFly 6 (matches odh-dashboard) |
| Build tool | Vite |
| Container | nginx on UBI 9 (static file serving) |
| API communication | REST adapter over MCP tools (see below) |

### Authentication

Authorino handles all API key validation at the infrastructure layer.
The Authorino operator is already deployed with RHOAI. An `AuthConfig`
CR defines the policy for the MCP server Route — validating API keys
stored as labeled Kubernetes Secrets and injecting identity headers
(`X-Auth-Owner-Name`, `X-Auth-Owner-Type`) into forwarded requests.

The landing page UI itself is accessed by platform admins via the
RHOAI dashboard, so it sits behind OpenShift OAuth (same as the
dashboard). For the demo, we can use an `oauth-proxy` sidecar on the
UI deployment, or simply rely on the cluster's network policy if all
users are already authenticated to the console.

For API key management (creating/revoking keys), the UI talks to the
Kubernetes API to manage Authorino Secrets — no custom auth backend
needed.

### API Layer

The MCP server speaks MCP protocol (streamable-http), not REST. The UI
needs a thin adapter. Two approaches:

1. **BFF (Backend for Frontend)** — A lightweight FastAPI service that
   translates REST calls into MCP tool invocations. Deployed alongside
   the UI in the same namespace. Also proxies Kubernetes API calls for
   API key management (listing/creating Authorino Secrets) so the
   React app doesn't need a direct k8s API dependency.

2. **Direct MCP client in browser** — Use the MCP TypeScript SDK to
   call the MCP server directly from the React app. Simpler deployment
   (no BFF) but ties the frontend to MCP transport details. Key
   management would still need a backend for k8s API access.

Recommendation: **BFF approach** for the demo. It keeps the React app
as a pure REST consumer, provides a single backend for both MCP tool
calls and Kubernetes Secret management (API keys), and lets us add
caching and aggregation as needed.

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
  namespace: memoryhub
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
  namespace: memoryhub
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
│               │ BFF endpoint │  (optional, could    │
│               │ /api/memory  │   be a dashboard     │
│               └──────┬───────┘   backend route)     │
│                      │                              │
└──────────────────────┼──────────────────────────────┘
                       ▼
                ┌──────────────┐
                │ MemoryHub    │
                │ MCP Server   │
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
| MCP auth | Authorino (both options) | Authorino (both options) |
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
