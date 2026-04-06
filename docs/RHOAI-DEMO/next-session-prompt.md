# Next Session: Memory Deletion and CLI Client

## Goal

Implement memory deletion (#42) and the CLI client (#25). By end of session: admins can delete memories from the dashboard, agents can delete via MCP tool, and a `memoryhub` CLI wraps the SDK for terminal use.

## What's deployed and working

- MCP server with RBAC enforcement (`mcp-server` in `memory-hub-mcp` namespace)
- OAuth 2.1 auth service with admin API (`auth-server` in `memoryhub-auth` namespace)
  - POST /token, /.well-known/*, /healthz
  - GET/POST/PATCH /admin/clients, POST /admin/clients/{id}/rotate-secret (X-Admin-Key protected)
- PostgreSQL + pgvector in `memoryhub-db` namespace
- SDK v0.1.0 on PyPI with JWT auth
- **Dashboard with 6 panels** (`memoryhub-ui` in `memory-hub-mcp` namespace, build 31)
  - Memory Graph (cytoscape.js/fcose, scope coloring, edge click, search, owner filter)
  - Status Overview (counts, donut chart, activity feed, MCP health)
  - Users & Agents (auth + DB merge, click-to-filter graph)
  - Client Management (create/deactivate/rotate-secret with one-time secret modal)
  - Curation Rules (CRUD, inline enable/disable Switch, detail modal with auto-generated rule summary + config explanations, tier+enabled filters)
  - Contradiction Log (stats bar, resolution+confidence filters, resolve/unresolve, EmptyState)
  - Observability panel still disabled (blocked on #10 Grafana)
- oauth-proxy sidecar (port 8443, reencrypt TLS, OpenShift login required)
- OdhApplication tile registered in RHOAI
- `noCache: true` on all BuildConfigs

## Design references

- `docs/RHOAI-DEMO/next-session.md` — detailed session scope
- `docs/memory-tree.md` — memory lifecycle and tree structure
- `docs/governance.md` — access control and authorization policies
- `src/memoryhub/models/memory.py` — MemoryNode SQLAlchemy model
- `memoryhub-ui/backend/src/routes.py` — existing BFF routes (16+ handlers)
- `memoryhub-ui/frontend/src/components/MemoryDetailDrawer.tsx` — where delete button goes

## Session scope

### 1. Memory Deletion — MCP tool (#42)

Add `delete_memory` tool to the MCP server:
- Soft-delete: add `deleted_at` column to `memory_nodes`, filter from all queries
- RBAC: only owner or `memory:admin` can delete
- Cascade: remove relationships, contradiction reports follow FK CASCADE
- Version chain: deleting current version marks entire chain as deleted
- Alembic migration for `deleted_at` column

### 2. Memory Deletion — Dashboard UI (#42)

Add delete capability to the memory detail drawer:
- "Delete" button with confirmation modal in MemoryDetailDrawer
- BFF endpoint: `DELETE /api/memory/{id}`
- Refresh graph after deletion
- Filter deleted memories from graph/search/stats queries

### 3. CLI Client (#25)

Create `memoryhub-cli/` with typer/click:
- `memoryhub login` — obtain JWT token via client_credentials
- `memoryhub search <query>` — search memories
- `memoryhub read <id>` — read a memory
- `memoryhub write <content>` — write a memory
- `memoryhub delete <id>` — delete a memory
- `memoryhub history <id>` — version history
- Uses the SDK (`memoryhub` PyPI package) under the hood
- Publish as `memoryhub-cli` on PyPI or as `memoryhub[cli]` extra

## Deployment notes

- **Build context**: Must include `memoryhub/` from repo root (contains SQLAlchemy models). Use temp dir with physical copies (symlinks don't work with `oc start-build`). The `memoryhub/` dir needs `pyproject.toml` at its root and `src/memoryhub/` inside.
- **Image pinning**: After build, use `oc set image deployment/memoryhub-ui memoryhub-ui=<full-digest>` to force the new image (ImageStream caching issue).
- **Secrets**: Don't put mutable Secrets in openshift.yaml manifests — `oc apply` clobbers them.
- **oauth-proxy**: Port 8443 HTTPS, cookie-secret must be 16/24/32 bytes exactly.
- **PF6 notes**: Label uses 'yellow' not 'gold'. No `--pf-v6-global--BackgroundColor--dark-100` CSS variable. Sidebar overlays content below ~1200px (`xl` breakpoint) — this is PF6 by-design, don't try to fix it.

## What we're NOT building this session

- Curation rule versioning (#40) — needs schema design
- Structured event logging (#41) — needs Grafana infrastructure (#10)
- Panel 6 Observability Links — blocked on #10
- Frontend component tests (#36) — separate effort
- Backend route tests (#43) — separate effort
- Bulk deletion — future enhancement
- Trash/recycle bin UI — future, depends on soft-delete implementation

## What comes after

- **#40** — Curation rule versioning and edit tracking
- **#41** — Structured event logging and memory usage tracking
- **#44** — Local dev server for frontend (would save ~3 min per UI iteration)
- **#36** — Frontend component tests
- **#43** — Backend route tests for BFF
- **Panel 6** — Observability Links (depends on #10 Grafana dashboards)
- **RBAC on admin API** — restrict client management to specific users/groups
