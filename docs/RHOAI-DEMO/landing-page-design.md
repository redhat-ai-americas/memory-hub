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
API keys, and understanding what their agents have stored. Uses panels 3
(Users and Agents), 7 (API Key Management), and the Memory Graph filtered
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
- Owner (agent or user name — from Authorino Secrets, same source as Panel 3)
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

- Table populated from Authorino API key Secrets (label
  `memoryhub.redhat.com/key=true`) — this is the same data source
  as the API Key Management panel (Panel 7), giving us the owner
  roster without a custom MCP tool
- Columns: name, owner type (agent/user badge), use case, memory
  count (`SELECT COUNT(*) FROM memory_nodes WHERE owner_id = ? AND is_current = true`),
  last active
- Click through to filter the Memory Graph by that owner
- Agent vs. human distinction via `memoryhub.redhat.com/owner-type`
  label on the Secret

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

### 7. API Key Management (via Authorino)

Self-service provisioning and lifecycle management for API keys, backed
by the Authorino operator.

This panel turns the landing page into the onboarding point for new
agents and users — rather than an admin manually creating keys, teams
can provision their own through the UI.

#### How it works

Authorino manages API keys as **labeled Kubernetes Secrets** in the
MemoryHub namespace. The landing page UI creates and lists these Secrets
via the Kubernetes API — no custom key management code in MemoryHub
itself.

Each API key Secret carries labels and annotations for metadata:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: memoryhub-key-prod-curator
  namespace: memoryhub
  labels:
    authorino.kuadrant.io/managed-by: authorino
    memoryhub.redhat.com/key: "true"
    memoryhub.redhat.com/owner-type: agent        # or "user"
  annotations:
    memoryhub.redhat.com/owner-name: "prod-curator-agent"
    memoryhub.redhat.com/use-case: "Production curation pipeline"
    memoryhub.redhat.com/created-by: "wjackson"
type: Opaque
data:
  api_key: <base64-encoded key>
```

When Authorino is deployed as defense-in-depth, it validates incoming requests against these Secrets before they reach the MCP server, injecting identity headers (`X-Auth-Owner-Name`, `X-Auth-Owner-Type`). However, the primary auth mechanism is the OAuth 2.1 authorization service — agents exchange API keys for short-lived JWTs via the `client_credentials` grant, and the MCP server validates JWTs independently via FastMCP's `JWTVerifier`. See [governance.md](../governance.md) for the full auth architecture.

#### AuthConfig

An Authorino `AuthConfig` CR defines the auth policy for the MCP
server Route:

```yaml
apiVersion: authorino.kuadrant.io/v1beta2
kind: AuthConfig
metadata:
  name: memoryhub-api
  namespace: memoryhub
spec:
  hosts:
    - memoryhub-mcp.apps.<cluster-domain>
  authentication:
    api-key:
      apiKey:
        selector:
          matchLabels:
            memoryhub.redhat.com/key: "true"
      credentials:
        authorizationHeader:
          prefix: Bearer
  response:
    success:
      headers:
        x-auth-owner-name:
          plain:
            selector: auth.identity.metadata.annotations.memoryhub\.redhat\.com/owner-name
        x-auth-owner-type:
          plain:
            selector: auth.identity.metadata.annotations.memoryhub\.redhat\.com/owner-type
```

#### UI panel

- Table of issued API keys, populated by listing Secrets with label
  `memoryhub.redhat.com/key=true` via the Kubernetes API
- Columns: name/label, owner type (agent/user), owner name, use case,
  created date, status (active/revoked annotation)
- Create new key via modal:
  - **Name/label** — human-readable identifier (e.g., "prod-curator-agent")
  - **Owner type** — user or agent (radio)
  - **Owner name** — who or what will use this key
  - **Use case** — free-text description of intended purpose
  - Key is shown once on creation, then only the prefix is visible
- Revoke: delete the Secret (Authorino stops accepting the key immediately)
- Rotate: create new Secret with same metadata, delete old one

#### MCP server changes

The MCP server validates JWTs using FastMCP's `JWTVerifier` at the transport layer. Tools access the authenticated identity via `get_access_token()`:

```python
from fastmcp.server.dependencies import get_access_token

@mcp.tool
async def search_memory(query: str, ...) -> dict:
    token = get_access_token()
    user_id = token.claims["sub"]
    tenant_id = token.claims["tenant_id"]
    # All queries filtered by tenant_id + scope authorization
```

The `register_session` tool is retained as a compatibility shim for MCP clients that cannot send HTTP Authorization headers. It is not the primary auth path.

#### Future direction: one agent, one key

A future policy option would enforce a 1:1 mapping between agent
identity and API key. With Authorino, this becomes an authorization
rule in the AuthConfig — e.g., a Rego policy or JSON pattern that
checks whether an owner already has an active key before allowing
a new one. The constraint lives in Authorino policy, not in
application code.

#### Relationship to Users and Agents panel (Panel 3)

The API key Secrets are also the authoritative source for the
Users and Agents panel — listing Secrets with the
`memoryhub.redhat.com/key` label gives us the roster of all
registered owners. This means Panel 3 doesn't need a separate
owner list endpoint; it queries the same Kubernetes Secrets
that Authorino uses. Memory counts per owner come from a filtered
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
