# vLLM KV Cache: Optimization Survey and Prefix-Cache Validation

> Consolidated 2026-07-08 from: `research/infra/vllm-cache-optimization.md`, `research/infra/vllm-prefix-cache-validation/design.md`, `research/infra/vllm-prefix-cache-validation/findings.md`. Originals removed; full text in git history.

**Related issues:** #168, #169, #171 (compiled knowledge articles), #175 (cache-optimized memory assembly), #185 (vLLM validation)
**Raw experiment data:** [`vllm-kv-cache-results/`](vllm-kv-cache-results/)

---

# Part 1: Optimization Survey (2026-04-11)

## 1. vLLM Automatic Prefix Caching (APC)

### How It Works

vLLM's APC stores computed KV tensors in fixed-size blocks (typically 16 tokens per block, configurable up to 32 on CUDA). When a new request arrives, the system identifies whether its token prefix matches previously computed blocks and reuses them, skipping prefill for matched portions.

The mechanism is content-addressed: each block is identified by `hash(parent_block_hash, tokens_in_block, extra_metadata)`. Parent-chaining means validating a single block hash implicitly guarantees the entire prefix up to that point is identical. Hash algorithm: SHA-256 (as of vLLM v0.11).

### Block-Level Granularity

Cache matching is strictly block-aligned and prefix-contiguous:

- Only **full blocks** (16 tokens default) can be cached and matched.
- Matching proceeds sequentially from block 0; the first miss terminates the search — no "skip and match later."
- A 50-token prompt with block_size=16 produces 3 full blocks + 1 partial (2 tokens); only the 48 full-block tokens can hit cache.
- If block 2 differs by a single token, blocks 0-1 hit but blocks 2+ recompute.

**Implication for MemoryHub:** memories injected as a prefix cache at block granularity. 960 identical leading tokens of a 1000-token prompt = 60 cached blocks, saving ~96% of prefill for that portion.

### What Invalidates the Cache

- Any token change within a block (invalidates that block and all downstream, per parent-chain).
- LRU eviction under GPU memory pressure — tail blocks evicted before prefix blocks.
- `cache_salt` changes (tenant isolation).
- LoRA adapter changes (included in hash extras).

### Concurrent Requests with Shared Prefixes

In-flight requests sharing a prefix share physical KV blocks via reference counting; referenced blocks are never evicted. 100 concurrent requests with the same system prompt compute it once.

### Performance Gains

| Scenario | Metric | Improvement |
|----------|--------|-------------|
| Repeated 10K-token prompt (Qwen3-32B) | TTFT | 4.3s → 0.6s (7x) |
| llm-d precise routing (8 pods, H100) | Output tokens/sec | 8,730 vs 4,429 (2x) |
| llm-d precise routing | Mean TTFT | 0.298s vs 45.28s (152x) |
| General prefix caching | Latency reduction | 3-10x typical |
| vLLM v1 engine over v0 | Throughput | +24% (generation-heavy) |

### vLLM V1 Engine (2025)

Prefix caching is **zero-overhead and enabled by default**: constant-time eviction (no penalty even at 0% hit rate), pre-allocated block pool, append-only block tables, no configuration required.

## 2. llm-d: Kubernetes-Native Distributed LLM Inference

llm-d (Red Hat, IBM Research, Google Cloud, CoreWeave, NVIDIA; CNCF Sandbox since March 2026; v0.5.1 as of Feb 2026) orchestrates vLLM pods with intelligent scheduling — cache-aware routing, disaggregated prefill/decode, hierarchical KV cache offloading. It does not replace vLLM.

Architecture: Request → Gateway API (Inference Extension) → EPP → Inference Scheduler (scoring) → vLLM pods (prefill/decode).

### Prefix-Cache-Aware Routing

The killer feature for MemoryHub: solves "cache scattering" where naive load balancers destroy cache locality.

1. **KVEvent Stream**: each vLLM pod publishes `BlockStored`/`BlockRemoved` events via ZMQ.
2. **KV Block Index**: lightweight in-memory index (339 KB for 365 GB of KV data) maps block hashes to pod locations.
3. **Prefix Scorer**: per request, computes what percentage of the prefix is already cached on each pod.
4. **Balanced Routing**: cache affinity combined with load-awareness.

**Result:** 87.4% cache hit rate across 4,776 queries, 88% faster TTFT (340ms vs 2,850ms baseline), 99.92% of requests routed to the warm pod.

### Other v0.5 Features

- **Hierarchical KV cache offloading:** GPU HBM → CPU DRAM → filesystem (SSD/NFS). Cross-replica cache reuse; new nodes access cached KV states immediately; 13.9x improvement at 250 concurrent users vs GPU-only.
- **Cache-aware LoRA routing:** routes to pods already holding the relevant adapter in prefix cache.

### Maturity

Production-ready: prefix caching, P/D disaggregation, basic scheduling. Active development: hierarchical offloading, LoRA routing, scale-to-zero. Validated: 50K output tok/s on 16x16 B200 topology.

## 3. Implications for MemoryHub Output Format

**Will vLLM cache recognize stable memory injections?** Yes, if: (1) byte-identical prefix — same text → same tokens → same block hashes; (2) consistent position in the prompt; (3) deterministic serialization — no reordering, timestamps, or random IDs.

**Exact byte-identity is required.** Zero tolerance for token-level variation; a single different token invalidates from that point forward (hash-chaining by design).

**When memories change slightly:**
- **Appended** at the end: all prior blocks still hit; only new content computes. The ideal "append-only" pattern.
- **Inserted, reordered, or modified** within the prefix: cache invalidates from the point of change.
- **Removed or resorted**: complete miss from the point of divergence.

**Compiled knowledge articles (#171) and cross-agent cache hits:** if compilation is deterministic (same memories → same compiled text), different agents requesting the same article produce identical token sequences and share the cache — the "shared document" use case APC was designed for. Requirements: fully deterministic compilation (no randomness/timestamps/agent metadata), same prompt position, served verbatim.

## 4. Cache-Aware Design Patterns for MemoryHub

### Optimal Content Placement

```
STABLE (cached):      system instructions, tool definitions,
                      compiled knowledge articles  ← MemoryHub output here
                      stable memories (high-weight, sorted)
                      [cache breakpoint]
SEMI-STABLE:          conversation history (append-only)
                      [cache breakpoint]
DYNAMIC (never cached): current user message, session context,
                      timestamps, request IDs
```

### Rules for MemoryHub Output Format

1. **Deterministic ordering:** sort by stable key (weight desc, created_at, ID). No random ordering or non-deterministic tie-breaking.
2. **No timestamps in output** ("retrieved at", "last updated" destroy cache).
3. **No per-request metadata** (session IDs, request IDs, agent identifiers).
4. **Append-only growth:** prefer appending over inserting/reordering.
5. **Deterministic serialization:** `sort_keys=True` equivalent for structured formats.
6. **Compiled articles as versioned, immutable blocks** until recompilation.
7. **Separate stable from volatile:** stable memories first, in their own block.

### Anti-Patterns That Thrash the Cache

| Anti-Pattern | Why It Breaks Cache |
|---|---|
| `"Retrieved at: 2026-04-11T10:30:00Z"` | New timestamp = new tokens = miss |
| Random memory ordering | Different tokens from first divergence |
| `request_id` / `session_id` in context | Unique per request |
| Truncating/summarizing old memories mid-sequence | Changes tokens at that position |
| Dynamic tool removal based on context | Changes tokens early in prompt |
| Non-deterministic JSON serialization | Different key order = different tokens |
| Per-agent metadata wrapping compiled articles | Breaks cross-agent sharing |

### Manus (Validated at Scale)

Manus reports: KV-cache hit rate is their "single most important metric"; average input-to-output ratio 100:1; logits masking instead of tool removal; filesystem as externalized memory; cached tokens $0.30/MTok vs $3.00/MTok uncached (10x on Claude Sonnet).

## 5. Multi-Provider Caching Comparison

| Provider | Mechanism | Min Tokens | Granularity | Cache TTL | Cost Savings |
|----------|-----------|-----------|-------------|-----------|-------------|
| **vLLM (self-hosted)** | Automatic (always-on in V1) | None (block-aligned) | 16-token blocks | LRU eviction | Throughput/latency |
| **Anthropic Claude** | Explicit breakpoints + lookback | 1,024-4,096 | Block-level (internal) | 5 min (or 1 hr) | 90% read discount, 25% write premium |
| **OpenAI** | Automatic prefix matching | 1,024 | 128-token increments | 5-10 min | 50% discount, no write premium |
| **Google Gemini** | Implicit (2.5+) or explicit | 1,024-4,096 | Not documented | Configurable | 75-90% read + storage fee |

**Universal principle:** all providers match on exact token-level prefix identity. Stable content first, dynamic content last, deterministic serialization, no timestamps in prefixes.

Key differences: Anthropic's 20-block lookback means fast-growing conversations can lose cache hits without explicit breakpoints; OpenAI is fully automatic but only 50% discount; vLLM's gains are throughput/TTFT rather than monetary; Gemini charges storage fees for explicit caches but gives the deepest discounts (90%) on 2.5+ models. A single MemoryHub output strategy (stable deterministic blocks, early placement, no request metadata, append-only growth, immutable versioned articles) optimizes all providers simultaneously.

## 6. Cost / Performance Implications

**Self-hosted (vLLM/llm-d):**

| Metric | Without APC | With APC + llm-d Routing |
|--------|-------------|--------------------------|
| TTFT (mean) | 45.3s | 0.3s |
| Output tokens/sec | 4,429 | 8,730 |
| Effective GPU utilization | Baseline | ~2x |
| Cache hit rate | ~0% (random routing) | 87.4% |

At high hit rates, a cache hit skips prefill entirely — effectively doubling serving capacity on the same hardware.

**Hosted API (Anthropic):** Opus 4.6 $5.00 base / $6.25 write / $0.50 read per MTok; Sonnet 4.6 $3.00 / $3.75 / $0.30; Haiku 4.5 $0.80 / $1.00 / $0.08 — 90% savings on hit. Break-even after **1.4 reads** (5-min TTL) or **2 reads** (1-hr TTL).

**For MemoryHub serving 10 agents with overlapping memory contexts:** hosted, first agent pays the write premium and the rest get 90% off — with a 100:1 input ratio this can cut total inference cost 50-80%. Self-hosted, subsequent agents get near-instant TTFT and cache-aware routing lands similar contexts on the same pod.

## 7. Recommendations

**Immediate (#171):** (1) compiled articles fully deterministic — byte-identical output for the same input set; (2) stable sort order (weight desc → created_at asc → UUID) documented as API contract; (3) plain text or minimal markup output; (4) version compiled articles, serve exact cached text until recompiled.

**Near-term:** (5) cache-stability scoring ("95% prefix stable"); (6) append-only memory deltas so consumers can structure prompts as `[unchanged prefix] + [delta]`; (7) consider llm-d integration on OpenShift for automatic cache-affinity routing.

**Long-term:** (8) shared compiled articles as cluster-level resources (cross-replica cache sharing via llm-d's filesystem tier); (9) a memory injection protocol standardizing position, format, and separator boundaries aligned to cache breakpoints; (10) avoid the "growing conversation" trap — Anthropic's 20-block lookback misses entirely if history grows >320 tokens between turns without a breakpoint.

---

# Part 2: Validation Experiment (2026-04-14)

## Experiment Design

**Goal:** validate MemoryHub's compilation epoch system (#175) against vLLM APC.

### MemoryHub Compilation Epochs

`get_injection_block()` assembles memories into an injection block: (1) sorts by `(weight DESC, created_at ASC, id ASC)`; (2) appends newly-written memories to a trailing appendix rather than resorting, keeping the prefix stable; (3) triggers a full recompile when the appendix exceeds a threshold (default: 5 entries or 30% of total), establishing a new stable prefix. The SDK strips per-request metadata (session IDs, timestamps) so two calls in the same epoch produce identical text.

### Hypotheses

1. **Stable prefix** — identical injection blocks produce >90% prefix cache hit rate on repeated requests.
2. **Append-only growth** — appending memories preserves hits for the stable prefix; only appended tokens are new.
3. **Recompile cost** — a recompile causes exactly one miss, then hits resume.

### Measurement

**Primary:** per-request `usage.prompt_tokens_details.cached_tokens` from the vLLM API response (requires `--enable-prompt-tokens-details`) — exact per-request data without concurrent-traffic noise, same mechanism OpenAI uses. **Cross-check:** Prometheus deltas (`vllm:prefix_cache_queries_total`, `vllm:prefix_cache_hits_total`, `prompt_tokens_by_source_total{source="cache"|"computed"}`), with 500 ms settle between response and scrape. Hit rate = `delta_hits / delta_queries`; block efficiency = cached / (cached + computed) tokens.

### Baseline Scenarios

- **STABLE_PREFIX:** 5 identical requests (1 cold + 4 warm); pass if warm hit rate >= 0.90.
- **APPEND_ONLY:** warm cache, write a memory, re-fetch block; pass if the first post-append request shows a partial hit (prefix cached, appendix computed) and the repeat shows a full hit.
- **RECOMPILE:** trigger recompile; pass if exactly 1 miss then >= 2 consecutive hits.
- **BLOCK_GRANULARITY:** same injection block, different user questions; pass if both cache and computed deltas are non-zero (partial reuse).
- **THRESHOLD_ANALYSIS:** observational; appendix size vs block efficiency and recompile recovery curve.

### Follow-Up Scenarios (defined, pending)

- **BYTE_STABILITY_FIX** — after fixing `get_injection_block()` to render compiled and appendix as separately stable segments, appending should preserve >= 80% cached tokens for the compiled section. This validates the entire compilation-epoch design (baseline APPEND_ONLY failed at 1.78%).
- **IMMEDIATE_RECOMPILE** — with `min_appendix=1`, verify post-recompile warm hit rate >= 95% and that immediate recompile is strictly better than appendix mode.
- **BLOCK_SIZE_32** — redeploy vLLM with `--block-size 32`; compare partial-block waste and hashing overhead; relevant for llm-d cross-instance sharing.
- **EVICTION_PRESSURE** — with `--num-gpu-blocks-override` at ~50%, measure how many unrelated prompts it takes to evict cached blocks (capacity planning).
- **CROSS_QUERY_SHARING** — do different search queries with overlapping memory sets share cache blocks? Informs whether a per-project (not per-query) compilation epoch is beneficial.

### How to Run

Prerequisites: Python 3.10+, `httpx`, `memoryhub>=0.5.0`, MemoryHub API key.

```bash
export VLLM_URL="https://granite-3-3-8b-instruct-granite-model.apps.cluster-n7pd5.n7pd5.sandbox5167.opentlc.com"
export MEMORYHUB_URL="https://memory-hub-mcp-memory-hub-mcp.apps.cluster-n7pd5.n7pd5.sandbox5167.opentlc.com/mcp/"
export MEMORYHUB_API_KEY="<your-api-key>"

python scripts/validate-prefix-cache.py                 # all baseline scenarios
python scripts/validate-prefix-cache.py --scenario BYTE_STABILITY_FIX
python scripts/validate-prefix-cache.py --list-scenarios
python scripts/validate-prefix-cache.py --cleanup-only  # remove leftover test memories
```

Results JSON (per scenario: `status` PASS/FAIL/ANALYSIS, per-request `cached_tokens`/`computed_tokens`) is written per run; archived runs live in [`vllm-kv-cache-results/`](vllm-kv-cache-results/). The script writes temporary memories during RECOMPILE and THRESHOLD_ANALYSIS and deletes them on exit.

### Known Limitations

- **Shared cluster noise:** concurrent traffic perturbs Prometheus deltas (`delta_queries > 1` is logged, not retried).
- **Approximate token counts in logs** (no local tokenizer); vLLM's internal accounting is exact.
- **LRU eviction** under memory pressure can evict warm blocks before measurement; run off-peak if suspected.
- **Epoch state dependency:** RECOMPILE/THRESHOLD_ANALYSIS abort if another session shifts the appendix state mid-scenario.

## Findings

### Summary

Validated against vLLM v0.19.0 APC on Granite 3.3 8B Instruct. **Stable-prefix and recompilation work as designed (98.29% and 99.03% hit rates). The append-only hypothesis failed:** appending memories invalidates the entire cached prefix because `get_injection_block()` does not produce a byte-stable prefix when appendix entries are present.

### Environment

| Parameter | Value |
|-----------|-------|
| vLLM version | 0.19.0 |
| Model | `RedHatAI/granite-3.3-8b-instruct` |
| `enable_prefix_caching` / `--enable-prompt-tokens-details` | `True` / `True` |
| `block_size` | 16 tokens; SHA-256 parent-chain |
| `max_model_len` / `gpu_memory_utilization` | 4096 / 0.9 |
| Deployment | Single pod, direct endpoint (no llm-d), OpenShift, NVIDIA GPU |
| Baseline results file | [`vllm-kv-cache-results/results-20260414-174434.json`](vllm-kv-cache-results/results-20260414-174434.json) |

### Stable Prefix (PASS)

Identical 879-token prompts x5; injection block 3756 chars, epoch 12.

| Request | Prompt Tokens | Cached Tokens | Hit Rate |
|---------|--------------|---------------|----------|
| cold_start | 879 | -- | 0.00% |
| warm_1..4 | 879 | 864 | 98.29% |

The 15 uncached tokens are the final partial block (`879 mod 16 = 15`); 54 full blocks x 16 = 864 cached. Cold start reports `cached_tokens: null` (vLLM omits details on zero hits); Prometheus confirms 0/879. This was a true cold start, unlike earlier runs polluted by stale cache from prior invocations.

### Append-Only (FAIL)

After writing 2 memories, block grew 3756 → 3797 chars (+41), `appendix_count=2`, epoch unchanged.

| Request | Prompt Tokens | Cached Tokens | Hit Rate |
|---------|--------------|---------------|----------|
| with_appendix | 897 | 16 | **1.78%** |
| repeat_appendix | 897 | 896 | 99.89% |

Effectively a complete miss — the 16 cached tokens are the shared system prompt block. `prefix_preserved=false` in the results: the rendered text changed earlier than the trailing appendix. The repeat recovered to 99.89%, confirming the new block is itself stable.

### Recompilation (PASS)

Epoch 12 → 13, `appendix_after_recompile=0`.

| Request | Prompt Tokens | Cached Tokens | Hit Rate |
|---------|--------------|---------------|----------|
| recompile_miss | 824 | 16 | 1.94% |
| post_recompile_1..3 | 824 | 816 | 99.03% |

One-time invalidation, then stable caching. Uncached remainder: `824 mod 16 = 8` tokens.

### Block Granularity (PASS)

Two prompts sharing a long memory prefix, different trailing questions. After warming with Q1, Q2 hit 96.74% (800/827 cached); only ~27 tokens (the divergent question suffix) computed. Confirms block-aligned partial reuse.

### Threshold Analysis

Appendix mode wastes ~98.22% of tokens per request (text changes break the prefix entirely); recompilation costs ~98.06% once. Break-even ≈ 1.0 requests. **The 30%/5-entry threshold provides no value under the current text rendering** — every append invalidates the cache like a recompile would, but without establishing a new stable prefix.

### Key Finding: Byte-Stability Gap

The append-only hypothesis assumed the compiled section of `get_injection_block()` output is byte-identical regardless of appendix entries. It is not. Likely mechanisms:

1. **Result list rendering is not segmented** — compiled and appendix memories render as one text block; separator interleaving shifts token boundaries even with identical compiled memory ordering.
2. **Token boundary propagation** — a single changed byte at position N shifts tokenization from that point; the sequential hash chain invalidates block K through the end.
3. **The 16-token block boundary amplifies the effect** — no partial-block recovery.

Result: every append is effectively a recompile that does not know it is one.

### Recommendations from Findings

1. **Fix byte-stability in `get_injection_block()`:** render compiled and appendix as two separate segments with a fixed-width separator (or pad the compiled section to fixed length) so compiled bytes never change. Until fixed, append-only mode provides no cache benefit.
2. **Lower the recompile threshold to 1 (`min_appendix=1`):** same one-time cost as an append, but the next request benefits from caching. Strictly better than current behavior.
3. **Align injection-block templates to 16-token multiples** where practical (mostly relevant for benchmarking/fixed scaffolding).
4. **The stable prefix path works — protect it.** 98.29% hit rate when blocks are truly identical; the compilation epoch design is architecturally sound, and the issue is isolated to the text rendering step.
5. **SDK model bug:** `Memory` requires `content: str` and `owner_id: str`, but the server returns appendix stubs without these fields when the token budget is exceeded. Make them optional or always populate.

---

## Sources

- [vLLM Automatic Prefix Caching (docs)](https://docs.vllm.ai/en/latest/features/automatic_prefix_caching/) · [v1 Prefix Caching Design](https://docs.vllm.ai/en/v0.8.5/design/v1/prefix_caching.html) · [stable design docs](https://docs.vllm.ai/en/stable/design/prefix_caching/)
- [vLLM RFC #2614: Automatic Prefix Caching](https://github.com/vllm-project/vllm/issues/2614) · [Cache Salting RFC #16016](https://github.com/vllm-project/vllm/issues/16016) · [V1 Alpha Release Blog](https://blog.vllm.ai/2025/01/27/v1-alpha-release.html)
- [Performance Boosts in vLLM 0.8.1 (Red Hat Developer)](https://developers.redhat.com/articles/2025/04/28/performance-boosts-vllm-081-switching-v1-engine)
- [llm-d GitHub](https://github.com/llm-d/llm-d) · [llm-d.ai](https://llm-d.ai/) · [KV-Cache Wins You Can See](https://llm-d.ai/blog/kvcache-wins-you-can-see) · [v0.5 Release](https://llm-d.ai/blog/llm-d-v0.5-sustaining-performance-at-scale)
- [Master KV Cache Aware Routing with llm-d (Red Hat Developer)](https://developers.redhat.com/articles/2025/10/07/master-kv-cache-aware-routing-llm-d-efficient-ai-inference) · [llm-d: Kubernetes-native Distributed Inferencing](https://developers.redhat.com/articles/2025/05/20/llm-d-kubernetes-native-distributed-inferencing)
- [llm-d CNCF Acceptance](https://www.cncf.io/blog/2026/03/24/welcome-llm-d-to-the-cncf-evolving-kubernetes-into-sota-ai-infrastructure/) · [IBM Research: Donating llm-d to CNCF](https://research.ibm.com/blog/donating-llm-d-to-the-cloud-native-computing-foundation)
- [Anthropic Prompt Caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching) · [OpenAI Prompt Caching](https://platform.openai.com/docs/guides/prompt-caching) · [Gemini Context Caching](https://ai.google.dev/gemini-api/docs/caching)
- [Manus: Context Engineering for AI Agents](https://manus.im/blog/Context-Engineering-for-AI-Agents-Lessons-from-Building-Manus)
- [Don't Break the Cache (arXiv)](https://arxiv.org/html/2601.06007v1) · [Prompt Caching Infrastructure (Introl)](https://introl.com/blog/prompt-caching-infrastructure-llm-cost-latency-reduction-guide-2025) · [How Prompt Caching Works](https://sankalp.bearblog.dev/how-prompt-caching-works/) · [Prefix-Aware Routing (BentoML)](https://bentoml.com/llm/inference-optimization/prefix-caching)
