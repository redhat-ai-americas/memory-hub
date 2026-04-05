# Retrospective: RHOAI Dashboard Integration Design

**Date:** 2026-04-05
**Effort:** Design docs for integrating MemoryHub into the OpenShift AI dashboard
**Issues:** #19, #20, #21, #22, #23, #24 (all filed this session, all Backlog)
**Commits:** cb6e10c, 8621aff, 4f2c4e5

## What We Set Out To Do

Determine whether MemoryHub could appear as a native tile in the RHOAI dashboard, and if so, design the full integration: tile registration, landing page content, UI architecture, and developer onboarding experience.

## What Changed

| Change | Type | Rationale |
|--------|------|-----------|
| Custom MCP tools for API keys → Authorino Secrets | Good pivot | Authorino is already deployed with RHOAI. Eliminates custom auth code; API key Secrets double as the agent roster for the Users & Agents panel. |
| BFF proxying MCP → FastAPI querying PostgreSQL directly | Good pivot | MCP requires stateful connections — can't proxy behind REST. More importantly, the UI serves humans, not agents. Direct DB access is simpler and faster. |
| Memory Browser (list view) → Memory Graph (interactive visualization) as hero | Good pivot | The graph is the most compelling demo element. Shows "what agents are building" at a glance instead of a flat search list. |
| Status Overview as default view → Memory Graph as default | Follows from above | Graph tells the story better than aggregate numbers for demo audience. |
| Users/Agents: custom list_agents MCP tool → Authorino Secrets query | Simplification | Falls out naturally from Authorino decision — the key registry IS the agent roster. |

## What Went Well

- **Grounded in the real cluster.** Inspected actual OdhApplication CRs (Jupyter, RHOAI, pgvector) to learn the schema instead of guessing. Got exact field names, label conventions, and ownerReferences behavior from live resources.
- **Persona thinking sharpened the design.** Distinguishing admin vs. developer use cases cleaned up the confused data-source story and made each panel's purpose clear.
- **Authorino was a clean architectural win.** Removed an entire category of work (custom auth), used existing infrastructure, and gave us the agent roster for free.
- **Issue tracker command fills a real gap.** The `/issue-tracker` skill was missing, causing manual work earlier in the session. Created it with review, and it was immediately useful for filing #20–#24.
- **Issues filed immediately for every gap.** 6 issues filed this session, all in Backlog. Consistent with the pattern praised in all three prior retros.
- **Design before implementation.** No code written — all discussion and docs. Three architectural pivots (Authorino, database-direct, graph hero) happened before any implementation cost was incurred.

## Gaps Identified

| Gap | Severity | Resolution |
|-----|----------|------------|
| Graph visualization library not chosen | Follow-up | #21 — spike to evaluate vis.js, cytoscape.js, d3-force with PatternFly |
| AuthConfig YAML API version unverified | Follow-up | #22 — check Authorino CRD version on cluster before implementation |
| No design doc for contradiction_reports table | Follow-up | #23 — extend docs/storage-layer.md before implementing #20 |
| OdhApplication getStartedMarkDown is placeholder | Minor | #24 — write real content before applying CR to cluster |
| Contradiction tracking is in-memory only | Follow-up | #20 — add contradiction_reports table |

## Action Items

- [x] Commit doc revisions (4f2c4e5)
- [x] File issues for all identified gaps (#20–#24)
- [x] Create `/issue-tracker` slash command (8621aff)

## Patterns

**Start:**
- Inspecting live cluster resources to inform design. The OdhApplication CR schema, label conventions, and operator behavior were all learned from the cluster, not documentation.

**Stop:**
- Nothing new.

**Continue:**
- Discussing the plan before implementing. Three pivots this session (Authorino, database-direct, graph hero) would have been expensive rework if we'd started coding first.
- Filing backlog issues immediately when gaps are identified. 6 issues filed, none deferred to memory.
- The implement → review sub-agent pattern for non-trivial deliverables. The issue-tracker command review caught the fragile title matching, missing close/view operations, and unsafe body handling.
- Using existing platform infrastructure (Authorino, PostgreSQL shared DB) instead of building custom solutions.
