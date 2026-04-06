# Retrospective: Dashboard — Memory Graph + Status Overview

**Date:** 2026-04-06
**Effort:** Build and deploy the first two panels of the MemoryHub landing page UI
**Issues:** #19, #21 (deferred)
**Commits:** 8e352bd, 28ba32d → 61ef3f8 (amend), f89a4b0 → d8f7836 (amend)

## What We Set Out To Do

Build panels 1 (Status Overview) and 2 (Memory Graph) of the MemoryHub dashboard, deploy as a standalone PatternFly 6 app with a FastAPI BFF backend, and register the OdhApplication tile in the RHOAI dashboard.

Deliverables from NEXT_SESSION.md:
- FastAPI BFF with REST endpoints (graph, search, stats, memory detail, version history)
- React + PatternFly 6 frontend with cytoscape.js graph visualization
- Single-container deployment to `memory-hub-mcp` namespace
- OdhApplication CR for RHOAI tile

Explicitly deferred: panels 3-7, write operations, oauth-proxy sidecar, graph library evaluation (#21).

## What Changed

| Change | Type | Rationale |
|--------|------|-----------|
| Skipped graph library evaluation (#21) | Scope deferral | Picked cytoscape.js directly — can swap later if needed |
| Single container instead of two (frontend + backend) | Good pivot | Simpler for demo; FastAPI serves static files and API from one process |
| `env_prefix="MEMORYHUB_"` instead of `AliasChoices` | Good pivot | Discovered pydantic-settings v2 doesn't use `validation_alias` for env var resolution — wasted two deploy cycles debugging connection refused |
| Multiple graph layout iterations | Missed | Didn't anticipate cytoscape re-running layout on every React re-render. Required three fixes: imperative layout, preset fallback, and stable listener registration |
| Added edge click → relationship detail view | Scope addition | Natural UX improvement; shows both connected memories and relationship type |
| Deleted 28 test memories from prod DB | Good pivot | SDK integration test artifacts cluttered the graph visualization |
| Frontend dist path: absolute container path with env override | Good pivot | `__file__` traversal breaks between local dev and container; hardcoded `/opt/app-root/src/frontend/dist` with `FRONTEND_DIST` env var override |

## What Went Well

- **Sub-agent parallelism** — backend and frontend implemented simultaneously by separate workers, then reviewed by a third. Caught PF6 API changes (Text/TextContent removal, chart import paths, Button `isSmall` → `size="sm"`) before first deploy.
- **Design docs were solid** — landing-page-design.md and ui-architecture.md eliminated architectural ambiguity. No time lost debating stack choices.
- **Existing deployment patterns** — MCP server's Containerfile, build-context.sh, and deploy.sh were directly reusable templates. The UI deploy scripts are structural clones.
- **Real data from day one** — 50 live memories in the graph immediately, not mock data. Made visual issues (test memory clutter, node overlap) obvious.
- **Incremental deployment** — fixing issues live on the cluster with rapid feedback loops. Six deploys in the session, each fixing a specific problem.

## Gaps Identified

| Gap | Severity | Resolution |
|-----|----------|------------|
| OpenShift BuildConfig caching caused 3+ redeploys with stale code | Fix now | Add `noCache: true` to UI BuildConfig — **same finding as RBAC retro** |
| No frontend tests (backend has 7 unit tests) | Follow-up | Add Vitest + React Testing Library for component tests |
| Test data accumulates in prod DB (repeat finding from RBAC retro) | Follow-up | Need automated cleanup or separate test namespace |
| No oauth-proxy on UI Route — publicly accessible | Follow-up | Planned for next session per design doc |
| pgvector similarity search untested end-to-end in UI | Follow-up | Text fallback works; embedding service path needs integration test |
| `calc(100vh - 76px)` hardcodes masthead height | Accept | Works for PatternFly 6; fragile if masthead height changes |
| RHOAI tile on "Enabled" page, not sidebar nav | Accept | By design — sidebar requires ODH Dashboard Plugin (Option B, long-term) |

## Action Items

- [ ] Add `noCache: true` to memoryhub-ui BuildConfig (fix the recurring build cache issue)
- [ ] Add `noCache: true` to memory-hub-mcp BuildConfig (same fix, never applied from RBAC retro)
- [ ] Frontend component tests with Vitest
- [ ] oauth-proxy sidecar for UI Route
- [ ] Automated test data cleanup strategy
- [ ] End-to-end test of pgvector similarity search through the UI

## Patterns

**Recurring (3rd occurrence):** OpenShift BuildConfig caching. The RBAC retro (2026-04-07) identified this and recommended `noCache: true`. It wasn't applied, and we hit it again here. This is now a systemic process gap — the fix needs to be applied to all BuildConfigs project-wide.

**Recurring (2nd occurrence):** Test data accumulating in the production database without cleanup.

**Start:** Apply BuildConfig fixes project-wide when identified, not just to the component that triggered the finding. Verify `noCache: true` on every new BuildConfig.

**Stop:** Using `removeAllListeners()` in cytoscape React integration — it strips internal listeners and causes handler loss on re-render.

**Continue:** Plan-then-implement-then-review sub-agent pattern. Design docs before implementation. Filing issues immediately when gaps are found. Parallel sub-agent execution for independent work streams.
