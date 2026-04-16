# UI Design

## Purpose and Audience

The MemoryHub dashboard is an operator-facing admin tool. Its primary users are platform engineers and AI-system maintainers who need to inspect the memory graph, manage contributors, configure guardrails, and handle OAuth clients. Operators are expected to understand the MemoryHub data model (scopes, branches, weights, curation rules).

The dashboard is NOT a memory-writing tool. Agents write and update memories through the MCP server; the UI surfaces what exists and provides administrative controls over it. There is no editor for memory content.

Operators should be able to perform these tasks without touching the database or API directly:
- Visualize the current state of the memory graph
- Investigate individual memories and their relationships
- Manage who has access and at what permission level
- Configure and tune curation rules
- Review and resolve contradiction reports

## Views

### Inventory

| Panel | Purpose | Key Actions | Status |
|---|---|---|---|
| Memory Graph | Visualize all memories and relationships as an interactive graph | Search, filter by scope/owner, click to open detail drawer | Shipped |
| Status Overview | At-a-glance health summary | Read-only stats dashboard, no actions | Shipped |
| Users & Agents | Roster of all memory owners | Cross-navigate to graph filtered by owner | Shipped |
| Curation Rules | Manage server-side guardrails | Create, enable/disable, delete rules; view detail | Shipped |
| Contradictions | Review agent-reported contradictions | Filter by confidence/resolution, mark resolved | Shipped |
| Observability | Metrics and logs (placeholder) | None | Stub (disabled) |
| Client Management | OAuth 2.1 client lifecycle | Create clients, rotate secrets, activate/deactivate | Shipped |

Navigation is a single-level left sidebar (`PageSidebar` with `NavList`). There is no routing library; the active view is managed via `activePanel` state in `App.tsx`. The Observability item is rendered at 45% opacity with `pointer-events: none` and `aria-disabled`.

### Memory Graph

The primary landing view. It renders the full set of active memories as a force-directed graph using `react-cytoscapejs` with the `cytoscape-fcose` layout algorithm. Archived and deleted memories do not appear.

**Node semantics**

Each node represents one memory at its current version. The node is colored by scope and sized by weight:

| Scope | Graph node color | Badge color |
|---|---|---|
| enterprise | `#C9190B` (red) | PatternFly `red` |
| organizational | `#0066CC` (blue) | PatternFly `blue` |
| project | `#3E8635` (green) | PatternFly `green` |
| user | `#6A6E73` (grey) | PatternFly `grey` |

Node diameter is `20 + weight * 30` pixels. A memory with weight 1.0 renders at 50px; one with weight 0.0 renders at 20px.

Node labels are the memory `stub` truncated to 60 characters with a trailing ellipsis. Labels render below the node at 10px font size.

**Edge semantics**

| Relationship type | Style | Color |
|---|---|---|
| `parent_child` | Solid line, arrowhead | `#6A6E73` grey |
| `derived_from` | Dashed line, arrowhead | `#0066CC` blue |
| `related_to` | Dotted line, no arrowhead | `#B8BBBE` light grey |
| `conflicts_with` | Solid line, arrowhead | `#C9190B` red |
| `supersedes` | Dashed line, arrowhead | `#EC7A08` orange |

Selected edges get a `#F0AB00` gold line color. Selected nodes get a `#151515` (near-black) border. Search-matched nodes receive a 4px `#F0AB00` gold border via the `highlighted` CSS class.

**Interaction model**

- Click a node: opens the Memory Detail Drawer for that memory.
- Click an edge: opens the Memory Detail Drawer in relationship mode, showing both endpoint summaries.
- Click the canvas background: closes the drawer.
- Toolbar: text search (`Enter` or button submit), scope filter checkboxes (one per scope), owner filter text input, Refresh button.
- Search highlights matching nodes in gold without removing others from the canvas. Clearing the search removes all highlights.
- Owner filter is a substring match against `owner_id`. Cross-panel navigation from Users & Agents pre-populates this field.
- Scope filter checkboxes are all checked by default; unchecking a scope removes those nodes from the rendered graph and triggers a layout re-run.

The graph re-runs fcose layout whenever the filtered element set changes. Between filter changes the layout is frozen (`preset`) so panning and zooming are preserved.

**Canvas background**

The graph canvas uses a dot-grid background (`radial-gradient` 20px dot pattern on `#fafafa`) to suggest a canvas/diagram context.

### Memory Detail Drawer

A right-side `Drawer` at 33% page width (`widths={{ default: 'width_33' }}`), opened by clicking graph nodes or edges. The graph canvas remains interactive while the drawer is open.

**Node mode (clicking a memory)**

The drawer title is the memory `stub`. The `ScopeBadge` appears in the header. If `is_current` is false, an orange "archived" `Label` appears alongside the scope badge.

A danger "Delete" button is always present in the drawer header for node mode (not for edge mode). It opens a confirmation modal.

Sections, in order:

| Section | Display |
|---|---|
| Content | Memory text in a monospace `pre` block with `#BackgroundColor--200` background |
| Details | `DescriptionList` (compact, horizontal) with the fields below |
| Metadata | `DescriptionList` of arbitrary key/value pairs; only shown when metadata is non-empty |
| Relationships | Stack of relationship links; only shown when relationships exist |
| Version History | Collapsible `ExpandableSection`; only shown when history entries exist |

**Details fields**

| Field | Rendering |
|---|---|
| Owner | Plain text (`owner_id`) |
| Weight | `toFixed(2)` — always two decimal places |
| Version | Integer version number |
| Branch Type | Blue `Label` (isCompact); row hidden when null |
| Parent ID | `<code>` element at 0.75rem; row hidden when null |
| Children | Integer count |
| Created | `formatDate()` — browser `toLocaleString()` |
| Updated | `formatDate()` — browser `toLocaleString()` |
| Expires | `formatDate()`; row hidden when null |

**Relationships**

Each relationship is a row with: a colored `Label` for the type (using `EDGE_TYPE_COLORS`), a direction arrow (`→` for source, `←` for target), and a link button showing the first 8 characters of the other memory's ID. Clicking the link switches the drawer to show that memory.

**Version history**

Each version entry shows: a `Label` (green for current, grey for past) with the version number, the stub text, and a relative timestamp (`formatRelativeTime` — `Xd ago`, `Xh ago`, `Xm ago`, `just now`). The current version has a `#BackgroundColor--200` background highlight.

**Edge mode (clicking a relationship)**

The drawer title is "Relationship". The header shows a colored `Label` for the relationship type with its human-readable description from `EDGE_TYPE_DESCRIPTIONS`:

| Type | Description shown |
|---|---|
| `parent_child` | "Parent → Child: This memory is a branch (rationale, provenance, etc.) of its parent." |
| `derived_from` | "Derived From: This memory was created based on information from the other." |
| `related_to` | "Related To: These memories cover related topics." |
| `conflicts_with` | "Conflicts With: These memories contain contradictory information." |
| `supersedes` | "Supersedes: The newer memory replaces or updates the older one." |

Below the description, source and target are rendered as compact clickable `Card` components. Each card shows the stub (as a link button that re-selects that node), scope badge, a truncated content preview (max 120px height, overflow hidden), and owner/weight metadata. The arrow between cards is an `ArrowRightIcon` rotated 90 degrees.

**Delete confirmation modal**

Variant `small`. Body copy: "This will soft-delete this memory and all versions in its chain. Deleted memories are excluded from search and graph views." The stub is shown below the prose in muted small text. After deletion, the drawer closes and the graph reloads. If deletion fails, an inline danger `Alert` appears inside the modal without closing it.

### Status Overview

A 2-column `Grid` with four `Card` components. Read-only; no actions.

- **Total Memories**: Large (`3.5rem`, `700` weight) count in primary blue. Subtitle line lists the per-scope breakdown (e.g. "12 user, 4 project").
- **Memories by Scope**: `ChartDonut` (180×180px, `innerRadius=55`) with scope colors from `SCOPE_COLORS`. Legend is a side stack of `ScopeBadge` + count + percentage.
- **Recent Activity**: Up to 10 entries. Each row: `ScopeBadge`, truncated stub (ellipsis, `title` attribute carries the full text), relative timestamp. No click interaction.
- **MCP Server Health**: `CheckCircleIcon` (green) or `ExclamationCircleIcon` (red) with status text. Unhealthy state shows "MCP server is not responding — check deployment logs".

### Users & Agents

A compact `Table` with columns: Name, Type, Owner ID, Memories (count), Last Active, action button.

- Type label colors: `service` → blue, `user` → grey, anything else → orange.
- Owner ID renders as `<code>`.
- Memory count is `toLocaleString()` formatted.
- Last Active uses `formatRelativeTime()`; shows "Never" when null.
- Rows are sorted by `memory_count` descending on load.
- The entire row is clickable when `onNavigateToGraph` is provided. The "View Memories" link button in the last column also triggers navigation (with `stopPropagation` to avoid double-firing).

Cross-panel navigation sets the owner filter in the Memory Graph and switches to that panel. The graph panel's `initialOwnerFilter` prop accepts the `owner_id` string.

The panel header subtitle reads: "Registered OAuth clients and memory owners. Click 'View Memories' to see an owner's memories in the graph."

### Curation Rules

A compact `Table` with tier and enabled/disabled filter `ToggleGroup` controls and a "Create Rule" primary button.

**Table columns**: Name (link to detail modal), Tier (label: `regex`=blue, `embedding`=purple), Action (label colored by `ACTION_COLORS`), Layer, Priority, Enabled (inline `Switch`), Actions (Delete link).

`ACTION_COLORS` mapping:

| Action | Label color |
|---|---|
| block | red |
| quarantine | orange |
| flag | yellow |
| reject_with_pointer | red |
| merge | blue |
| decay_weight | grey |

**Detail modal** (medium variant): The first element is an auto-generated prose summary from `describeRule()`, rendered in a styled block with a left border accent and italic text. Format: "[Trigger sentence], [tier sentence]. If matched, [action sentence]." Below that, a `describeConfig()` call adds a human-readable config summary if one applies (e.g. threshold percentages, pattern set descriptions). Raw config JSON is always shown in a `<pre>` block.

**Create modal** (medium variant): Fields are Name (required), Description, Tier (radio), Action (select), Trigger (select), Scope Filter (text), Layer (select), Priority (`NumberInput`), Config (JSON `TextArea`). The config field accepts raw JSON; invalid JSON is caught client-side and shown as a validation error before submission.

**Delete confirmation modal** (small variant): Body reads "Are you sure you want to delete rule [name]? This action cannot be undone." No additional context shown. Primary button is `variant="danger"`.

The panel header subtitle reads: "Server-side guardrails that run automatically when memories are written or read. Agents cannot see or bypass these rules."

### Contradictions

A compact `Table` with resolution and confidence filter `ToggleGroup` controls. A stats bar (`Label` row) at the top shows total, unresolved, high-confidence, and medium-confidence counts.

When no contradiction reports exist at all, the view renders a PatternFly `EmptyState` with `CheckCircleIcon` and `status="success"`.

**Table columns**: Memory ID (8-char truncated, link button), Observed Behavior (80-char truncated with `title` attribute on the `Td`), Confidence (colored label), Reporter, Created, Status, Action.

Confidence label colors:
- `> 0.8` → red
- `>= 0.5 and <= 0.8` → yellow
- `< 0.5` → green

The confidence color convention is inverted from intuition: high confidence in a contradiction is the alarming case, so red = high.

Status label: resolved → green, unresolved → orange.

Action button: resolved rows show a `variant="link"` "Unresolve" button; unresolved rows show a `variant="secondary"` "Resolve" button. The toggle is immediate (no confirmation modal).

Memory ID link buttons navigate to the Memory Graph panel (current implementation navigates to graph without highlighting the specific node; future work).

The panel subtitle reads: "Reports from agents that observed behavior conflicting with a stored memory. High contradiction counts may trigger memory revision."

### Client Management

A compact `Table` with a "Create Client" primary button.

**Table columns**: Client ID (`<code>`), Name, Type (label: service=blue, user=grey), Scopes (comma-joined plain small text), Tenant, Status (active=green, inactive=red), Created, Actions.

Row actions: "Activate"/"Deactivate" (`variant="secondary"`) and "Rotate Secret" (`variant="warning"`). Both are inline in a `Flex` row.

**Create modal** (medium variant): Fields are Client ID (required), Client Name (required), Identity Type (select: user/service), Tenant ID (required), Scopes (checkboxes). The button is disabled until the Name field is non-empty.

Available scopes: `memory:read`, `memory:write:user`, `memory:write`, `memory:admin`.

**SecretRevealModal**: Shown immediately after create or rotate-secret. Contains two `ClipboardCopy` blocks (both `ClipboardCopyVariant.expansion`):
1. The raw client secret, with a warning `Alert` ("Copy the secret now — it will not be shown again."). `hoverTip="Copy secret"`, `clickTip="Copied"`.
2. A pre-rendered welcome email body (from `renderWelcomeEmail()` in `welcomeEmail.ts`), marked `isExpanded` and `isCode`. `hoverTip="Copy email body"`, `clickTip="Copied"`. The email body includes the client ID, secret, tenant, scopes, MCP URL, and auth URL.

If `/api/public-config` fails on load, the welcome email falls back to `mcp-server.example.com` and `auth-server.example.com` placeholder URLs. This failure is logged as a console warning and does not surface as a UI error.

The panel subtitle reads: "Manage OAuth 2.1 clients that authenticate agents and services to MemoryHub."

## Information Architecture

### Navigation model

Navigation is flat: one level, no sub-navigation, no breadcrumbs. All six active panels are peers in the left sidebar. The sidebar can be toggled via the masthead hamburger button (`BarsIcon`). Default landing panel is Memory Graph.

### Cross-panel navigation

Two cross-panel navigations exist:

1. **Users & Agents → Memory Graph**: Clicking "View Memories" or any table row sets the Memory Graph's owner filter to that row's `owner_id` and switches the active panel. Implemented via `handleNavigateToGraph(ownerId)` in `App.tsx`, which sets `graphOwnerFilter` state and `activePanel = 'graph'`.

2. **Contradictions → Memory Graph**: Clicking a Memory ID link calls `handleNavigateToMemory(memoryId)`. Currently this clears the owner filter and switches to the graph without targeting the specific node. The `memory_id` parameter is accepted but not yet acted on in the graph.

No other cross-panel navigation exists. The Memory Detail Drawer's relationship links navigate within the drawer (switching which node is selected), not between panels.

## Affordance Conventions

### Help Text Hierarchy

The current codebase uses this hierarchy, from lowest to highest cost to the user:

1. **Subtitle copy** — `Content component="small"` with `color: var(--pf-v6-global--Color--200)` immediately below a panel heading. Used for panel-level orientation. Present in Users & Agents, Curation Rules, Contradictions, and Client Management.

2. **Native `title` attribute** — On `Td` cells and `Content` elements where text is truncated. Hovering shows the full value without any component overhead. Used in Status Overview recent activity and Contradictions observed behavior column.

3. **`ClipboardCopy` hover/click tips** — `hoverTip` and `clickTip` props on `ClipboardCopy`. Used only in SecretRevealModal.

4. **Inline Alert** — For transient errors or one-time warnings (e.g., "Copy the secret now"). Not used for instructional help.

5. **Modal body prose** — For destructive action confirmation. Describes the consequence, not how to use the feature.

PatternFly `Tooltip` and `Popover` components are not used anywhere in the current codebase. Before introducing them, prefer extending subtitle copy or `title` attributes.

### Field Display Conventions

**Weight**: Always `toFixed(2)`. Never show raw floats. Range is 0.0–1.0.

**Timestamps**: Two functions in `utils/time.ts`:
- `formatRelativeTime()` for recency-oriented displays (recent activity, version history, last active): `Xd ago`, `Xh ago`, `Xm ago`, `just now`.
- `formatDate()` for precise audit-oriented displays (created, updated, expires): `toLocaleString()` (browser locale).

**Scope badges**: Always use the `ScopeBadge` component, which wraps PatternFly `Label isCompact` with `SCOPE_LABEL_COLORS`. Do not render scope as plain text in contexts where it is a primary property.

**Branch type labels**: Blue `Label isCompact`. Only shown when `branch_type` is non-null. No color variation by type — blue is the conventional "metadata/annotation" color in this UI.

**UUIDs and IDs**: Render in `<code>` elements. For display in space-constrained contexts (relationship links, contradiction Memory ID), truncate to 8 characters with `...` suffix.

**Truncation with title**: When a string is truncated for display (stubs, observed behavior), always add a native `title` attribute containing the full value. Do not truncate without providing a way to see the full text.

**Counts**: Use `toLocaleString()` for large numbers (memory counts). Use integers directly for small counts (version numbers, priority, children count).

### Confirmation Patterns

Confirmation modals (`variant="small"`) are required for:
- Deleting a memory (from the detail drawer)
- Deleting a curation rule

Confirmation modals are NOT used for:
- Toggling a curation rule enabled/disabled (Switch, immediate)
- Toggling contradiction resolved/unresolved (button, immediate)
- Activating/deactivating an OAuth client (button, immediate)
- Rotating an OAuth secret (immediate, but followed by a reveal modal)

Confirmation modal prose convention: state what will be destroyed, state the irreversibility, and show the specific item name or stub in muted secondary text below. Do not add instructional content to a confirmation modal.

Danger variant buttons (`variant="danger"` or `isDanger`) are used for destructive actions in table rows and modal footers. Non-destructive toggles use `variant="secondary"`.

### Icons and Color

The application masthead uses a custom SVG logo (circle with radiating lines) on a `#1b1d21` dark background. No other icons are used in navigation.

Functional icon usage:
- `SearchIcon` — graph search submit button
- `BarsIcon` — sidebar toggle
- `TrashIcon` — delete button in memory detail drawer header
- `ArrowRightIcon` (rotated 90°) — source-to-target arrow in edge panel
- `CheckCircleIcon` — healthy MCP server, empty contradictions state
- `ExclamationCircleIcon` — unhealthy MCP server

Status colors (used directly, not via scope map):
- Healthy/active/current: `#3E8635` green
- Unhealthy/inactive/danger: `#C9190B` red
- Archived/warning: `#EC7A08` orange
- Selected/highlighted: `#F0AB00` gold

The scope color map (`SCOPE_COLORS`) is for graph nodes. The `SCOPE_LABEL_COLORS` map is for PatternFly `Label` components. They are parallel but use different types — hex strings vs PatternFly color names. Always use the correct map for the context.

## Transport Model

The UI is a Vite + React SPA served by a FastAPI Backend-for-Frontend (BFF). All API calls go to `/api/*` on the same origin; the BFF proxies to `memoryhub-core` and `memoryhub-auth`. Authorization and audit logging are handled at the BFF layer and are not re-implemented in the frontend. See [docs/admin/README.md](../admin/README.md) for the BFF's endpoint inventory, authz model, and audit behavior.

## Out of Scope / Future Work

Items that are intentionally not in the current UI and belong in future work:

- **Observability panel**: The nav item exists as a disabled stub. Content TBD (metrics, log streams, cost tracking).
- **Memory node highlighting from Contradictions**: Clicking a Memory ID navigates to the graph panel but does not highlight or zoom to the specific node.
- **Memory editor**: The UI has no way to edit memory content. All writes go through the MCP server.
- **Project management panel**: No panel exists for managing project memberships or project-scoped memory quotas.
- **Thread viewer**: No visualization of conversation thread associations.
- **Knowledge browser**: No taxonomy or faceted navigation of memories by topic, project, or tag.
- **Pagination**: All tables load their full dataset on mount. The graph also loads all nodes. Large deployments will need pagination or lazy loading.
- **Dark mode**: The masthead is dark (`#1b1d21`) but the content area is light. PatternFly supports a dark theme; it is not configured.
