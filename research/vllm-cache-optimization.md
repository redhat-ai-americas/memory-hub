# vLLM Prefix Caching, KV Cache Optimization, and llm-d

Research investigation for MemoryHub issue #171 (compiled knowledge articles) and general output format design.

**Date**: 2026-04-11
**Status**: Complete
**Related issues**: #168, #169, #171

---

## 1. vLLM Automatic Prefix Caching (APC)

### How It Works

vLLM's Automatic Prefix Caching stores computed KV tensors in fixed-size blocks (typically 16 tokens per block, configurable up to 32 on CUDA). When a new request arrives, the system identifies whether its token prefix matches previously computed blocks and reuses them, skipping the expensive prefill computation for matched portions.

The mechanism is content-addressed: each block is uniquely identified by `hash(parent_block_hash, tokens_in_block, extra_metadata)`. This parent-chaining means validating a single block hash implicitly guarantees the entire prefix up to that point is identical. The hash algorithm is SHA-256 (as of vLLM v0.11).

### Block-Level Granularity

Cache matching is strictly block-aligned and prefix-contiguous:

- Blocks are fixed-size (16 tokens default). Only **full blocks** can be cached and matched.
- Matching proceeds sequentially from block 0 forward. The first miss terminates the search -- there is no "skip and match later" behavior.
- A 50-token prompt with block_size=16 produces 3 full blocks + 1 partial block (2 tokens). Only the 3 full blocks (48 tokens) can hit cache.
- If block 2 differs by even a single token, blocks 0-1 hit cache but blocks 2+ are recomputed.

**Implication for MemoryHub**: Memories injected as a prefix will cache at block granularity. A prompt of 1000 tokens with the first 960 tokens (60 blocks) identical to a previous request will cache 60 blocks, saving ~96% of prefill for that portion.

### What Invalidates the Cache

- Any token change within a block invalidates that block and all subsequent blocks (parent-chain dependency).
- LRU eviction when GPU memory fills -- least recently used blocks are freed first, with tail blocks (end of sequences) evicted before prefix blocks (more likely to be shared).
- `cache_salt` changes (used for tenant isolation).
- LoRA adapter changes (included in hash extras).

### Concurrent Requests with Shared Prefixes

Multiple in-flight requests sharing a prefix naturally share the same physical KV cache blocks. vLLM uses reference counting: blocks with active references are never evicted. This is the core scaling advantage -- 100 concurrent requests with the same system prompt compute it once and share the cached blocks.

### Performance Gains

| Scenario | Metric | Improvement |
|----------|--------|-------------|
| Repeated 10K-token prompt (Qwen3-32B) | TTFT | 4.3s → 0.6s (7x reduction) |
| llm-d precise routing (8 pods, H100) | Output tokens/sec | 8,730 vs 4,429 (2x) |
| llm-d precise routing | Mean TTFT | 0.298s vs 45.28s (152x) |
| General prefix caching | Latency reduction | 3-10x typical |
| vLLM v1 engine over v0 | Throughput | +24% (generation-heavy) |

### vLLM V1 Engine Changes (2025)

The V1 engine made prefix caching **zero-overhead and enabled by default**. Key improvements:
- Constant-time eviction (no performance penalty even at 0% hit rate)
- Pre-allocated block pool (avoids Python object creation overhead)
- Append-only block tables (no in-place modification)
- No configuration required -- users get caching "for free"

---

## 2. llm-d: Kubernetes-Native Distributed LLM Inference

### Overview

llm-d is a Kubernetes-native high-performance inference framework created by Red Hat, IBM Research, Google Cloud, CoreWeave, and NVIDIA. It was accepted as a CNCF Sandbox project in March 2026. Current version: v0.5.1 (February 2026).

llm-d does **not** replace vLLM -- it orchestrates vLLM pods with intelligent scheduling, adding cache-aware routing, disaggregated prefill/decode, and hierarchical KV cache offloading.

### Architecture

```
Request → Gateway API (Inference Extension) → EPP (External Processing Pod)
                                                   ↓
                                              Inference Scheduler
                                              (scoring algorithms)
                                                   ↓
                                         ┌─────────────────────────┐
                                         │  vLLM Pod 1 (prefill)   │
                                         │  vLLM Pod 2 (decode)    │
                                         │  vLLM Pod N ...         │
                                         └─────────────────────────┘
```

### Prefix-Cache-Aware Routing

This is the killer feature for MemoryHub's use case. llm-d solves the "cache scattering" problem where naive load balancers destroy cache locality by spreading related requests across pods.

**How it works**:

1. **KVEvent Stream**: Each vLLM pod publishes `BlockStored`/`BlockRemoved` events via ZMQ.
2. **KV Block Index**: A lightweight in-memory index (339 KB for 365 GB of KV data) maps block hashes to pod locations.
3. **Prefix Scorer**: For each incoming request, queries the index to determine what percentage of the prefix is already cached on each pod.
4. **Balanced Routing**: Cache affinity score is combined with load-awareness to avoid overwhelming a single pod.

**Result**: 87.4% cache hit rate across 4,776 queries, with 88% faster TTFT (340ms vs 2,850ms baseline) and 99.92% of requests routed to the warm pod.

### Hierarchical KV Cache Offloading (v0.5)

Three-tier storage: GPU HBM → CPU DRAM → Filesystem (SSD/NFS). Enables:
- Cross-replica cache reuse via shared filesystem
- New nodes access cached KV states immediately (no warm-up)
- 13.9x improvement at 250 concurrent users vs GPU-only

### Cache-Aware LoRA Routing (v0.5)

Routes requests to pods already holding the relevant LoRA adapter in their prefix cache, avoiding redundant adapter loading and kernel execution.

### Maturity Assessment

- **Production-ready for:** Prefix caching, P/D disaggregation, basic scheduling
- **Active development:** Hierarchical offloading, LoRA routing, scale-to-zero
- **CNCF Sandbox:** Governance established, multi-vendor backing
- **Validated performance:** 50K output tok/s on 16x16 B200 topology

---

## 3. Implications for MemoryHub Output Format

### Will vLLM Cache Recognize Stable Memory Injections?

**Yes**, provided these conditions are met:

1. **Byte-identical prefix**: The tokenized form of the memory injection must be identical across requests. Same text → same tokens → same block hashes → cache hit.
2. **Consistent position**: Memories must appear at the same position in the prompt (i.e., always as the first user message, or always as the system message).
3. **Deterministic serialization**: The memory text must serialize identically each time. No reordering, no timestamp injection, no random IDs.

### Does It Require Exact Byte-Identical Prefixes?

**Yes, absolutely.** There is zero tolerance for variation at the token level. A single different token invalidates the cache from that point forward. This is by design (hash-chaining).

### What Happens When Memories Change Slightly?

If one new memory is **appended** to the end of the memory block:
- All blocks before the new memory still hit cache (the prefix is unchanged).
- Only the new content and everything after it requires computation.
- This is the ideal "append-only" growth pattern.

If a memory is **inserted**, **reordered**, or **modified** within the existing prefix:
- The cache invalidates from the point of change onward.
- Everything after the modification is recomputed.

If memories are **removed** or the sort order changes:
- Complete cache miss from the point of divergence.

### Compiled Knowledge Articles (#171) and Cross-Agent Cache Hits

If compiled articles produce **deterministic output for the same input set** (same memories → same compiled text), then:

- Different agents requesting the same compiled article will produce identical token sequences.
- vLLM will recognize the shared prefix and serve subsequent agents from cache.
- This is the "shared document" use case that APC was designed for.

**Requirements for this to work**:
- Compilation must be fully deterministic (no randomness, no timestamps, no agent-specific metadata in the compiled output).
- The compiled article must be placed at the same position in each agent's prompt.
- The article must be served verbatim (no per-agent decoration or wrapping).

---

## 4. Cache-Aware Design Patterns for MemoryHub

### Optimal Content Placement

```
┌──────────────────────────────────────────┐
│  STABLE (cached)                         │
│  ├─ System instructions                  │
│  ├─ Tool definitions                     │
│  ├─ Compiled knowledge articles          │  ← MemoryHub output goes here
│  ├─ Stable memories (high-weight, sorted)│
│  └─ [cache breakpoint]                   │
├──────────────────────────────────────────┤
│  SEMI-STABLE (partially cached)          │
│  ├─ Conversation history (append-only)   │
│  └─ [cache breakpoint]                   │
├──────────────────────────────────────────┤
│  DYNAMIC (never cached)                  │
│  ├─ Current user message                 │
│  ├─ Session-specific context             │
│  └─ Timestamps, request IDs             │
└──────────────────────────────────────────┘
```

### Rules for MemoryHub Output Format

1. **Deterministic ordering**: Sort memories by a stable key (weight descending, then creation time, then ID). Never use random ordering or non-deterministic tie-breaking.

2. **No timestamps in output**: Memory injection should not include "retrieved at" or "last updated" timestamps. These change every request and destroy cache.

3. **No per-request metadata**: Don't include session IDs, request IDs, or agent-specific identifiers in the memory block.

4. **Append-only growth**: When memories change between requests, prefer appending new content to the end rather than inserting or reordering. This preserves the cached prefix up to the append point.

5. **Deterministic serialization**: If using JSON or structured formats, ensure `sort_keys=True` equivalent. Key ordering differences produce different tokens.

6. **Compiled articles as stable blocks**: Compiled knowledge articles should be versioned. Once compiled, the exact text is immutable until recompilation. This makes them ideal cache-friendly prefixes.

7. **Separate stable from volatile**: If some memories change frequently and others rarely, emit them in separate blocks with the stable ones first.

### Anti-Patterns That Thrash the Cache

| Anti-Pattern | Why It Breaks Cache |
|---|---|
| `"Retrieved at: 2026-04-11T10:30:00Z"` | New timestamp = new tokens = cache miss |
| Random memory ordering | Different order = different tokens from first divergence |
| Including `request_id` or `session_id` in context | Unique per request |
| Truncating/summarizing old memories mid-sequence | Changes tokens at that position |
| Dynamic tool removal based on context | Changes token sequence early in prompt |
| Non-deterministic JSON serialization | Different key order = different tokens |
| Per-agent metadata wrapping compiled articles | Breaks cross-agent cache sharing |

### Manus's Approach (Validated at Scale)

Manus (a production AI agent system) reports:
- KV-cache hit rate is their "single most important metric"
- Average input-to-output ratio is 100:1 (context dominates cost)
- They use logits masking instead of tool removal to preserve cache
- They treat file system as externalized memory rather than bloating context
- Cached tokens cost $0.30/MTok vs $3.00/MTok uncached (10x on Claude Sonnet)

---

## 5. Multi-Provider Caching Comparison

### Provider Mechanisms

| Provider | Mechanism | Min Tokens | Granularity | Cache TTL | Cost Savings |
|----------|-----------|-----------|-------------|-----------|-------------|
| **vLLM (self-hosted)** | Automatic (always-on in V1) | None (block-aligned) | 16-token blocks | LRU eviction | Throughput/latency (no per-token cost) |
| **Anthropic Claude** | Explicit breakpoints + lookback | 1,024-4,096 (model-dependent) | Block-level (internal) | 5 min (or 1 hr) | 90% read discount, 25% write premium |
| **OpenAI** | Automatic prefix matching | 1,024 tokens | 128-token increments | 5-10 min | 50% discount, no write premium |
| **Google Gemini** | Implicit (2.5+) or explicit | 1,024-4,096 | Not documented | Configurable | 75-90% read discount + storage fee |

### Universal Principle

All providers share the same fundamental constraint: **the cache matches on exact token-level prefix identity**. Any divergence from the cached prefix invalidates from that point forward. The implication is the same everywhere:

> Stable content first, dynamic content last. Deterministic serialization. No timestamps in prefixes.

### Key Differences

- **Anthropic** is the only provider requiring explicit `cache_control` breakpoints (though it now has auto-caching for system prompts). The 20-block lookback window means growing conversations can lose cache hits if they grow too fast.
- **OpenAI** is fully automatic but only gives 50% discount (vs Anthropic's 90%).
- **vLLM** has no monetary discount (self-hosted) but the gains are in throughput and TTFT -- the same GPU serves more requests per second.
- **Gemini** charges storage fees for explicit caches but gives the deepest discounts on 2.5+ models (90%).

### Design for Portability

Since the underlying principle is identical across providers, MemoryHub can adopt a single output format strategy that works everywhere:

1. Emit stable, deterministic memory blocks.
2. Place them early in the context window.
3. Never include request-specific metadata.
4. Use append-only growth patterns.
5. Version compiled articles immutably.

This strategy optimizes for vLLM (throughput/TTFT), Anthropic (cost), OpenAI (cost), and Gemini (cost) simultaneously.

---

## 6. Cost / Performance Implications

### Self-Hosted (vLLM / llm-d)

For self-hosted deployments, the "cost" of prefix caching is measured in GPU utilization efficiency:

| Metric | Without APC | With APC + llm-d Routing |
|--------|-------------|--------------------------|
| TTFT (mean) | 45.3s | 0.3s |
| Output tokens/sec | 4,429 | 8,730 |
| Effective GPU utilization | Baseline | ~2x |
| Cache hit rate | ~0% (random routing) | 87.4% |

The 10x price gap that Manus exploits on Claude ($0.30 vs $3.00/MTok) translates to a throughput multiplier in self-hosted settings. A cache hit skips prefill entirely, meaning the GPU can immediately proceed to decoding. At high cache hit rates, you effectively double your serving capacity for the same hardware.

### Hosted API (Anthropic Claude)

| Model | Base Input | Cache Write (5min) | Cache Read | Savings on Hit |
|-------|-----------|-------------------|------------|----------------|
| Opus 4.6 | $5.00/MTok | $6.25/MTok | $0.50/MTok | 90% |
| Sonnet 4.6 | $3.00/MTok | $3.75/MTok | $0.30/MTok | 90% |
| Haiku 4.5 | $0.80/MTok | $1.00/MTok | $0.08/MTok | 90% |

Break-even: A cache write pays for itself after just **1.4 reads** (5-min TTL) or **2 reads** (1-hr TTL).

### What This Means for MemoryHub

If MemoryHub serves 10 agents with overlapping memory contexts:
- **Hosted API**: First agent pays the write premium; subsequent agents get 90% discount. With a 100:1 input-to-output ratio (per Manus), the input cost dominates. Achieving high cache hits on the memory prefix could reduce total inference costs by 50-80%.
- **Self-hosted (vLLM + llm-d)**: First agent computes the full prefill; subsequent agents with the same prefix get near-instant TTFT and the GPU is freed for other work. Cache-aware routing ensures requests with similar memory contexts land on the same pod.

---

## 7. Recommendations for MemoryHub

### Immediate (Design Decisions for #171)

1. **Compiled articles must be fully deterministic**: Same input memories → byte-identical output text. No randomness, no timestamps, no per-retrieval metadata.

2. **Memory injection should use stable sort order**: Weight descending → created_at ascending → UUID as tiebreaker. This order should be documented as part of the API contract.

3. **Output format should be plain text or minimal markup**: Avoid JSON wrappers with metadata that might vary. The memory content itself should be the token sequence.

4. **Version compiled articles**: Each compilation gets a version hash. Serve the exact cached text until explicitly recompiled.

### Near-Term (Platform Design)

5. **Cache-stability scoring**: Track whether an agent's memory context changed since last request. Report cache-friendliness to consumers (e.g., "95% prefix stable").

6. **Append-only memory deltas**: When memories change between requests, provide a mechanism to tell the consumer what changed so they can structure their prompt as `[unchanged prefix] + [delta]`.

7. **Consider llm-d integration**: If deploying on OpenShift with vLLM, llm-d's prefix-cache-aware routing would automatically route agents with similar memory contexts to the same pod, maximizing cache hits without application-level coordination.

### Long-Term (Architecture)

8. **Shared compiled articles as cluster-level resources**: Multiple agents requesting the same compiled knowledge article should produce identical token sequences. llm-d's cross-replica cache sharing (via filesystem tier) means even different pods can benefit.

9. **Memory injection protocol**: Standardize how memories are injected into prompts. The protocol should specify position (early in prompt), format (deterministic), and boundaries (explicit separators for cache breakpoint alignment).

10. **Avoid the "growing conversation" trap**: Anthropic's 20-block lookback means that if conversation history grows by >320 tokens (20 * 16 tokens/block) between turns without an explicit breakpoint, the cache misses entirely. MemoryHub should recommend breakpoint placement guidance to consumers.

---

## Sources

- [vLLM Automatic Prefix Caching (latest docs)](https://docs.vllm.ai/en/latest/features/automatic_prefix_caching/)
- [vLLM v1 Prefix Caching Design](https://docs.vllm.ai/en/v0.8.5/design/v1/prefix_caching.html)
- [vLLM Prefix Caching (stable design docs)](https://docs.vllm.ai/en/stable/design/prefix_caching/)
- [vLLM RFC #2614: Automatic Prefix Caching](https://github.com/vllm-project/vllm/issues/2614)
- [vLLM Cache Salting RFC #16016](https://github.com/vllm-project/vllm/issues/16016)
- [vLLM V1 Alpha Release Blog](https://blog.vllm.ai/2025/01/27/v1-alpha-release.html)
- [Performance Boosts in vLLM 0.8.1 (Red Hat Developer)](https://developers.redhat.com/articles/2025/04/28/performance-boosts-vllm-081-switching-v1-engine)
- [llm-d GitHub Repository](https://github.com/llm-d/llm-d)
- [llm-d Official Site](https://llm-d.ai/)
- [llm-d: KV-Cache Wins You Can See](https://llm-d.ai/blog/kvcache-wins-you-can-see)
- [llm-d v0.5 Release Blog](https://llm-d.ai/blog/llm-d-v0.5-sustaining-performance-at-scale)
- [Master KV Cache Aware Routing with llm-d (Red Hat Developer)](https://developers.redhat.com/articles/2025/10/07/master-kv-cache-aware-routing-llm-d-efficient-ai-inference)
- [llm-d CNCF Acceptance Blog](https://www.cncf.io/blog/2026/03/24/welcome-llm-d-to-the-cncf-evolving-kubernetes-into-sota-ai-infrastructure/)
- [IBM Research: Donating llm-d to CNCF](https://research.ibm.com/blog/donating-llm-d-to-the-cloud-native-computing-foundation)
- [Anthropic Prompt Caching Documentation](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)
- [OpenAI Prompt Caching Guide](https://platform.openai.com/docs/guides/prompt-caching)
- [Google Gemini Context Caching](https://ai.google.dev/gemini-api/docs/caching)
- [Manus: Context Engineering for AI Agents](https://manus.im/blog/Context-Engineering-for-AI-Agents-Lessons-from-Building-Manus)
- [Don't Break the Cache: Evaluation of Prompt Caching for Long-Horizon Agentic Tasks (arXiv)](https://arxiv.org/html/2601.06007v1)
- [Prompt Caching Infrastructure (Introl)](https://introl.com/blog/prompt-caching-infrastructure-llm-cost-latency-reduction-guide-2025)
- [How Prompt Caching Works (sankalp.bearblog.dev)](https://sankalp.bearblog.dev/how-prompt-caching-works/)
- [Prefix-Aware Routing (BentoML LLM Inference Handbook)](https://bentoml.com/llm/inference-optimization/prefix-caching)
- [llm-d: Kubernetes-native Distributed Inferencing (Red Hat Developer)](https://developers.redhat.com/articles/2025/05/20/llm-d-kubernetes-native-distributed-inferencing)
