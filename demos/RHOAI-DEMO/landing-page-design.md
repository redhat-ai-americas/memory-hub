# Landing Page Design

The MemoryHub landing page serves as the entry point from the RHOAI
dashboard tile. It should communicate "platform-grade agent memory
governance" at a glance.

## Layout

PatternFly `Page` with a left nav sidebar and a main content area.
The sidebar provides navigation between the seven panels below. The default
view is the Memory Graph — the hero panel for the demo.

## Personas

Two primary audiences use this UI:

**Platform Admin** — Focused on operational health, curation policy oversight,
and a birds-eye view of the memory landscape across all agents and scopes.
Uses panels 1 (Status Overview), 2 (Memory Graph), 4 (Curation Rules),
5 (Contradiction Log), and 6 (Observability Links).

**Developer / Team Lead** — Focused on onboarding their agents, managing
OAuth clients, and understanding what their agents have stored. Uses panels 3
(Users and Agents), 7 (Client Management), and the Memory Graph filtered
to their agent's owner_id.

## Panels

### 1. Status Overview

High-level health and metrics at a glance.

| Element | Data source | Notes |
|---|---|---|
| MCP server health | HTTP health check against the MCP server pod | Green/red indicator |
| Total memories stored | `SELECT COUNT(*) FROM memory_nodes WHERE is_current = true` | Headline number |
| Active sessions | Kubernetes API — count of MCP server pods in Running state | Headline number |
| Memories by scope | `SELECT scope, COUNT(*) FROM memory_nodes WHERE is_current = true GROUP BY scope` | Donut chart |
| Contradiction rate | Curation rule trigger metadata (limited until `contradiction_reports` table exists — see Panel 5) | Trend sparkline |
| Recent activity | `SELECT * FROM memory_nodes ORDER BY updated_at DESC LIMIT N` | Time-ordered feed |

PatternFly components: `Card`, `Grid`, `ChartDonut`, `DescriptionList`.

### 2. Memory Graph (default view)

Interactive visualization of the memory landscape — the hero panel for
the demo and for understanding what agents are building and how memories
relate.

The graph is the default and primary view of this panel. It tells the story
of MemoryHub at a glance: nodes are memories, edges are the relationships
between them, and the structure reveals how agents reason and accumulate
knowledge over time.

#### Graph visualization

An interactive node-link diagram built from two data sources joined at
render time:

- **Nodes** — `memory_nodes` where `is_current = true`. Each node represents
  one active memory.
- **Edges** — two types:
  - Tree hierarchy: parent-child edges derived from `parent_id` adjacency list
  - Explicit relationships: edges from `memory_relationships` table
    (source_id → target_id with relationship_type)

**Node visual encoding:**
- Color by `scope` (matching the badge palette: enterprise = red,
  organizational = blue, project = green, user = grey)
- Size by `weight` (higher weight = larger node)
- Icon or shape by `branch_type` (main vs. rationale vs. provenance vs. evidence)

**Edge visual encoding:**
- Solid line — parent-child tree hierarchy
- Dashed line — `derived_from`
- Dotted line — `related_to`
- Red line — `conflicts_with`
- Orange line — `supersedes`

**Library candidates:** vis.js, cytoscape.js, or d3-force. These need
evaluation for PatternFly integration compatibility — vis.js has the
easiest setup; cytoscape.js is more flexible for custom layouts; d3-force
offers the most control but requires more implementation work. Pick based
on available time and PatternFly theming constraints.

#### Filter sidebar

A collapsible sidebar within the panel provides graph-level filtering:
- Owner (agent or user name — from `oauth_clients` table or `DISTINCT owner_id` from `memory_nodes`)
- Scope (enterprise / organizational / project / user)
- Date range (created_at or updated_at)
- Relationship type (filter which edge types are visible)
- Branch type (show only rationale branches, etc.)

Filters translate to SQL `WHERE` clauses against `memory_nodes` and
`memory_relationships` before the graph data is returned.

#### Node detail drawer

Clicking a node opens a right-side drawer showing:
- Full memory content
- Metadata: scope, weight, branch_type, owner_id, created_at, updated_at
- Version history: walk the `previous_version_id` chain to show prior versions
- Relationships: list entries from `memory_relationships` where this node
  is source or target

#### Search

A search input above the graph accepts a text query. The backend runs a
pgvector similarity query (`SELECT ... ORDER BY embedding <=> query_embedding`)
and returns matching node IDs. Matching nodes are highlighted/filtered in
the graph rather than shown in a separate list. This keeps search integrated
with the graph view rather than fragmenting the UI into two separate modes.

Data queries:
- Graph data: join `memory_nodes` with `memory_relationships`, filtered by
  sidebar selections
- Search: pgvector similarity query on `memory_nodes.embedding`
- Tree traversal: recursive CTE on `parent_id` for subtree expansion
- Version history: chain of `previous_version_id` lookups

PatternFly components: `SearchInput`, `Drawer`, `Label` (scope/weight badges),
`Toolbar` (filter sidebar trigger), `Spinner` (while graph loads).

### 3. Users and Agents

List the users and agents whose memories are being managed.

- Table populated from the `oauth_clients` table in the auth service
  database, joined with memory counts from `memory_nodes`. For
  deployments without the auth service, falls back to
  `SELECT DISTINCT owner_id FROM memory_nodes WHERE is_current = true`
- Columns: name, owner type (agent/user badge), use case, memory
  count (`SELECT COUNT(*) FROM memory_nodes WHERE owner_id = ? AND is_current = true`),
  last active
- Click through to filter the Memory Graph by that owner
- Agent vs. human distinction via `identity_type` column in
  `oauth_clients` (values: `user` or `service`)

PatternFly components: `Table`, `Label`, `Badge`.

### 4. Curation Rules

View and manage duplicate detection and quality rules.

- Table of rules from the `curator_rules` table: name, tier
  (regex/embedding), action (flag/block/quarantine/etc.), scope filter,
  priority, enabled status
- Query: `SELECT * FROM curator_rules ORDER BY priority DESC`
- Toggle enabled/disabled inline (UI writes back to `curator_rules.enabled`)
- Create new rule via modal form (INSERT into `curator_rules`)
- Show hit count per rule (roadmap — requires a trigger count column or
  separate tracking table)

PatternFly components: `Table`, `Switch`, `Modal`, `Form`,
`ToggleGroup` (for tier filter).

### 5. Contradiction Log

Reported contradictions between stored memories and observed behavior.

- Table: memory ID (linked), observed behavior, confidence, timestamp,
  contradiction count, whether revision was triggered
- Filter by resolution status
- Click through to the memory in the Memory Graph

**Current limitation:** There is no `contradiction_reports` table yet —
contradictions are tracked in-memory by the curation engine and are lost
on restart. A separate issue has been filed to add persistent contradiction
tracking. Until that table exists, this panel shows a placeholder state
with a note explaining the gap, and may surface limited data from
`curator_rules` trigger metadata where available.

PatternFly components: `Table`, `Label` (severity), `Toolbar` (filters),
`EmptyState` (placeholder until persistence is implemented).

### 6. Observability Links

Links to external dashboards for deeper operational insight.

- Grafana dashboard links (when built):
  - Memory volume and growth over time
  - Search latency (pgvector query performance)
  - Contradiction rate trends
  - Curation rule effectiveness
- OpenShift monitoring links (built-in metrics)
- MCP server logs (OpenShift console link)

PatternFly components: `Card`, `SimpleList` with external link icons.

### 7. Client Management (via OAuth 2.1 Auth Service)

Self-service provisioning and lifecycle management for OAuth clients,
backed by the MemoryHub auth service.

This panel turns the landing page into the onboarding point for new
agents and users — rather than an admin manually creating clients, teams
can provision their own through the UI.

#### How it works

The MemoryHub auth service manages OAuth clients in the `oauth_clients`
table. Each client has credentials for the `client_credentials` grant
flow, which exchanges the client_id/secret for a short-lived JWT.
The UI manages these clients via the auth service's admin API.

Each OAuth client has:

| Field | Description |
|-------|-------------|
| `client_id` | Unique identifier (e.g., `prod-curator-agent`) |
| `client_name` | Human-readable name |
| `identity_type` | `user` or `service` |
| `tenant_id` | Multi-tenant isolation key |
| `default_scopes` | Operational scopes (e.g., `memory:read`, `memory:write:user`) |
| `active` | Whether the client can obtain tokens |

When Authorino is deployed as defense-in-depth, it can additionally
validate JWTs at the infrastructure layer before requests reach the
MCP server. This is optional — the MCP server validates JWTs
independently via `_extract_jwt_from_headers()` in `core/authz.py`.

#### UI panel

- Table of registered clients, populated from `oauth_clients` table
  via the auth service admin API
- Columns: client_id, client_name, identity_type (user/service badge),
  scopes, tenant_id, active status, created date
- Create new client via modal:
  - **Client ID** — unique identifier (e.g., "prod-curator-agent")
  - **Client name** — human-readable description
  - **Identity type** — user or service (radio)
  - **Scopes** — checkboxes for operational scopes
  - Client secret is shown once on creation, then only the prefix is visible
- Deactivate: set `active = false` (tokens stop being issued)
- Rotate secret: generate new secret, invalidate old one

#### MCP server auth flow

The MCP server resolves caller identity via three paths in priority order:

1. FastMCP `get_access_token()` — when the auth middleware populates it
2. JWT from `Authorization` header — decoded directly via `_extract_jwt_from_headers()` in `core/authz.py`
3. Session fallback — `register_session` API key lookup for MCP clients that can't send HTTP headers

All authorization decisions use `authorize_read()` / `authorize_write()` from `core/authz.py`, which consume a normalized claims dict regardless of which path provided it.

#### Relationship to Users and Agents panel (Panel 3)

The `oauth_clients` table is the authoritative source for the
Users and Agents panel — querying it gives us the roster of all
registered identities. Memory counts per owner come from a filtered
COUNT query against `memory_nodes`.

PatternFly components: `Table`, `Modal`, `Form`, `ClipboardCopy`
(for the one-time key display), `Label` (status badges),
`Alert` (key-shown-once warning).

---

## Visual Design Notes

- Use Red Hat brand colors via PatternFly's default theme (no custom
  overrides needed — PatternFly ships with the Red Hat palette)
- Header should show "MemoryHub" with the same icon used in the
  OdhApplication tile
- Scope badges should use semantic colors: `enterprise` = red,
  `organizational` = blue, `project` = green, `user` = grey
- Keep the design information-dense — this is a platform admin tool,
  not a consumer product
- The UI backend queries PostgreSQL directly for all memory data. The
  MCP server is the agent-facing interface and is not involved in UI
  data access. Both the UI backend and MCP server read from the same
  database, but they serve different audiences.
