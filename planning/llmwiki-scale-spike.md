# Spike: LLMWiki / OKF Format at Scale vs MemoryHub

**Status:** Proposed
**Date:** 2026-09-16
**Audience:** Architecture team
**Question:** "Could we use markdown files with YAML frontmatter (OKF format / llm-wiki pattern) instead of PostgreSQL?"

---

## 1. Why This Spike Exists

The architecture team has raised a good question: whether MemoryHub could use a file-based storage format (markdown with YAML frontmatter) instead of PostgreSQL. The llm-wiki pattern and OKF spec are appealing for their simplicity, portability, and human-readability, and their success at personal scale (Karpathy reports ~100 articles / ~400K words working well) makes the question worth investigating seriously. The qualitative tradeoffs (governance, RBAC, concurrent writes, contradiction detection) are documented in `research/surveys/knowledge-and-graph-memory.md` Sections 7-8, but qualitative arguments go only so far. What's missing is **performance data at the scale we're targeting**: 10M memories, 5k concurrent users.

This spike produces that data. The deliverable is a benchmark report showing where file-based storage excels, where it struggles, and where the crossover points are, so we can make the decision together from numbers rather than assumptions.

## 2. What We're Comparing

Three tiers, tested at four scale points (10K, 100K, 1M, 10M memories):

| Tier | Storage | Search | Represents |
|------|---------|--------|------------|
| **T1: Pure OKF** | Directory of .md files with YAML frontmatter | `grep` / directory traversal / static `index.md` | What the OKF spec and llm-wiki gist actually describe |
| **T2: OKF + Search Infra** | Same files on disk, plus SQLite FTS5 + FAISS IVF index | FTS5 keyword search + FAISS ANN vector search + RRF merge | The best-case file-based architecture: markdown as the source of truth, with purpose-built indexes layered on top |
| **T3: MemoryHub** | PostgreSQL + pgvector + tsvector | Hybrid RRF (vector cosine + tsvector keyword + scope filter) | Current architecture |

T2 is the critical comparison. If T2 performs comparably to T3, the file format is viable at scale and we should investigate further. If T2 trails significantly, the spike quantifies the gap and identifies which specific operations drive it.

### What We're Not Comparing

- **Git versioning at scale.** Git with 10M files hits known index-size limits. Worth a separate investigation if file-based storage looks promising, but not the question this spike answers.
- **Graph traversal.** OKF has no graph model. Apples-to-oranges.
- **Reranking.** Both sides would need an LLM/cross-encoder call. Cancels out.
- **Embedding generation.** We use synthetic 384-dim vectors so we test index performance, not embedding throughput. Both backends would use the same embedding infra in production.

## 3. Workloads

### W1: Search Latency (the core question)

100 queries per scale point, measuring p50 / p95 / p99 latency:

- **Semantic search**: find memories similar to a query embedding (top-10)
- **Keyword search**: find memories matching a text query
- **Hybrid search**: RRF blend of semantic + keyword (MemoryHub's default path)
- **Filtered search**: same as above but scoped to one tenant (1/100th of the corpus) -- this is where multi-tenancy cost shows up

Each query runs cold (no cache) and warm (after index is hot). All three tiers run the same 100 queries for direct comparison.

### W2: Concurrent Write Throughput

Simulate 5,000 users each writing one memory concurrently:

- **T1**: 5,000 concurrent file creates in a shared directory (asyncio + aiofiles)
- **T2**: same as T1, plus synchronous SQLite FTS + FAISS index updates
- **T3**: 5,000 concurrent `INSERT` via asyncpg connection pool

Measure: wall-clock time, failures, data integrity (all 5,000 memories retrievable after).

For T1 and T2, also measure what happens when two writers update the same memory simultaneously (last-write-wins corruption vs. transaction isolation).

### W3: Storage Footprint

At each scale point, measure total disk consumption:

- **T1**: file count, inode usage, total bytes (including filesystem overhead -- ext4 4KB block minimum)
- **T2**: T1 + SQLite DB size + FAISS index size
- **T3**: `pg_total_relation_size('memory_nodes')` including indexes

### W4: Cold Start / Index Build Time

How long to go from raw data to searchable state:

- **T1**: N/A (files are immediately "searchable" via grep)
- **T2**: time to build FTS5 index + FAISS index from 10M files
- **T3**: time to bulk-load 10M rows + build pgvector HNSW index + GIN index on tsvector

This matters for disaster recovery and fresh deployments.

## 4. Data Generation

Synthetic memories matching MemoryHub's real distribution:

- **Stub**: 30-80 tokens (1-2 sentences)
- **Content**: 100-2,000 tokens, log-normal distribution centered around 400 tokens
- **Frontmatter fields**: scope (7 values, weighted), domains (1-4 tags from a pool of 50), weight (0.0-1.0), content_type (3 values), tenant_id (100 tenants, Zipf-distributed so some tenants have 500K+ memories and most have <10K)
- **Embeddings**: 384-dim random unit vectors (synthetic, but correctly normalized for cosine similarity testing)

A Python generator script produces the dataset once and writes it to a shared PVC. All three tiers read from the same generated data.

## 5. Cluster Resources

### Namespace

`memoryhub-spike` -- isolated from the production `memoryhub-db` and `memory-hub-mcp` namespaces.

### PVCs

| PVC | Size | Access Mode | Purpose |
|-----|------|-------------|---------|
| `spike-generated-data` | 5Gi | ReadWriteOnce | Raw generated data (JSONL, one record per line) |
| `spike-okf-files` | 80Gi | ReadWriteOnce | T1/T2: 10M markdown files on ext4. 10M small files with 4KB block minimum = ~40GB actual. Budget 80Gi for headroom + index files. |
| `spike-sqlite-faiss` | 30Gi | ReadWriteOnce | T2: SQLite FTS5 DB (~10GB at 10M docs) + FAISS IVF index (~6GB for 384-dim × 10M vectors) |
| `spike-pg-data` | 50Gi | ReadWriteOnce | T3: PostgreSQL data directory. 10M rows with vectors + tsvector + indexes ≈ 25-35GB |

**Total PVC: ~165Gi**

### Pods

| Pod | Image | CPU | Memory | Notes |
|-----|-------|-----|--------|-------|
| `spike-pg` | `pgvector/pgvector:0.8.2-pg16` | 2 cores | 4Gi | Dedicated PostgreSQL for the spike. Higher resource limits than prod (256Mi/1 core) because HNSW index build is memory-hungry at 10M vectors. `shared_buffers=1GB`, `work_mem=256MB`, `maintenance_work_mem=1GB`. |
| `spike-runner` | UBI9 + Python 3.11 | 4 cores | 8Gi | Runs all workloads. Needs memory for FAISS index (loaded in-process) and asyncio concurrency. Mounts all four PVCs. |

**Total compute: 6 cores, 12Gi memory (during spike only -- tear down after).**

### Why These Sizes

**The 80Gi OKF PVC** is larger than you might expect for ~12GB of content. ext4 allocates a minimum 4KB block per file regardless of content size, and each file needs an inode (256 bytes) and directory entry. At 10M small files, filesystem overhead runs 3-4x the content size. Quantifying this overhead is one of the spike's goals.

**The 50Gi PostgreSQL PVC** is generous. PostgreSQL TOAST-compresses text columns over 2KB and shares B-tree/GIN/HNSW indexes across all rows. Estimated actual usage is 25-35GB, but we budget headroom for temp files during index builds and WAL during concurrent writes.

### Duration

| Phase | Estimated Time | Notes |
|-------|---------------|-------|
| Data generation (10M records) | ~15 min | CPU-bound JSONL generation, parallelizable |
| T1: Write 10M files to PVC | ~45-90 min | Inode allocation is the bottleneck at 10M files; may hit ext4 inode limits |
| T2: Build FTS5 + FAISS indexes | ~30-60 min | FAISS IVF training on 10M vectors; SQLite bulk insert |
| T3: Bulk load PostgreSQL + build indexes | ~30-60 min | `COPY` for data, then `CREATE INDEX CONCURRENTLY` for HNSW |
| W1-W4 workloads (all scales, all tiers) | ~2-3 hours | Runs each workload at 10K/100K/1M/10M; smaller scales are fast |

**Total estimated wall-clock: 4-6 hours.** Single-run, tear down after.

## 6. Implementation Outline

```
benchmarks/scale-spike/
  generate_data.py       # Synthetic memory generator → JSONL
  tier1_okf.py           # File-based storage: write + grep search
  tier2_okf_indexed.py   # File-based + SQLite FTS5 + FAISS
  tier3_memoryhub.py     # PostgreSQL + pgvector + tsvector
  runner.py              # Orchestrates all workloads, collects metrics
  report.py              # Generates HTML report with charts (plotly)
  Containerfile          # UBI9 + Python + deps
  job.yaml               # K8s Job manifest (mounts PVCs, runs runner.py)
  postgres.yaml          # Spike-specific PostgreSQL StatefulSet
  pvcs.yaml              # All four PVCs
  kustomization.yaml     # Tie it together
```

The Job runs `runner.py`, which:
1. Calls `generate_data.py` if the generated-data PVC is empty
2. Runs each tier's setup (file writes, index builds, bulk load)
3. Executes W1-W4 at each scale point
4. Writes results to `results.json` on the generated-data PVC
5. Calls `report.py` to produce `report.html`

Results are extracted from the PVC via `oc cp` after the job completes.

## 7. Expected Outcome

Based on filesystem behavior at scale and PostgreSQL benchmarks, the predicted results (to be validated or refuted by the spike):

| Metric | T1: Pure OKF | T2: OKF + Infra | T3: MemoryHub |
|--------|-------------|-----------------|---------------|
| Search p95 (10M, hybrid) | >10s (grep) | ~200-500ms | ~50-150ms |
| Search p95 (10M, filtered to 1 tenant) | ~same as unfiltered (grep scans everything) | ~100-300ms (FAISS partition + FTS5 filter) | ~20-80ms (B-tree index on tenant_id prunes before vector scan) |
| Concurrent write (5k users) | Filesystem contention, possible corruption | SQLite writer lock serializes all writes (one at a time) | Connection pool, row-level locks, ~5-15s wall clock |
| Storage at 10M | ~40-50GB | ~55-65GB (files + indexes) | ~25-35GB |
| Cold start (index build) | N/A | ~45-60 min | ~30-45 min |

**Hypothesis to test:** T2 may underperform T3 at large scale because maintaining consistency between files and indexes adds overhead, and SQLite's single-writer lock constrains concurrent writes. If the data confirms this, we'll know the crossover point. If it doesn't, we'll have evidence that the file-based architecture scales better than expected.

## 8. What the Architecture Team Gets

A report containing:

1. **Four charts** (one per workload) showing latency/throughput/storage across scale points for all three tiers. Log-scale x-axis (10K to 10M), clear visual separation between tiers.

2. **The storage-overhead chart** showing that file-per-memory storage at 10M entries costs 2-3x more disk than PostgreSQL due to filesystem block allocation -- before you even add search infrastructure.

3. **The concurrent-write chart** showing SQLite's writer lock serializing 5,000 writes vs. PostgreSQL handling them in parallel.

4. **A one-page summary** identifying the crossover points: at what scale does file-based storage need additional infrastructure, and what does that infrastructure cost in complexity and performance? The llm-wiki pattern works well at the scales Karpathy reports (~100 articles); this spike finds where the scaling curve bends.

5. **A clear recommendation** on the right storage strategy for MemoryHub's target scale (10M memories, 5k users), with data to support it either way.

## 9. Risks and Mitigations

| Risk | Mitigation |
|------|-----------|
| ext4 inode exhaustion at 10M files | Format PVC with `-N` flag for high inode count, or use XFS (default on RHEL/OpenShift) which allocates inodes dynamically |
| FAISS index doesn't fit in 8Gi runner memory | Use IVF with on-disk index (`faiss.write_index` + `mmap`) instead of flat in-memory |
| PostgreSQL HNSW build OOMs at 10M vectors | Set `maintenance_work_mem=1GB`; if still OOMs, build IVFFlat index instead (faster build, slightly worse recall) |
| Spike PVCs consume quota needed for production | Use `memoryhub-spike` namespace with separate ResourceQuota; tear down immediately after |
| Synthetic vectors give unrealistically good/bad recall | We're measuring *latency and throughput*, not recall quality. Synthetic vectors are correct for this purpose. |

## 10. Decision Criteria

After the spike, the recommendation to the architecture team:

- **If T2 ≈ T3 on all metrics**: the file format is viable at scale, and we should investigate OKF as a primary storage format (unlikely based on prior art, but data wins over intuition).
- **If T2 is 2-5x worse than T3**: file-based storage works but costs more. Viable for personal/small-team use. MemoryHub should support OKF as an export/import format (already planned, #560).
- **If T2 is >5x worse on any critical metric**: file-based storage is not viable at our target scale. MemoryHub should support OKF as an interchange format for import/export and personal-scale use, but not as the primary storage backend.
