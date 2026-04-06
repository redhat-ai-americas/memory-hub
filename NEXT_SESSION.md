# Next Session: MemoryHub Dashboard — Memory Graph + Status Overview (#19)

## Goal

Build and deploy the first two panels of the MemoryHub landing page UI (Memory Graph + Status Overview) and register the OdhApplication tile in the RHOAI dashboard. By end of session: clicking the MemoryHub tile in RHOAI opens a PatternFly 6 app showing an interactive force-directed memory graph with scope coloring, plus headline metrics.

## What's deployed and working

- MCP server with RBAC enforcement on OpenShift (`mcp-server` in `memory-hub-mcp` namespace)
- OAuth 2.1 auth service (`auth-server` in `memoryhub-auth` namespace)
- PostgreSQL + pgvector in `memoryhub-db` namespace
- SDK v0.1.0 on PyPI with JWT auth — 8 integration tests passing
- 102 MCP tests, 106 core tests, 8 SDK integration tests — all passing
- RHOAI dashboard with OdhApplication CRD available on cluster

## Design references

- `docs/RHOAI-DEMO/README.md` — overview and index
- `docs/RHOAI-DEMO/landing-page-design.md` — 7-panel spec (updated for OAuth 2.1)
- `docs/RHOAI-DEMO/ui-architecture.md` — Option A: standalone PatternFly app + FastAPI BFF
- `docs/RHOAI-DEMO/odh-application-cr.md` — OdhApplication CR manifest

## Session scope

### Panel 2: Memory Graph (hero panel)

Interactive force-directed graph visualization of the memory landscape.

**Data:**
- Nodes: `memory_nodes WHERE is_current = true` — each node is a memory
- Edges: parent-child (from `parent_id`) + explicit relationships (from `memory_relationships`)

**Visual encoding:**
- Node color by scope: enterprise=red, organizational=blue, project=green, user=grey
- Node size by weight (higher weight = larger)
- Edge style by type: solid=parent-child, dashed=derived_from, dotted=related_to, red=conflicts_with
- Node click opens detail drawer with full content, metadata, version history

**Interactions:**
- Search input → pgvector similarity query → highlight matching nodes
- Filter sidebar: scope, owner, date range
- Zoom, pan, drag nodes

**Library:** Evaluate cytoscape.js vs d3-force vs vis.js. Cytoscape.js is the leading candidate (flexible layouts, good React integration, built-in event handling).

### Panel 1: Status Overview

Headline metrics in a card grid.

| Card | Data source |
|------|------------|
| Total memories | `COUNT(*) FROM memory_nodes WHERE is_current = true` |
| Memories by scope | `GROUP BY scope` → donut chart |
| Recent activity | `ORDER BY updated_at DESC LIMIT 10` → time feed |
| MCP server health | HTTP health check |

PatternFly components: `Card`, `Grid`, `ChartDonut`, `DescriptionList`.

### OdhApplication CR registration

Apply the CR from `docs/RHOAI-DEMO/odh-application-cr.md` to register the MemoryHub tile in the RHOAI dashboard. Update `#24` (getStartedMarkDown content) at the same time.

## Architecture (Option A from design doc)

```
RHOAI Dashboard
  └─ OdhApplication tile → memoryhub-ui Route
                                │
                    ┌───────────┴────────────┐
                    │   memoryhub-ui         │
                    │   React + PatternFly 6 │
                    │   (Vite, nginx on UBI) │
                    └───────────┬────────────┘
                                │ REST API
                    ┌───────────┴────────────┐
                    │   memoryhub-bff        │
                    │   FastAPI backend      │
                    │   (reads PostgreSQL    │
                    │    directly, not MCP)  │
                    └───────────┬────────────┘
                                │ SQLAlchemy
                    ┌───────────┴────────────┐
                    │   PostgreSQL + pgvector │
                    └────────────────────────┘
```

Both components deploy to the `memory-hub-mcp` namespace alongside the MCP server.

## Implementation plan

### 1. FastAPI BFF (`memoryhub-ui/backend/`)

REST API endpoints consumed by the React frontend:

```
GET  /api/graph          → nodes + edges for the memory graph
GET  /api/graph/search   → pgvector similarity search, returns matching node IDs
GET  /api/stats          → headline metrics (counts, scope distribution)
GET  /api/memory/{id}    → full memory detail for the drawer
GET  /api/memory/{id}/history → version history
GET  /healthz            → liveness probe
```

Uses `memoryhub-core` library for SQLAlchemy models (same as MCP server). Reads only — no writes through the UI in this session.

### 2. React frontend (`memoryhub-ui/frontend/`)

- Vite + React 18 + TypeScript
- PatternFly 6 (`@patternfly/react-core`, `@patternfly/react-charts`)
- Graph library (cytoscape.js or alternative from #21 evaluation)
- PatternFly `Page` layout with sidebar nav (panels 1+2, placeholders for 3-7)
- Memory detail drawer on node click

### 3. Containerization

Two containers:
- **Frontend:** Multi-stage build — node for building, nginx on UBI 9 for serving
- **Backend:** Python on UBI 9, same pattern as MCP server Containerfile

Or single container with FastAPI serving both the API and static files (simpler for demo).

### 4. OpenShift deployment

- Deployment, Service, Route in `memory-hub-mcp` namespace
- Route name: `memoryhub-ui` (referenced by OdhApplication CR)
- DB credentials from existing `memoryhub-db-credentials` Secret

### 5. OdhApplication CR

Apply the manifest from `docs/RHOAI-DEMO/odh-application-cr.md` with:
- Updated `getStartedMarkDown` content (#24)
- `routeNamespace: memory-hub-mcp`
- SVG icon (simple branded placeholder)

## What we're NOT building this session

- Panels 3-7 (Users/Agents, Curation Rules, Contradiction Log, Observability Links, Client Management) — placeholders only
- Write operations through the UI (all read-only)
- oauth-proxy sidecar for admin auth (defer to next session)
- Graph library evaluation (#21) — pick one and go; can swap later

## What comes after

- **#10 Grafana dashboards** — observability metrics, feeds Panel 6
- **Panels 3-7** — incremental additions to the landing page
- **oauth-proxy** for admin auth on the UI Route
- **#25 CLI client** — typer/click wrapper around the SDK
