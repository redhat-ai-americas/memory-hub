# Capability Taxonomy

Refined from the user's rough cut. This is the union of what the benchmarks in `benchmark-inventory.md` collectively measure, organized so that each capability can be cross-referenced against MemoryHub's shipped, planned, and not-contemplated features in `memoryhub-gap-analysis.md`.

The taxonomy has five groups:

1. **Retrieval quality** — can the memory layer return the right things?
2. **Temporal semantics** — does the memory layer understand time and change?
3. **Memory lifecycle** — how do things get in, get updated, get forgotten?
4. **Multi-agent / multi-tenant properties** — isolation, consistency, governance
5. **Operational properties** — cost, latency, usability, trust

The persistent-memory benchmarks focus almost entirely on groups 1–3. The enterprise / governance literature dominates groups 4–5.

---

## 1. Retrieval quality

### 1.1 Top-k retrieval accuracy

- **What it measures:** given a query, does the memory layer return the relevant memory in its top-k results?
- **Metrics:** recall@k, precision@k, nDCG, MRR, and (most commonly in AMB/LoCoMo/LongMemEval) downstream LLM-as-judge accuracy when the retrieved memories are fed into an answering prompt.
- **Benchmarks:** LoCoMo, LongMemEval, AMB (all datasets), MemoryAgentBench (accurate retrieval competency).
- **Gotcha:** downstream-accuracy is the dominant metric in practice because IR metrics on LLM-judged answers don't always track perceived quality. Anatomy of Agentic Memory (2602.19320) calls this out: "evaluation metrics are misaligned with semantic utility".

### 1.2 Multi-hop retrieval / reasoning chains

- **What it measures:** can the memory layer surface facts that require combining information across multiple memories?
- **Benchmarks:** LoCoMo (multi-hop sub-category — 11% relative improvement achievable with graph memory per Mem0), LongMemEval (multi-session reasoning), AMA-Bench (causality graph tasks).
- **Note:** This is where graph-native systems (Zep, Mem0^g, Graphiti) claim an advantage over flat vector systems.

### 1.3 Long-range retrieval under noise

- **What it measures:** whether retrieval holds up when the relevant memory is far back in history and there is a lot of noise.
- **Benchmarks:** BEAM (100K–10M context), LongMemEval (scalable histories), BABILong (long-context only — flagged as not persistent memory).
- **Gotcha:** this conflates "good retrieval" with "model handles long context". AMB's multi-context-length BEAM splits try to disentangle these.

### 1.4 Agentic retrieval

- **What it measures:** the agent, rather than a fixed pipeline, decides when and how to query memory, potentially iterating.
- **Benchmarks:** AMB's `agentic-rag` and `agent` modes, Letta's LoCoMo result (74% with filesystem tools), MemoryArena, AMA-Bench.
- **Key practitioner insight (Letta blog):** "memory is more about how agents manage context than the exact retrieval mechanism used." Specialized memory tools may under-perform well-tooled filesystem agents because the agent is trained on filesystem patterns.

---

## 2. Temporal semantics

### 2.1 Temporal reasoning over stored facts

- **What it measures:** answering questions like "what did I say last Tuesday?" or "what was the state of X before the update?"
- **Benchmarks:** LongMemEval (temporal-reasoning sub-category), LoCoMo (temporal question type), Zep's +38.4% improvement on the LongMemEval temporal sub-task.
- **Architectural implications:** bi-temporal models (Zep uses T + T') score best on this.

### 2.2 Knowledge updates / supersession

- **What it measures:** the memory layer correctly prefers newer information when old and new conflict. Old value is recoverable for audit, but current queries see the new value.
- **Benchmarks:** LongMemEval (knowledge-update sub-category), MemoryAgentBench (FactConsolidation), LifeBench.
- **Note:** this is distinct from contradiction detection. Supersession is "I was a vegetarian, now I eat fish" (update). Contradiction is "I said I was 30, now the agent thinks I'm 40" (conflict needing resolution).

### 2.3 Staleness detection

- **What it measures:** the memory layer invalidates entries when an upstream source changes, without being asked.
- **Benchmarks:** **None of the academic benchmarks test this.** Atlan's governance piece ("Stale context — the agent that acts on yesterday's truth") calls it out as a structural gap in every memory-layer tool.
- **Gotcha:** this is an architectural property (push invalidation from upstream data sources into memory) that benchmarks simply do not reach.

### 2.4 Temporal validity (TTL) and explicit expiry

- **What it measures:** memories can be declared valid-until, can expire, can be tiered.
- **Benchmarks:** none of the major ones test this directly. Mentioned as an architectural requirement in the Atlan piece.

---

## 3. Memory lifecycle

### 3.1 Writing / ingestion quality

- **What it measures:** is the layer good at deciding what to store and how to structure it?
- **Benchmarks:** AMB (ingestion time tracked separately), MemoryAgentBench (test-time learning), AMA-Bench (causality graph construction during ingest).
- **Ergonomic sub-question (Letta):** if an agent is given explicit write tools (e.g. `create_entity`, `add_observation`), does it actually use them correctly? The "well-designed agent with a filesystem beats specialized memory tools" result says agent-driven writes are fragile.

### 3.2 Deduplication / consolidation

- **What it measures:** does the memory layer avoid storing near-duplicates, or merge them when it detects overlap?
- **Benchmarks:** MemoryAgentBench's FactConsolidation is the closest fit. Mem0 paper claims latency/cost improvements attributed to consolidation but doesn't isolate the dedup contribution.

### 3.3 Versioning and history

- **What it measures:** can you retrieve the history of a memory (previous versions, provenance of updates)?
- **Benchmarks:** **No persistent-memory benchmark tests this directly.** The Atlan piece frames it as an audit requirement (EU AI Act Article 12 traceability to source data). The "Anatomy of Agentic Memory" survey flags "decision traces" as an architectural component "no memory layer tool provides natively".
- **MemoryHub does this** (`isCurrent` flag, `get_memory_history` tool) but has nowhere to report it against.

### 3.4 Selective forgetting / decay

- **What it measures:** the memory layer can be told (or can autonomously decide) to forget specific entries. Decay or aging can be configured.
- **Benchmarks:** MemoryAgentBench explicitly tests selective forgetting as a core competency.
- **Regulatory:** GDPR Article 17 (right to erasure) is mentioned in every enterprise governance doc reviewed. The problem the industry has not solved: provable deletion of embedded personal data. The Atlan piece says "no commercially available vector database provides a provable deletion mechanism".

### 3.5 Curation / quality signals

- **What it measures:** ability to apply quality filters, user-defined rules, or learned quality signals to reduce noise in the store.
- **Benchmarks:** none of the benchmarks reviewed test curation rules as a first-class feature.
- **Industry evidence:** curation is pitched heavily by Mem0 and Zep. Neither publishes an isolated curation benchmark.

---

## 4. Multi-agent / multi-tenant properties

### 4.1 Scope / isolation

- **What it measures:** memories written in one user's scope do not leak into another user's retrieval. Same for projects, tenants, roles.
- **Benchmarks:** **None of the academic benchmarks test this.** All the PM benchmarks reviewed assume a single agent ↔ single user setup.
- **Enterprise evidence:** Atlan piece's Risk #3 (Access Control Violations) is entirely about this. Databricks AI Security Framework (DASF v3.0) identifies per-user memory namespacing as a mandatory control. 45.6% of enterprises rely on shared API keys for agent-to-agent auth (Zenity 2026 Threat Landscape), meaning shared memory scope by default.
- **Gap:** there is a real benchmark-shaped hole here. A test suite that verifies per-user / per-tenant retrieval isolation, with adversarial queries that try to cross the boundary, does not exist publicly. **MemoryHub could contribute this.**

### 4.2 Cross-agent consistency

- **What it measures:** multi-agent systems don't diverge on the same fact. Two agents asked about the same entity give the same answer. When they can't, there is a conflict-detection mechanism.
- **Benchmarks:** none reviewed. This is the Atlan piece's Risk #6 ("Multi-agent memory conflicts"), with a specific paper citation: "Governed Memory: A Production Architecture for Multi-Agent Workflows" (https://arxiv.org/html/2603.17787, Mar 2026).
- **Relevance:** MemoryHub has one tenant in production. Cross-tenant isolation (just shipped 2026-04-08 via #46 Phase 4) is the dual of this — blocked leakage, not forced consistency. Active cross-agent consistency is not in scope.

### 4.3 Contradiction handling

- **What it measures:** when a new memory conflicts with an existing one, what does the system do?
- **Options observed in the literature:**
  - Let the more recent write win silently (most memory tools)
  - Mark both and let the agent resolve
  - Detect and flag for a human (Cq, MemoryHub's `report_contradiction`)
  - Reject the write until reconciled
- **Benchmarks:** MemoryAgentBench FactConsolidation is the only close match. LongMemEval knowledge-update is adjacent but tests the retrieval side, not the detect-and-flag side.

### 4.4 Provenance / citability

- **What it measures:** for any given memory-based answer, can you trace which stored memory contributed, when it was written, by whom, from what source?
- **Benchmarks:** none directly. This is an audit-trail capability.
- **Regulatory hook:** EU AI Act Article 12 (record-keeping, enforceable Aug 2 2026) requires "traceability to source data and decision rationale". Article 13 requires "sufficient transparency to enable deployers to interpret outputs".
- **MemoryHub-relevant:** the memory-tree's branch types include `provenance` explicitly.

---

## 5. Operational properties

### 5.1 Latency

- **What it measures:** retrieval latency, ingestion latency, end-to-end question-answer latency. Often reported as p50 / p95 / p99.
- **Benchmarks:** AMB tracks retrieval time and ingestion time separately. Mem0 headline: 91% p95 latency reduction vs full-context. Zep LongMemEval: 90% latency reduction vs baseline.
- **Industry argument:** Hindsight's AMB launch post argues latency and cost should sit alongside accuracy because a system that is 8 percentage points less accurate at 1% of the cost is the better production choice.

### 5.2 Cost (token + infrastructure)

- **What it measures:** tokens consumed per operation, dollar cost per user per day, cost of the ingest side vs query side.
- **Benchmarks:** AMB tracks token cost. Letta Context-Bench publishes cost in dollars per run as a first-class column.
- **Quote (Hindsight):** "a system that scores 90% accuracy but costs $10 per user per day is not better than a system that scores 82% and costs $0.10."
- **Anatomy of Agentic Memory (2602.19320):** "system-level costs are frequently overlooked" is one of the paper's main critiques.

### 5.3 Scale under load

- **What it measures:** how the memory layer performs at 10K, 100K, 1M+ memories; concurrent writes; large-fanout reads.
- **Benchmarks:** none of the academic persistent-memory benchmarks stress this directly. BEAM's 10M-token split tests model scale but not store scale.
- **Practitioner concern:** often mentioned in vendor blogs, rarely quantified. This is a gap.

### 5.4 Configuration / operator burden

- **What it measures:** is it hard to deploy, tune, run?
- **Benchmarks:** AMB explicitly lists "usability" as one of its four axes but the live leaderboard does not score it.
- **Implicit in:** vendor leaderboards (if it's easy enough to add a provider, more providers show up).

### 5.5 Trust / poisoning resistance

- **What it measures:** does the memory layer resist attacker-injected memories being returned as authoritative facts?
- **Benchmarks:** none of the mainstream ones test this. PoisonedRAG (2024) is the closest — it showed that 5 malicious documents in a corpus of millions cause 90% attack success on targeted queries.
- **Relevance:** every enterprise governance doc highlights memory poisoning as the top risk. The HN Cq thread's top-comment skepticism was about poisoning. This is a **benchmark-shaped hole** with regulatory tailwind.

### 5.6 Deletion provability

- **What it measures:** can you prove that data was deleted, including from embeddings?
- **Benchmarks:** none. Atlan piece calls out that no vector database currently provides this.
- **Regulatory hook:** GDPR Art. 17 (right to erasure) — ongoing compliance risk.

---

## Group-by-group coverage

| Capability group | Benchmark coverage | Where MemoryHub sits |
|---|---|---|
| Retrieval quality | **Strong** — most benchmarks focus here | MemoryHub's two-vector retrieval + cross-encoder rerank + RRF blend with focus is well-aligned; team has already run self-benchmark |
| Temporal semantics | Partial (LongMemEval, Zep) | MemoryHub has versioning + `isCurrent` but no bi-temporal model, no staleness detection, no TTL |
| Memory lifecycle | Partial (MemoryAgentBench) | Strong on versioning, curator-agent dedup, contradiction handling; weak on decay and provable deletion |
| Multi-agent / multi-tenant | **Weak** (nothing academic) | Tenant isolation just shipped (#46 Phase 4); cross-agent consistency not in scope |
| Operational | Growing (AMB, Letta, Anatomy) | Latency measured internally, not exposed; cost not measured; poisoning not tested |

**The biggest gap in the benchmark landscape** is that multi-tenant, scope isolation, poisoning resistance, provable deletion, and staleness detection — all of which matter enormously for enterprise deployment — have **no widely accepted benchmark**. They show up in governance checklists but not in leaderboards.

This is the "never contemplated" direction from the user's Part 4 question, in reverse: the benchmarks have never contemplated the things enterprises actually need to verify.
