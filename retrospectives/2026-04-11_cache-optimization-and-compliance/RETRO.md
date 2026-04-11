# Retrospective: Cache Optimization, Compliance Positioning, and Epoch-Aware Memory

**Date:** 2026-04-11
**Effort:** Continuation of scope expansion research — vLLM cache optimization, EU AI Act compliance positioning, epoch-aware memory assembly, Lanham article analysis
**Issues:** #175 (cache-optimized memory assembly), comments on #168, #169, #171
**Commits:** `d084aec`, `b180b33`, `8caa872`

## What We Set Out To Do

Tie up loose ends from the April 10 scope expansion session: commit the planning overview and vLLM cache research, add EU AI Act compliance positioning, and analyze the Lanham "Markdown File That Beat a $50M Vector Database" article for design insights.

## What Changed

| Change | Type | Rationale |
|--------|------|-----------|
| EU AI Act compliance became a dedicated strategy section | Good pivot | Started as a "findings discussion" item, elevated to a primary selling point because MemoryHub's governance substrate directly maps to Article 12/19 requirements |
| Lanham article led to cache optimization issue #175 | Good pivot | The article's KV cache economics analysis exposed a gap: our search_memory response format isn't cache-friendly. Simple sort-order change has outsized impact. |
| Epoch-aware memory assembly concept emerged | Good pivot | Connected cache stability (technical) with sprint/phase structure (workflow) and RAG minimalism (principle). Novel synthesis that no one else is doing. |
| Epoch-scoped RBAC flagged as long-term | Scope deferral | Structural prevention of cross-scope memory access — powerful for regulated environments but Phase 3+ complexity. Captured as forward-looking design note. |
| Branch protection adjusted (enforce_admins → false) | Process | Solo admin can't require approval from nobody. Non-admins still need PRs with review. Re-enable when second admin joins. |

## What Went Well

- **The Lanham article was a catalyst, not just a reference.** It surfaced the cache invalidation problem that led directly to #175 and the epoch concept. Good example of external input generating concrete design work.
- **EU AI Act positioning was a natural fit.** The compliance story didn't require new capabilities — it's reframing what we already have (versioning, provenance, scope isolation, dual-track storage) through a regulatory lens. Low effort, high positioning value.
- **Epoch-aware memory is genuinely novel.** Nobody else is framing work-structure-aware retrieval as a cache optimization strategy. The connection between "what phase of work am I in" and "what should my KV cache prefix look like" is a differentiating insight.
- **The `scope_id` field already supports epochs.** The data model doesn't need changes to carry sprint/task identifiers. Design-to-not-preclude worked retroactively.
- **Config init as the integration point.** Instead of requiring agents to understand epoch theory, the config workflow generates rules that guide compliant behavior. The complexity is absorbed by tooling, not imposed on users.

## Gaps Identified

| Gap | Severity | Resolution |
|-----|----------|------------|
| The cache assembly section in design.md proposes schema extensions (.memoryhub.yaml fields) but the SDK doesn't implement them yet | Accept | #175 tracks implementation. Design committed, implementation is future work. |
| No benchmark proving cache optimization impact in our specific workload | Medium | Should benchmark before/after once #175 ships. Add to #175 acceptance criteria. |
| Epoch detection heuristics are speculative (git branches, temporal clustering) | Low | Accept for now. Design phase of #175 should validate which heuristics are reliable. |
| vLLM research was done by sub-agent; specific claims (16-token blocks, SHA-256 hashing) not independently verified | Low | Sources are cited with URLs. Verify against live vLLM when implementing. |

## Action Items

- [x] Strategy doc updated with EU AI Act compliance section
- [x] Planning overview committed
- [x] vLLM cache research committed
- [x] Cache assembly section added to ergonomics design doc
- [x] Issue #175 filed for implementation
- [x] Design notes on #169 (epoch compaction triggers) and #175 (epoch-aware assembly, config init, RBAC)
- [x] Branch protection adjusted for solo admin workflow
- [ ] Benchmark cache optimization impact once #175 ships (add to issue acceptance criteria)

## Patterns

**Continue:**
- **Using external articles as design catalysts.** The Lanham article and Karpathy post both generated concrete design work. Keep feeding external thinking into the project.
- **Connecting technical mechanisms to business value.** Cache optimization → cost reduction. Scope isolation → EU AI Act compliance. Epoch awareness → structural prevention. The technical work is more compelling when the positioning is explicit.
- **Capturing forward-looking design notes on issues.** Epoch-scoped RBAC is years away but now won't be forgotten. The issue comment serves as a bookmark for the idea.

**Validated:**
- **"Design the data model to not preclude it" pays dividends.** `scope_id` was added for project/role isolation. It already supports epoch/task scoping without schema changes. Foresight in data modeling is high-ROI.
- **One format strategy works across all providers.** Deterministic serialization + stable sort + no timestamps = cache hits on vLLM, Anthropic, OpenAI, and Google simultaneously. No provider-specific code paths needed.
