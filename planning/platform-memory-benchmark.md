# Platform-Level Memory Management Benchmark: Preliminary Design

**Status:** Preliminary landscape analysis + design sketch (for #337)
**Date:** 2026-07-11
**Revised:** 2026-07-11 (review pass: corrected PersonaMem attribution, added cost dimension, dimension sequencing)
**Author:** @rdwj (designed with Claude Code Opus 4.6)

---

## 1. The Gap: Nobody Grades the Librarian

Agent memory benchmarks measure retrieval -- "given a collection of memories, can you find the right one?" This is necessary but insufficient. A memory system that perfectly retrieves memories but never curates, deduplicates, detects patterns, resists poisoning, or improves over time is a filing cabinet, not a librarian.

The compound value of good memory management is unmeasured:
- Does proactive curation improve retrieval quality over time?
- Does conflict detection prevent stale memories from misleading agents?
- Does pattern recognition surface insights that no single trace contains?
- Does poisoning resistance protect the agent's decision-making?
- Does governed lifecycle management (retention, compaction, versioning) keep the collection healthy?

MemoryHub builds all of these capabilities. Without a benchmark, their value is anecdotal.

## 2. Existing Benchmark Landscape

### Retrieval-focused ("measuring the library")

| Benchmark | Year | What it measures | Scoring | Limitations |
|-----------|------|-----------------|---------|-------------|
| PersonaMem | 2025 | Personal preference tracking across sessions | MCQ exact match | Only tests recall of stated preferences; no curation pressure |
| LoCoMo | 2024 | Multi-session conversational QA | LLM judge | 6.4% ground-truth errors found in 2026 audit; judge accepts 63% of intentionally wrong answers |
| LongMemEval | 2025 | Six question types over long conversations | LLM judge | Oracle variant isolates retrieval; full variant mixes retrieval with haystack filtering |
| BEAM | 2026 | 100K-10M token conversations, 2000 questions | Nugget scoring (fine-grained) | Pure retrieval; no management pressure |
| LongMemEval-V2 | 2026 | Web agent trajectories, "experienced colleague" framing | Task success | Closest to measuring downstream value, but web-agent-specific |

### Capability-focused ("measuring some library skills")

| Benchmark | Year | What it measures | Key insight |
|-----------|------|-----------------|-------------|
| MemoryAgentBench | ICLR 2026 | Four axes: retrieval, test-time learning, long-range understanding, conflict resolution | Conflict resolution is the closest axis to "librarian quality" -- detecting and overwriting outdated facts |
| AMA-Bench | 2026 | Separates memory processing from retrieval | Processing axis = extraction quality (dreaming); but evaluated per-trace, not over time |

### Poisoning resistance ("measuring collection security")

| Work | Year | Key finding |
|------|------|-------------|
| MINJA | 2026 | 95% injection success rate, 70% attack success rate |
| FARMA | 2026 | Forges reasoning history; 100% attack success against existing defenses |
| SENTINEL | 2026 | Reasoning Guard reduces FARMA to 0% success with zero false positives |
| PoisonedRAG | 2024 | 5 malicious docs in millions cause 90% attack success |
| OWASP ASI06 | 2026 | Memory and Context Poisoning recognized as deployment-relevant attack class |

No standard benchmark exists. Each paper brings its own attack/defense setup.

### What nobody measures

1. **Curation quality over time.** Does the memory collection get better-organized as the system runs? Metrics: duplicate ratio, staleness ratio, average memory freshness, coverage of user's actual topics vs stored topics.

2. **Pattern emergence.** Can the system surface insights from memory evolution that no single trace contains? The cheese test: after N preference updates, does the system recognize the exploration pattern?

3. **Compound agent improvement.** Does a well-managed memory system make the agent measurably better at downstream tasks over time? Not just "can you retrieve X" but "does your task success rate improve as your memory collection matures?"

4. **Governance under pressure.** Under concurrent multi-agent writes, adversarial inputs, and high churn: does the system maintain integrity? Metrics: false acceptance rate (poisoned memories that pass curation), false rejection rate (legitimate memories incorrectly blocked), consistency under concurrent writes.

5. **Lifecycle management.** Do retention policies, compaction, and versioning keep the collection healthy? Metrics: growth rate with and without lifecycle management, retrieval quality degradation over time, ability to answer "what did I think about X three months ago?" (temporal reasoning over versions).

## 3. Design Principles for a Platform Benchmark

### Measure over time, not at a point

Existing benchmarks are snapshots: ingest documents, run queries, score. A platform benchmark must run over a simulated timeline -- days or weeks of agent interactions -- and measure how the memory collection evolves. The score at day 30 matters more than the score at day 1.

### Measure the management, not just the retrieval

Retrieval accuracy is one metric, not the metric. The benchmark should independently score:
- **Retrieval quality** (existing benchmarks handle this)
- **Collection health** (duplicate ratio, staleness, coverage)
- **Conflict handling** (correct updates vs stale persistence vs duplication)
- **Pattern detection** (insights surfaced from version history)
- **Resilience** (behavior under adversarial writes)
- **Downstream improvement** (agent task performance over time)

### Separate the library from the librarian

A system that stores raw text and retrieves well is a good library. A system that also curates, extracts, reconciles, and reflects is a good librarian. The benchmark should score both independently and in combination, so the marginal value of each capability is visible.

### Reproducible without proprietary infrastructure

The benchmark should run against any memory system that exposes CRUD + search operations. No dependency on specific vector databases, LLMs, or cloud services. Provide a standard interface (similar to AMB's MemoryProvider ABC) and let systems implement it.

## 4. Preliminary Benchmark Dimensions

### Dimension 1: Temporal Consistency (the cheese test, generalized)

**Setup:** A synthetic user expresses preferences across 50 sessions over simulated 30 days. Some preferences are stable ("I'm a vegetarian"), some evolve ("favorite cheese" changes 4 times), some are one-time corrections ("actually my name is spelled Wes, not Wesley").

**Scoring:**
- At each checkpoint (day 7, 14, 21, 30), query the system for current preferences
- Correct current value: +1
- Stale value (superseded preference): -1
- Both current and stale returned: -0.5 (duplication)
- Version history accessible when asked "what did I used to prefer?": +0.5 bonus

**What it measures:** Conflict resolution + lifecycle management. Systems that store raw traces will accumulate stale values. Systems with extraction + reconciliation will maintain current state. Systems with versioning can answer temporal queries.

**Design principle worth stating explicitly:** this dimension uses exact ground-truth checkpoint queries — no LLM judge. Given LoCoMo's judge accepted 63% of intentionally wrong answers, judge-free scoring wherever ground truth permits is a deliberate credibility feature of this benchmark, not an implementation detail.

### Dimension 2: Collection Health Under Load

**Setup:** 1000 agent sessions produce memories at varying rates. Some sessions produce redundant information (multiple agents discovering the same fact). Some produce contradictions. Some produce noise (low-value observations).

**Scoring at day 30:**
- Duplicate ratio: what fraction of stored memories are semantically redundant?
- Signal-to-noise ratio: what fraction of stored memories are retrievable for meaningful queries?
- Consolidation: were redundant discoveries from multiple agents merged?
- Growth curve: does the collection grow linearly with sessions, or does management flatten the curve?

**What it measures:** Curation quality. Systems without dedup will have high redundancy. Systems with curation will have a healthier collection.

### Dimension 3: Adversarial Resilience

**Setup:** Among the 1000 sessions, 5% contain adversarial writes: factually incorrect memories, prompt injection attempts, or memories designed to mislead future retrieval (PoisonedRAG-style).

**Scoring:**
- False acceptance rate: adversarial memories that survive curation
- False rejection rate: legitimate memories incorrectly blocked
- Retrieval poisoning rate: queries whose top-k results include adversarial memories
- Recovery: after adversarial memories are identified, can the system roll back to a clean state?

**What it measures:** Platform-level security, not per-attack defense. OWASP ASI06 compliance.

**Known v1 limitation:** synthetically labeled adversarial sessions may carry superficial markers a curation pipeline can learn to detect without real robustness. Acceptable for v1; note it in the methodology and plan for attack diversity (paraphrase variants, benign-looking poisoning) in v2.

### Dimension 4: Pattern Emergence

**Setup:** The synthetic user has behavioral patterns embedded in the session data: evolving preferences (cheese test), recurring topics (asks about the same project weekly), seasonal interests (gardening in spring, skiing in winter).

**Scoring:**
- Can the system identify evolving preferences without being asked?
- Can the system surface recurring topics as a pattern?
- Can the system distinguish stable facts from evolving preferences?
- Does pattern detection produce actionable insights or noise?

**What it measures:** Provenance-driven reflection (Layer 3 of the dreaming pipeline). Most systems will score zero here today.

### Dimension 5: Downstream Agent Performance

**Setup:** An agent performs a series of tasks (scheduling, recommendations, Q&A) using the memory system. Tasks are designed so that good memory management improves performance:
- Recommendations should reflect current preferences, not stale ones
- Scheduling should account for known patterns
- Q&A should leverage consolidated knowledge, not raw traces

**Scoring:**
- Agent task success rate at day 1 vs day 30
- Improvement slope: how quickly does the agent get better?
- Regression detection: does any management action (curation, compaction) hurt downstream performance?

**What it measures:** The compound value -- the whole point. Does a well-managed memory system make the agent measurably better?

**Caution:** this is the hardest and most confounded dimension — agent model quality dominates memory quality in task success rates. Treat as v2/aspirational; see "Dimension sequencing" below.

### Dimension 6: Cost Efficiency

**Setup:** Instrument every dimension's run with token and compute accounting: LLM tokens spent on ingestion/extraction, maintenance, and query-time processing, per session ingested.

**Scoring:**
- Cost per session ingested (tokens, and dollars at reference pricing)
- Cost per point of composite score (efficiency frontier)
- Marginal cost of each management capability vs its marginal score contribution

**What it measures:** Extraction pipelines trade tokens for quality; a benchmark that ignores cost favors expensive systems. Reporting cost also rewards architectures that reason over compact metadata (like provenance-driven reflection) rather than re-reading raw traces. Every serious deployer asks this question; no memory benchmark answers it.

### Dimension sequencing

Ship in phases rather than all six at once:

- **v1: Dimensions 1-3 + 6.** Temporal consistency is nearly implementable today (the cheese-test simulator is the only new artifact), collection health and adversarial resilience follow from the same simulator, and cost accounting is instrumentation. All four score without an LLM judge.
- **v2: Dimension 4** (pattern emergence) — needs a reliable scoring method for insights (open question 3).
- **v2+: Dimension 5** (downstream improvement) — most confounded, needs the most design care. Don't let it block publishing v1.

## 5. Implementation Sketch

### Data generation

Synthetic user simulator that produces realistic multi-session interaction traces with controlled properties:
- Known ground-truth preferences (stable + evolving)
- Known redundancies (same fact from multiple sessions)
- Known adversarial inputs (labeled for scoring)
- Known patterns (for pattern detection scoring)

The simulator is the hardest part. It needs to produce traces that feel like real agent interactions while maintaining ground-truth labels for scoring. Consider basing it on PersonaMem's user profiles (which already model diverse personas with evolving preferences) but extending with temporal structure and adversarial examples.

### Memory system interface

```python
class MemoryPlatform(ABC):
    """Interface for platform-level memory benchmark."""
    
    async def ingest_session(self, session: Session) -> None:
        """Process a complete agent session (conversation trace)."""
    
    async def query(self, query: str, user_id: str) -> list[Memory]:
        """Retrieve relevant memories for a query."""
    
    async def run_maintenance(self) -> None:
        """Trigger any background management (curation, reflection, etc)."""
    
    async def get_collection_stats(self) -> CollectionStats:
        """Return collection health metrics."""
    
    async def get_version_history(self, memory_id: str) -> list[Version]:
        """Return version chain for a memory (if supported)."""
```

The `run_maintenance()` call is key -- it gives systems with background processing (dreaming, curation) a chance to run between evaluation checkpoints. Systems without background processing simply no-op.

### Scoring framework

Composite score with weighted dimensions:

| Dimension | Weight | Rationale |
|-----------|--------|-----------|
| Retrieval quality | 0.25 | Table stakes; well-measured elsewhere |
| Temporal consistency | 0.20 | The cheese test; critical for trust |
| Collection health | 0.15 | Long-term system health |
| Adversarial resilience | 0.15 | Security; OWASP ASI06 |
| Pattern emergence | 0.10 | Differentiator; novel |
| Downstream improvement | 0.15 | The compound value |
| Cost efficiency | reported, unweighted | Orthogonal axis; report as $/score frontier rather than folding into the composite |

Weights are preliminary. **Per-dimension scores are the primary output; the composite is secondary.** Composite weights are the first thing competitors will dispute — leading with the per-dimension breakdown (and publishing the weighting as one suggested view) deflects that argument and is more honest about what a single number can capture.

## 6. Strategic Considerations

### Credibility requires self-awareness

Publishing a benchmark where your own product excels invites skepticism. Mitigations:
- Include dimensions where MemoryHub is NOT the best (raw retrieval speed, for example -- pgvector on CPU is slower than Qdrant on GPU)
- Include a "no management" baseline (raw vector store) to show the marginal value of each capability
- Open-source the benchmark suite so others can verify and extend
- Invite external systems (Mem0, Hindsight, Cognee) to run against it
- Publish the methodology before the results

### The AMB precedent

(Corrected 2026-07-11: an earlier draft attributed PersonaMem to Vectorize. PersonaMem is an academic benchmark — Jiang et al., 2025. What Vectorize built is **AMB**, the open harness that runs PersonaMem/LoCoMo/LongMemEval/BEAM against pluggable memory providers, plus Hindsight, the top performer on it.)

The precedent still holds — arguably more strongly, because AMB-the-harness is the closer analog to what we're proposing. Vectorize built the measurement infrastructure, ran their own system against it openly alongside competitors, and published everything (datasets, prompts, scoring, results). It earned credibility because the harness was genuinely useful independent of Hindsight's placement on it. If our platform benchmark measures something genuinely unmeasured (and it does -- nobody grades the librarian), the same dynamic applies: the benchmark must stand on its own as measurement infrastructure, with MemoryHub as one provider among several.

### Naming

Working title: **MemoryMgmt-Bench** or **LibrarianBench**. The name should signal that this measures management quality, not retrieval quality.

## 7. Open Questions

1. **Simulation fidelity.** How realistic do synthetic traces need to be? Too simple and the benchmark is toy; too complex and it's hard to control ground truth.

2. **Temporal compression.** Real memory management plays out over weeks. How do we compress time without losing the signal? Simulated timestamps + explicit maintenance windows?

3. **LLM judge reliability.** LoCoMo's judge accepted 63% of intentionally wrong answers. Pattern emergence scoring especially needs a reliable evaluation method -- possibly human evaluation for the initial version.

4. **Scope of "downstream improvement."** What tasks? Scheduling and recommendations are natural but narrow. Should we include tool use, code generation, or open-ended conversation?

5. **Interaction with existing benchmarks.** Should this be an extension of AMB (additional datasets/dimensions) or a standalone benchmark? AMB integration would give us the existing provider ecosystem; standalone gives us more freedom.

## 8. Related Issues

- #336 -- Dreaming pipeline (builds the capabilities this benchmark measures)
- #334 -- Poisoning resistance (Dimension 3)
- #281 -- Curation agents (Dimension 2)
- #332 -- AMB baseline (Dimension 1 retrieval component)
- #333 -- RRF ablation (understanding signal contribution)
