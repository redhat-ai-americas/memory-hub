# Next Session: Memory Deletion and CLI Client

## Goal

Implement memory deletion (#42) and the CLI client (#25). By end of session: admins can delete memories from the dashboard, agents can delete via MCP tool, and a `memoryhub` CLI wraps the SDK for terminal use.

## What's deployed and working

- MCP server with RBAC enforcement (`mcp-server` in `memory-hub-mcp` namespace)
- OAuth 2.1 auth service with admin API (`auth-server` in `memoryhub-auth` namespace)
- PostgreSQL + pgvector in `memoryhub-db` namespace
- SDK v0.1.0 on PyPI with JWT auth
- **Dashboard with 6 panels** (`memoryhub-ui` in `memory-hub-mcp` namespace, build 31)
  - Memory Graph, Status Overview, Users & Agents, Client Management
  - Curation Rules (CRUD, detail modal with auto-generated summary, config explanations)
  - Contradiction Log (stats bar, filters, resolve/unresolve)
  - Observability panel still disabled (blocked on #10 Grafana)
- oauth-proxy sidecar, OdhApplication tile in RHOAI

## Session scope

### 1. Memory Deletion — MCP tool (#42)

Add `delete_memory` tool to the MCP server:
- Soft-delete: add `deleted_at` column to `memory_nodes`, filter from queries
- RBAC: only owner or `memory:admin` can delete
- Cascade: remove relationships, contradiction reports follow FK CASCADE
- Version chain: deleting current version marks entire chain as deleted
- Alembic migration for `deleted_at` column

### 2. Memory Deletion — Dashboard UI (#42)

Add delete capability to the memory detail drawer:
- "Delete" button with confirmation modal
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

## What we're NOT building this session

- Curation rule versioning (#40) — needs schema design
- Structured event logging (#41) — needs Grafana infrastructure (#10)
- Panel 6 Observability Links — blocked on #10
- Frontend component tests (#36) — separate effort
- Bulk deletion — future enhancement
- Trash/recycle bin UI — future, depends on soft-delete implementation

## Deployment notes

- **memoryhub-ui build context**: temp dir with physical copies of `memoryhub/` (pyproject.toml + src/memoryhub/), `backend/`, `frontend/`. Symlinks don't work with `oc start-build`.
- **Image pinning**: `oc set image deployment/memoryhub-ui memoryhub-ui=<full-digest>`
- **PF6 notes**: Label uses 'yellow' not 'gold'. No `--pf-v6-global--BackgroundColor--dark-100` variable. Sidebar overlays content below ~1200px (PF6 responsive breakpoint, by design).
