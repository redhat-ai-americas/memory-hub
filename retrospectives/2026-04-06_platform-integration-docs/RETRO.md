# Retrospective: Platform Integration Docs (Kagenti + LlamaStack)

**Date:** 2026-04-06
**Effort:** Research kagenti and LlamaStack, produce integration design docs for both platforms
**Issues:** #28–#35 (created as follow-up)
**Commits:** `edd2575`, `1ee3d29`

## What We Set Out To Do

Research kagenti as an alternative agent framework to LlamaStack, produce integration design docs with gap analysis, phased plans, and technical architecture. Scope expanded mid-session to include LlamaStack (realized we had no integration docs for it either). Six documents total: overview, integration-phases, and architecture for each platform.

## What Changed

| Change | Type | Rationale |
|--------|------|-----------|
| Added LlamaStack docs (originally just kagenti) | Good pivot | Parity — no LlamaStack integration docs existed either |
| CLI scoped out of both plans | Scope deferral | Already tracked in a separate future planning phase |
| Third RHOAI research agent got stuck | One-off | First two agents had sufficient coverage; proceeded without it |
| Major API corrections after verification | Good pivot | Verified both SDKs against live repos; found fabricated CRD and removed Agents API |

## What Went Well

- Parallel research agents produced comprehensive coverage of both platforms quickly
- Review sub-agent caught real cross-doc inconsistencies (kagenti overview misrepresented LlamaStack security, scope naming drift, SDK described as future when v0.1.0 exists)
- Verification agents caught serious factual errors before they could mislead implementation
- User-driven scoping was crisp — clear signals on "no implementation", "CLI is tracked", "let's discuss"
- Three-phase structure (MCP first, then typed integration + auth, then deep framework integration) applies cleanly to both platforms

## Gaps Identified

| Gap | Severity | Resolution |
|-----|----------|------------|
| Research agents fabricated kagenti MCPServerRegistration CRD | Fix now | Fixed in `1ee3d29` — removed CRD, toolPrefix, targetRef |
| Research agents used removed LlamaStack Agents API | Fix now | Fixed in `1ee3d29` — replaced with Agent helper class |
| LlamaStack MCPProviderConfig has no config fields | Fix now | Fixed in `1ee3d29` — noted in run.yaml examples |
| Connector endpoint was /connectors, should be /api/v1/connectors | Fix now | Fixed in `1ee3d29` |
| How MCP server URL is configured for tool_runtime provider unclear | Accept | Noted as needing investigation during Phase 1 implementation |

## Action Items

- [x] Fix all verified API surface issues (done in `1ee3d29`)
- [x] Update SYSTEMS.md with new subsystems (done in `1ee3d29`)
- [x] Create tracking issues #28–#35 for all phased work
- [ ] Investigate how LlamaStack's remote::model-context-protocol provider receives its MCP server URL (no config fields on MCPProviderConfig) — needed before llamastack Phase 1 (#31)

## Patterns

**Start:** Verify SDK/API code examples against live repos before committing design docs. Research agents confidently fabricate plausible-looking CRDs and API calls. This session's verification step caught a nonexistent CRD and a removed API that would have sent implementors down wrong paths.

**Stop:** Trusting research agent output for specific API surfaces (class names, method signatures, CRD schemas). The high-level architecture research was accurate; the specific code-level details were not. Research agents should gather context, but verification agents should confirm specifics.

**Continue:** Parallel research + write + review + verify workflow. The four-stage pipeline (research → write → review → verify) caught progressively deeper issues at each stage.
