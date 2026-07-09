# Research

Investigations that informed (or may inform) MemoryHub's design. Shipped conclusions live in `docs/design/`; these files preserve the reasoning, alternatives, and external literature behind them. Consolidated 2026-07-08 from ~21 files into the set below; original files are in git history.

Status legend: **current** = still-live reference material; **partially superseded** = key conclusions absorbed into a shipped design doc (pointers inline); **snapshot** = accurate as of its date, will age.

| File | What it covers | Status |
|---|---|---|
| [agent-memory-foundations.md](agent-memory-foundations.md) | Primer on agent memory types and terms: core vocabulary (harness, working vs durable memory, platform tier) and the four classification axes (temporal, cognitive, storage, architectural role) with literature citations, incl. the cognitive↔`content_type` mapping. Start here. | current |
| [agent-memory-protocol-rfc.md](agent-memory-protocol-rfc.md) | RFC-style proposal for a standard agent-memory protocol. | current (proposal) |
| [surveys/knowledge-and-graph-memory.md](surveys/knowledge-and-graph-memory.md) | Knowledge graphs vs context graphs, graph memory systems and benchmarks, graph DB options, llm-wiki landscape, OKF, ontology contextualization. | partially superseded by [docs/design/graph-enhanced-memory.md](../docs/design/graph-enhanced-memory.md) |
| [surveys/memory-products-landscape.md](surveys/memory-products-landscape.md) | 2026 product landscape + comparisons: Mem0, MemPalace, OpenViking, Perplexity Brain, Neo4j Agent Memory, and others; gaps worth closing. | snapshot (2026) |
| [surveys/retrieval-compaction-persistence.md](surveys/retrieval-compaction-persistence.md) | Tiered retrieval / associative memory position paper; context-compaction survey (incl. external ACE framework); conversation-persistence survey. | partially superseded by [docs/design/context-compaction.md](../docs/design/context-compaction.md) and [docs/design/conversation-persistence.md](../docs/design/conversation-persistence.md) |
| [infra/vllm-kv-cache.md](infra/vllm-kv-cache.md) | vLLM KV-cache optimization survey + prefix-cache validation experiment (raw data in [infra/vllm-kv-cache-results/](infra/vllm-kv-cache-results/)). | current |
| [infra/fips-storage.md](infra/fips-storage.md) | FIPS considerations for the storage layer. | current |
| [infra/claude-code-jwt-limitations.md](infra/claude-code-jwt-limitations.md) | JWT/auth limitations when Claude Code is the MCP client. | current |
| [agent-memory-benchmarks/](agent-memory-benchmarks/) | Benchmark inventory, capability taxonomy, enterprise requirements, MemoryHub gap analysis. | current |
| [agent-memory-ergonomics/](agent-memory-ergonomics/) | Research half of the ergonomics effort: two-vector retrieval benchmarking, pivot detection, FastMCP 3 push notifications. Design half: [docs/agent-memory-ergonomics/](../docs/agent-memory-ergonomics/). | partially superseded (Layers 1–3 shipped) |

When adding new research: put product/system comparisons and literature surveys in `surveys/`, infrastructure investigations in `infra/`, and give each file a Status line in its header so this index stays honest.
