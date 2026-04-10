# Sources — Agent Memory Benchmark Research

Annotated list of every URL consulted. Primary sources (papers, official repos, benchmark leaderboards) are marked [P]; secondary sources (blogs, analysis articles, marketing pages) are marked [S].

## Part 1 — User-provided URLs

### 1. HN thread 46943506 — "Stack Overflow for AI Coding Agents" [S]

- URL: https://news.ycombinator.com/item?id=46943506
- Submitted URL: `shareful.ai`
- **Not about agent memory benchmarks.** Discussion of a distributed knowledge-sharing platform for coding agents. Comments are mostly celebratory; no substantive skepticism about memory evaluation.
- **Relevance:** Tangential — the thread touches on cross-agent shared knowledge, which is the same problem space as `nexmem-mcp` and the other HN thread below, but it offers nothing about benchmarks or evaluation.
- **Noted as likely mis-linked by the user** — it is probably a stand-in for a different HN discussion they meant to include.

### 2. HN thread 47491466 — "Show HN: Cq – Stack Overflow for AI coding agents" [S]

- URL: https://news.ycombinator.com/item?id=47491466
- Submitted URL: `https://blog.mozilla.ai/cq-stack-overflow-for-agents/`
- **Not about benchmarks either**, but directly relevant to enterprise memory concerns. Mozilla.ai's Cq is a system where agents propose "knowledge units" (KUs) — documented solutions — that can be stored locally by default or optionally shared with team approval (human-in-the-loop review).
- **Top-comment skepticism** (the practitioner signal the user wanted):
  - **Poisoning / supply-chain attack:** malicious actors injecting bad KUs disguised as solutions
  - **Compounding hallucination:** agents "confirming" each other's wrong answers
  - **Rule-following under pressure:** an agent knowing a rule ≠ an agent following it; hard verification tools are more valuable than shared knowledge
  - **Trust infrastructure:** reputation/PageRank for KUs, sybil resistance, all unresolved before launch
- **Relevance to MemoryHub:** this maps directly onto MemoryHub's governance subsystem, specifically contradiction handling and provenance. See `enterprise-requirements.md` for how this ties to the Atlan governance piece.

### 3. nexmem-mcp GitHub repo [P]

- URL: https://github.com/arpanroy41/nexmem-mcp
- **What it is:** A plug-and-play MCP memory server for coding agents; exposes a shared knowledge graph across teams. Supports JSONL / SQLite / MongoDB / PostgreSQL / Redis as storage backends. Personal-mode and team-mode. Advertises atomic operations for concurrent writes.
- **Tools:** `read_graph`, `search_nodes`, `create_entities`, `create_relations`, `add_observations`, `delete_entities`, `delete_observations`, `delete_relations`, `get_memory_status`, `import_jsonl` (11 tools).
- **Benchmark data in repo:** None. The README describes features and setup; there is no evaluation data.
- **Relevance to MemoryHub:** Closest comparable open-source MCP memory server in surface area. It is entity/relation oriented (no weights, no scopes, no branches, no session focus). It has no benchmark of its own, so it cannot be used as a reference score.

### 4. Hindsight (Vectorize) AMB blog post [S — primary source references inside]

- URL: https://hindsight.vectorize.io/blog/2026/03/23/agent-memory-benchmark
- **What it is:** Vectorize's launch post for Agent Memory Benchmark (AMB). Manifesto-style. Argues existing memory benchmarks are either saturated (LoCoMo, LongMemEval) because million-token context windows have made "dump everything into context" competitive, or chatbot-only (they don't cover agentic tasks with tool use, research, multi-step decisions).
- **AMB v1 datasets:** LoCoMo, LongMemEval, LifeBench, MemBench, MemSim, PersonaMem (six). Plus BEAM and AMA-Bench on the live site.
- **Hindsight self-reported scores:**
  - LoCoMo: 92.0%
  - LongMemEval: 94.6%
  - LifeBench: 71.5%
  - PersonaMem: 86.6%
- **Four axes they argue matter:** accuracy, speed, cost, usability. Explicit: "90% accuracy at $10/user/day is not better than 82% at $0.10."
- **Honesty caveat:** the blog only benchmarks Hindsight itself. No competing systems (Mem0, Zep, Letta, Cognee) are run in the post — but the public leaderboard does show Cognee and a "hybrid-search" baseline.

### 5. agentmemorybenchmark.ai [P — hosts the live leaderboard]

- URL: https://agentmemorybenchmark.ai/
- **What it is:** The live AMB leaderboard site, operated by Vectorize (the HTML references `analytics.hindsight.vectorize.io`).
- **Datasets on the site:**
  - **BEAM** — open-ended. 100 conversations, 100K–10M tokens, 2 000 questions across 10 "memory ability categories". Hindsight: 73.9% (4 splits × 4 runs).
  - **LifeBench** — open-ended. Long-horizon multi-source personalized memory across 10 users. Hindsight: 71.5%; hybrid-search: 61.0%.
  - **LoCoMo** — open-ended. Multi-session long-term conversations, 1 986 QA pairs. Hindsight: 92.0%; Cognee: 80.3%; hybrid-search: 79.1%.
  - **LongMemEval** — open-ended. Long-term memory eval for LLM chat assistants. Hindsight: 94.6%; hybrid-search: 74.0%.
  - **PersonaMem** — multiple choice. Long-horizon preference tracking. Hindsight: 86.6%; hybrid-search: 84.4%; Cognee: 81.8%.
  - **AMA-Bench** — listed, 1 split × 0 runs (not yet scored at time of visit).
  - **MemSim** — multiple choice. Chinese daily-life. 6 splits × 0 runs.
  - **MemBench** — multiple choice. Memory at different abstraction levels. 4 splits × 0 runs.
- **Modes:** `rag` (default: retrieve top-k, inject into LLM prompt), `agentic-rag` (LLM can make multiple retrieval calls with different queries), `agent` (bypasses benchmark retrieval pipeline and calls the provider's native `direct_answer()`).
- **Providers currently listed:** `hindsight`, `cognee`, `hybrid-search`, `bm25`. Generator and judge are both Gemini calls.
- **Comparison table (from the site, as of visit):**

  | Provider | BEAM 100K | BEAM 500K | BEAM 1M | BEAM 10M | LIFEBENCH EN | LOCOMO10 | LONGMEMEVAL S | PERSONAMEM 32K |
  |---|---|---|---|---|---|---|---|---|
  | cognee | — | — | — | — | — | 80.3% | — | 81.8% |
  | hindsight · local | 73.4% | 71.1% | 73.9% | 64.1% | 71.5% | 92.0% | 94.6% | 86.6% |
  | hybrid-search | — | — | — | — | 61.0% | 79.1% | 74.0% | 84.4% |

- **Code repo:** https://github.com/vectorize-io/agent-memory-benchmark (MIT-adjacent, 19 stars at visit). Also a second repo `vectorize-io/open-memory-benchmark` for contributors adding new memory systems.
- **Credibility note:** AMB is currently a vendor leaderboard (Hindsight is the top scorer on every dataset because Hindsight built the harness). The harness itself is open source, so a MemoryHub-authored provider plugin could produce a reproducible, comparable number. That is the actionable part.

### 6. arxiv.org/pdf/2602.16313 — MemoryArena [P]

- **User flagged this arxiv ID as suspicious (format check).** It resolves. The format YYMM.NNNNN means YY=26, MM=02 → February 2026. Current date is 2026-04-08, so this is a recent paper and plausible.
- **Verified resolution:** https://arxiv.org/abs/2602.16313v1
- **Title:** "MemoryArena: Benchmarking Agent Memory in Interdependent Multi-Session Agentic Tasks"
- **Date:** 19 Feb 2026
- **Authors:** Zexue He, Yu Wang, Churan Zhi, Yuanzhe Hu, Tzu-Ping Chen, Lang Yin, Ze Chen, Tong Arthur Wu, Siru Ouyang, Zihan Wang, Jiaxin Pei, Julian McAuley, Yejin Choi, Alex Pentland. Affiliations include MIT Media Lab, UW, CMU, UCSD.
- **What it measures:** Agent memory across multiple *interdependent* sessions. Four domains: web navigation, preference-constrained planning, information search, formal reasoning. Key framing: "agents that acquire memory while interacting with the environment" and then reuse it in later sessions.
- **Key finding from the abstract:** Agents that perform well on long-context benchmarks **perform poorly in MemoryArena's agentic setting**. This is important — it directly supports the AMB authors' claim that LoCoMo/LongMemEval no longer discriminate.

## Part 2 — Additional benchmarks found

### LoCoMo (2024) [P]

- https://arxiv.org/abs/2402.17753 — Maharana et al., Snap Research. ACL 2024.
- Site: https://snap-research.github.io/locomo/
- GitHub: https://github.com/snap-research/locomo
- 300 turns × up to 35 sessions per conversation; ~9K tokens avg per convo. 1 986 QA pairs.
- Tasks: QA (single-hop, multi-hop, temporal, commonsense, adversarial), event summarization, multi-modal dialogue generation.
- **Caveat:** built for 32K context-window era; now saturated by frontier models.

### LongMemEval (2024, updated 2025) [P]

- https://arxiv.org/abs/2410.10813 — Di Wu et al. ICLR 2025.
- https://github.com/xiaowu0162/LongMemEval
- https://xiaowu0162.github.io/long-mem-eval/
- 500 curated questions embedded in freely scalable user-assistant chat histories.
- **Five core memory abilities tested:** information extraction, multi-session reasoning, temporal reasoning, knowledge updates, abstention.
- Reported headline: commercial chat assistants and long-context LLMs show a **30% accuracy drop** on memorizing info across sustained interactions.
- Optimizations proposed in the paper: session decomposition, fact-augmented key expansion, time-aware query expansion.

### MemoryAgentBench (2025, ICLR 2026) [P]

- https://arxiv.org/abs/2507.05257 — Hu, Wang, McAuley (UC San Diego).
- https://github.com/HUST-AI-HYZ/MemoryAgentBench
- HuggingFace dataset: `ai-hyz/MemoryAgentBench`
- **Four core memory competencies** evaluated: accurate retrieval, test-time learning, long-range understanding, selective forgetting.
- Contributes two new datasets on top of restructured existing ones: **EventQA** and **FactConsolidation**.
- Explicit critique in the paper: "existing benchmarks either rely on limited context lengths or are tailored for static, long-context settings like book-based QA, which do not reflect the interactive, multi-turn nature of memory agents that incrementally accumulate information."

### AMA-Bench (Feb 2026) [P]

- https://arxiv.org/abs/2602.22769 — "AMA-Bench: Evaluating Long-Horizon Memory for Agentic Applications"
- **Critique:** existing benchmarks are dialogue-centric (human ↔ agent). Real agent memory is a stream of agent ↔ environment interactions dominated by machine-generated content.
- **Two components:** (1) real-world agentic trajectories across representative applications with expert-curated QA, (2) synthetic trajectories scalable to arbitrary horizons with rule-based QA.
- Finding: existing memory systems underperform "because they lack causality and objective information and are constrained by the lossy nature of similarity-based retrieval." AMA-Agent (their proposed system) uses a causality graph + tool-augmented retrieval and achieves 57.22% average accuracy, beating the strongest memory baseline by 11.16%.
- Listed on AMB leaderboard as "ama-bench" with 1 split × 0 runs at time of visit.

### RULER (2024) [P]

- https://arxiv.org/abs/2404.06654 — Hsieh et al., NVIDIA.
- **This is a long-context benchmark, NOT a persistent-memory benchmark.** Included here to be explicit about the distinction.
- Extends vanilla NIAH with multi-hop tracing, aggregation, and other tasks. 13 tasks total. Evaluated 17 LCLMs.
- Headline finding: despite near-perfect vanilla NIAH, only half of 17 long-context models maintain satisfactory performance at 32K tokens.

### HELMET (2024) [P]

- https://arxiv.org/abs/2410.02694 — Princeton NLP.
- https://github.com/princeton-nlp/HELMET
- **Also a long-context benchmark, not persistent-memory.**
- Seven "application-centric" task categories at controllable lengths up to 128K. 59 long-context LMs evaluated.
- Key finding: "synthetic tasks like NIAH do not reliably predict downstream performance" and open-source LCLMs lag closed-source significantly on tasks requiring full-context reasoning.

### BABILong (2024) [P]

- https://arxiv.org/abs/2406.10149 — Kuratov et al. NeurIPS 2024 Datasets & Benchmarks.
- **Long-context reasoning in a haystack** — 20 reasoning tasks distributed across extremely long documents. Extendable up to 10M tokens.
- Key finding: popular LLMs effectively use only 10–20% of context; RAG achieves ~60% on single-fact QA independent of context length.
- **Again, long-context not persistent-memory.** Tests whether the model can do bAbI-style reasoning when the relevant facts are buried in very long input, not whether an external memory system retrieves them.

### StreamBench (2024) [P]

- https://arxiv.org/abs/2406.08747
- https://stream-bench.github.io/
- Evaluates **continuous improvement of LLM agents over an input-feedback sequence**. Binary feedback (thumbs up / thumbs down). Agent iterates and improves.
- This is adjacent to memory but the primary framing is online learning, not memory retrieval.

### NIAH (Needle in a Haystack) (2023) [P]

- GitHub reference: https://github.com/gkamradt/LLMTest_NeedleInAHaystack (Kamradt, 2023).
- The original format: place a "needle" sentence at varying depths in a long "haystack", ask the model to recall it, sweep context length and depth.
- **Long-context, not persistent-memory.** HELMET showed NIAH does not predict downstream performance well; RULER extended it with more realistic variants.

### MemGPT (2023) + DMR benchmark [P]

- https://arxiv.org/abs/2310.08560 — Packer et al. (UC Berkeley Sky Lab).
- Now part of Letta. Introduced the "OS-style" memory hierarchy: core memory, conversational memory, archival memory, external files.
- **DMR (Deep Memory Retrieval)** is the custom benchmark MemGPT defined. It tests consistency — asking agents questions whose answers require knowledge from earlier sessions.
- MemGPT DMR score: 93.4%. Zep later surpassed it at 94.8%.

### Zep (2025) [P]

- https://arxiv.org/abs/2501.13956 — Rasmussen et al. Jan 2025.
- https://github.com/getzep/graphiti (Graphiti is the open-source temporal knowledge graph engine underneath Zep).
- Temporal knowledge graph architecture. Bi-temporal model: timeline T (event chronology) + timeline T' (transactional ingestion order). Three hierarchical subgraphs: episode, semantic entity, community.
- **Benchmarks run:**
  - DMR: Zep 94.8% vs MemGPT 93.4%.
  - LongMemEval: "up to 18.5% accuracy improvement, 90% latency reduction vs baseline." Notable sub-metric: **+38.4% on temporal reasoning questions**.
- **Enterprise framing:** the paper argues DMR is too easy and LongMemEval "better reflects enterprise use cases through complex temporal reasoning tasks".

### Mem0 (2025) [P]

- https://arxiv.org/abs/2504.19413 — Chhikara et al.
- https://github.com/mem0ai/mem0
- Two variants: base Mem0 and Mem0^g (graph-based).
- **Benchmark reported on LoCoMo:** 5% / 11% / 7% relative improvements on single-hop / temporal / multi-hop question types over the best prior methods. **91% lower p95 latency** and **>90% token cost reduction** vs full-context baselines. Claims +26% improvement in LLM-as-judge metric over OpenAI baseline.
- **Controversy noted by Letta** (see below): Mem0's LoCoMo numbers for MemGPT are disputed. The Letta team (MemGPT authors) said they could not reproduce Mem0's MemGPT-on-LoCoMo setup and Mem0 did not respond to clarification requests.

### Letta Filesystem + Context-Bench (2025–2026) [P, S]

- https://www.letta.com/blog/benchmarking-ai-agent-memory — Letta's counter-argument post.
- https://docs.letta.com/leaderboard — live leaderboard, last updated Mar 13, 2026.
- https://github.com/letta-ai/letta-leaderboard
- **Key finding:** Letta agents running GPT-4o mini and using only a filesystem (tools: `grep`, `search_files`, `open`, `close`) achieve **74.0% on LoCoMo**, beating Mem0's reported 68.5% graph-variant score.
- **Thesis:** "memory is more about how agents manage context than the exact retrieval mechanism used"; simple tools that are well-represented in training data beat specialized memory APIs.
- **Letta's own benchmark: Context-Bench**, with two suites:
  - **Filesystem Suite:** chain file ops, trace entity relationships, multi-step retrieval. Top score at visit: GPT-5.2-codex-xhigh 93% at $44.46 cost.
  - **Skills Suite:** discover and load relevant skills from a library to complete tasks. Top: GPT-5.2 85.31% / 63.12%.
- **Cost column is first-class on the Letta leaderboard.** This matches AMB's framing that cost belongs alongside accuracy.

### "Memory in the Age of AI Agents: A Survey" (Dec 2025) [P]

- https://arxiv.org/abs/2512.13564 — 47 authors, lead Shichun Liu.
- https://github.com/Shichun-Liu/Agent-Memory-Paper-List (paper list)
- **Three-dimensional taxonomy:**
  - **Forms:** token-level, parametric, latent
  - **Functions:** factual, experiential, working
  - **Dynamics:** formation, evolution, retrieval
- Includes a compilation of memory benchmarks and OSS frameworks; articulates frontiers: memory automation, RL integration, multimodal memory, multi-agent memory, trustworthiness.
- **Useful as a reference list** for anything we might have missed.

### "Anatomy of Agentic Memory" (Feb 2026) [P]

- https://arxiv.org/abs/2602.19320 — Jiang et al. 22 Feb 2026.
- **Taxonomy of Memory-Augmented Generation (MAG) systems around four structures:**
  1. Lightweight Semantic
  2. Entity-Centric and Personalized
  3. Episodic and Reflective
  4. Structured and Hierarchical
- **Main critique** (important for this research): existing benchmarks are "underscaled, evaluation metrics are misaligned with semantic utility, performance varies significantly across backbone models, and system-level costs are frequently overlooked."
- Specific pain points called out: benchmark saturation, metric validity, judge sensitivity, backbone-dependent accuracy, latency/throughput overhead of memory maintenance.

## Part 5 — Enterprise / governance sources

### Atlan — "AI Agent Memory Governance: Why Ungoverned Memory Is an Enterprise Risk" (April 2026) [S]

- https://atlan.com/know/ai-agent-memory-governance/
- Published 02 April 2026 by Emily Winks. Vendor blog (Atlan sells governance), but it cites primary sources extensively and the framing is unusually sharp.
- **Six governance risks** that no academic benchmark currently measures:
  1. Memory poisoning
  2. Stale context (no temporal validity model; no source-change invalidation)
  3. Access control violations (shared memory surfaces elevated-permission data to unauthorized users)
  4. Compliance failures (GDPR Art. 17 right to erasure; HIPAA retention; SOX ITGC; EU AI Act Art. 12/13)
  5. Audit trail absence (can't reconstruct what the agent knew at decision time)
  6. Multi-agent memory conflicts (two agents with inconsistent state for the same entity)
- **Specific regulatory anchors:** EU AI Act Articles 12, 13, 14 become enforceable **August 2, 2026**, with penalties up to 4% global turnover. GDPR Art. 17 erasure requirement: "no commercially available vector database provides a provable deletion mechanism" (citing IAPP 2025 and Cloud Security Alliance 2025).
- **Research cited:** PoisonedRAG (2024) — 5 malicious docs in millions cause 90% targeted-query attack success. Zenity 2026 Threat Landscape — 45.6% of enterprises rely on shared API keys for agent-to-agent auth (so shared memory scope by default). "Governed Memory: A Production Architecture for Multi-Agent Workflows" https://arxiv.org/html/2603.17787 (Mar 2026).

### Oracle — "Introducing Oracle AI Agent Memory" (Dec 2025) [S]

- https://blogs.oracle.com/database/introducing-oracle-ai-agent-memory-a-unified-memory-core-for-enterprise-ai-systems
- **Positioning matches MemoryHub's architecture** almost exactly: "architectural sprawl makes memory difficult to manage at enterprise scale ... what enterprises need instead is a unified memory core built on a data platform they already trust."
- Converged database approach: vector + JSON + relational + graph in one system, pitched as the alternative to the "fragmented" stack (separate vector store + graph DB + doc store + RDBMS).
- Ships as a Python SDK integrated with Oracle AI Database Private Agent Factory. Expected CY2026.
- **Relevance:** validates MemoryHub's Postgres-only approach (pgvector for vectors, same DB for graph queries, no separate vector DB). Oracle just made the same architectural bet.

## Ancillary references picked up during search

- https://blog.getzep.com/state-of-the-art-agent-memory/ — Zep blog post announcing DMR/LongMemEval wins. [S]
- https://www.marktechpost.com/2025/02/04/zep-ai-introduces-a-smarter-memory-layer-for-ai-agents-outperforming-the-memgpt-in-the-deep-memory-retrieval-dmr-benchmark/ — secondary coverage of Zep's numbers. [S]
- https://github.com/letta-ai/letta/issues/3115 — Feature request in Letta: "Add Standard Memory Evaluation Benchmarks (LOCOMO, MemBench, LongMemEval)". Confirms even Letta does not yet ship all three standard benchmarks in its CI. [P]

## Sources attempted but not usable

- Direct HTML fetch of `agentmemorybenchmark.ai` returned only a SPA shell. Rendered content obtained via headless browser (Puppeteer).
- `defuddle` against AMB site initially returned "very little content" (SPA). Fallback worked.

## Sources the team should probably know about but I did not deep-dive

- **Supermemory Research** (https://supermemory.ai/research/) — another commercial entrant claiming SOTA; positioned alongside Mem0, Zep, Letta.
- **Cognee** — appears on the AMB leaderboard as the only non-Hindsight provider scored, so it is in commercial play. Worth checking their harness and claims if we ever publish comparable numbers.
- **LoCoMo-Plus** (https://arxiv.org/abs/2602.10715) — extension that tests "beyond-factual cognitive memory" and "cue-trigger semantic disconnect". Feb 2026.
- **MEMTRACK** (https://arxiv.org/abs/2510.01353) — "Evaluating Long-Term Memory and State Tracking". Not reviewed here in depth.
- **AMemGym** (https://arxiv.org/html/2603.01966) — "Interactive Memory Benchmarking for Assistants in Long-horizon Conversations". Mar 2026. Not reviewed.
- **MemoryBench** (https://arxiv.org/html/2510.17281v2) — "A Benchmark for Memory and Continual Learning in LLM Systems". Not reviewed.
- **OP-Bench** (https://arxiv.org/html/2601.13722) — "Over-Personalization for Memory-Augmented Personalized Conversational Agents". Tests a failure mode (too much memory) rather than recall.
- **PersonaMem-v2** (https://arxiv.org/abs/2512.06688) — successor to PersonaMem with 1 000 personas and implicit preference inference at 128K context. Not reviewed.
- **AlpsBench** (https://arxiv.org/html/2603.26680) — personalization benchmark for real-dialogue memorization and preference alignment. Not reviewed.
- **MemTrack** and the general cluster of 2603.x agent-memory papers — there is a visible surge of agent-memory benchmark papers in Feb–Mar 2026. Worth a full pass in a later session.
