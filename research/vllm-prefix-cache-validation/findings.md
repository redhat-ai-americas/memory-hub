# vLLM Prefix Cache Validation Findings

## Summary

MemoryHub's compilation epoch system was validated against vLLM v0.19.0 automatic prefix caching (APC) on Granite 3.3 8B Instruct. Stable-prefix and recompilation scenarios work as designed, achieving 98.29% and 99.03% hit rates respectively. The append-only hypothesis failed: appending memories to the injection block invalidates the entire cached prefix because `get_injection_block()` does not produce a byte-stable prefix when appendix entries are present.

## Environment

| Parameter | Value |
|-----------|-------|
| vLLM version | 0.19.0 |
| Model | `RedHatAI/granite-3.3-8b-instruct` |
| `enable_prefix_caching` | `True` |
| `--enable-prompt-tokens-details` | `True` |
| `block_size` | 16 tokens |
| Hash algorithm | SHA-256 (parent-chain) |
| `max_model_len` | 4096 |
| `gpu_memory_utilization` | 0.9 |
| Deployment | Single pod, direct endpoint (no llm-d routing) |
| Infrastructure | OpenShift cluster, NVIDIA GPU |
| Results file | `results-20260414-174434.json` |

## Background

MemoryHub is a centralized memory service for AI agents. Agents call `search_memory` and inject the results as a text prefix into LLM prompts. To maximize vLLM prefix cache hit rates, MemoryHub uses a "compilation epoch" system (issue #175): memories are sorted into a deterministic order and frozen. New memories are appended to a trailing appendix region rather than re-sorted, preserving the byte-level prefix. When the appendix grows past a configurable threshold (default: 5 entries or 30% of total), the entire block is recompiled into a new sorted order, establishing a new stable prefix.

vLLM's APC stores KV-cache blocks in a content-addressed structure keyed by SHA-256 hash chains over the token sequence. Blocks are 16 tokens each. A cache hit requires the token sequence to be byte-identical from position 0 through the block boundary. A single changed token at position N invalidates block `floor(N/16)` and all subsequent blocks.

This validation tests three hypotheses: (1) stable prefixes cache well, (2) append-only growth preserves the cached prefix, and (3) recompilation causes exactly one miss before caching resumes.

**Metrics used:** The primary measurement is per-request `usage.prompt_tokens_details.cached_tokens` from the vLLM API response (requires `--enable-prompt-tokens-details`). This is the same mechanism OpenAI's API uses to report cached tokens, giving exact per-request data without the noise of Prometheus counter deltas. Prometheus metrics (`vllm:prefix_cache_queries_total`, `vllm:prefix_cache_hits_total`) are retained as a cross-check.

## Results

### Stable Prefix (PASS)

Identical 879-token prompts sent 5 times. Injection block: 3756 chars, compilation epoch 12.

| Request | Prompt Tokens | Cached Tokens | Hit Rate |
|---------|--------------|---------------|----------|
| cold_start | 879 | -- | 0.00% |
| warm_1 | 879 | 864 | 98.29% |
| warm_2 | 879 | 864 | 98.29% |
| warm_3 | 879 | 864 | 98.29% |
| warm_4 | 879 | 864 | 98.29% |

The 15 uncached tokens are the final partial block: `879 mod 16 = 15`. vLLM caches only full 16-token blocks (54 full blocks * 16 = 864 tokens). The remaining 15 tokens form a partial block that is always computed.

The cold start shows `cached_tokens: null` (not 0) because vLLM does not report cached token details when there are no cache hits. The Prometheus counters confirm 0 hits / 879 queries. This is a proper cold start -- unlike previous runs where stale cache from prior script invocations gave a false warm reading. The cold_start to warm_1 transition shows the real cache population behavior: a complete miss on the first request, followed by consistent 98.29% hits once the prefix is cached.

### Append-Only (FAIL)

After writing 2 new memories, the injection block grew from 3756 to 3797 chars (+41 chars). `appendix_count=2`, compilation epoch unchanged (12).

| Request | Prompt Tokens | Cached Tokens | Hit Rate |
|---------|--------------|---------------|----------|
| with_appendix | 897 | 16 | 1.78% |
| repeat_appendix | 897 | 896 | 99.89% |

The first request with the appended block achieved only 1.78% hit rate -- effectively a complete cache miss. The 16 cached tokens (1 block) correspond to the shared system prompt prefix. The results JSON confirms `prefix_preserved=false`: the injection block text changed not just at the end but earlier in the rendered output. See "Key Finding" below.

The repeat request recovered to 99.89%, confirming that the new block is itself cache-stable once established.

### Recompilation (PASS)

After triggering recompilation, the epoch incremented from 12 to 13. `block_changed=true`, `appendix_after_recompile=0`.

| Request | Prompt Tokens | Cached Tokens | Hit Rate |
|---------|--------------|---------------|----------|
| recompile_miss | 824 | 16 | 1.94% |
| post_recompile_1 | 824 | 816 | 99.03% |
| post_recompile_2 | 824 | 816 | 99.03% |
| post_recompile_3 | 824 | 816 | 99.03% |

The 16-token hit on the "miss" request is from the shared system prompt prefix. Post-recompile requests immediately resume at 99.03%, confirming one-time invalidation followed by stable caching. Post-recompile uncached: 8 tokens = `824 mod 16 = 8`.

### Block Granularity (PASS)

Two prompts sharing a long memory prefix but with different trailing questions:

- Q1: "Describe the authentication approach..." (58 chars)
- Q2: "Explain the storage architecture..." (54 chars)

After warming the cache with Q1, Q2 achieved 96.74% hit rate (800/827 cached). Only 27 tokens were computed -- approximately the divergent question suffix. This confirms block-aligned prefix matching: the shared prefix caches, and only the suffix where the prompts diverge is computed.

### Threshold Analysis

Appendix mode wastes approximately 98.22% of tokens per request (because the text changes break the prefix entirely). Recompilation costs approximately 98.06% once. Break-even is at approximately 1.0 requests.

The 30%/5-entry threshold provides no value under the current text rendering approach. Every append invalidates the entire cache just as a recompilation would, but without establishing a new stable prefix. Recompiling immediately would be strictly better: the one-time cost is the same, but subsequent requests benefit from caching.

## Key Finding: Byte-Stability Gap

The append-only hypothesis assumed that `get_injection_block()` produces output where the compiled section is byte-identical regardless of appendix entries. This assumption does not hold.

When new memories are added, the rendered text changes at positions earlier than the trailing appendix. The likely mechanisms:

1. **Result list rendering is not segmented.** The compiled and appendix memories are rendered together as a single text block. Memory content varies in length, and the interleaving of separators shifts token boundaries even when the "compiled" memory IDs are in the same order.

2. **Token boundary propagation.** A single changed byte at position N shifts the tokenization from that point forward. Because vLLM's hash chain is sequential (each block's hash depends on the parent block's hash), a change at block K invalidates blocks K through the end of the prompt.

3. **The 16-token block boundary amplifies the effect.** Even a 1-byte change within a 16-token block invalidates that block and all downstream blocks. There is no partial-block recovery.

The result: the append-only path performs identically to a full recompilation in terms of cache cost (~98% miss), but without the benefit of establishing a new stable ordering. Every append is effectively a recompile that does not know it is one.

## Recommendations

1. **Fix byte-stability in `get_injection_block()`.** The compiled section must produce byte-identical output regardless of appendix content. Options: (a) render compiled and appendix as two separate text segments concatenated with a fixed-width separator, ensuring the compiled segment's bytes never change; (b) pad the compiled section to a fixed length so appended content does not shift its token boundaries. Until this is fixed, the append-only mode provides no cache benefit.

2. **Lower the recompile threshold to 1.** Since appendix mode invalidates the entire cache anyway, the current 30%/5-entry threshold only delays re-establishing a stable cache. Set `min_appendix=1` so that any memory change triggers an immediate recompile. This is strictly better than the current behavior: same one-time cost, but the next request benefits from caching.

3. **Leverage the 16-token block boundary in prompt design.** Where practical, design the injection block template so the total token count aligns to a multiple of 16. This is unlikely to be controllable in general (token counts depend on memory content), but it matters for benchmarking and for fixed prompt scaffolding.

4. **The stable prefix path works well -- protect it.** When the injection block is truly identical across requests, 98.29% hit rate is achieved consistently. The compilation epoch design is architecturally sound. The issue is isolated to the text rendering step that converts structured results to a prompt string.

5. **SDK model bug.** The `Memory` model requires `content: str` and `owner_id: str`, but the server returns appendix entries as stubs (when token budget is exceeded) without these fields. Either make these fields optional on the model or ensure the server always populates them.

## Raw Data

- [`results-20260414-174434.json`](results-20260414-174434.json) -- baseline validation run with per-request `cached_tokens` instrumentation

## Reproduction

Prerequisites: Python 3.10+, `httpx`, `memoryhub>=0.5.0` (SDK). Network access to both the vLLM and MemoryHub endpoints. A valid MemoryHub API key.

```bash
export VLLM_URL="https://<vllm-route>"
export MEMORYHUB_URL="https://<memoryhub-route>/mcp/"
export MEMORYHUB_API_KEY="<your-api-key>"

python scripts/validate-prefix-cache.py
```

Results are written to `research/vllm-prefix-cache-validation/results-<timestamp>.json`. The script writes temporary memories during the RECOMPILE and THRESHOLD_ANALYSIS scenarios and deletes them on exit. If interrupted, run `python scripts/validate-prefix-cache.py --cleanup-only` to remove leftover test memories.
