# vLLM Prefix Cache Validation — Test Plan

**Related issues:** #175 (cache-optimized memory assembly), #185 (vLLM validation)  
**Status:** Active

## Background

### vLLM Automatic Prefix Caching (APC)

vLLM's APC stores KV-cache blocks (16 tokens each by default) in a content-addressed structure keyed by a SHA-256 hash chain over the token sequence. When a new request arrives, vLLM walks the prefix tree and reuses any block whose hash matches. Blocks that are not reused are subject to LRU eviction.

For cache hits to occur, the token sequence at the start of the prompt must be **byte-for-byte identical** across requests. Even a single token difference invalidates all downstream blocks.

### MemoryHub Compilation Epochs

MemoryHub assembles memories into an injection block via `get_injection_block()`. The assembly algorithm:

1. Sorts memories by `(weight DESC, created_at ASC, id ASC)` — deterministic ordering.
2. Appends newly-written memories to the end of the block (appendix), rather than resorting, so the prefix of the block is stable.
3. Triggers a full recompile when the appendix exceeds a configured threshold; after recompile the block is re-sorted and a new stable prefix is established.

### Token Stability via `get_injection_block()`

The `get_injection_block()` SDK method strips per-request metadata (session IDs, timestamps, request-specific annotations) before returning the block. This ensures that two calls in the same epoch produce identical text, which in turn produces identical tokens when fed to the same model.

## Hypotheses

1. **Stable prefix** — Identical injection blocks produce a >90% prefix cache hit rate on repeated requests to vLLM.
2. **Append-only growth** — Appending new memories (appendix region) preserves the hit rate for the stable prefix; only the appended tokens are new.
3. **Recompile cost** — A recompile causes exactly one cache miss (the first post-recompile request), after which hits resume at the new prefix.

## Metrics

Scraped from vLLM's `/metrics` Prometheus endpoint before and after each request:

| Metric | Meaning |
|--------|---------|
| `prefix_cache_queries_total` | Total number of KV-cache prefix lookups |
| `prefix_cache_hits_total` | Lookups that resulted in at least one cached block |
| `prompt_tokens_by_source_total{source="cache"}` | Prompt tokens served from cache |
| `prompt_tokens_by_source_total{source="computed"}` | Prompt tokens computed fresh |

**Hit rate** for a single request = `delta_hits / delta_queries` (0 or 1 per request).  
**Block efficiency** = `delta_tokens_cache / (delta_tokens_cache + delta_tokens_computed)`.

A 500 ms settle time is observed between receiving the HTTP response and scraping metrics, to allow vLLM's metric counters to flush.

**Primary measurement (preferred):** Per-request `usage.prompt_tokens_details.cached_tokens` from the vLLM API response. Requires `--enable-prompt-tokens-details` on the server. This gives exact per-request cache hit data without noise from concurrent traffic, matching the approach OpenAI uses in their API.

**Cross-check:** Prometheus metric deltas as described above.

## Test Scenarios

### STABLE_PREFIX

Validates hypothesis 1.

1. Fetch the injection block with `get_injection_block()`.
2. Send 5 requests to vLLM, all with the **same system prompt** (injection block) and the same user question.
   - Request 1: cold — expect cache miss.
   - Requests 2–5: warm — expect cache hit.
3. **Pass criteria:** hit rate >= 0.90 across requests 2–5.

### APPEND_ONLY

Validates hypothesis 2: appending a memory does not invalidate the cached prefix.

1. Fetch the injection block; send 2 warm-up requests (establishes cache).
2. Write a new memory via the MemoryHub API.
3. Fetch the injection block again — the new memory appears in the appendix.
4. Send 1 request with the updated block.
5. Send 1 more request with the same updated block.

**Pass criteria:** request in step 4 shows a partial hit (prefix blocks still cached, only appendix blocks miss); request in step 5 shows a full hit on the new prefix+appendix. The cached token ratio for step 4 should be >= ratio of original-prefix length to total new length.

### RECOMPILE

Validates hypothesis 3: recompile causes exactly one miss then hits resume.

1. Fetch the injection block; send 2 warm-up requests.
2. Trigger a recompile by writing enough memories to exceed the appendix threshold (or by calling the admin recompile endpoint if available).
3. Fetch the (new) injection block.
4. Send request 1 post-recompile — expect miss.
5. Send requests 2 and 3 post-recompile — expect hits.

**Pass criteria:** exactly 1 miss in post-recompile requests, then >= 2 consecutive hits.

### BLOCK_GRANULARITY

Validates that cache hits operate at block granularity, not all-or-nothing.

1. Two requests share the same injection block but differ only in the user question.
2. Confirm that prefix blocks are reused and only the question-specific suffix is computed.

**Pass criteria:** `prompt_tokens_by_source_total{source="cache"}` delta > 0 on the second request; `prompt_tokens_by_source_total{source="computed"}` delta > 0 (question tokens are computed). Both deltas are non-zero, confirming partial reuse.

### THRESHOLD_ANALYSIS

Observational — no explicit pass/fail. Documents the trade-off between appendix cost and recompile cost.

1. Write memories one at a time, measuring block efficiency before and after each write.
2. Continue until a recompile is triggered.
3. Record: (a) efficiency at each appendix size, (b) efficiency immediately after recompile, (c) efficiency after 2 warm requests post-recompile.

Output: a table of `appendix_size → block_efficiency` and the recompile recovery curve. This informs tuning the appendix threshold.

## Follow-Up Scenarios

These scenarios build on the baseline findings and target specific optimizations or deployment configurations. Run with `--scenario <name>` to execute individually.

### BYTE_STABILITY_FIX

**Prerequisite:** Fix `get_injection_block()` to render compiled and appendix as separately stable text segments (recommendation #1 from findings.md).

**Purpose:** Validate that the fix restores the append-only cache benefit. With byte-stable compiled sections, appending should preserve prefix cache hits for the compiled portion.

1. Fetch injection block, warm cache with 2 requests.
2. Write 2 new memories (below recompile threshold).
3. Fetch updated block — verify the compiled section bytes are identical to step 1.
4. Send request with updated block.
5. **Pass criteria:** cached tokens >= 80% of the compiled section's token count. The appendix tokens are computed fresh, but the compiled prefix hits cache.

**Why it matters:** This is the scenario that validates the entire compilation epoch design. The baseline APPEND_ONLY scenario failed at 1.78% — this fix should bring it to ~80-90%.

### IMMEDIATE_RECOMPILE

**Prerequisite:** Set `min_appendix=1` in the compilation config.

**Purpose:** Validate that immediate recompilation (on every memory change) is strictly better than appendix mode, given the byte-stability gap.

1. Fetch injection block, warm cache with 2 requests.
2. Write 1 new memory — should trigger immediate recompile (new epoch, appendix_count=0).
3. Send request with recompiled block — expect miss.
4. Send 3 more requests — expect hits.
5. **Pass criteria:** Post-recompile warm hit rate >= 95%. Verify that the one-miss cost is identical to the appendix-mode cost (both ~98%), confirming no regression.

**Comparison:** Run alongside the current `min_appendix=5` behavior to produce a side-by-side table.

### BLOCK_SIZE_32

**Prerequisite:** Redeploy vLLM with `--block-size 32`.

**Purpose:** Measure whether larger cache blocks improve or degrade hit rates for MemoryHub's prompt shapes.

1. Run STABLE_PREFIX with block_size=32.
2. Compare: partial final block waste changes (`prompt_tokens mod 32` vs `mod 16`).
3. Compare: hash computation overhead (half as many blocks to hash).
4. **Pass criteria:** Warm hit rate >= 95%. Report the delta vs. baseline block_size=16.

**Why it matters:** When deploying with llm-d across multiple vLLM pods, block size affects cross-instance cache sharing efficiency. Larger blocks mean fewer hashes to compare during routing.

### EVICTION_PRESSURE

**Prerequisite:** Redeploy vLLM with `--num-gpu-blocks-override N` (set to ~50% of profiled blocks).

**Purpose:** Measure cache behavior under memory pressure to understand degradation characteristics.

1. Run STABLE_PREFIX — warm cache.
2. Send 20 unrelated prompts to fill the cache (force LRU eviction of our blocks).
3. Re-send the original prompt — measure whether our blocks survived or were evicted.
4. Monitor `vllm:num_preemptions_total` throughout.
5. **Pass criteria:** None (observational). Report the eviction curve: how many unrelated prompts does it take to evict our cached blocks?

**Why it matters:** In production, MemoryHub's cached blocks compete with other workloads for GPU memory. Understanding the eviction threshold informs capacity planning.

### CROSS_QUERY_SHARING

**Purpose:** Test whether different search queries returning overlapping memory sets share cache blocks.

1. Search with query A ("project conventions") — get block A, warm cache.
2. Search with query B ("deployment patterns") — get block B.
3. Compare block A and block B: measure the character-level longest common prefix.
4. Send request with block B.
5. **Pass criteria:** If blocks share a prefix (same compilation epoch, same top memories), cached tokens should include the shared portion. If blocks differ from the start, expect a miss.

**Why it matters:** In multi-agent deployments, different agents searching for different topics may get overlapping memory sets. Understanding whether the compilation epoch's deterministic ordering enables cross-query cache sharing informs whether a shared compilation epoch (per project, not per query) would be beneficial.

## How to Run

### Prerequisites

- Python 3.10+ with `httpx` and `memoryhub>=0.5.0` installed
- Network access to both endpoints
- Valid MemoryHub API key

### Environment

```bash
export VLLM_URL="https://granite-3-3-8b-instruct-granite-model.apps.cluster-n7pd5.n7pd5.sandbox5167.opentlc.com"
export MEMORYHUB_URL="https://memory-hub-mcp-memory-hub-mcp.apps.cluster-n7pd5.n7pd5.sandbox5167.opentlc.com/mcp/"
export MEMORYHUB_API_KEY="<your-api-key>"
```

### Execution

```bash
# Run all baseline scenarios
python scripts/validate-prefix-cache.py

# Run a specific follow-up scenario
python scripts/validate-prefix-cache.py --scenario BYTE_STABILITY_FIX

# List available scenarios
python scripts/validate-prefix-cache.py --list-scenarios
```

The script runs all five scenarios in order. Progress and per-request metrics are logged to stdout. Final results are written to:

```
research/vllm-prefix-cache-validation/results-<timestamp>.json
```

### Cleanup

The script writes temporary memories to MemoryHub during RECOMPILE and THRESHOLD_ANALYSIS. It deletes them on exit (including on keyboard interrupt). If the script is killed hard, run:

```bash
python scripts/validate-prefix-cache.py --cleanup-only
```

to remove any leftover test memories tagged `validation-run-<timestamp>`.

## Interpreting Results

Each scenario in the JSON output has:

```json
{
  "scenario": "STABLE_PREFIX",
  "status": "PASS",
  "requests": [
    {
      "index": 0,
      "delta_queries": 1,
      "delta_hits": 0,
      "hit_rate": 0.0,
      "cached_tokens": 0,
      "computed_tokens": 312
    },
    ...
  ],
  "summary": {
    "warm_hit_rate": 0.95,
    "threshold": 0.90
  }
}
```

`status` is one of:
- `PASS` — criteria met
- `FAIL` — criteria not met
- `ANALYSIS` — observational scenario (THRESHOLD_ANALYSIS), no pass/fail

A low hit rate on warm requests in STABLE_PREFIX almost always means the injection block is not token-stable. Check `get_injection_block()` output for non-deterministic fields (timestamps, UUIDs).

## Known Limitations

**Shared cluster noise.** The validation runs against a shared cluster. Concurrent traffic from other users adds noise to metric deltas — a `delta_queries > 1` on a single request means another request was in-flight during the measure window. The script logs a warning when this is detected but does not retry, since retrying would perturb the cache state.

**Approximate token counts.** The script does not load the model's tokenizer locally. Token counts from `prompt_tokens_by_source_total` are exact (from vLLM's internal accounting); any token-count estimates in logging are approximate.

**LRU eviction.** If the cluster is under memory pressure, blocks cached by the warm-up requests may be evicted before the hit-rate measurement requests arrive. This will manifest as unexpected misses. Run during off-peak hours if eviction noise is suspected.

**Epoch state dependency.** RECOMPILE and THRESHOLD_ANALYSIS depend on the current appendix size relative to the recompile threshold. If a recompile occurs between setup and measurement (due to another session writing memories), the scenario may produce unexpected results. The script reads the current epoch metadata before each scenario and aborts if the state has shifted unexpectedly.
