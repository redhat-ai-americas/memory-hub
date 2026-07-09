# Agent Memory Foundations: Types and Terms

A primer on the vocabulary and classification axes of agent memory, as used across the research literature. It assumes you know what an LLM agent is and have used a local agent harness like Claude Code or Cursor. For the conceptual argument — why memory is a context-assembly problem and when it becomes a platform concern — read [What Agent Memory Really Is](../docs/guides/what-is-agent-memory.md); this document is the reference layer underneath it. For the broader research landscape, see the [Memory Systems for LLM-Based Agents survey](https://arxiv.org/abs/2603.10062) and the surveys in this `research/` directory.

## Core terms

**Agent.** A running system built around an LLM that has tools, memory, and some lifecycle. The LLM does inference; the agent is the broader thing that reads input, calls tools, manages state, and produces useful work over time.

**Harness.** The runtime scaffolding around the LLM that turns inference calls into an agent: assembling the prompt for each turn, routing tool calls, maintaining conversation lifecycle, managing local state. Claude Code, Cursor, Copilot, and the agent SDKs (LangChain, LangGraph, Letta, OpenAI Agents SDK, Claude Agent SDK) are all harnesses.

**Working memory.** The state the model is reasoning over right now — the prompt the harness assembles for the current inference call: system prompt, prior turns, tool results, retrieved documents, current user message. Working memory has exactly one place to live, because the assembled prompt is the only thing the model sees.

**Durable memory.** State that survives across sessions: facts learned, preferences accumulated, decisions made, experiences recallable. Unlike working memory, durable memory can live anywhere — a markdown file, SQLite, a vector store, a managed memory service, a graph database — and the choice has real trade-offs.

**Platform tier vs harness tier.** As agent systems mature, some responsibilities stay close to the inference loop (working memory, prompt assembly, tool routing) because they need to be fast and local. Others move to platform services any harness can call (durable memory, conversation persistence, audit logs) because they need to be governed, multi-tenant, and shared. The harness/platform line is the orienting concept for everything else in this repo; see [When Agent Memory Becomes a Platform Concern](https://medium.com/@wjackson_63436/when-agent-memory-becomes-a-platform-concern-4b6cd23af47f).

## Classification axes

Four axes recur across the literature. They are orthogonal: any given memory has a position on each.

### Axis 1: Temporal scope (how long it lasts)

- **Working memory** — the current inference context; discarded after each LLM call [1].
- **Short-term / session memory** — full conversation history within one session; implemented via checkpointing (LangGraph) or conversation buffers [2].
- **Long-term memory** — persists across sessions; storage mechanism is an orthogonal choice [1].

### Axis 2: Cognitive type (what kind of knowledge)

The cognitive-science taxonomy, combining Tulving's episodic/semantic distinction [3] with Cohen and Squire's procedural/declarative split [4], adapted for agents:

- **Semantic memory** — general knowledge independent of personal experience. "FastAPI uses Pydantic for validation." What things are [5].
- **Episodic memory** — records of specific experiences tied to time and context. "On May 15, user approved the schema change because of the compliance deadline." What happened [6].
- **Procedural memory** — how to do things: workflows, standing instructions, recipes. "When deploying, always run migrations before rolling out new pods" [5].

**Important caveat:** from the LLM's perspective, all context is processed identically regardless of type label. These categories are most useful as **extraction heuristics** (what to remember), not as storage schema or retrieval axes. See [Tiered Retrieval and Associative Memory](surveys/retrieval-compaction-persistence.md).

#### Mapping to MemoryHub's content_type enum

MemoryHub's shipped `content_type` enum (experiential / behavioral / knowledge) roughly aligns with the cognitive vocabulary. The mapping is **approximate** — the enum was designed for extraction and governance, not to mirror cognitive science:

| Cognitive term | MemoryHub content_type | Notes |
|---|---|---|
| Episodic | `experiential` | What happened, tied to time and context |
| Procedural | `behavioral` | How to act; workflows and standing instructions |
| Semantic | `knowledge` | General facts, independent of experience |

Declarative memory (the semantic + episodic umbrella) has no single enum value; working memory is out of scope entirely (harness-owned).

### Axis 3: Storage / retrieval strategy (how it's stored and found)

- **File-based** — memories as files in a directory structure agents naturally traverse: CLAUDE.md, Cursor rules, copilot-instructions.md [7].
- **Vector/embedding** — content embedded in a vector DB, retrieved by semantic similarity; scales well but loses structure [1].
- **Graph** — entities and relationships in a knowledge/property graph; preserves structure, supports traversal. Graphiti implements a bi-temporal model (event time T, ingestion time T', four timestamps per fact) enabling temporal queries and fact invalidation [8].
- **Hybrid** — most production systems combine strategies: Graphiti uses graph + vector + community summaries [8]; Mem0 uses vector + graph [5].

### Axis 4: Architectural role (what function it serves)

- **World memory** — objective external facts, separated from the agent's own experiences (Latimer et al.'s "World Network") [9].
- **Behavioral memory** — agent personality, communication style, tool preferences; related to Karpathy's "system prompt learning" [10] and LangMem's procedural memory. Liao et al.'s STEAM shows structured atomic memory units outperform single unstructured summaries [11]. Note this term as applied to agent self-representation is emerging usage, not yet formal in the literature.
- **Observational memory** — compressed summaries synthesized by background observer/reflector processes; Mastra reports 3-40x compression [12].
- **Reasoning traces** — records of how past problems were solved. Reflexion [13] showed stored verbal self-reflections improve subsequent attempts; Retrieval-of-Thought [14] formalizes reward-guided traversal of a thought graph.

### Cross-cutting: retrieval resolution

Orthogonal to all four axes: *how much* of a memory to surface. Most systems treat retrieval as binary, but a resolution gradient — stub (~10 tokens) → summary (~50-100 tokens) → full hydration — enables much better context budget utilization. See [Tiered Retrieval and Associative Memory](surveys/retrieval-compaction-persistence.md).

### Cross-cutting: governance

Who can read, who can write, retention, audit, deletion on request. Absent from cognitive-science taxonomies because it is an enterprise concern — and it is the axis that turns agent memory from a research topic into a procurement decision. See the [Agent Memory Protocol RFC](agent-memory-protocol-rfc.md).

## Where MemoryHub sits on these axes

For orientation only (the design docs are authoritative): MemoryHub is a **platform-tier, durable-memory** service — long-term on Axis 1, spanning all three cognitive types via `content_type` on Axis 2, hybrid vector+graph on PostgreSQL on Axis 3, and centered on experiential/behavioral roles on Axis 4, with governance (six scopes, identity, versioning, curation, audit) as its differentiating cross-cutting axis. Working memory, conversation orchestration, and RAG corpora are deliberately out of scope — those belong to the harness, orchestration services, and the retrieval layer respectively. See [docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md) and [strategy/platform-architecture.md](../strategy/platform-architecture.md).

## References

[1] Packer, C., Fang, V., et al. (2023). MemGPT: Towards LLMs as Operating Systems. [arXiv:2310.08560](https://arxiv.org/abs/2310.08560)

[2] LangChain. (2025). Memory overview. [docs.langchain.com/oss/python/concepts/memory](https://docs.langchain.com/oss/python/concepts/memory)

[3] Tulving, E. (1972). Episodic and semantic memory. In *Organization of Memory* (pp. 381-403). Academic Press. [APA PsycNet](https://psycnet.apa.org/record/1973-08477-007)

[4] Cohen, N. J., & Squire, L. R. (1980). Preserved learning and retention of pattern-analyzing skill in amnesia. *Science*, 210(4466), 207-209. [PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC2791502/)

[5] Chhikara, P., et al. (2025). Mem0: Building Production-Ready AI Agents with Scalable Long-Term Memory. *ECAI 2025*. [arXiv:2504.19413](https://arxiv.org/abs/2504.19413). Memory types: [docs.mem0.ai/core-concepts/memory-types](https://docs.mem0.ai/core-concepts/memory-types)

[6] Qi, B., et al. (2026). Memory for Autonomous LLM Agents: Mechanisms, Evaluation, and Emerging Frontiers. [arXiv:2603.07670](https://arxiv.org/abs/2603.07670)

[7] Anthropic. (2025). Claude Code: Memory. [docs.anthropic.com/en/docs/claude-code/memory](https://docs.anthropic.com/en/docs/claude-code/memory)

[8] Rasmussen, P., et al. (2025). Zep: A Temporal Knowledge Graph Architecture for Agent Memory. [arXiv:2501.13956](https://arxiv.org/abs/2501.13956). Bi-temporal model: [HTML version](https://arxiv.org/html/2501.13956v1), Section 3.

[9] Latimer, C., et al. (2025). Hindsight is 20/20: Building Agent Memory that Retains, Recalls, and Reflects. [arXiv:2512.12818](https://arxiv.org/abs/2512.12818)

[10] Karpathy, A. (2025). "System prompt learning." [X post, May 10, 2025](https://x.com/karpathy/status/1921368644069765486).

[11] Liao, Y., et al. (2026). From Atom to Community: Structured and Evolving Agent Memory for User Behavior Modeling. [arXiv:2601.16872](https://arxiv.org/abs/2601.16872). Addresses *user* behavior modeling, cited for the structural insight.

[12] Mastra. (2026). Observational Memory: 95% on LongMemEval. [mastra.ai/research/observational-memory](https://mastra.ai/research/observational-memory)

[13] Shinn, N., et al. (2023). Reflexion: Language Agents with Verbal Reinforcement Learning. *NeurIPS 2023*.

[14] Retrieval-of-Thought: Efficient Reasoning via Reusing Thoughts. [arXiv:2509.21743](https://arxiv.org/abs/2509.21743)
