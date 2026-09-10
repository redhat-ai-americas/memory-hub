# Characterizing the Performance Envelope of Flat-File Storage for Agent Memory Systems

Status: research plan, not started.

## Thesis

Hybrid storage (flat files + derived index) has a quantifiable cost envelope compared to native database storage for agent memory, and that envelope is predictable from corpus characteristics. The paper characterizes the trade-off curve so system designers can make an informed backend choice without running their own benchmarks.

## Motivation

Agent memory systems face a storage format decision: database-native (SQLite, PostgreSQL+pgvector) vs. flat files (markdown, JSON lines) with derived search indexes. Flat files offer human readability, git trackability, and portability. Database-native storage offers transactional consistency, indexed search, and predictable performance. No published work quantifies the crossover point where the flat-file overhead exceeds its benefits.

The MemoryHub personal edition provides a controlled environment for this comparison: the same retrieval pipeline (five-signal RRF hybrid search), the same embedding model, the same service layer, with only the storage backend varying. This eliminates confounds from algorithmic differences and isolates the storage format as the independent variable.

## What we can measure (no user study required)

### 1. Retrieval equivalence under perturbation

The clean case (sidecar index in sync with files) is trivially equivalent to native storage. The interesting case: how much does retrieval quality degrade when the sidecar is stale?

- Run AMB PersonaMem against a sidecar that is N edits behind the filesystem (N = 1, 5, 10, 50, 100 edits).
- Measure R@5, MRR, and precision at each staleness level.
- Compare to the native SQLite backend (which is always consistent).
- Result: a quality-vs-staleness curve that characterizes the consistency cost of derived indexes.

### 2. The rebuild cost function

Not just "how long does rebuild take" but "what predicts the cost."

Independent variables:
- Memory count (100, 500, 1K, 2K, 5K, 10K, 25K, 50K)
- Mean content length (short: 100 chars, medium: 500 chars, long: 2000 chars)
- Embedding dimensionality (384-dim baseline, 768-dim comparison)
- Filesystem type (APFS on macOS, ext4 on Linux, NTFS on Windows/WSL)

Dependent variables:
- Full rebuild time (cold start, no sidecar)
- Incremental rebuild time (N files changed since last sync)
- Peak memory usage during rebuild

Goal: fit a predictive model (linear or piecewise-linear) from corpus characteristics to rebuild time. A reusable result for anyone building a similar system.

### 3. Write amplification

Per-write overhead comparison at various scales.

Markdown backend write path: serialize YAML frontmatter, write temp file, atomic rename, update sidecar metadata table, update FTS5 entry, generate and store embedding. Six operations.

SQLite backend write path: single transaction with ORM insert + FTS5 trigger + embedding column update. One transaction.

Measure:
- Per-write latency at each scale point (100 to 50K memories)
- Whether write amplification is constant or grows with corpus size
- Fsync cost (the atomic rename forces a sync; SQLite WAL mode batches syncs)

### 4. The git tax

Git is a core part of the flat-file value proposition. Its performance ceiling directly bounds the useful range.

Measure at each scale point (100 to 50K memories), with and without directory sharding:
- `git status` latency
- `git add .` latency
- `git commit` latency
- `git diff` latency (against previous commit)
- `git clone` time and transfer size
- Repo size growth over 1,000 simulated write/update/delete operations

Sharding strategies to compare:
- Flat directory (all files in one dir)
- Two-level sharding by logical_id prefix (`7a/3b1c2d.md`)
- Date-based sharding (`2026/09/7a3b1c2d.md`)

### 5. Format comparison

Same retrieval pipeline, same corpus, different serialization formats:

| Backend | Serialization | Index |
|---------|--------------|-------|
| SQLite (baseline) | ORM rows | Native FTS5 + brute-force cosine |
| Markdown + sidecar | YAML frontmatter + markdown body | Sidecar SQLite (FTS5 + brute-force cosine) |
| JSON lines + sidecar | One JSON object per line in append-only file | Sidecar SQLite |
| Claude Code format | Markdown with frontmatter in `~/.claude/` | None (grep-based) |

Measure retrieval quality (should be identical) and operational metrics (startup, query, write, rebuild) at each scale point.

## What we cannot measure (and what we say about it)

**Human utility.** The primary benefit of flat-file storage is direct editability — users can open, read, and modify memories with standard text tools. Without a user study, we cannot measure when this benefit stops mattering. We note that an OKF-style viewer could decouple the editing experience from the storage format entirely, making the performance envelope the dominant selection criterion. This is a single paragraph in the discussion, not a claim.

**Edit frequency in the wild.** We hypothesize that direct file edits drop to near-zero above ~5-10K memories, but we have no telemetry to support this. Future work with opt-in instrumentation in deployed systems.

## Experimental infrastructure

**Corpus generation.** Synthetic memories with realistic content distributions sampled from real agent conversations (content length, domain tag distribution, scope distribution, version chain depth). Parameterized generator that produces N memories at a specified scale point.

**Benchmark harness.** Extends the existing MemoryHub AMB harness. Runs the same benchmark corpus against pluggable storage backends. Reports retrieval quality metrics and operational latency metrics in a unified format.

**Hardware matrix.** At minimum: one modern Mac (Apple Silicon, APFS) and one Linux machine (x86_64, ext4). Ideally also WSL on Windows (NTFS) since many developers use that environment.

## Paper structure (sketch)

1. Introduction: the storage format decision for agent memory systems
2. Background: hybrid retrieval pipelines, flat-file-with-derived-index pattern (Obsidian, Logseq, Claude Code)
3. System description: MemoryHub's retrieval pipeline and the RecallBackend abstraction
4. Experimental setup: corpus generation, benchmark harness, hardware
5. Results:
   - 5a. Retrieval equivalence (clean and under perturbation)
   - 5b. Rebuild cost model
   - 5c. Write amplification
   - 5d. Git performance tax
   - 5e. Format comparison
6. Discussion: the crossover point, OKF viewer as a decoupling strategy, limitations (no user study)
7. Related work: Obsidian/Logseq ecosystem, agent memory benchmarks (AMB, LongMemEval), vector database benchmarks
8. Conclusion: decision framework for storage format selection

## Target venue

Workshop paper (4-6 pages): latency curves + retrieval equivalence + format comparison. Enough for a solid contribution.

Full paper (8-10 pages): add the cost model, git tax analysis, and the perturbation study. Stronger contribution with the predictive model.

## Related work to cite

- AMB benchmark (PersonaMem, LongMemEval) — retrieval quality measurement
- Obsidian/Logseq/Dendron — markdown with derived indexes for knowledge management
- RRF (Cormack et al., 2009) — the fusion algorithm used in the retrieval pipeline
- Vector database benchmarks (ann-benchmarks, VectorDBBench) — ANN performance characterization
- The MemoryHub retrieval pipeline doc (`docs/design/retrieval-pipeline.md`) and two-vector design (`docs/design/two-vector-retrieval.md`)

## Relationship to other MemoryHub work

This research builds on the markdown storage backend design exploration at `planning/markdown-storage-backend.md`. The design doc provides the architecture; this paper provides the empirical validation (or invalidation) of its scale hypothesis.

The benchmark infrastructure can be built on top of the existing AMB harness at `benchmarks/amb-harness/`. The corpus generator and backend-comparison framework would be new.
