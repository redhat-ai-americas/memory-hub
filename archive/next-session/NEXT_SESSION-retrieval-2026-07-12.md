# Next Session -- Retrieval Quality (v0.4)

## Next: Complete AMB PersonaMem run and process results

470/589 MemoryHub + Gemini 3.1 Pro Preview queries completed (80.0% accuracy), saved to `benchmarks/amb-outputs/personamem/memoryhub/rag/32k.json` with incremental checkpoints. Hit Gemini RPD limit twice (at query 230 and 470) -- quota recovered after ~70 minutes the first time. A background run is still retrying as of 5:22 AM CDT.

### To resume the remaining 119 queries:

```bash
cd benchmarks/amb-harness
oc port-forward statefulset/memoryhub-pg 25432:5432 --context mcp-rhoai -n memoryhub-db &

# Option A: Use the RPD-aware wrapper (probes before starting)
./scripts/run-with-rpd-wait.sh

# Option B: Direct run (if you know the quota has reset)
GEMINI_KEY=$(grep GEMINI_API_KEY ~/.secrets | cut -d'=' -f2)
PYTHONPATH=../../src:${PYTHONPATH:-} GOOGLE_API_KEY=$GEMINI_KEY \
OMB_ANSWER_LLM=gemini OMB_JUDGE_LLM=gemini \
OMB_ANSWER_MODEL=gemini-3.1-pro-preview \
uv run omb run --dataset personamem --split 32k --memory memoryhub \
  --skip-ingestion -o ../../benchmarks/amb-outputs
```

The runner resumes automatically from saved progress -- it skips all 470 completed queries and processes the remaining 119.

### After MemoryHub run completes:

1. **Run BM25 baseline** with Gemini Pro (existing BM25 result used Haiku):
   ```bash
   PYTHONPATH=../../src:${PYTHONPATH:-} GOOGLE_API_KEY=$GEMINI_KEY \
   OMB_ANSWER_LLM=gemini OMB_JUDGE_LLM=gemini \
   OMB_ANSWER_MODEL=gemini-3.1-pro-preview \
   uv run omb run --dataset personamem --split 32k --memory bm25 \
     -o ../../benchmarks/amb-outputs
   ```

2. **Commit results** to `benchmarks/amb-outputs/`
3. **Update `benchmarks/RESULTS.md`** with AMB PersonaMem section and leaderboard comparison
4. **Create PR** from `feat/332-amb-harness-integration`, merge, close #332

### Stretch: #333 -- RRF ablation study
Same harness, toggle pipeline configs. Can run with any LLM.

## What landed this session (2026-07-10 + 2026-07-11)

**New commits on `feat/332-amb-harness-integration` (pushed):**
- `bench: Add incremental save/resume and RPD-resilient retry` -- Runner batch mode saves every 10 queries and resumes from saved progress on restart
- `bench: Fix unbound PYTHONPATH in RPD wait script`

**Key resilience changes:**
- Runner batch mode now saves every 10 queries to disk (was: only at end)
- Resume from saved progress on restart (skip already-completed query IDs)
- Gemini adapter uses 60s base delay for quota errors (was: 5s), capped at 600s
- Runner retry: 8 attempts with 60-600s waits for rate limits (was: 4 attempts / 60s max)
- `RESOURCE_EXHAUSTED` added to retryable error patterns
- New `scripts/run-with-rpd-wait.sh` wrapper: probes API before starting harness

**Partial results at 470/589 (80.0%):**
- MemoryHub + Gemini 3.1 Pro Preview: 80.0% accuracy (470/589 queries)
- For context: AMB leaderboard Hindsight = 86.6%, Cognee = 81.8%, hybrid-search = 84.4%
- Existing BM25 + Haiku baseline: 62.6% (needs Gemini Pro re-run)

**Gemini RPD limit behavior observed:**
- Limit hit at ~230 requests (11:44 PM CDT), recovered after ~70 minutes (2:00 AM)
- Hit again at ~470 total requests (3:27 AM CDT), not yet recovered as of 5:22 AM
- Limit appears to be rolling-window, not midnight-reset. Reset mechanism is unclear.
- The probe + adapter + runner triple-layer retry worked perfectly for the first recovery

## Watch out for

- **Gemini RPD limit**: Hit twice in one session. May need to spread the remaining 119 queries across a different day or upgrade API key quota.
- **Port-forward stability**: Use tmux for the final 119-query run (~35 min at full speed).
- **`amb-*` tenant data**: 195 PersonaMem docs still in PostgreSQL. Verify before `--skip-ingestion`.
- **BM25 needs Gemini Pro**: The existing BM25 result (62.6%) used Haiku. Must re-run with same model for fair comparison.
- **`test_graduation.py::test_graduate_with_evidence`**: Pre-existing broken test (offset-naive vs offset-aware datetime).

## If blocked

- **If Gemini RPD persists**: Run with `gemini-3.1-flash-lite` (~$0.70). Not leaderboard-comparable but validates pipeline.
- **If cluster is down**: AMB harness can use local PostgreSQL (integration compose on port 15433). Re-ingest needed.
- **Curation agents epic**: `NEXT_SESSION-curation-agents.md` is independent and ready.
