# Context Compaction & Agentic Context Engineering: State of the Art Survey

**Date**: 2026-04-10
**Purpose**: Strategic planning for governed context compaction in MemoryHub
**Status**: Research survey

---

## 1. Definitions and Scope

### What is Context Compaction?

Context compaction is the practice of taking a conversation or agent session nearing the context window limit, summarizing or compressing its contents, and reinitiating a new context window with the compressed representation. It is the first lever in context engineering for long-running agent coherence.

More broadly, context compaction applies to every layer of information that occupies tokens in an LLM's context window: system prompts, memory store contents, conversation history, tool call results, retrieved documents, and multi-agent shared context.

### What is Context Engineering?

Anthropic's engineering team [defined context engineering](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents) (September 2025) as:

> The set of strategies for curating and maintaining the optimal set of tokens (information) during LLM inference.

Good context engineering means "finding the smallest possible set of high-signal tokens that maximize the likelihood of some desired outcome." This reframes the problem from "prompt engineering" (finding the right words) to the broader question of information management across all token sources.

### What is Agentic Context Engineering (ACE)?

ACE is a specific academic framework proposed by researchers at Stanford, SambaNova Systems, and UC Berkeley ([arXiv:2510.04618](https://arxiv.org/abs/2510.04618)). It treats contexts as **evolving playbooks** that accumulate, refine, and organize strategies through a modular process of generation, reflection, and curation. Key contributions:

- **Structured division of labor**: Generator (produces reasoning trajectories), Reflector (distills insights from successes/errors), Curator (integrates insights via delta updates)
- **Delta updates over full rewrites**: Localized edits that accumulate new insights while preserving prior knowledge, avoiding "brevity bias" (dropping domain insights for conciseness) and "context collapse" (iterative rewriting eroding detail)
- **Offline and online optimization**: System prompts (offline) and agent memory (online) can both be evolved
- **Results**: +10.6% on agent benchmarks, +8.6% on finance tasks. On AppWorld, ReAct + ACE matched IBM's production GPT-4.1 agent using only open-source DeepSeek-V3.1, and surpassed it by 8.4% on the harder test-challenge split

ACE has an [open-source implementation](https://github.com/ace-agent/ace) and a [hosted commercial offering by Kayba](https://github.com/kayba-ai/agentic-context-engine) (~1.9K GitHub stars). Kayba's key innovation is a "Recursive Reflector" that writes and executes Python code in a sandbox to programmatically search for patterns and isolate errors, rather than single-pass summarization.

---

## 2. Existing Approaches and Implementations

### 2.1 Provider-Native Compaction APIs

#### Anthropic (Claude)

[Anthropic's server-side compaction](https://platform.claude.com/docs/en/build-with-claude/compaction) (beta header `compact-2026-01-12`) is the recommended strategy for long-running conversations:

- Automatically summarizes when input tokens exceed a configured threshold
- Generates a compaction block containing the summary
- All message blocks prior to the compaction block are dropped on subsequent requests
- Works across Claude API, AWS Bedrock, Google Vertex AI, and Microsoft Foundry
- Supports Zero Data Retention

**Claude Code specifics**: Auto-compact triggers at ~95% capacity (25% remaining). Users can customize compaction behavior in CLAUDE.md with instructions like "When compacting, always preserve the full list of modified files and any test commands." Claude Code produces structured summaries (7-12k characters) with sections for analysis, files, pending tasks, and current state.

#### OpenAI

[OpenAI's compaction](https://developers.openai.com/api/docs/guides/compaction) takes a fundamentally different approach:

- **Opaque, encrypted representation**: Returns compressed items that are not human-interpretable
- **Two modes**: Server-side automatic (via `context_management` parameter with `compact_threshold`) and standalone `/responses/compact` endpoint
- Achieves the highest compression ratios (99.3%) but sacrifices interpretability
- Released February 2026 via the Responses API
- Codex relies on this mechanism for long-running coding tasks

The architectural difference matters: Anthropic produces readable summaries; OpenAI produces opaque compressed tokens. This has direct implications for auditability and governance.

#### Microsoft Agent Framework

[Microsoft's compaction framework](https://learn.microsoft.com/en-us/agent-framework/agents/conversations/compaction) (currently experimental) operates on a `MessageIndex` that groups messages into atomic `MessageGroup` instances. Key concepts:

- `CompactionTriggers`: delegates that evaluate whether compaction should proceed based on current MessageIndex metrics
- Part of the unified Microsoft Agent Framework that merged AutoGen and Semantic Kernel (production 1.0 released April 2026)

### 2.2 Agent Framework Approaches

#### LangGraph / LangChain

[LangGraph's memory system](https://docs.langchain.com/oss/python/langgraph/memory) provides two core approaches:

- **Message Buffering**: Keep the last k messages in memory (simple but lossy)
- **Summarization nodes**: Add summary nodes in the graph to condense long histories, extending `MessagesState` with a `summary` field
- **Long-term memory**: Stored in custom "namespaces" (cross-session), with tools like `hindsight_reflect` that synthesize across multiple memories
- Short-term memory is thread-scoped via checkpoints; long-term memory is namespace-scoped

In 2026, the prevailing pattern is to combine LlamaIndex for data structuring with LangGraph for agent orchestration.

#### CrewAI

[CrewAI's automatic context window management](https://docs.crewai.com/en/concepts/memory):

- `respect_context_window` parameter: when True, automatically detects when conversation history exceeds limits and summarizes
- After each task, discrete facts are extracted and stored; before each task, relevant context is recalled and injected
- Works in the background without explicit function calls

#### AutoGen (now Microsoft Agent Framework)

AutoGen keeps a centralized transcript as short-term memory and prunes aggressively at token limits:

- **Buffer Memory**: Recent interactions up to a token limit
- **Summary Memory**: Periodic summarization of past interactions
- **Semantic Memory**: Embedding-based retrieval by similarity
- Aggressive pruning pushes users toward external stores for long-lived data

#### LlamaIndex

[LlamaIndex memory](https://developers.llamaindex.ai/python/framework/module_guides/deploying/agents/memory/) handles context window management with condensation or relevant history retrieval. Recent additions include flexible Memory Blocks for fact extraction and vector memory, combining chat history with document context.

#### Google ADK

[Google's Agent Development Kit](https://google.github.io/adk-docs/sessions/) provides structured context management through three layers:

- **Session**: Chronological sequence of messages/actions in a single interaction
- **State**: Data stored within a specific session
- **Memory**: Searchable archive spanning across conversations
- Hierarchical agent trees where root agents delegate to sub-agents (each with their own context boundaries)
- Production backends: SQL databases, or Vertex AI Agent Engine

### 2.3 Memory-Centric Systems

#### MemGPT / Letta

[Letta](https://docs.letta.com/concepts/memgpt/) pioneered the "LLM as Operating System" metaphor, treating the LLM context window as virtual memory:

- **Core Memory**: Small block living in context (like RAM) -- read/written directly
- **Recall Memory**: Searchable conversation history outside context (like disk cache)
- **Archival Memory**: Long-term storage queried via tool calls (like cold storage)
- Agents run *inside* Letta, not just *use* Letta for memory
- **Letta Code** (2026): Adds git-backed memory, skills, subagents, and cross-device access

#### Mem0

[Mem0](https://mem0.ai/) is the "universal memory layer for AI agents":

- **Triple storage**: Vector databases (semantic search), graph databases (relationships), key-value stores (fast fact retrieval)
- **Actor-aware memories** (June 2025): Tags each memory with its source actor, enabling filtering between user statements and agent inferences
- 91% lower p95 latency, 90%+ token cost savings vs. naive approaches
- 26% improvement over OpenAI on LLM-as-a-Judge metrics
- Published paper: [arXiv:2504.19413](https://arxiv.org/abs/2504.19413)

#### MemOS (Multiple Implementations)

Three distinct MemOS projects emerged in 2025:

1. **MemOS by MemTensor** ([arXiv:2505.22101](https://arxiv.org/abs/2505.22101)): Memory OS for LLMs with three-layer architecture (Interface, Operation, Infrastructure). Uses "MemCube" as a standardized memory unit. V2.0 (December 2025) added multi-modal memory and tool memory.
2. **MemOS for AI Systems** ([arXiv:2507.03724](https://arxiv.org/abs/2507.03724)): Unified management for heterogeneous memory types (parametric, activation, explicit plaintext)
3. **MemoryOS by BAI-LAB** (EMNLP 2025 Oral): Hierarchical storage with Storage, Updating, Retrieval, and Generation modules for personalized agents

#### Amazon Bedrock AgentCore Memory

[AgentCore Memory](https://aws.amazon.com/blogs/machine-learning/amazon-bedrock-agentcore-memory-building-context-aware-agents/) (announced AWS Summit NYC 2025):

- Short-term working memory (within session) + long-term intelligent memory (across sessions)
- Episodic memory for learning from experiences (re:Invent 2025)
- Hierarchical namespaces for data organization and access control
- Encrypted at rest and in transit

### 2.4 Specialized Compaction Tools

#### Morph FlashCompact

[FlashCompact](https://www.morphllm.com/flashcompact) takes a "prevention-first" approach:

- **WarpGrep**: Returns only relevant code snippets instead of entire files (0.73 F1 in 3.8 steps)
- **Fast Apply**: Compact diffs instead of full file rewrites (10,500 tok/s)
- **Morph Compact**: Verbatim deletion of noise (50-70% reduction, zero hallucination)
- Extends context life by 3-4x at 33,000+ tokens/second

---

## 3. Academic Research

### 3.1 Prompt Compression Survey (NAACL 2025)

The definitive survey: [Prompt Compression for Large Language Models: A Survey](https://aclanthology.org/2025.naacl-long.368/) (Li et al., NAACL 2025 Main, Selected Oral). Taxonomy:

**Hard Prompt Methods** -- remove low-information tokens or paraphrase for conciseness:
- Token-level pruning (LLMLingua family)
- Sentence-level selection
- Abstractive summarization

**Soft Prompt Methods** -- compress text into fewer special tokens:
- ICAE (In-Context Autoencoder)
- Gisting
- AutoCompressors

Future directions include optimizing the compression encoder, combining hard and soft prompt methods, and leveraging multimodality insights.

### 3.2 LLMLingua Family (Microsoft Research)

[LLMLingua](https://www.llmlingua.com/) achieves up to 20x compression with minimal performance loss:

- **LLMLingua** (EMNLP 2023): Coarse-to-fine compression with budget controller for semantic integrity, token-level iterative compression, instruction tuning for distribution alignment
- **LLMLingua-2** (ACL 2024): Data distillation from GPT-4 for token classification with BERT-level encoder. Task-agnostic, extractive compression
- **LongLLMLingua**: Focuses on long-context scenarios, improving key information perception
- **SecurityLingua** (CoLM 2025): Defense against jailbreak attacks via security-aware compression

### 3.3 In-Context Autoencoder (ICAE)

[ICAE](https://arxiv.org/abs/2307.06945) (ICLR 2024) compresses long context into short compact "memory slots" that can be directly conditioned on:

- Pretrained with autoencoding + language modeling objectives on massive text
- ~1% additional parameters added to the base LLM
- Achieves 4x context compression on Llama
- Improves both latency and GPU memory cost during inference

### 3.4 Gisting and AutoCompressors

- **Gisting**: Fine-tunes an LLM to produce "gist tokens" as compression of a prompt. Limited to short prompts.
- **AutoCompressors**: Recursively compress long text into summary vectors. Sophisticated but requires LLM fine-tuning to generate summary vectors.

### 3.5 ACON: Agent Context Optimization

[ACON](https://arxiv.org/abs/2510.00615) (October 2025) optimizes both environment observation and interaction history compression:

- **Failure-driven guideline optimization**: Given paired trajectories where full context succeeds but compressed fails, an LLM analyzes failure causes and updates compression guidelines
- **Gradient-free**: No parameter updates, works with closed-source models
- **Distillation**: Optimized compressors can be distilled into smaller models
- Results: 26-54% peak token reduction, preserves 95%+ accuracy, up to 46% performance improvement for smaller LMs

### 3.6 Token-Level Approaches

- **H2O (Heavy Hitter Oracle)**: Evicts KV-cache tokens with low cumulative attention scores
- **SnapKV**: Uses local prompt context to predict and retain important tokens for future generation
- **SlimInfer**: Dynamic token pruning for long-context inference
- **COMPACT**: Joint pruning of rare vocabulary tokens and FFN channels using common-token-weighted activations

### 3.7 ACE (Stanford/SambaNova/UC Berkeley)

[ACE](https://arxiv.org/abs/2510.04618) (October 2025, reviewed at [OpenReview](https://openreview.net/forum?id=eC4ygDs02R)):

- Addresses brevity bias and context collapse in prior approaches
- Generator/Reflector/Curator architecture with delta updates
- Adapts without labeled supervision using natural execution feedback
- Demonstrates scalable self-improvement through structured, evolving contexts

---

## 4. The Layers of Context That Can Be Compacted

### 4.1 System Prompts / Instructions

System prompts are the "offline" compaction target. ACE's Curator performs delta updates to system prompts based on accumulated insights. Key challenge: system prompts often contain critical governance rules, tool definitions, and behavioral constraints that cannot safely be summarized.

**Current practice**: System prompts are typically static or minimally evolved. ACE demonstrates they can be treated as living documents that improve with experience.

### 4.2 Memory Store Contents

Memories themselves get stale, redundant, or contradictory. This is distinct from conversation compaction -- it's about the health of the memory store itself.

- **Staleness**: Preferences or decisions that were superseded
- **Redundancy**: Multiple memories encoding the same fact with slight variations
- **Contradiction**: Memories that conflict with each other or with observed behavior
- **Scope creep**: Project-scoped memories that are really user-scoped, or vice versa

Memory compaction strategies: periodic deduplication sweeps, contradiction detection, staleness scoring based on access patterns and age, merge suggestions for overlapping memories.

### 4.3 Conversation History Within a Session

This is the most well-studied compaction target. Key findings:

- **Structured summarization** outperforms freeform summarization ([Factory.ai benchmark](https://factory.ai/news/evaluating-compression): 3.70 vs 3.44 for Anthropic, 3.35 for OpenAI on their probe-based evaluation across 36,611 messages)
- **Compaction timing matters**: Jason Liu's hypothesis that "compaction is momentum" -- if compaction preserves learning trajectories, then when you compact affects what the agent learns
- **Performance degradation accelerates beyond 30,000 tokens** in most agent workloads; automatic compaction should trigger at ~70% utilization
- Anthropic's auto-compact at 95% is reactive; proactive compaction at 70% is emerging as the recommendation

### 4.4 Tool Call Results

Tool results are often the largest single token consumers. Strategies:

- **Prevention-first** (Morph FlashCompact): Return only relevant code snippets, not entire files
- **Observation masking**: Strip or truncate verbose tool outputs post-hoc
- **Selective attention**: Weight important tool results higher in compaction decisions
- **Result summarization**: Replace raw tool output with structured summaries

### 4.5 Retrieved Documents / RAG Context

RAG contexts are transient by nature but consume significant tokens:

- **Pre-retrieval compression**: Compress documents before they enter context (LLMLingua approach)
- **Post-retrieval filtering**: Remove low-relevance retrieved chunks
- **Hierarchical retrieval**: Retrieve summaries first, expand only the most relevant

### 4.6 Multi-Agent Shared Context

The mathematical constraint ([Phase Transition for Budgeted Multi-Agent Synergy](https://dev.to/crabtalk/context-compaction-in-agent-frameworks-4ckk), January 2026):

- **Star topologies saturate** at N ~ W/m agents (context window W / message length m)
- **Hierarchical trees bypass this**: N = b^L total agents across L depth levels, each aggregation node maintaining local token budgets
- **BATS** (November 2025): Budget Tracker with four spending regimes (HIGH, MEDIUM, LOW, CRITICAL), replacing historical trajectories with summaries, achieving comparable accuracy at 10x less budget

Most frameworks (except AutoGen's group chat) use context isolation -- the parent never holds the child's full context. This is itself a form of compaction-by-architecture.

---

## 5. Governance Angles

### 5.1 Lossy vs. Lossless Compression

All practical compaction today is **lossy**. The critical question is: what is safe to discard?

| Approach | Compression | Interpretable | Auditable | Lossiness |
|----------|------------|---------------|-----------|-----------|
| Anthropic | Moderate | Yes (readable summary) | Yes | Moderate -- structured sections preserve key details |
| OpenAI | Very high (99.3%) | No (opaque/encrypted) | No | Unknown -- cannot inspect what was kept |
| Factory structured | Moderate | Yes | Yes | Low -- forced sections prevent silent drops |
| LLMLingua | Up to 20x | Yes (token pruning) | Yes (original recoverable) | Variable |
| ICAE | 4x | No (memory slots) | No | Moderate |

**Governance implication**: Opaque compression (OpenAI's approach) is incompatible with audit requirements. Any governed system must use an approach where the compressed representation is inspectable.

### 5.2 Audit Trail Requirements

The regulatory environment is tightening:

- **EU AI Act** (phased enforcement through August 2026): High-risk AI systems require demonstrating what happened and why. Fines up to 35M EUR or 7% global revenue.
- **DORA** (January 2025): Mandatory technical controls and governance for financial technology providers.
- **HIPAA**: Activity logs retained for 6 years.
- **Financial services**: May require 7+ year retention.

An audit trail for compaction needs to capture: the original context (or a hash), the compaction method and trigger, the resulting summary, what was dropped, and who/what approved the compaction.

### 5.3 Who Approves Compaction?

Current approaches are fully automatic -- the system compacts when a threshold is crossed, with no human in the loop. In governed environments:

- **Policy-driven triggers**: Compaction rules defined by administrators, not hardcoded
- **Scope-dependent policies**: Enterprise-scope memories might require different retention than user-scope
- **Approval workflows**: High-weight or compliance-tagged memories might require human approval before compaction
- **Override capability**: Users/admins can mark specific memories or context as "never compact"

### 5.4 Compliance Implications

Summarizing vs. retaining full records creates tension:

- **Right to explanation** (GDPR Art. 22): If an AI decision was informed by context that was later compacted, can you explain the decision?
- **Data minimization** (GDPR Art. 5): Argues *for* compaction -- don't retain more than necessary
- **Record-keeping** (financial regulations): Argues *against* lossy compaction -- retain full records
- **Resolution**: Separate the operational context (compacted for performance) from the audit record (full, archived, never compacted). The LLM sees the compacted version; the compliance team sees the full history.

---

## 6. What Would Make This a "Killer Feature" in a Governed Memory Platform

### 6.1 Not Just Compression -- Governed Compression

The gap in the market: every framework does some form of compaction, but none treat compaction as a governed operation with provenance, audit trails, and policy-driven retention. The components:

**Policy Engine for Compaction**
- Per-scope retention policies (enterprise memories: never auto-compact; user memories: compact after 90 days inactive)
- Per-weight thresholds (weight >= 0.9: protected; weight < 0.5: auto-compact candidates)
- Domain-specific rules (compliance-tagged content: archive-before-compact; experimental notes: aggressive compaction)

**Provenance Chain**
- Every compaction produces a provenance record: source memory IDs, compaction method, resulting summary, timestamp, triggering policy
- The provenance record is itself a memory (branch_type: "compaction_provenance")
- Full bidirectional traceability: from any current memory, you can trace back through every compaction that shaped it

**Dual-Track Storage**
- Hot path: compacted context for agent performance
- Cold path: full original records for compliance and forensics
- The agent never needs to know about the cold path; governance tooling queries it directly

**Contradiction-Aware Compaction**
- When compacting, if the compaction would merge or summarize memories that have active contradiction reports, flag for human review
- Prevent compaction from silently resolving contradictions

**Memory Health Dashboard**
- Staleness scores, redundancy clusters, contradiction counts
- Compaction candidates ranked by token savings vs. information value
- Audit log of all compaction events with drill-down to originals

### 6.2 Multi-Layer Compaction Orchestration

The unique opportunity for a memory platform like MemoryHub is orchestrating compaction across layers:

1. **Memory store curation** (background): Deduplicate, merge, archive stale memories. This is the "cold" compaction that improves the quality of what gets retrieved.
2. **Retrieval-time filtering** (per-query): Select only the most relevant memories for the current query, weighted by scope and domain. This is token-budget-aware context assembly.
3. **Session-level compaction** (during conversation): When the conversation grows long, compact the history while preserving memory-derived context. This coordinates with the memory store so compacted facts can be re-retrieved if needed.
4. **Cross-agent compaction** (multi-agent): When agents share context through MemoryHub, each agent's view is already compacted to its needs. The memory platform is the natural coordination point.

### 6.3 ACE-Style Learning from Compaction

Applying ACE's Generator/Reflector/Curator pattern to memory governance:

- **Generator**: The agent operates normally, producing memory writes and reads
- **Reflector**: Analyzes which memories were actually useful vs. retrieved-but-ignored, which compaction events caused information loss, and which memory patterns correlate with successful task completion
- **Curator**: Updates memory weights, suggests merges, recommends archival, and tunes compaction policies

This turns the memory platform into a self-improving system that learns not just *what* to remember, but *how aggressively to compact* based on observed outcomes.

### 6.4 Differentiation Summary

| Capability | Existing Systems | Governed Memory Platform |
|-----------|-----------------|-------------------------|
| Compaction trigger | Token threshold only | Policy-driven, scope-aware, weight-sensitive |
| Audit trail | None | Full provenance chain per compaction event |
| Original preservation | Discarded | Cold-path archive with regulatory retention |
| Compaction method | One-size-fits-all | Per-scope, per-domain, per-weight policies |
| Cross-layer coordination | None | Memory store + session + retrieval orchestrated |
| Self-improvement | None (except ACE) | ACE-style reflection on compaction effectiveness |
| Contradiction handling | None | Compaction blocked when contradictions are unresolved |
| Human oversight | None | Approval workflows for protected content |

---

## 7. Key Benchmarks and Evaluation

### Factory.ai Evaluation Framework

[Factory.ai](https://factory.ai/news/evaluating-compression) tested on 36,611 messages from production software engineering sessions. Evaluation uses four probe types: recall (specific facts), artifact (file paths/outputs), continuation (can the agent continue working), and decision (rationale for choices made).

Results: Structured summarization (3.70) > Anthropic default (3.44) > OpenAI opaque (3.35).

### ACON Benchmarks

Tested on AppWorld, OfficeBench, and Multi-objective QA: 26-54% peak token reduction while preserving 95%+ accuracy. Distilled compressors maintain performance at lower cost.

### ACE Benchmarks

On AppWorld leaderboard (September 2025): ReAct + ACE matched IBM CUGA (production GPT-4.1 agent) using open-source DeepSeek-V3.1. +8.4% on test-challenge split with online adaptation.

---

## 8. Recommendations for MemoryHub

### Near-Term (Integrate)

1. **Implement memory-level compaction**: Add staleness scoring, redundancy detection (MemoryHub already has `get_similar_memories` and `suggest_merge`), and automated archival for low-weight stale memories
2. **Add compaction provenance**: When memories are merged or archived, create a provenance branch recording what happened and why
3. **Define retention policies per scope**: Enterprise/organizational memories get longer retention; user memories can be more aggressively compacted

### Medium-Term (Build)

4. **Policy engine for compaction rules**: Admin-configurable rules for when and how compaction happens, integrated with the existing RBAC model
5. **Dual-track storage**: Hot (PostgreSQL) for active memories, cold (MinIO/S3) for archived originals
6. **Session-aware memory retrieval**: Coordinate with agent session compaction so that facts compacted out of the conversation can be re-retrieved from the memory store

### Long-Term (Differentiate)

7. **ACE-style reflector**: Analyze which memories drive successful outcomes and tune compaction policies accordingly
8. **Cross-agent compaction coordination**: As MemoryHub serves multiple agents, orchestrate per-agent context assembly with token-budget awareness
9. **Compliance certification**: Build toward demonstrable compliance with EU AI Act transparency requirements for memory operations

---

## Sources

### Academic Papers
- [ACE: Agentic Context Engineering (arXiv:2510.04618)](https://arxiv.org/abs/2510.04618) -- Stanford/SambaNova/UC Berkeley
- [ACON: Optimizing Context Compression for Long-horizon LLM Agents (arXiv:2510.00615)](https://arxiv.org/abs/2510.00615)
- [Prompt Compression for Large Language Models: A Survey (NAACL 2025)](https://aclanthology.org/2025.naacl-long.368/)
- [LLMLingua: Compressing Prompts (EMNLP 2023)](https://arxiv.org/abs/2310.05736)
- [LLMLingua-2: Data Distillation (ACL 2024)](https://arxiv.org/abs/2403.12968)
- [LongLLMLingua: Long Context Scenarios](https://arxiv.org/abs/2310.06839)
- [In-Context Autoencoder / ICAE (ICLR 2024)](https://arxiv.org/abs/2307.06945)
- [MemGPT: LLMs as Operating Systems](https://research.memgpt.ai/)
- [Mem0: Building Production-Ready AI Agents (arXiv:2504.19413)](https://arxiv.org/abs/2504.19413)
- [MemOS: Memory-Augmented Generation (arXiv:2505.22101)](https://arxiv.org/abs/2505.22101)
- [MemOS: A Memory OS for AI System (arXiv:2507.03724)](https://arxiv.org/abs/2507.03724)
- [MemoryOS for Personalized AI Agents (EMNLP 2025 Oral)](https://github.com/BAI-LAB/MemoryOS)

### Provider Documentation
- [Anthropic: Compaction API](https://platform.claude.com/docs/en/build-with-claude/compaction)
- [Anthropic: Automatic Context Compaction Cookbook](https://platform.claude.com/cookbook/tool-use-automatic-context-compaction)
- [Anthropic: Effective Context Engineering for AI Agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)
- [OpenAI: Compaction Guide](https://developers.openai.com/api/docs/guides/compaction)
- [OpenAI: Compact a Response](https://developers.openai.com/api/reference/resources/responses/methods/compact)
- [Microsoft: Agent Framework Compaction](https://learn.microsoft.com/en-us/agent-framework/agents/conversations/compaction)
- [Google ADK: Session, State, and Memory](https://google.github.io/adk-docs/sessions/)
- [Amazon Bedrock AgentCore Memory](https://aws.amazon.com/blogs/machine-learning/amazon-bedrock-agentcore-memory-building-context-aware-agents/)

### Framework Documentation
- [LangGraph Memory Overview](https://docs.langchain.com/oss/python/langgraph/memory)
- [CrewAI Memory](https://docs.crewai.com/en/concepts/memory)
- [LlamaIndex Memory](https://developers.llamaindex.ai/python/framework/module_guides/deploying/agents/memory/)
- [Letta / MemGPT Docs](https://docs.letta.com/concepts/memgpt/)
- [Mem0](https://mem0.ai/)
- [LLMLingua](https://www.llmlingua.com/)
- [Kayba Agentic Context Engine](https://github.com/kayba-ai/agentic-context-engine)

### Industry Analysis and Benchmarks
- [Factory.ai: Evaluating Context Compression for AI Agents](https://factory.ai/news/evaluating-compression)
- [Morph FlashCompact: Every Context Compaction Method Compared](https://www.morphllm.com/flashcompact)
- [Jason Liu: Two Experiments on Agent Compaction](https://jxnl.co/writing/2025/08/30/context-engineering-compaction/)
- [Zylos Research: AI Agent Context Compression Strategies](https://zylos.ai/research/2026-02-28-ai-agent-context-compression-strategies)
- [InfoQ: Researchers Introduce ACE](https://www.infoq.com/news/2025/10/agentic-context-eng/)
- [Context Compaction in Agent Frameworks (DEV Community)](https://dev.to/crabtalk/context-compaction-in-agent-frameworks-4ckk)
- [State of Context Engineering in 2026](https://www.newsletter.swirlai.com/p/state-of-context-engineering-in-2026)
- [Context Engineering for AI Governance (Atlan)](https://atlan.com/know/context-engineering-ai-governance/)
- [AI Agent Compliance & Governance (Galileo)](https://galileo.ai/blog/ai-agent-compliance-governance-audit-trails-risk-management)
