# Scope Expansion Overview: Four New MemoryHub Features

**Status:** Roadmap map. Each feature needs a design doc before implementation begins.
**Issues:** #168 (threads), #169 (compaction/ACE), #170 (graph), #171 (compilation)
**All issues:** tagged `needs-design`, in Backlog

---

## Why We're Expanding

Colleague feedback from April 2026 validated that these capabilities are category expectations, not scope creep. Developers evaluating agent memory platforms expect: raw conversation persistence, graph-based entity relationships, context compaction, and compiled knowledge synthesis. Shipping only extracted memories leaves MemoryHub at a subset of what the category requires.

The April 8 scoping decision holds: episodic + procedural memory, not semantic retrieval. All four features operate on experiential data — what agents did, observed, and decided — under MemoryHub's existing governance substrate. This is not a pivot toward RetrievalHub territory; it is filling out the experiential memory tier that was always in scope.

The phrase that captured the April discussion: *"letting us into the room we've asked to enter."*

---

## The Four Features

| Issue | Feature | Summary |
|-------|---------|---------|
| #168 | Conversation thread persistence | First-class `ConversationThread` + `ConversationMessage` entities. Raw transcripts with the same governance guarantees (RBAC, retention, audit). Produces the raw material the other three consume. |
| #170 | Graph-enhanced memory | Temporal validity on relationships, graph-enhanced retrieval (vector + graph traversal via RRF), lightweight entity extraction at write time (POLE+O). PostgreSQL-first; AGE and Neo4j deferred. |
| #169 | Context compaction (ACE) | Policy-driven memory curation, conversation compaction, and cross-agent context management. Governed compression with provenance — auditable summaries (Anthropic-style), not opaque tokens. Dual-track hot/cold storage. |
| #171 | Knowledge compilation | LLM-driven pipeline that transforms threads + memories + graph into structured, interlinked knowledge articles. Maintained continuously via a virtuous loop. Runs on-cluster as a shared service with HPA. The crown jewel: where the other three compose. |

### Dependency chain

```
#168 (threads) → #170 (graph/entities) → #169 (compaction) → #171 (compilation)
```

Each feature delivers independent value. The dependency chain indicates what feeds what, not what must ship first. #171 is where they compose into the full capability.

---

## Key Architectural Decisions (Already Made)

**Build location:** Option B — all features within MemoryHub, not as standalone projects. Rationale: reuse of the governance substrate (scope isolation, tenant isolation, RBAC, versioning, contradiction detection) is the differentiator. Rebuilding it per-project loses that.

**Graph backend:** PostgreSQL-first. Apache AGE is in Apache Incubator and adds ergonomics but not graph algorithms. Neo4j is justified when deep traversals (>5 hops) or graph algorithms become requirements. Decision revisited at Phase 3 of #170.

**Data ownership boundary:** MemoryHub's graph is experiential — decisions, provenance, rationale chains. RetrievalHub's graph sources are factual — curated knowledge about infrastructure, compliance, reference data. Both can expose graph query surfaces but over different data with different ingestion pipelines.

**Thread model:** Inherently n-participant. n=2 (agent + human) is the common case, not the only case. Kagenti multi-agent swarms and A2A handoffs are first-class.

**Compilation service:** Runs on-cluster as a shared platform service with HPA, not inside the requesting agent's context window. Agents call `compile_knowledge`; compilation pods do the work on dedicated infrastructure and cache results by (tenant, scope, topic_hash).

**Memory injection:** Memories injected as user-message context (not system prompt), sorted by weight descending. Supports KV cache stability for compiled articles.

---

## Research Completed

All four features have research surveys in `research/`:

| Feature | Research document |
|---------|------------------|
| #168 Threads | `research/conversation-persistence-survey.md` |
| #169 Compaction | `research/context-compaction-survey.md` |
| #170 Graph | `research/graph-memory-survey.md` |
| #171 Compilation | `research/llm-wiki-landscape.md` |

Design docs should incorporate findings from these surveys, particularly: the EU AI Act Article 12 audit trail requirement (August 2026 deadline), the ACE Generator/Reflector/Curator pattern (+10.6% on agent benchmarks), the Anthropic vs OpenAI transparency fork on compaction, and the Meta 50-agent tribal knowledge extraction case study.

---

## What's Next

Each issue's first deliverable is a design doc. The issues enumerate the expected doc path and scope in their issue bodies. Start by reading the research survey for the feature, then draft the design doc incorporating any comments already on the issue.

Design should address reviewer concerns logged in issue comments before implementation begins.

---

## Build Order

The dependency chain suggests a natural sequence:

**Recommended:** threads (#168) → graph (#170) → compaction (#169) → compilation (#171)

**Pragmatically:** work can begin on any feature whose dependencies are met. Graph (#170) Phase 1 (temporal validity + graph-enhanced retrieval) has no hard dependency on threads and can proceed in parallel. Compaction (#169) can begin design in parallel with graph since the curator subsystem (`src/memoryhub_core/services/curation.py`) already provides primitives to build on.

Compilation (#171) should not begin implementation until threads, graph, and compaction have landed — it is the composition layer and will produce incorrect architecture if designed in isolation.
