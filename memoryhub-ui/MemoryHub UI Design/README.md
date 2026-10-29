# MemoryHub UI Design — handoff package

This folder holds the complete MemoryHub dashboard design: 14 screens in the Red Hat / OpenShift AI style (PatternFly 6, Red Hat Display, Text and Mono type). Use it to build the real web UI in `memoryhub-ui/` of the [memory-hub](https://github.com/redhat-ai-americas/memory-hub) repository, with every number and list coming from the backend.

**Do not redesign.** Reproduce the layouts, styles, spacing, colours and copy as drawn. The only content that changes is the data: every figure, name and row in the screens is illustrative and must come from the API.

## What's here

| Path | What it is |
| --- | --- |
| `static/*.html` | **Start here.** Every screen as a standalone HTML page with all styles inline and all sample data rendered. Open `static/Main.html` in a browser; the sidebar and buttons link between screens. |
| `screenshots/*.png` | Full-page PNG of each screen at its design size (1440 px wide). |
| `project/*.dc.html` | Original canvas sources, unchanged. Same markup as `static/`, but lists are templates (`<sc-for>`, `<sc-if>`, `{{holes}}`) filled from the `renderVals()` object at the bottom of each file. That object shows the **shape of the data each screen needs**. |
| `project/canvas.json` | Canvas index: screen titles, sizes and grouping. |

The pages load Google Fonts (Red Hat Display, Text and Mono). In the app, use the fonts bundled with PatternFly 6 instead.

## Screens

| # | Screen | File | Purpose |
| --- | --- | --- | --- |
| 01 | Overview | `Main` | KPIs, 14-day activity, memories by scope, recent activity, component health |
| 02 | Memory browser | `Memories` | Filterable table of memories across scopes, with bulk actions |
| 03 | Memory detail | `MemoryDetail` | Versions and diff, branches, relationships, metadata, contradictions, similar memories |
| 04 | Memory graph | `Graph` | Graph explorer with edge-type filters and a side panel for the selected node |
| 05 | Search playground | `Search` | Run `search_memory` as an identity; pipeline timing and per-result scores |
| 06 | Projects & campaigns | `Projects` | Projects, enrollment, members, focus history, `.memoryhub.yaml` |
| 07 | Users & agents | `Identities` | Users, user agents and service agents; scope permission matrix |
| 08 | OAuth clients & API keys | `Clients` | OAuth clients, API keys and trusted token issuers; secret shown once |
| 09 | Curation rules | `Curation` | System, organization and user rules; editor with a test box |
| 10 | Review queue | `Review` | Enterprise approvals, promotions, contradictions and quarantine |
| 11 | Audit & forensics | `Audit` | Reconstruct what an agent knew at a given time; append-only audit log |
| 12 | Settings | `Settings` | Retrieval defaults, models, isolation, audit retention, MCP profile |
| 13 | Login | `Login` | OpenShift OAuth login, plus an API key option for development clusters |
| 14 | Foundations & components | `StyleGuide` | Colour, scope labels, type, buttons, form controls, empty state, layout rules |

## Design foundations

These values are taken from the screens. Screen 14 shows them together.

- **Shell:** masthead 60 px tall, background `#151515`. Dark sidebar 256 px wide, background `#212427`. The active nav item is `#3a3f45` with a 3 px `#ee0000` left bar. Group labels are uppercase 12 px, colour `#a3a3a3`. Page header is white with a `#d2d2d2` bottom border. Content area background is `#f2f2f2`.
- **Colour:** red `#ee0000` is used only for identity (the mark, the active nav bar, badges). Actions are blue: primary `#0066cc`, hover `#004d99`. Danger is `#b1380b`. Status colours: success `#3d7317`, warning `#8f6100`.
- **Scope tiers.** Each tier has one hue, used for labels, graph nodes and bars. The label text always names the tier, so colour is never the only signal.
  - User: `#0066cc`
  - Project: `#009596`
  - Campaign: `#5e40be`
  - Role: `#ca6c0f`
  - Organizational: `#3d7317`
  - Enterprise: `#ee0000`

  The light label background and text colours for each tier are the `.s-*` classes in any screen's `<style>` block.
- **Type:**
  - Page title: Red Hat Display, 28 px, weight 500.
  - Card title: Red Hat Display, 16 px, weight 600.
  - Body and tables: Red Hat Text, 14 px.
  - IDs, scopes and tool names: Red Hat Mono, 12.5 px.
- **Shapes:** cards have a 16 px radius, a 1 px `#d2d2d2` border, about 24 px padding and 16–20 px gaps. Buttons and labels are pills. Inputs have an 8 px radius.
- **Behaviour rules:**
  - On list pages, the table sits on the left and the detail panel on the right. They stack below 960 px.
  - Destructive actions say what they remove and that the action is audited.
  - Results hidden by RBAC are counted (`omitted_count`), never dropped silently.

## Wiring to the backend

The target is the existing `memoryhub-ui`: React with PatternFly 6, behind the FastAPI BFF in `memoryhub-ui/backend/src`. All BFF queries are scoped to `MEMORYHUB_UI_TENANT_ID`.

**Already built on branch `ui-improvement`:**
- The new app shell.
- Screen 01, Overview, backed by `GET /api/overview`. It returns memory totals and growth, identities, scope split, 14-day activity, contradictions, audit events and service health.
- When the tenant has no memories, Overview shows a "Waiting for the first memory" state and polls every 5 s until the first `write_memory`.
- Follow that pattern for the other screens: shell, CSS tokens, empty states and loading skeletons.

**BFF endpoints that already exist:**
- `GET /api/graph`
- `GET /api/graph/search`
- `GET /api/stats`
- `GET /api/memory/{id}`
- `GET /api/memory/{id}/history`
- `DELETE /api/memory/{id}`
- `GET /api/users`
- `GET`, `POST`, `PATCH /api/clients`, plus `rotate-secret` and `rotate-api-key`
- `GET`, `POST`, `PATCH`, `DELETE /api/rules`, plus `/history`
- `GET /api/contradictions`, `GET /api/contradictions/stats`, `PATCH /api/contradictions/{id}`
- `GET /api/public-config`
- `GET /api/overview` (on the branch)

**Where each screen's data comes from:**

| Screen | Existing source | Still needed |
| --- | --- | --- |
| 02 Memory browser | `memory_nodes`; `/api/graph` filters by scope and owner | Paginated `GET /api/memories` with scope, owner, project, domain, weight and flag filters, status tabs (current, all versions, quarantined, deleted), and facet counts |
| 03 Memory detail | `/api/memory/{id}` and `/history`; `contradiction_reports`; `memory_relationships` | Branches list, similar memories (pgvector cosine), relationships with `omitted_count`, contradictions for one memory |
| 04 Memory graph | `/api/graph`, `/api/graph/search` | Depth-limited neighbourhood around a focus node; provenance chain |
| 05 Search playground | Same retrieval as MCP `search_memory` in `memoryhub_core` | `POST /api/search` that runs as a chosen identity and returns per-stage timings and scores (vector, focus, RRF, rerank, weight) |
| 06 Projects & campaigns | `projects`, `project_memberships`, `campaigns`, `campaign_memberships`; MCP `manage_project`, `get_focus_history` | List, create and update projects and campaigns; members; focus histogram |
| 07 Users & agents | `/api/users`; auth service clients; `role_assignments` | Identity detail with a scope matrix and 24 h activity from `audit_log` |
| 08 Clients & keys | `/api/clients` and its rotate endpoints | Trusted issuers (auth service trust config) |
| 09 Curation rules | `/api/rules` | Rule test endpoint (regex or embedding against sample text); 7-day match counts |
| 10 Review queue | `contradiction_reports`; quarantined memories (`status`) | Enterprise approval requests and curator promotions, plus approve, reject and request-changes actions (recorded in the audit log) |
| 11 Audit & forensics | `audit_log` | Paginated audit log with filters; "what did agent X know at time T", which joins search and read events with version history |
| 12 Settings | `config.py` settings | Read and update tenant settings; model endpoints and health |
| 13 Login | OpenShift OAuth proxy in front of the UI | Optional API-key login for development clusters |

**Every screen needs:**
- A loading state (skeletons).
- An error state with a retry.
- An empty state that explains what will appear and how to get there.
- Counts that come from the backend, never hard-coded.
