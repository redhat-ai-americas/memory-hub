# Running AMB Benchmarks

## Prerequisites

1. **Port-forward to MemoryHub PostgreSQL:**
   ```bash
   oc port-forward statefulset/memoryhub-pg 25432:5432 --context mcp-rhoai -n memoryhub-db
   ```

2. **Embedding and reranker services** are exposed via OpenShift routes (hardcoded in the provider, no setup needed).

3. **Install the harness:**
   ```bash
   cd benchmarks/amb-harness
   uv sync
   ```

4. **API key** -- set one of:
   ```bash
   export GEMINI_API_KEY=...      # For Gemini models
   export GOOGLE_API_KEY=...      # Same key, alternative name
   export ANTHROPIC_API_KEY=...   # For Claude models
   ```

## Running a benchmark

### Gemini (leaderboard-comparable)

```bash
# Flash Lite -- cheap (~$0.35/provider for PersonaMem 32k)
PYTHONPATH=../../src:$PYTHONPATH \
GOOGLE_API_KEY=$GEMINI_API_KEY \
OMB_ANSWER_LLM=gemini OMB_JUDGE_LLM=gemini \
OMB_ANSWER_MODEL=gemini-3.1-flash-lite \
uv run omb run --dataset personamem --split 32k --memory memoryhub -o ../../benchmarks/amb-outputs

# Pro Preview -- matches AMB leaderboard (~$19/provider for PersonaMem 32k)
OMB_ANSWER_MODEL=gemini-3.1-pro-preview \
# ... same as above
```

### Anthropic

```bash
PYTHONPATH=../../src:$PYTHONPATH \
OMB_ANSWER_LLM=anthropic OMB_JUDGE_LLM=anthropic \
OMB_ANSWER_MODEL=claude-haiku-4-5-20251001 \
uv run omb run --dataset personamem --split 32k --memory memoryhub -o ../../benchmarks/amb-outputs
```

### BM25 baseline (run with same LLM for comparison)

```bash
# Same command but --memory bm25 (no --skip-ingestion needed, BM25 is local)
uv run omb run --dataset personamem --split 32k --memory bm25 -o ../../benchmarks/amb-outputs
```

## Available datasets (MCQ -- no judge LLM needed)

| Dataset | Split | Queries | Documents |
|---------|-------|---------|-----------|
| personamem | 32k | 589 | 195 |
| memsim | * | varies | varies |
| membench | * | varies | varies |

## Available datasets (open-ended -- requires judge LLM)

| Dataset | Split | Queries |
|---------|-------|---------|
| locomo | locomo10 | 1,540 |
| longmemeval | s | 500 |
| beam | 100k-10m | varies |
| lifebench | en | 2,003 |

## Notes

- The MemoryHub provider uses `amb-*` tenant IDs to isolate benchmark data from production.
- First run ingests documents; use `--skip-ingestion` on subsequent runs with the same dataset.
- The reranker returns 413 on PersonaMem's long transcripts; search falls back to cosine ranking.
- Results are saved to `<output-dir>/<dataset>/<provider>/rag/<split>.json`.
- Use `--query-limit N` for quick smoke tests.
