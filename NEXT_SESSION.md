# Next Session: Curation Rules (Panel 4) and Contradiction Log (Panel 5)

## Goal

Add the remaining admin panels to the MemoryHub dashboard: Curation Rules management (Panel 4) and Contradiction Log (Panel 5). By end of session: admins can view/create/toggle curation rules and browse contradiction reports with resolution tracking.

## What's deployed and working

- MCP server with RBAC enforcement (`mcp-server` in `memory-hub-mcp` namespace)
- OAuth 2.1 auth service with admin API (`auth-server` in `memoryhub-auth` namespace)
  - POST /token, /.well-known/*, /healthz
  - GET/POST/PATCH /admin/clients, POST /admin/clients/{id}/rotate-secret (X-Admin-Key protected)
- PostgreSQL + pgvector in `memoryhub-db` namespace
- SDK v0.1.0 on PyPI with JWT auth
- **Dashboard with 4 panels** (`memoryhub-ui` in `memory-hub-mcp` namespace)
  - Memory Graph (cytoscape.js/fcose, scope coloring, edge click, search, owner filter)
  - Status Overview (counts, donut chart, activity feed, MCP health)
  - Users & Agents (auth + DB merge, click-to-filter graph)
  - Client Management (create/deactivate/rotate-secret with one-time secret modal)
- oauth-proxy sidecar (port 8443, reencrypt TLS, OpenShift login required)
- OdhApplication tile registered in RHOAI
- `noCache: true` on all BuildConfigs

## Design references

- `docs/RHOAI-DEMO/landing-page-design.md` — Panels 4 and 5 specs
- `docs/RHOAI-DEMO/ui-architecture.md` — data architecture
- `docs/curator-agent.md` — curation rule layers, actions, evaluation order
- `src/memoryhub/models/curation.py` — CuratorRule SQLAlchemy model
- `src/memoryhub/models/contradiction.py` — ContradictionReport SQLAlchemy model
- `src/memoryhub/models/schemas.py` — CuratorRuleCreate, CuratorRuleRead Pydantic schemas

## Database state

Both tables exist and are migrated:
- `curator_rules` — migration 004
- `contradiction_reports` — migration 005

## Existing MCP tools

- `set_curation_rule` — creates/updates user-layer rules (tier, action, config, scope_filter, priority)
- `report_contradiction` — records contradiction against a memory (observed_behavior, confidence)

## Session scope

### 1. BFF endpoints for Curation Rules (Panel 4)

Add to `memoryhub-ui/backend/src/routes.py`:

```
GET    /api/rules              → list all curation rules (from curator_rules table)
POST   /api/rules              → create a new rule
GET    /api/rules/{rule_id}    → get rule detail
PATCH  /api/rules/{rule_id}    → update (toggle enabled, change priority, etc.)
DELETE /api/rules/{rule_id}    → delete a rule
```

These query the DB directly (same pattern as /api/graph, /api/stats — the BFF shares the PostgreSQL database).

**CuratorRule model** (already in `src/memoryhub/models/curation.py`):
- id (UUID PK), name (unique per layer/owner_id), description, trigger, tier (regex/embedding)
- config (JSON), action (block/quarantine/flag/reject_with_pointer/merge/decay_weight)
- scope_filter, layer (system/organizational/user), owner_id, override (bool)
- enabled (bool), priority (int, lower = first), created_at, updated_at

### 2. BFF endpoints for Contradiction Log (Panel 5)

```
GET    /api/contradictions                     → list all contradiction reports (with filters)
PATCH  /api/contradictions/{id}                → mark as resolved
GET    /api/contradictions/stats               → summary counts (total, unresolved, by confidence range)
```

**ContradictionReport model** (already in `src/memoryhub/models/contradiction.py`):
- id (UUID PK), memory_id (FK → memory_nodes), observed_behavior (text)
- confidence (float 0-1), reporter (str), created_at
- resolved (bool), resolved_at (datetime | None)

### 3. Panel 4: Curation Rules (frontend)

**Table columns:** name, tier (regex/embedding badge), action (badge), scope filter, layer, priority, enabled (Switch toggle), created date

**Actions:**
- Toggle enabled/disabled inline via Switch component (PATCH)
- Create new rule via modal: name, description, tier radio, action dropdown, scope_filter, priority, config JSON editor
- Delete rule (with confirmation)

**Filters:**
- ToggleGroup for tier (All / Regex / Embedding)
- Toggle for enabled status (All / Enabled / Disabled)

### 4. Panel 5: Contradiction Log (frontend)

**Table columns:** memory ID (truncated, linked), observed behavior (truncated), confidence (color-coded label), reporter, created date, resolved status

**Actions:**
- Mark as resolved (button or toggle)
- Click memory ID to navigate to Memory Graph with that node selected

**Filters:**
- Resolution status (All / Unresolved / Resolved)
- Confidence range (High >0.8 / Medium 0.5-0.8 / Low <0.5)

**Empty state:** If no contradictions exist, show PatternFly EmptyState with explanation.

### 5. Wire into App.tsx

- Enable "Curation Rules" and "Contradictions" nav items
- Extend ActivePanel type with `'rules' | 'contradictions'`

## Architecture

```
memoryhub-ui :8080
  │
  ├─ /api/rules/*            → Direct SQL to curator_rules table
  ├─ /api/contradictions/*   → Direct SQL to contradiction_reports table
  ├─ /api/graph, /api/stats  → Direct SQL to memory_nodes (existing)
  └─ /api/clients, /api/users → Proxy to auth-server :8081 (existing)
```

Both new endpoints read/write the shared PostgreSQL database directly — no proxy to other services needed.

## Implementation plan

### Step 1: Pydantic schemas for rules and contradictions

Add to `memoryhub-ui/backend/src/schemas.py`:
- CurationRuleResponse, CreateRuleRequest, UpdateRuleRequest
- ContradictionResponse, ContradictionStatsResponse, UpdateContradictionRequest

### Step 2: BFF routes

Add to `memoryhub-ui/backend/src/routes.py`:
- Curation rules CRUD (5 endpoints)
- Contradiction log (3 endpoints)
- Import CuratorRule and ContradictionReport from `memoryhub.models`

### Step 3: Frontend types and API client

- TypeScript interfaces for rules and contradictions
- API client functions (fetchRules, createRule, updateRule, deleteRule, fetchContradictions, etc.)

### Step 4: React components

- `CurationRules.tsx` — Table with inline toggle, create modal, delete confirmation, tier filter
- `ContradictionLog.tsx` — Table with resolution filter, confidence badges, empty state
- Wire into `App.tsx`

### Step 5: Deploy and verify

- Rebuild memoryhub-ui (same build context pattern: temp dir with memoryhub/ + backend/ + frontend/)
- Verify panels render with data

## Deployment notes

- **Build context**: Must include `memoryhub/` from repo root (contains SQLAlchemy models). Use temp dir with physical copies (symlinks don't work with `oc start-build`).
- **Image pinning**: After build, use `oc set image deployment/memoryhub-ui memoryhub-ui=<full-digest>` to force the new image (ImageStream caching issue).
- **Secrets**: Don't put mutable Secrets in openshift.yaml manifests — `oc apply` clobbers them.
- **oauth-proxy**: Port 8443 HTTPS, cookie-secret must be 16/24/32 bytes exactly.

## What we're NOT building this session

- Panel 6 (Observability Links) — blocked on Grafana dashboards (#10)
- Rule hit count tracking (requires trigger count column or separate table)
- Bulk operations on contradictions
- Curation rule evaluation engine changes

## What comes after

- **Panel 6** — Observability Links (depends on #10 Grafana dashboards)
- **#25 CLI client** — typer/click wrapper around the SDK
- **#36 Frontend component tests** — Vitest + React Testing Library
- **RBAC on admin API** — restrict client management to specific users/groups
- **Rule hit tracking** — counter per curation rule for operational visibility
