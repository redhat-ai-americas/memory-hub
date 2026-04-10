# Agent Memory Benchmarks — Research Index

Discussion-prep research on the state of agent-memory benchmarks and their applicability to MemoryHub. **Nothing in this folder is a plan to implement anything.** It exists so the team can have an informed conversation about where benchmarks fit (and where they don't) before committing to any evaluation work.

Research pass performed 2026-04-08.

## Files

- [`sources.md`](sources.md) — every URL consulted, annotated, primary vs secondary. Start here for provenance.
- [`benchmark-inventory.md`](benchmark-inventory.md) — one section per benchmark reviewed. Categorized as persistent-memory vs long-context vs agent-capability vs survey.
- [`capability-taxonomy.md`](capability-taxonomy.md) — refined taxonomy of what the benchmarks collectively measure, grouped into five layers.
- [`memoryhub-gap-analysis.md`](memoryhub-gap-analysis.md) — **the main discussion file.** Two-way mapping between MemoryHub subsystems and benchmark capabilities. Honest gaps called out.
- [`enterprise-requirements.md`](enterprise-requirements.md) — what enterprises need that academic benchmarks don't measure. Audit, governance, poisoning, provable deletion, cost control.

## Executive summary — 5 findings for the discussion

### 1. LoCoMo is saturated; LongMemEval, MemoryAgentBench, and AMA-Bench are where the action is

The two benchmarks practitioners default to when they say "agent memory benchmark" — LoCoMo and the vanilla DMR — are both saturated. Letta showed GPT-4o mini hits **74% on LoCoMo using only filesystem tools** (`grep`, `search_files`, `open`, `close`), beating Mem0's reported graph-variant score. Hindsight reports 92% on LoCoMo. The signal has mostly washed out. **LongMemEval** (ICLR 2025) still discriminates on its temporal-reasoning and knowledge-update sub-tasks — Zep reports **+38.4% on LongMemEval temporal reasoning** after their bi-temporal redesign. **MemoryAgentBench** (UCSD, ICLR 2026) and **AMA-Bench** (Feb 2026) both explicitly target the capabilities where flat vector systems fail. If MemoryHub runs against anything, these three are the ones that would actually produce a signal.

### 2. The Vectorize AMB harness is the cleanest on-ramp — and it is a vendor leaderboard

**Agent Memory Benchmark (AMB)** from Vectorize/Hindsight is an open-source harness that wraps LoCoMo, LongMemEval, LifeBench, PersonaMem, MemBench, MemSim, BEAM, and AMA-Bench under one Ingest → Retrieve → Generate → Judge pipeline. Generator and judge are both Gemini. Token cost, ingest time, and retrieval time are tracked separately. Code: https://github.com/vectorize-io/agent-memory-benchmark. This is the **single best existing way to put MemoryHub alongside Cognee, hybrid-search, BM25, and Hindsight on a level playing field.** Caveat: AMB is a vendor leaderboard and Hindsight is at the top of every row. The harness itself is neutral, and running our own numbers against it is a legitimate move.

### 3. Long-context benchmarks are not memory benchmarks — stop conflating them

NIAH, RULER, HELMET, and BABILong are all **long-context benchmarks**. They measure whether a model uses a single large input well. They do **not** measure whether an external memory layer stores, retrieves, updates, and governs information across sessions. The AMB launch post, the MemoryArena paper (https://arxiv.org/abs/2602.16313), and the "Anatomy of Agentic Memory" survey (https://arxiv.org/abs/2602.19320) all make the same point independently: **agents that score well on long-context benchmarks perform poorly in agentic multi-session memory settings.** When the team hears "memory benchmark", always check which of these two very different things the speaker means.

### 4. Most of MemoryHub's differentiators (versioning, provenance, scope isolation, audit) get zero credit from any academic benchmark

Direction A of the gap analysis ("we have X, is there a benchmark for it?") returned mostly null. Memory-tree versioning, the `isCurrent` flag, `get_memory_history`, provenance branches, the scope system, tenant isolation (#46 Phase 4) — **none of these score anywhere on any academic memory benchmark.** The benchmarks reward downstream QA accuracy. They do not reward the audit-trail, isolation, or governance properties that make MemoryHub enterprise-deployable. This is a structural mismatch and worth naming in any external positioning work.

### 5. The biggest "never contemplated" gap is poisoning resistance

The most consequential item to surface: **MemoryHub has no defense against authorized-but-adversarial writes.** The curator-agent's regex scanning and embedding dedup are tuned for quality, not adversarial detection. PoisonedRAG (2024) showed that **5 malicious documents in a corpus of millions cause 90% attack success on targeted queries**. Microsoft Security Blog (Feb 2026) documented "AI Recommendation Poisoning" at enterprise scale. Every enterprise governance source reviewed flags this as the top risk, with regulatory tailwind from FTC Act Section 5 and EU AI Act Article 12. MemoryHub already has the right architectural home for a fix — the curator-agent — but there is no design, no issue, and no test for this today.

Close runners-up (see `memoryhub-gap-analysis.md` for the full list):

- **Staleness / upstream invalidation** — will become blocking the day org-ingestion ships.
- **Cost instrumentation** — we cannot participate in a "good memory at reasonable cost" conversation because we have no numbers.
- **Provable deletion** (GDPR Art. 17) — partial; needs the audit log (#67) to produce a deletion receipt.
- **Multi-agent consistency** — out of scope today, will land in scope as soon as kagenti-integration or llamastack-integration ships.

---

## Benchmark map (at a glance)

| Benchmark | Year | Category | Saturated? | MemoryHub fit |
|---|---|---|---|---|
| LoCoMo | 2024 | Persistent memory | **Yes** | Weak discriminator |
| LongMemEval | 2024 | Persistent memory | Partial | **Strong — run this** |
| MemoryAgentBench | 2025 | Persistent memory + agent | Not yet | **Strong for curator/versioning** |
| AMA-Bench | 2026 | Persistent memory + agent | Not yet | **Will expose retrieval gaps** |
| MemoryArena | 2026 | Persistent memory + agent | Not yet | Mirrors our use case |
| DMR (MemGPT) | 2023 | Persistent memory | Yes | Legacy |
| Letta Context-Bench | 2025–26 | Agent (framework-held) | No | **Wrong fit** — tests models, not memory systems |
| AMB harness | 2026 | PM harness | N/A | **The on-ramp** |
| BEAM | 2026 | Persistent memory | Not yet | Good for scale |
| LifeBench | 2026 | Personalization (non-declarative) | No | Niche |
| MemBench | 2025 | Persistent memory | No | Plausible |
| MemSim | 2024 | Simulator | N/A | **Methodology worth borrowing** |
| PersonaMem / v2 | 2025–26 | Personalization | No (37–48% top scores) | **Strong for scope system** |
| DMR | 2023 | Persistent memory | Yes | Legacy |
| NIAH | 2023 | **Long-context only** | Yes | Not applicable |
| RULER | 2024 | **Long-context only** | N/A | Not applicable |
| HELMET | 2024 | **Long-context only** | N/A | Not applicable |
| BABILong | 2024 | **Long-context only** | N/A | Not applicable |
| StreamBench | 2024 | Online learning | N/A | Tangential |

Full details, links, and numbers in [`benchmark-inventory.md`](benchmark-inventory.md).

---

## What the user's sources actually turned into

- **Both HN threads (46943506 and 47491466)** turned out to be about Mozilla Cq / "Stack Overflow for AI agents", not about agent memory benchmarks directly. The Cq thread's top-comment skepticism — poisoning, compounding hallucination, trust infrastructure for shared memory — does map onto `enterprise-requirements.md`. The first thread is essentially a duplicate with no new signal and may have been mis-linked.
- **nexmem-mcp** is a close comparable MCP memory server (entity/relation style, multi-backend storage) with **no benchmark data of its own**.
- **Hindsight blog + agentmemorybenchmark.ai** are the same project: Vectorize's Agent Memory Benchmark. Live leaderboard, open-source harness, eight datasets bundled. This is the most actionable single source reviewed.
- **arxiv 2602.16313** was flagged by the user as possibly invalid. **It resolves** — MemoryArena, Feb 19 2026, He et al., MIT/UW/CMU/UCSD. The format YYMM.NNNNN with YY=26 MM=02 is a legitimate February 2026 paper. Current date is 2026-04-08, so this is six weeks old. Its key finding (agents good at long-context are bad at multi-session memory) is the single cleanest independent corroboration of Finding #3 above.

---

## Discussion outcome (2026-04-08)

After working through this research the team decided **not to pursue any of the public benchmarks** — not LoCoMo, not LongMemEval, not MemoryAgentBench, not AMB. Chasing scores on benchmarks built for a different problem shape would bend MemoryHub's architecture toward being an also-ran in a crowded pool. The research above still stands as an honest read of the landscape; it simply does not translate into a "run this benchmark next" action.

### Framing that came out of the discussion

The cleanest vocabulary we found for explaining what MemoryHub is:

- **Semantic memory** — facts, knowledge, shared corpora, retrievable 24×7. This is RAG and its descendants, including GraphRAG. The library in the analogy we kept coming back to.
- **Episodic memory** — time-indexed, private, experiential. "The librarian told me the best fiction is on the back-right shelf." Not in the corpus; belongs to this user, this project, this session; shapes the next decision.
- **Procedural memory** — private tactics and workflows ("how I navigated this kind of problem last time") that persist across sessions.

**MemoryHub is the episodic + procedural layer with editorial governance.** It is deliberately *not* the semantic layer. A separate hub project in planning targets the semantic side with the same governance posture; together they form a two-hub stack for agents operating in regulated environments. The scoping is intentional and should shape how the roadmap is explained externally — MemoryHub is not trying to replace GraphRAG, vector stores, or knowledge graphs, and it is not trying to be one end-to-end memory platform.

The one-line summary that kept landing in conversation: **nobody in the public literature is measuring the librarian.** Every benchmark in `benchmark-inventory.md` measures the library, more or less well. MemoryHub's differentiators — branches carrying intent (rationale, provenance, evidence, approval), scope as a first-class access-control boundary, versioning with `isCurrent` as a normal query shape, a pluggable three-layer curator — are all librarian properties. None of them score on any benchmark reviewed here.

### How we will actually evaluate

Not by authoring a MemoryHub-branded benchmark. Not by bending the architecture to win on existing ones. The honest evaluation path is:

- **Agent-level evals with memory ablation.** Use existing agent evaluation harnesses (AgentBench-style suites, the RHOAI / Kagenti agent-eval stacks as they land) and run the same agent configuration with MemoryHub on and with it off. Grade the agent-level metrics that reward multi-session retention, freshness handling, scope respect, and auditable behaviour. The memory layer is a lever; the agent is what gets graded. This is the strongest signal available to us and it does not require anyone outside the team to adopt a new benchmark.
- **A governance rubric we publish.** Modelled on frameworks like Atlan's six-risk or DASF v3.0, scoring MemoryHub and comparable systems against auditability, isolation, poisoning resistance, deletion provability, staleness handling, and cost. Not a leaderboard — a scorecard. Our strongest columns (scope isolation, provenance, versioning) become legible without waiting for the academic community to catch up.
- **Adversarial red-team runs on what already shipped.** Particularly the scope-isolation and tenant-isolation code from #46 Phase 4. Public benchmarks do not touch this; an in-house adversarial test is the only way to pressure-test it.

### Primary value story

Regulated customers — government, financial services, healthcare, defence — where governance is not a nice-to-have and where flat vector memory is structurally disqualified. The long form is in `enterprise-requirements.md`. The short version: every item the enterprise governance literature says memory-layer-only tools cannot deliver (Atlan's six risks, DASF v3.0 per-user namespacing, GDPR Art. 17 provable deletion, EU AI Act Art. 12 audit trails) is either already shipped in MemoryHub or is the natural next extension of what it is. The research did not change the roadmap. It confirmed that the roadmap is aimed at a real gap.

### Items the research surfaced that still want a decision (not now)

These are not being acted on in this session. They are recorded here so a future retrospective can pick them up:

- **Audit log (#67)** is the linchpin for four of the enterprise requirements (auditability, provable deletion, decision traceability, FIPS story). Its hold-state is the single biggest governance blocker.
- **Poisoning resistance** has no design and no issue. The curator-agent is the right structural home.
- **Cost instrumentation** is zero. Any external conversation about "good memory at reasonable cost" is unanswerable today.
- **Staleness / upstream invalidation** becomes blocking the day org-ingestion ships.
