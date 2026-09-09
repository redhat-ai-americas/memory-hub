# Benchmarks

Retrieval quality and performance benchmarks for MemoryHub.

## Results Summary

**AMB PersonaMem 32k** (589 MCQ queries across 195 conversation transcripts, 37 personas):

- **83.7%** accuracy with Gemini 3.1 Pro Preview, Granite embeddings + reranker
- Submitted to the [AMB leaderboard](https://agentmemorybenchmark.ai) as [PR #34](https://github.com/vectorize-io/agent-memory-benchmark/pull/34), pending review
- Best internal result: 84.9% (same pipeline, internal harness)

**LongMemEval oracle** (500 session-retrieval questions):

- R@5=0.999, R@10=1.000, MRR=1.000
- Oracle variant only (evidence sessions as haystack, not full 115K-token corpus)

Full results with methodology, per-run configurations, ablation data, and competitive
context are in [RESULTS.md](RESULTS.md).

## Directory Layout

```
benchmarks/
├── RESULTS.md                 # Living results document (all runs, methodology, analysis)
├── amb-harness/               # Vendored AMB harness with MemoryHub provider adapter
├── amb-outputs/               # Archived AMB output files by provider/config
├── evalhub-adapter/           # EvalHub integration (BYOF adapter for TrustyAI)
├── results/                   # Human-readable result summaries and analysis
├── preflight.py               # Pre-run deployment validation
├── analyze-failures.py        # Post-run failure analysis
└── *.json                     # Raw result files (committed for reproducibility)
```

## Benchmarks

| Benchmark | What it measures | Status |
|-----------|-----------------|--------|
| AMB PersonaMem 32k | End-to-end preference tracking across long conversations | Submitted to leaderboard, pending review |
| LongMemEval oracle | Session-level retrieval (small haystack) | Run internally, not submitted |
| Cluster retrieval | Hybrid vs vector-only on production memories | Internal |
| Retrieval at scale | pgvector latency scaling (100 to 10K items) | Internal |
| Cross-encoder pool sweep | Reranker candidate pool size optimization | Internal |

## Running Benchmarks

Benchmarks run against a deployed MemoryHub cluster. The primary benchmark (AMB PersonaMem)
requires:

1. A running MemoryHub instance with Granite embedding + reranker models
2. A Gemini API key for the answer LLM
3. The AMB harness environment set up in `amb-harness/`

```bash
cd benchmarks/amb-harness
cp .env.example .env    # configure credentials
uv run omb run --provider memoryhub --dataset personamem --split 32k
```

See `amb-harness/README.md` for full setup instructions.

## Leaderboard Submissions

| Leaderboard | Status | Score | Date |
|-------------|--------|-------|------|
| [AMB](https://agentmemorybenchmark.ai) | PR submitted, pending review | 83.7% PersonaMem 32k | 2026-08-21 |
| [AML](https://agentmemories.ai) | Not yet submitted (target ~Nov 2026) | TBD | -- |
