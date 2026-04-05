# Landing Page Design

The MemoryHub landing page serves as the entry point from the RHOAI
dashboard tile. It should communicate "platform-grade agent memory
governance" at a glance.

## Layout

PatternFly `Page` with a left nav sidebar and a main content area.
The sidebar provides navigation between the seven panels below. The default
view is the Status Overview.

## Panels

### 1. Status Overview (default view)

High-level health and metrics at a glance.

| Element | Data source | Notes |
|---|---|---|
| MCP server health | Health check endpoint | Green/red indicator |
| Total memories stored | `search_memory` total count | Headline number |
| Active sessions | Session tracking | Headline number |
| Memories by scope | Aggregate by scope (user/project/org/enterprise) | Donut chart |
| Contradiction rate | `report_contradiction` aggregates | Trend sparkline |
| Recent activity | Latest writes/updates | Time-ordered feed |

PatternFly components: `Card`, `Grid`, `ChartDonut`, `DescriptionList`.

### 2. Memory Browser

Search and explore the memory tree.

- Search bar backed by `search_memory` (semantic search via pgvector)
- Results show content stub, scope, weight, owner, relevance score
- Clicking a result expands via `read_memory` with depth, showing the
  branch structure (rationale, provenance, evidence, etc.)
- Version history available via `get_memory_history`
- Relationship links shown inline via `get_relationships`

PatternFly components: `SearchInput`, `DataList`, `TreeView`,
`ExpandableSection`, `Label` (for scope/weight badges).

### 3. Users and Agents

List the users and agents whose memories are being managed.

- Table populated from Authorino API key Secrets (label
  `memoryhub.redhat.com/key=true`) — this is the same data source
  as the API Key Management panel (Panel 7), giving us the owner
  roster without a custom MCP tool
- Columns: name, owner type (agent/user badge), use case, memory
  count (from `search_memory` filtered by owner), last active
- Click through to filter the Memory Browser by that owner
- Agent vs. human distinction via `memoryhub.redhat.com/owner-type`
  label on the Secret

PatternFly components: `Table`, `Label`, `Badge`.

### 4. Curation Rules

View and manage duplicate detection and quality rules.

- Table of rules from `set_curation_rule` data: name, tier
  (regex/embedding), action (flag/block/quarantine/etc.), scope filter,
  priority, enabled status
- Toggle enabled/disabled inline
- Create new rule via modal form
- Show hit count per rule (roadmap — requires tracking)

PatternFly components: `Table`, `Switch`, `Modal`, `Form`,
`ToggleGroup` (for tier filter).

### 5. Contradiction Log

Reported contradictions between stored memories and observed behavior.

- Table: memory ID (linked), observed behavior, confidence, timestamp,
  contradiction count, whether revision was triggered
- Filter by resolution status
- Click through to the memory in the Memory Browser

PatternFly components: `Table`, `Label` (severity), `Toolbar` (filters).

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

Authorino validates incoming requests against these Secrets before
they reach the MCP server. On successful auth, Authorino injects
identity headers (e.g., `X-Auth-Owner-Name`, `X-Auth-Owner-Type`)
that the MCP server can trust without re-validating.

#### AuthConfig

An Authorino `AuthConfig` CR defines the auth policy for the MCP
server Route:

```yaml
apiVersion: authorino.kuadrant.io/v1beta3
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
            value: auth.identity.metadata.annotations.memoryhub\.redhat\.com/owner-name
        x-auth-owner-type:
          plain:
            value: auth.identity.metadata.annotations.memoryhub\.redhat\.com/owner-type
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

Minimal. The MCP server's `register_session` no longer validates the
API key itself — Authorino already did that. Instead, `register_session`
reads the identity from the headers Authorino injected:

```python
# Before: server validates key
api_key = request.headers["Authorization"]
user = validate_key(api_key)  # custom code

# After: Authorino validated, server trusts headers
owner_name = request.headers["X-Auth-Owner-Name"]
owner_type = request.headers["X-Auth-Owner-Type"]
```

This removes auth logic from the MCP server entirely and pushes it
to the infrastructure layer where it belongs.

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
`list_agents` MCP tool; it queries the same Kubernetes Secrets
that Authorino uses. Memory counts per owner would still come
from the MCP server (via `search_memory` filtered by owner), but
the owner list itself comes from the key registry.

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
