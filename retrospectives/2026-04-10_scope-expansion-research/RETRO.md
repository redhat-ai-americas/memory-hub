# Retrospective: Scope Expansion Research and Platform Positioning

**Date:** 2026-04-10
**Effort:** Research and strategic design for four new MemoryHub capabilities, plus cross-project platform architecture positioning
**Issues:** #168 (conversation persistence), #169 (context compaction/ACE), #170 (graph-enhanced memory), #171 (knowledge compilation)
**Commits:** `162aa76`

## What We Set Out To Do

Investigate two features that colleagues and evaluators keep asking about — conversation persistence and context compaction — to determine whether they belong in MemoryHub, as standalone projects, or out of scope. Research the landscape, discuss the design implications, and file tracking issues for team discussion.

## What Changed

| Change | Type | Rationale |
|--------|------|-----------|
| Expanded from 2 features to 4 tracking issues | Good pivot | Graph memory (#170) came up naturally when discussing data access patterns. Knowledge compilation (#171) emerged from the Karpathy/LLM wiki analysis. Each was a logical extension, not scope creep. |
| Added platform architecture positioning doc | Good pivot | The conversation about where features belong led to a clear articulation of the MemoryHub + RetrievalHub + enterprise tools stack. Worth capturing while the thinking was fresh. |
| Created `strategy/` directory | Good pivot | The platform architecture doc didn't belong in `docs/` (not MemoryHub-specific reference). Created a proper home and moved `rfe_draft.md` there too. |
| Reorganized `docs/admin/` | Good pivot | Operational/contributor guides were cluttering `docs/` alongside reference material. Clean separation. |
| Decided Option B (features within MemoryHub, not standalone projects) | Good pivot | Governance substrate reuse was the deciding factor — building a third hub means rebuilding scope isolation, tenant isolation, RBAC, versioning, and audit trails. |
| On-cluster compilation service architecture added to #171 | Good pivot | Wes's insight that compilation should be a platform service (not in-agent) — dedicated pods with HPA, cached results shared across agent fleet. Transforms a per-agent cost into a shared infrastructure capability. |

## What Went Well

- **Natural expansion was productive, not scattered.** Started with 2 features, ended with 4 issues + a strategy doc, and each step followed logically from the previous discussion. The session had a clear arc: research → decide scope → research more → position the platform story.
- **The "experiential vs. factual" split crystallized.** Walking through concrete scenarios (incident response, compliance review, research synthesis, onboarding, conference talk) produced a clean data ownership boundary: MemoryHub = "why is it this way?" (experiential), RetrievalHub = "what is this?" (factual). This was discovered through discussion, not prescribed.
- **Research agents delivered thorough, well-sourced surveys.** Four research documents totaling ~150K words of source analysis with concrete references. The conversation-persistence and context-compaction surveys both identified governance as the clear whitespace — validating MemoryHub's positioning.
- **PostgreSQL-first graph rationale is documented.** AGE evaluated and deferred with clear data (one benchmark showed CTEs outperforming AGE by 40x). Decision captured in both MemoryHub memory and the graph survey. This will save repeated conversations.
- **The "nobody has built the governed multi-user version" finding.** The Karpathy wiki landscape analysis confirmed that every implementation is personal-only. The governed, scoped, multi-tenant version is genuinely unclaimed territory.
- **Colleague feedback validated, not diluted.** Features people ask about (conversation persistence, compaction, graph memory) turned out to be natural expectations of the category, not scope creep. "Letting us into the room we've asked to enter."

## Gaps Identified

| Gap | Severity | Resolution |
|-----|----------|------------|
| Research docs were written by sub-agents with no human review of factual claims | Low | Surveys are clearly labeled as research, not design docs. Claims will be verified during design phase. Accept for now. |
| MemoryHub MCP server disconnected mid-session | Low | Lost ability to write the second memory (scope expansion decision) atomically with the first (graph DB strategy). Both were written before disconnect. No data loss. |
| No design docs written yet — only tracking issues | Accept | Intentional. This was a research and discussion session, not a design session. Design docs are the next step per the `needs-design` label on each issue. |
| The llm-wiki-landscape research was returned inline (not written to file by the agent) | Low | Manually saved to file. The agent may have hit a write issue. Result was complete; just needed manual persistence. |
| RetrievalHub relationship not captured in a shared document | Medium | The platform-architecture.md describes the relationship, but it lives only in the MemoryHub repo. RetrievalHub should reference it too, or it should live in a shared location. Follow up when RetrievalHub work resumes. |

## Action Items

- [x] All four tracking issues filed and in Backlog (#168, #169, #170, #171)
- [x] Research docs committed and pushed
- [x] Strategic decisions captured in MemoryHub memory
- [x] Platform architecture doc in `strategy/`
- [x] File reorg (docs/admin, strategy/) committed
- [ ] Cross-reference `strategy/platform-architecture.md` from RetrievalHub when that project resumes

## Patterns

**Continue:**
- **Discussion-first, then research, then issues.** This session's flow — discuss the shape of the problem, research the landscape, refine the framing, file issues — produced better-scoped issues than jumping straight to filing. The issues have clear scope precisely because we discussed before writing.
- **Parallel research agents for independent topics.** Running conversation-persistence and context-compaction research simultaneously saved ~10 minutes. The graph-memory and llm-wiki agents ran later but could have been parallelized too.
- **Concrete scenarios to test abstractions.** The five worked scenarios (incident response, compliance, research, onboarding, conference talk) were what crystallized the experiential-vs-factual split. Abstract arguments about data ownership didn't resolve it; concrete examples did.
- **Capturing architectural decisions in MemoryHub memory.** The PostgreSQL-first graph strategy and the scope expansion decision are now findable in future sessions without re-deriving them.

**Start:**
- **When a research agent returns inline results instead of writing a file, save immediately.** The llm-wiki agent's results were nearly lost because it returned text instead of writing to disk. Check for file output promptly and save manually if needed.

**Validated:**
- **The "smart people's first question" signal is reliable.** When multiple independent evaluators ask about the same capability, it's a category expectation, not a nice-to-have. This session proved that conversation persistence, compaction, and graph memory all fit naturally within MemoryHub's governance substrate rather than diluting it.
