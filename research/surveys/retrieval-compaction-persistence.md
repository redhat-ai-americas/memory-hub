# Retrieval, Compaction, and Persistence: Consolidated Survey

## Abstract

This document consolidates three research surveys that shaped MemoryHub's retrieval and
context-management direction: (1) a cognitive-science argument that tiered resolution and
associative connectivity — not type taxonomies — are the load-bearing axes for agent memory
retrieval; (2) a state-of-the-art survey of context compaction and agentic context engineering;
and (3) a state-of-the-art survey of conversation persistence for agent systems. The compaction
and persistence surveys fed the now-shipped designs in `docs/design/context-compaction.md` and
`docs/design/conversation-persistence.md`; material absorbed into those designs is summarized
here with pointers rather than repeated. Findings not yet acted on, rejected alternatives, and
the external literature landscape are preserved in full.

Consolidated 2026-07-08 from:
- `research/surveys/tiered-retrieval-and-associative-memory.md`
- `research/surveys/context-compaction-survey.md`
- `research/surveys/conversation-persistence-survey.md`

Originals removed; full text in git history.

**Status:** Research survey (consolidated). Tiered retrieval remains an unimplemented design
direction; compaction and persistence sections are historical context for shipped designs.

---

## Terminology

Three distinct terms are used in MemoryHub and must not be conflated:

- **Compaction** (#169) — thread/session summarization: reducing a conversation's active
  context (and background memory-store curation) via governed, audited structured
  summarization. See `docs/design/context-compaction.md`.
- **Token compression** (#246) — reducing the token cost of a given piece of content
  (prompt compression, token pruning, soft-prompt encoding — the LLMLingua/ICAE family).
- **Knowledge compilation** (#171) — compiling the memory store into an injectable context
  artifact (compilation epochs, `memoryhub:compilation:<tenant>:<owner>` keys).

"Compress" and "compact" are not synonyms in this codebase.

---

# Part 1: Tiered Retrieval and Associative Memory

*Original: standalone position paper, July 2026, Wes Jackson. Not yet absorbed into any
shipped design — preserved in full as the conceptual basis for a future tiered-retrieval API.*

## 1.1 The Cognitive Science Bridge

### The taxonomy everyone uses

Tulving's 1972 episodic/semantic distinction [1], extended by Cohen and Squire's
procedural/declarative split [2]: episodic memory (specific experiences tied to time and
place), semantic memory (general knowledge), procedural memory (how to do things). The agent
memory community has adopted this combined taxonomy wholesale. Mem0 classifies memories into
these types [3]. LangMem ships with separate stores for each [4]. MAGMA proposes distinct
graphs per cognitive category [5]. The taxonomy is not wrong — it is a useful teaching tool for
explaining *why* agents need memory. But it is being used for something it was never designed
to do: drive storage schema and retrieval architecture.

### What Tulving actually showed

The taxonomy comes from lesion studies: Patient K.C. (hippocampal damage) could not form new
episodic memories but retained semantic knowledge [6]; Patient H.M. [7] lost declarative
memory formation but could still learn motor skills [2]. It describes *different neural
substrates* — a statement about neuroanatomy, not a retrieval architecture. LLMs do not have
hippocampi; everything reaches the model through the same channel, the assembled prompt. A
memory tagged `type: episodic` is not processed differently from one tagged `type: semantic`.

### The metadata objection

A reasonable objection: type metadata helps the *retrieval system* decide what to surface. In
practice, good semantic search already handles this: for "what happened when we deployed on
May 15th," the most relevant results will be time-and-context-anchored memories because those
are semantically closest to the query. If the type genuinely matters, it belongs in the memory
text itself, which the model actually sees. Where type classification does earn its keep is
**extraction**, not retrieval — for smaller models that need guidance on what to remember
("remember corrections, remember decisions, remember procedures"). The cognitive categories
are guidance for the extraction process, not schema for the storage layer.

### How humans actually retrieve memories

You smell cinnamon and are suddenly in your grandmother's kitchen — the pie, the bird feeders,
the conversation when your grandfather came home wanting to go fishing. You did not think
"retrieving episodic memory, cluster: grandmother." You followed links. This is Collins and
Loftus's spreading activation [8]; Herz and Schooler [9] confirmed that olfactory cues evoke
memories more emotional and immersive than visual or verbal cues. The retrieval path was
*associative*, not *taxonomic* — what makes those memories accessible together is that they
are *connected*, not that they share a type. Tulving and Thomson's encoding specificity
principle [10] supports this: retrieval cues are effective to the extent they match the
encoding context, not a category label.

The same pattern shows up in development work: an agent proposes a direction that feels "off,"
triggering recall that we already solved this a month ago — not the full solution, just the
stub, the shape of the thing. Cognitive scientists call this "feeling of knowing" or
metamemory: Hart [11] showed people accurately judge whether they have stored information they
cannot currently recall; Nelson and Narens [12] formalized this as a meta-level model of what
the object-level knows. The "stub" in agent memory is a direct analog.

### Two problems, not one

**What to write down** — the extraction/curation problem. Bits do not decay: unlike human
long-term memory, which requires myelination [13] and repetition, a database row persists
indefinitely, so the entire challenge is *selection*. Implicit for frontier models; guided by
the cognitive categories for smaller ones.

**What to put in context** — the retrieval/injection problem, where the real architectural
decisions live: "how much of this memory should be in context right now, and what else should
come along with it?" The answer is almost never binary — it is a gradient. Humans carry
concepts, stubs, pointers to detail; when something triggers a concept, you hydrate it to the
level of detail the situation needs ("FastAPI," then middleware config only if asked). Not
binary retrieval — **tiered resolution**.

## 1.2 Tiered Retrieval as an API Primitive

### The gap in every existing standard

Every system evaluated — OMP [14], Mem0 [3], the OpenAI Agents SDK [15], LangMem [4], the
official MCP memory server [16] — treats retrieval as binary: a memory is either not in
context or fully retrieved. The middle ground is where the cost/value tradeoff is best. An
agent with 200 stubs in context has a rough map of everything it knows for ~2,000 tokens, and
can selectively hydrate the two or three that matter. The alternative — top-K full retrieval —
wastes tokens on irrelevant detail and misses relevant memories outside the K window.

### Four resolution levels

- **Level 0: Latent.** In storage, not represented in context. Requires explicit search or an
  associative trigger from a connected higher-level memory.
- **Level 1: Stub.** A one-line pointer (~5-15 tokens): topic, scope, weight, connection
  count. Two hundred stubs fit in ~2,000-3,000 tokens. Claude Code already does this with
  skills [17]; MemoryHub's hook-based `<memoryhub-context>` injection is the same pattern.
- **Level 2: Summary.** ~50-100 tokens — the key decision, the conclusion without supporting
  evidence. The level most useful for background awareness.
- **Level 3: Full hydration.** Complete content, all branches (rationale, provenance),
  metadata. Needed when the agent is actively working with the memory.

The key insight: a memory can *move between levels* during a conversation — stub at session
start, summary when the conversation touches a related topic, full when the agent acts on it,
and back to stub when the topic passes, freeing context budget.

### The retrieval operations

**`index(scope, project_id, budget) -> stubs[]`** — Return stubs for all accessible memories,
packed to a token budget, sorted by weight. The "memory map" operation. Each stub carries:
`memory_id`, one-line preview, `scope`, `weight`, `relationship_count`, `has_rationale`,
`has_children`.

**`search(query, resolution, budget) -> results[]`** — Semantic search with a resolution
parameter (`stub` | `summary` | `full`). The budget is a soft cap: when exhausted, remaining
results degrade to a lower resolution rather than being silently dropped. A `full` search with
a tight budget might return two full results and eight stubs. The resolution parameter is the
critical addition to standard search APIs.

**`hydrate(memory_id, resolution) -> memory + relationship_stubs[]`** — Expand a memory to a
higher resolution, returning stubs for all connected memories. This is the associative
primitive — the "smell triggers the kitchen" operation. Hydrating A surfaces stubs for B, C,
D; the agent hydrates C and gets stubs for E, F. Graph traversal driven by the agent's
judgment, not a fixed algorithm.

**`compact(memory_id) -> stub`** — Compress a memory back to stub form; the inverse of
hydration, for context management when the conversation shifts topics. (Note: this is
context-window resolution management, distinct from #169 compaction of threads/stores.)

### Associative retrieval in practice

`index()` at session start returns 200 stubs, including
`{id: "m42", preview: "Grandma's kitchen - childhood visits, baking, bird feeders", weight: 0.7, relationships: 5}`.
The user mentions cinnamon; search returns the kitchen memory at Level 2 with relationship
stubs for "Grandpa's fishing trips," "Apple pie recipe," "Bird species at the feeder." The
agent hydrates whichever stub the conversation turns toward, then compacts the cluster back to
stubs when the topic passes. At no point did anyone classify these as "episodic" — the
connectivity did the work.

### What this means for a standard

A memory API standard should define: (1) a **stub format**; (2) a **resolution parameter** on
search; (3) a **hydration operation** returning connected memories as stubs; (4) a **budget
mechanism** that degrades resolution gracefully rather than truncating. CRUD is necessary but
not sufficient. These primitives are absent from every existing standard and proposal.

## 1.3 MemoryHub Wiring

**What already exists:**
- `search_memory` with `mode: index` returns stubs; `mode: full` returns full content. The gap
  is `mode: summary` — a middle tier without full branches.
- `max_response_tokens` already implements budget-aware degradation (full -> stub). Extending
  to full -> summary -> stub is an evolution, not a redesign.
- `read_memory` with `include_versions` and `hydrate` supports on-demand expansion; adding
  relationship stubs to the hydration response is a straightforward extension.
- `relate()` provides the associative graph (`derived_from`, `supersedes`, `conflicts_with`,
  `related_to`).
- Hook-based session-start injection is already Level 1.

**What needs to be formalized:**
- A canonical structured stub format (currently ad-hoc compressed strings).
- `mode: summary` as a retrieval tier. Pre-compute summaries at write time (better latency),
  invalidate and recompute on update.
- Relationship stubs in hydration responses — turning single-memory reads into associative
  clusters without a separate `get_relationships` call.
- A `compact` operation or harness-side compaction convention.

This is design direction, not specification — schema changes, migration path, and API
versioning belong in a planning document once the framework is validated.

## 1.4 Conclusion

The unit of design is not the memory type — it is the **connection** between memories and the
**resolution** at which each appears in context. A system that gets these two axes right
handles episodic clustering, procedural sequencing, and semantic facts without labeling them.
The taxonomy falls out of the graph structure and the retrieval gradient, not the other way
around.

---

# Part 2: Context Compaction and Agentic Context Engineering

*Original survey dated 2026-04-10. The MemoryHub-specific recommendations — governed
compaction, policy engine, provenance chain, dual-track storage, contradiction-aware
compaction, ACE-style reflection, per-scope retention — were **absorbed into
`docs/design/context-compaction.md`** and are only summarized here. The external landscape,
literature, and benchmarks are preserved.*

## 2.1 Definitions

**Context compaction**: taking a conversation or agent session nearing the context window
limit, summarizing or compressing its contents, and reinitiating with the compressed
representation. Applies to every token layer: system prompts, memory store contents,
conversation history, tool results, RAG context, multi-agent shared context.

**Context engineering** ([Anthropic, September 2025](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)):
"The set of strategies for curating and maintaining the optimal set of tokens (information)
during LLM inference" — finding the smallest set of high-signal tokens that maximize the
likelihood of the desired outcome.

**Agentic Context Engineering (ACE)** is an **external academic framework from Stanford,
SambaNova Systems, and UC Berkeley** ([arXiv:2510.04618](https://arxiv.org/abs/2510.04618)) —
its "Curator" role is a component of that framework and is **distinct from MemoryHub's own
curator components** (`curator_rules`, curation pipeline). ACE treats contexts as evolving
playbooks refined through generation, reflection, and curation:

- **Structured division of labor**: Generator (reasoning trajectories), Reflector (distills
  insights from successes/errors), Curator (integrates insights via delta updates).
- **Delta updates over full rewrites**: localized edits that avoid "brevity bias" (dropping
  domain insights for conciseness) and "context collapse" (iterative rewriting eroding detail).
- **Offline and online optimization**: system prompts (offline) and agent memory (online).
- **Results**: +10.6% on agent benchmarks, +8.6% on finance tasks. On AppWorld, ReAct + ACE
  matched IBM's production GPT-4.1 agent using open-source DeepSeek-V3.1, +8.4% on the harder
  test-challenge split.

ACE has an [open-source implementation](https://github.com/ace-agent/ace) and a
[hosted commercial offering by Kayba](https://github.com/kayba-ai/agentic-context-engine)
(~1.9K stars). Kayba's key innovation is a "Recursive Reflector" that writes and executes
Python in a sandbox to programmatically isolate errors, rather than single-pass summarization.
MemoryHub's shipped design applies the ACE Generator/Reflector/Curator pattern to compaction
policy tuning (re-retrieval rate signals, recommendation memories) — see
`docs/design/context-compaction.md` §ACE-Style Reflection.

## 2.2 Provider and Framework Landscape

### Provider-native compaction APIs

**Anthropic** ([server-side compaction](https://platform.claude.com/docs/en/build-with-claude/compaction),
beta header `compact-2026-01-12`): automatic summarization above a threshold; a compaction
block replaces prior messages; works across Claude API, Bedrock, Vertex, Foundry; supports
Zero Data Retention. Claude Code auto-compacts at ~95% capacity, produces structured 7-12k
character summaries, and respects CLAUDE.md compaction instructions.

**OpenAI** ([compaction guide](https://developers.openai.com/api/docs/guides/compaction),
Responses API, February 2026): **opaque, encrypted** compressed items — 99.3% compression but
zero interpretability. Two modes: server-side automatic (`context_management` /
`compact_threshold`) and a standalone `/responses/compact` endpoint. Codex relies on it.

The transparency fork matters: Anthropic produces readable summaries, OpenAI produces opaque
tokens. This drove the shipped design's rejection of opaque compression as incompatible with
audit requirements (absorbed into `docs/design/context-compaction.md` §Strategic Context).

**Microsoft Agent Framework** ([experimental compaction](https://learn.microsoft.com/en-us/agent-framework/agents/conversations/compaction)):
`MessageIndex` grouping messages into atomic `MessageGroup` instances, with
`CompactionTriggers` delegates. Part of the merged AutoGen + Semantic Kernel framework
(production 1.0, April 2026).

### Agent frameworks

- **LangGraph/LangChain** ([memory docs](https://docs.langchain.com/oss/python/langgraph/memory)):
  message buffering (last k), summarization nodes extending `MessagesState`, namespace-scoped
  long-term memory with `hindsight_reflect`. 2026 pattern: LlamaIndex for data structuring +
  LangGraph for orchestration.
- **CrewAI** ([memory docs](https://docs.crewai.com/en/concepts/memory)):
  `respect_context_window` auto-summarization; per-task fact extraction and recall.
- **AutoGen**: centralized transcript, aggressive pruning at token limits (buffer / summary /
  semantic memory tiers), pushing users toward external stores.
- **LlamaIndex** ([memory](https://developers.llamaindex.ai/python/framework/module_guides/deploying/agents/memory/)):
  condensation or relevant-history retrieval; flexible Memory Blocks.
- **Google ADK** ([sessions](https://google.github.io/adk-docs/sessions/)): Session / State /
  Memory layers; hierarchical agent trees with per-subagent context boundaries.

### Memory-centric systems

- **MemGPT / Letta** ([docs](https://docs.letta.com/concepts/memgpt/)): "LLM as OS" — Core
  Memory (RAM), Recall Memory (disk cache), Archival Memory (cold storage). Agents run
  *inside* Letta. Letta Code (2026) adds git-backed memory, skills, subagents.
- **Mem0** ([mem0.ai](https://mem0.ai/), [arXiv:2504.19413](https://arxiv.org/abs/2504.19413)):
  triple storage (vector + graph + KV); actor-aware memories (June 2025); 91% lower p95
  latency and 90%+ token savings vs naive full-context.
- **MemOS** — three distinct 2025 projects: MemTensor's MemOS
  ([arXiv:2505.22101](https://arxiv.org/abs/2505.22101), "MemCube" units, V2.0 multi-modal);
  MemOS for AI Systems ([arXiv:2507.03724](https://arxiv.org/abs/2507.03724), parametric /
  activation / plaintext memory); MemoryOS by BAI-LAB (EMNLP 2025 Oral, hierarchical
  Storage/Updating/Retrieval/Generation).
- **Amazon Bedrock AgentCore Memory** ([blog](https://aws.amazon.com/blogs/machine-learning/amazon-bedrock-agentcore-memory-building-context-aware-agents/)):
  short-term + long-term memory, episodic memory (re:Invent 2025), hierarchical namespaces.

### Specialized tools

**Morph FlashCompact** ([morphllm.com/flashcompact](https://www.morphllm.com/flashcompact)) —
prevention-first: WarpGrep (relevant snippets only, 0.73 F1 in 3.8 steps), Fast Apply (compact
diffs, 10,500 tok/s), Morph Compact (verbatim noise deletion, 50-70% reduction, zero
hallucination). Extends context life 3-4x.

## 2.3 Academic Research on Token Compression

*This section is the literature basis for **token compression (#246)** — distinct from
compaction (#169). Not yet acted on; preserved in full.*

**Prompt Compression Survey** ([Li et al., NAACL 2025 Main, Selected Oral](https://aclanthology.org/2025.naacl-long.368/)) —
the definitive taxonomy. **Hard prompt methods** (remove low-information tokens or
paraphrase): token-level pruning (LLMLingua family), sentence-level selection, abstractive
summarization. **Soft prompt methods** (compress text into fewer special tokens): ICAE,
Gisting, AutoCompressors. Future directions: optimizing the compression encoder, combining
hard and soft methods, multimodality.

**LLMLingua family** ([llmlingua.com](https://www.llmlingua.com/), Microsoft Research) — up to
20x compression with minimal loss: LLMLingua (EMNLP 2023, coarse-to-fine with budget
controller), LLMLingua-2 (ACL 2024, GPT-4 data distillation into a BERT-level token
classifier, task-agnostic extractive), LongLLMLingua (long-context key-information
perception), SecurityLingua (CoLM 2025, security-aware compression against jailbreaks).

**ICAE** ([arXiv:2307.06945](https://arxiv.org/abs/2307.06945), ICLR 2024) — compresses long
context into "memory slots"; ~1% additional parameters; 4x compression on Llama; improves
latency and GPU memory.

**Gisting and AutoCompressors** — Gisting fine-tunes an LLM to produce "gist tokens" (limited
to short prompts); AutoCompressors recursively compress into summary vectors but require
fine-tuning.

**ACON** ([arXiv:2510.00615](https://arxiv.org/abs/2510.00615), October 2025) — optimizes
environment-observation and history compression via failure-driven guideline optimization
(paired trajectories where full context succeeds but compressed fails); gradient-free; works
with closed models; compressors distillable into smaller models. Results: 26-54% peak token
reduction, 95%+ accuracy preserved, up to 46% improvement for smaller LMs.

**Token/KV-cache-level approaches**: H2O (evicts low-attention KV tokens), SnapKV (predicts
important tokens from local prompt context), SlimInfer (dynamic token pruning), COMPACT
(joint pruning of rare vocabulary tokens and FFN channels).

## 2.4 Compactable Context Layers — Findings Not Fully Absorbed

The shipped design covers memory-store compaction, retrieval-time budgets, session compaction,
and cross-agent coordination. Notable survey findings that remain reference material:

- **System prompts as an offline compaction target**: ACE demonstrates system prompts can be
  living documents evolved via delta updates. MemoryHub has no system-prompt evolution
  feature; this remains an unexplored direction.
- **Compaction timing**: Jason Liu's "compaction is momentum" hypothesis
  ([writeup](https://jxnl.co/writing/2025/08/30/context-engineering-compaction/)) — if
  compaction preserves learning trajectories, *when* you compact affects what the agent
  learns. Performance degradation accelerates beyond ~30,000 tokens in most agent workloads;
  proactive compaction at ~70% utilization is the emerging recommendation over Anthropic's
  reactive 95%. (The 70% trigger was adopted in the shipped design.)
- **Tool-result strategies**: prevention-first retrieval (return snippets, not files),
  observation masking, selective attention weighting, result summarization. Only budget-based
  truncation shipped; prevention-first tool design remains open.
- **RAG-context compression**: pre-retrieval compression (LLMLingua-style), post-retrieval
  filtering, hierarchical retrieval (summaries first, expand best). Hierarchical retrieval
  converges with Part 1's tiered-resolution proposal.
- **Multi-agent math** ([Phase Transition for Budgeted Multi-Agent Synergy](https://dev.to/crabtalk/context-compaction-in-agent-frameworks-4ckk),
  January 2026): star topologies saturate at N ~ W/m agents (window W / message length m);
  hierarchical trees bypass this (N = b^L with local budgets per aggregation node). BATS
  (November 2025): four spending regimes, comparable accuracy at 10x less budget. The shipped
  design deliberately scoped MemoryHub out of cross-agent window coordination (orchestrator's
  job) — a rejected-scope decision recorded in the design's Layer 4 section.

## 2.5 Governance Findings (Absorbed)

The survey's governance analysis — lossy-vs-lossless comparison table, audit-trail
requirements (EU AI Act, DORA, HIPAA, financial retention), approval workflows, and the
GDPR Art. 5 / Art. 22 tension resolved by dual-track storage (compacted hot path for the LLM,
full cold-path archive for compliance) — was **absorbed into
`docs/design/context-compaction.md`** (§Strategic Context, §Policy Engine, §Dual-Track
Storage, §Compliance). Key retained comparison:

| Approach | Compression | Interpretable | Auditable |
|----------|------------|---------------|-----------|
| Anthropic structured summary | Moderate | Yes | Yes |
| OpenAI opaque | 99.3% | No | No — **rejected for governed use** |
| Factory structured | Moderate | Yes | Yes — forced sections prevent silent drops |
| LLMLingua | up to 20x | Yes (pruning) | Yes (original recoverable) |
| ICAE | 4x | No (memory slots) | No |

The "killer feature" framing (policy engine, provenance chain as a memory branch, dual-track
storage, contradiction-aware compaction blocking, memory health dashboard, multi-layer
orchestration, ACE-style learning) is now the shipped architecture. The **memory health
dashboard** (staleness scores, redundancy clusters, ranked compaction candidates with
drill-down) is the one component from that list not yet in the shipped design — flagged as
future work.

## 2.6 Benchmarks

- **Factory.ai** ([evaluating compression](https://factory.ai/news/evaluating-compression)):
  36,611 production messages, four probe types (recall, artifact, continuation, decision).
  Structured summarization (3.70) > Anthropic default (3.44) > OpenAI opaque (3.35). This
  result drove the shipped design's structured-summarization choice.
- **ACON**: AppWorld, OfficeBench, Multi-objective QA — 26-54% token reduction at 95%+
  accuracy; distilled compressors hold performance.
- **ACE**: AppWorld leaderboard (September 2025) — ReAct + ACE matched IBM CUGA (production
  GPT-4.1 agent) with open-source DeepSeek-V3.1; +8.4% on test-challenge with online
  adaptation.

---

# Part 3: Conversation Persistence

*Original survey dated 2026-04-10, Wes Jackson. The strategic recommendations — first-class
governed threads, thread-level RBAC, auditable extraction pipeline, retention with cascade,
governed handoff, conversation-scoped session identity — were **absorbed into
`docs/design/conversation-persistence.md`** (#168) and are summarized with pointers. The
landscape survey and architecture-pattern analysis are preserved.*

## 3.1 Persistence vs. Memory

**Conversation persistence** = storage, retrieval, and resumption of raw dialog threads
("What was said?"). **Memory** = extracted, consolidated knowledge ("What was learned?").
The industry converged on three layers: session/thread (working state), memory extraction
(durable, governed knowledge), and conversation archive (raw transcript for audit/replay).

Persistence is **append-only** (you can't un-say something), **high-fidelity** (exact words
matter for audit), and **per-thread**. Memory is **mutable** (ADD/UPDATE/DELETE/NOOP —
Mem0, [arXiv:2504.19413](https://arxiv.org/abs/2504.19413)), **lossy by design**, and
**cross-thread**. The relationship is a pipeline: conversations → raw archive → extraction
(entity identification, relationship inference, conflict detection, deduplication, scope
assignment, weight scoring) → memory store. Zep's Graphiti
([arXiv:2501.13956](https://arxiv.org/abs/2501.13956)) processes episodes into a temporal
knowledge graph the same way.

Key operations: thread creation, append, retrieve, resume, fork/branch, handoff,
compact/summarize, expire/delete, search. (These became the `thread(action=...)` tool in the
shipped design.)

## 3.2 Implementation Landscape

- **LangGraph** ([persistence docs](https://docs.langchain.com/oss/python/langgraph/persistence)):
  the most mature open-source system. Checkpointing per super-step keyed by `thread_id`
  (`BaseCheckpointSaver`); nested subgraph namespaces; separate cross-thread `Store` with
  semantic search; backends InMemory → Postgres/CosmosDB with AES `EncryptedSerializer`; full
  time travel and fork-by-checkpoint. 92% of production deployments use checkpointing.
- **OpenAI**: two distinct layers. The **Conversations API** — raw thread persistence with
  durable identifiers, exempt from the 30-day Response TTL (persists indefinitely);
  alternative `previous_response_id` chaining. **ChatGPT Memory** (consumer, April 2025) —
  saved extracted facts + recent conversation summaries + current session; notably does
  **not** use traditional RAG over history.
  ([Conversation state guide](https://developers.openai.com/api/docs/guides/conversation-state))
- **Google ADK** ([sessions](https://adk.dev/sessions/)): Session (events) / State (KV) /
  Memory (cross-session search); InMemory, SQL-backed (`DatabaseSessionService`), and
  Vertex AI managed implementations including `VertexAIMemoryBankService`.
- **Microsoft Agent Framework** ([architecture](https://learn.microsoft.com/en-us/agent-framework/overview/)):
  serializable `AgentThread` abstraction; `AzureAIAgentThread` keeps history server-side.
  AutoGen v0.4 remains in-memory with no built-in Team checkpointing — persistence must be
  external.
- **CrewAI** ([memory docs](https://docs.crewai.com/en/concepts/memory)): unified `Memory`
  class, LLM-inferred scope/importance; ChromaDB + SQLite storage; extraction-oriented — no
  thread replay/resume at all.
- **Claude Code** ([how it works](https://code.claude.com/docs/en/how-claude-code-works)):
  JSONL files under `~/.claude/projects/`; `--continue` / `--resume`; `--fork-session`
  copies history into a new session ID; auto-compaction near window limits; CLAUDE.md survives
  compaction. Governance: none beyond file permissions — no multi-user access control, audit
  trail, or retention.
- **A2A Protocol** ([spec](https://a2a-protocol.org/latest/specification/), Linux Foundation):
  `contextId` (thread grouping) + `taskId` (work units) + `historyLength` retrieval parameter.
  Deliberately lightweight: defines the wire format for continuity, delegates storage entirely
  to participating agents. No handoff governance, no ownership model.
- **MCP** ([intro](https://modelcontextprotocol.io/docs/getting-started/intro)): explicitly
  out of scope — "session state is a transport convenience, not a workflow ledger."
  Persistence is always the host application's responsibility — exactly the gap a governed
  memory platform fills.
- **Kagenti** ([GitHub](https://github.com/kagenti/kagenti)): `ContextStore` Protocol
  (`load_history` / `store` / `delete_history_from_id`); `InMemoryContextStore` (TTL, lost on
  restart) and `PlatformContextStore` (durable, append-only). No cross-session memory,
  cross-agent sharing, contradiction detection, provenance, or governance — intentional; it's
  an infrastructure platform. MemoryHub integration: Phase 3 `MemoryHubContextStore` — note
  the shipped design **supersedes** the survey-era plan of storing turns as weight-0.3 memory
  child nodes; Kagenti Phase 3 now targets `create_thread` + `append_message` (see
  `docs/design/conversation-persistence.md` §Dependencies).
- **Letta/MemGPT** ([concepts](https://docs.letta.com/concepts/memgpt/)): Core / Recall /
  Archival tiers; the key innovation is **self-editing memory** — the agent loop itself
  decides what to remember via tools.
- **Zep/Graphiti** ([arXiv:2501.13956](https://arxiv.org/abs/2501.13956)): the most
  sophisticated conversation-to-knowledge extraction. Three-tier temporal knowledge graph
  (Episode / Semantic Entity / Community subgraphs); **bi-temporal model** (event timeline T +
  ingestion timeline T'); sliding-window extraction (4 messages / 2 turns) with
  Reflexion-style reflection. 94.8% on Deep Memory Retrieval (vs MemGPT 93.4%); up to 18.5%
  LongMemEval improvement with 90% latency reduction. The 4-message window and temporal
  conflict tiebreaking were adopted in the shipped extraction pipeline.
- **Amazon Bedrock AgentCore** ([docs](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/memory.html)):
  short-term + long-term with configurable extraction strategies; async extraction default in
  production.
- **Mem0** ([paper](https://arxiv.org/abs/2504.19413),
  [State of AI Agent Memory 2026](https://mem0.ai/blog/state-of-ai-agent-memory-2026)):
  clearest articulation of the extraction pipeline (ADD/UPDATE/DELETE/NOOP; Mem0g graph
  variant); four-scope model (user / agent / session / org); actor-aware memories.
  LOCOMO benchmark: full-context 72.9% at 17.12s p95 and ~26K tokens/query vs Mem0 vector
  66.9% at 1.44s and ~1.8K tokens — selective extraction trades ~6 points of accuracy for
  91% lower latency and 90% fewer tokens. (This benchmark justified async-by-default
  extraction in the shipped design.)

## 3.3 Academic Papers and Standardization

- "Memory in the Age of AI Agents: A Survey" (2025,
  [paper list](https://github.com/Shichun-Liu/Agent-Memory-Paper-List)) — catalogs shared
  memory patterns: blackboard stores, orchestrator-level hosting, agent-private stores.
- Zep ([arXiv:2501.13956](https://arxiv.org/abs/2501.13956)) — bi-temporal knowledge graphs;
  episode subgraph as ground truth beneath extracted knowledge.
- A-MEM ([arXiv:2502.12110](https://arxiv.org/abs/2502.12110)) — agents managing their own
  memory lifecycle.
- Mem0 ([arXiv:2504.19413](https://arxiv.org/abs/2504.19413)) — extraction pipeline
  formalization and benchmarks.
- Memoria ([arXiv:2512.12686](https://arxiv.org/abs/2512.12686)) — session-level
  summarization + weighted knowledge graph for incremental user modeling.
- "In Prospect and Retrospect: Reflective Memory Management"
  ([ACL 2025](https://aclanthology.org/2025.acl-long.413.pdf)) — reflection for conversation
  memory management.
- "Beyond the Context Window" ([arXiv:2603.04814](https://arxiv.org/html/2603.04814v1),
  2026) — cost/performance of fact-based memory vs long-context injection.

**Standardization: no conversation persistence standard exists.** A2A provides continuity
identifiers but delegates persistence; MCP explicitly disclaims it. This remains unoccupied
whitespace. Industry convergence points (Mem0 2026 report): four-scope model, three memory
types, async extraction as production default, actor-aware provenance, graph-enhanced memory
moving to production.

## 3.4 Governance Findings (Largely Absorbed)

The governance analysis — thread ownership ambiguity, multi-tenant isolation patterns,
retention policy gaps, EU AI Act Article 12 audit requirements, GDPR erasure/portability with
cascade to extracted memories — was **absorbed into `docs/design/conversation-persistence.md`**
(§Strategic Context, §Governance Model, §Deletion Hierarchy). Points worth retaining here:

- **Thread ownership** has no satisfying industry answer: OpenAI (platform-owned), LangGraph
  (application-controlled), A2A (no ownership model — contextId is a wire identifier, not an
  ownership claim), Kagenti (namespace-scoped via K8s RBAC).
- **Five identity layers** ([Scalekit](https://www.scalekit.com/blog/access-control-multi-tenant-ai-agents)):
  trigger, execution, authorization, tenant, and data identity — all need explicit modeling or
  "access control bugs surface silently months later." Data-bleed risks: warm-pool pod
  recycling between tenants; unscoped queries combining tenant data.
- **GDPR vulnerability rates** ([Protecto](https://www.protecto.ai/blog/gdpr-compliance-for-ai-agents-startup-guide/)):
  47% of cases lack explicit consent, 39% store conversations indefinitely with no retention
  policy, 31% lack erasure/portability mechanisms.
- **EU AI Act** ([Art. 12](https://artificialintelligenceact.eu/article/12/),
  [Art. 19](https://artificialintelligenceact.eu/article/19/), effective 2026-08-02 for
  high-risk): logs must link outputs to source data, model versions, and prompts; penalties up
  to 7% of global revenue / EUR 35M. No framework provides Act-ready audit trails out of the
  box.

## 3.5 Architecture Patterns

### Append-only log vs. summarized store

| Dimension | Append-Only Log | Summarized/Extracted Store |
|---|---|---|
| Fidelity | Exact transcript | Lossy (extracted facts) |
| Retrieval quality | Degrades as log grows | Stable (deduplicated, indexed) |
| Audit value | High (ground truth) | Low (derived) |
| Prompt cost | ~26K tokens full-context | ~1.8K tokens/query |
| p95 latency | 17.12s (LOCOMO) | 1.44-2.59s |
| Mutability | Append-only | ADD/UPDATE/DELETE/NOOP |
| Governance | Simple (immutable) | Complex (versioning needed) |

**Production pattern: use both** — the log as audit trail and ground truth, the extracted
store as agent working memory, with extraction as the pipeline between them. This is the
shipped design's core structure.

### Thread branching

Valuable for exploration, human-in-the-loop decision forks, A/B testing, and error recovery.
LangGraph forks by checkpoint replay; Claude Code via `--fork-session`; OpenAI Conversations
has no built-in forking (create-and-replay); A2A contextId is strictly linear. Observation:
branching is a developer tool more than an end-user feature — except in multi-agent
orchestration, where it happens implicitly on fan-out. (A `fork` action shipped in the
`thread` tool.)

### Cross-agent conversation sharing

| Pattern | Coupling | Governance | Scalability | Typical use |
|---|---|---|---|---|
| Shared thread (LangGraph, Azure AI) | Tight | Hard | Limited | Small agent teams |
| Context injection (A2A, Kagenti Phase 2) | Loose | Medium | Good | Cross-org A2A |
| Shared memory store (MemoryHub, Mem0) | Loose | Good | Good | Platform-level memory |
| Orchestrator-mediated (CrewAI, AutoGen GroupChat) | Medium | Centralized | Limited | Multi-agent orchestration |
| Blackboard (MedAgents, PC-Agent) | Medium | Centralized | Medium | Research workflows |

## 3.6 Strategic Positioning (Absorbed)

The survey's central conclusion — "conversation persistence is the raw material; memory
extraction is the refined product; governance is the differentiator" — and the whitespace list
(thread-level RBAC, auditable conversation-to-memory pipeline, retention with cascade,
governed handoff, tenant-isolated archives, conversation-scoped session identity) became the
shipped design's Strategic Context and feature set. See
`docs/design/conversation-persistence.md`. Items from the whitespace list not fully realized
in the shipped design and worth tracking:

- **Thread search** (full-text or semantic search over message content) — explicitly deferred
  in the shipped design's Open Questions; message-level embeddings double per-message storage.
- **Handoff redaction patterns** (`handoff_redact_patterns`) shipped as a mechanism, but the
  survey's fuller vision — recording what was redacted and why per handoff — is only partially
  covered by `handoff_redacted` flags.
- **"Show me every conversation that influenced this decision"** — the decision-to-conversation
  direction of the audit chain requires linking agent *actions* (not just memories) to
  extractions; no shipped component covers action provenance.

---

## References — Part 1 (Cognitive Science and Agent Memory)

[1] Tulving, E. (1972). Episodic and semantic memory. In *Organization of Memory* (pp. 381-403). Academic Press. [APA PsycNet](https://psycnet.apa.org/record/1973-08477-007)
[2] Cohen, N. J., & Squire, L. R. (1980). Preserved learning and retention of pattern-analyzing skill in amnesia. *Science*, 210(4466), 207-209. [PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC2791502/)
[3] Chhikara, P., et al. (2025). Mem0. *ECAI 2025*. [arXiv:2504.19413](https://arxiv.org/abs/2504.19413). Memory types: [docs.mem0.ai/core-concepts/memory-types](https://docs.mem0.ai/core-concepts/memory-types)
[4] LangChain. (2025). LangMem SDK. [langchain.com/blog/langmem-sdk-launch](https://www.langchain.com/blog/langmem-sdk-launch); [docs](https://langchain-ai.github.io/langmem/)
[5] Jiang, D., Li, Y., Li, G., & Li, B. (2026). MAGMA: A Multi-Graph based Agentic Memory Architecture. [arXiv:2601.03236](https://arxiv.org/abs/2601.03236)
[6] Rosenbaum, R. S., et al. (2005). The case of K.C. *Neuropsychologia*, 43(7), 989-1021. [PubMed](https://pubmed.ncbi.nlm.nih.gov/15769487/)
[7] Scoville, W. B., & Milner, B. (1957). Loss of recent memory after bilateral hippocampal lesions. *J Neurol Neurosurg Psychiatry*, 20(1), 11-21. [10.1136/jnnp.20.1.11](https://doi.org/10.1136/jnnp.20.1.11)
[8] Collins, A. M., & Loftus, E. F. (1975). A spreading-activation theory of semantic processing. *Psych Review*, 82(6), 407-428. [10.1037/0033-295X.82.6.407](https://doi.org/10.1037/0033-295X.82.6.407)
[9] Herz, R. S., & Schooler, J. W. (2002). A naturalistic study of autobiographical memories evoked by olfactory and visual cues. *Am J Psychology*, 115(1), 21-32. [10.2307/1423672](https://doi.org/10.2307/1423672)
[10] Tulving, E., & Thomson, D. M. (1973). Encoding specificity and retrieval processes in episodic memory. *Psych Review*, 80(5), 352-373. [10.1037/h0020071](https://doi.org/10.1037/h0020071)
[11] Hart, J. T. (1965). Memory and the feeling-of-knowing experience. *J Educational Psychology*, 56(4), 208-216. [10.1037/h0022263](https://doi.org/10.1037/h0022263)
[12] Nelson, T. O., & Narens, L. (1990). Metamemory: A theoretical framework and new findings. *Psychology of Learning and Motivation*, 26, 125-173. [10.1016/S0079-7421(08)60053-5](https://doi.org/10.1016/S0079-7421(08)60053-5)
[13] Pan, S., et al. (2020). Preservation of a remote fear memory requires new myelin formation. *Nature Neuroscience*, 23(4), 487-499. [10.1038/s41593-019-0582-1](https://doi.org/10.1038/s41593-019-0582-1)
[14] SMJAI. (2026). Open Memory Protocol (OMP), v0.4. [github.com/SMJAI/open-memory-protocol](https://github.com/SMJAI/open-memory-protocol)
[15] OpenAI. (2025). Agents SDK: Memory. [openai.github.io/openai-agents-python/ref/memory](https://openai.github.io/openai-agents-python/ref/memory/)
[16] MCP Memory Server. [github.com/modelcontextprotocol/servers/tree/main/src/memory](https://github.com/modelcontextprotocol/servers/tree/main/src/memory)
[17] Anthropic. (2025). Claude Code: Memory. [docs.anthropic.com/en/docs/claude-code/memory](https://docs.anthropic.com/en/docs/claude-code/memory)

Additional background: MemGPT ([arXiv:2310.08560](https://arxiv.org/abs/2310.08560)); Zep
([arXiv:2501.13956](https://arxiv.org/abs/2501.13956)); Raaijmakers & Shiffrin (1981), Search
of associative memory, *Psych Review* 88(2), 93-134
([10.1037/0033-295X.88.2.93](https://doi.org/10.1037/0033-295X.88.2.93)); Kumar, Steyvers &
Balota (2022), network-based and distributional approaches to semantic memory, *Topics in
Cognitive Science* 14(1), 54-77 ([10.1111/tops.12548](https://doi.org/10.1111/tops.12548)).

## Sources — Part 2 (Compaction)

Academic: [ACE (arXiv:2510.04618)](https://arxiv.org/abs/2510.04618) ·
[ACON (arXiv:2510.00615)](https://arxiv.org/abs/2510.00615) ·
[Prompt Compression Survey (NAACL 2025)](https://aclanthology.org/2025.naacl-long.368/) ·
[LLMLingua](https://arxiv.org/abs/2310.05736) · [LLMLingua-2](https://arxiv.org/abs/2403.12968) ·
[LongLLMLingua](https://arxiv.org/abs/2310.06839) · [ICAE](https://arxiv.org/abs/2307.06945) ·
[MemGPT](https://research.memgpt.ai/) · [Mem0 (arXiv:2504.19413)](https://arxiv.org/abs/2504.19413) ·
[MemOS (arXiv:2505.22101)](https://arxiv.org/abs/2505.22101) ·
[MemOS for AI Systems (arXiv:2507.03724)](https://arxiv.org/abs/2507.03724) ·
[MemoryOS (BAI-LAB)](https://github.com/BAI-LAB/MemoryOS) ·
[ACE OpenReview](https://openreview.net/forum?id=eC4ygDs02R)

Providers: [Anthropic Compaction API](https://platform.claude.com/docs/en/build-with-claude/compaction) ·
[Anthropic compaction cookbook](https://platform.claude.com/cookbook/tool-use-automatic-context-compaction) ·
[Effective Context Engineering (Anthropic)](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents) ·
[OpenAI Compaction Guide](https://developers.openai.com/api/docs/guides/compaction) ·
[OpenAI /responses/compact](https://developers.openai.com/api/reference/resources/responses/methods/compact) ·
[Microsoft Agent Framework Compaction](https://learn.microsoft.com/en-us/agent-framework/agents/conversations/compaction) ·
[Google ADK Sessions](https://google.github.io/adk-docs/sessions/) ·
[Bedrock AgentCore Memory](https://aws.amazon.com/blogs/machine-learning/amazon-bedrock-agentcore-memory-building-context-aware-agents/)

Frameworks: [LangGraph Memory](https://docs.langchain.com/oss/python/langgraph/memory) ·
[CrewAI Memory](https://docs.crewai.com/en/concepts/memory) ·
[LlamaIndex Memory](https://developers.llamaindex.ai/python/framework/module_guides/deploying/agents/memory/) ·
[Letta/MemGPT](https://docs.letta.com/concepts/memgpt/) · [Mem0](https://mem0.ai/) ·
[LLMLingua](https://www.llmlingua.com/) ·
[Kayba Agentic Context Engine](https://github.com/kayba-ai/agentic-context-engine)

Industry: [Factory.ai compression eval](https://factory.ai/news/evaluating-compression) ·
[Morph FlashCompact](https://www.morphllm.com/flashcompact) ·
[Jason Liu on compaction](https://jxnl.co/writing/2025/08/30/context-engineering-compaction/) ·
[Zylos compression strategies](https://zylos.ai/research/2026-02-28-ai-agent-context-compression-strategies) ·
[InfoQ on ACE](https://www.infoq.com/news/2025/10/agentic-context-eng/) ·
[Context Compaction in Agent Frameworks](https://dev.to/crabtalk/context-compaction-in-agent-frameworks-4ckk) ·
[State of Context Engineering 2026](https://www.newsletter.swirlai.com/p/state-of-context-engineering-in-2026) ·
[Atlan: Context Engineering for AI Governance](https://atlan.com/know/context-engineering-ai-governance/) ·
[Galileo: AI Agent Compliance](https://galileo.ai/blog/ai-agent-compliance-governance-audit-trails-risk-management)

## Sources — Part 3 (Persistence)

Frameworks: [LangGraph Persistence](https://docs.langchain.com/oss/python/langgraph/persistence) ·
[langgraph-checkpoint](https://pypi.org/project/langgraph-checkpoint/) ·
[OpenAI Conversation State](https://developers.openai.com/api/docs/guides/conversation-state) ·
[Google ADK Sessions](https://adk.dev/sessions/) ·
[Google Cloud: Agent State and Memory](https://cloud.google.com/blog/topics/developers-practitioners/remember-this-agent-state-and-memory-with-adk) ·
[CrewAI Memory](https://docs.crewai.com/en/concepts/memory) ·
[CrewAI memory deep dive](https://sparkco.ai/blog/deep-dive-into-crewai-memory-systems) ·
[Microsoft SK Agent Architecture](https://learn.microsoft.com/en-us/semantic-kernel/frameworks/agent/agent-architecture) ·
[Microsoft Agent Framework](https://learn.microsoft.com/en-us/agent-framework/overview/) ·
[A2A Spec](https://a2a-protocol.org/latest/specification/) · [A2A GitHub](https://github.com/a2aproject/A2A) ·
[MCP Intro](https://modelcontextprotocol.io/docs/getting-started/intro) ·
[IBM: What is MCP](https://www.ibm.com/think/topics/model-context-protocol) ·
[Kagenti](https://github.com/kagenti/kagenti) ·
[Red Hat: Zero Trust Agents on Kagenti](https://next.redhat.com/2026/03/05/zero-trust-ai-agents-on-kubernetes-what-i-learned-deploying-multi-agent-systems-on-kagenti/) ·
[Letta Concepts](https://docs.letta.com/concepts/memgpt/) ·
[Letta Agent Memory](https://www.letta.com/blog/agent-memory) ·
[Graphiti](https://github.com/getzep/graphiti) ·
[AgentCore Memory](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/memory.html) ·
[AgentCore Memory Types](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/memory-types.html) ·
[Claude Code: How It Works](https://code.claude.com/docs/en/how-claude-code-works) ·
[Claude Code Session Management](https://stevekinney.com/courses/ai-development/claude-code-session-management)

Papers: [Zep (arXiv:2501.13956)](https://arxiv.org/abs/2501.13956) ·
[Mem0 (arXiv:2504.19413)](https://arxiv.org/abs/2504.19413) ·
[A-MEM (arXiv:2502.12110)](https://arxiv.org/abs/2502.12110) ·
[Memoria (arXiv:2512.12686)](https://arxiv.org/abs/2512.12686) ·
[Agent Memory Paper List](https://github.com/Shichun-Liu/Agent-Memory-Paper-List) ·
[Memory in LLM Multi-agent Systems (TechRxiv)](https://www.techrxiv.org/users/1007269/articles/1367390) ·
[Reflective Memory Management (ACL 2025)](https://aclanthology.org/2025.acl-long.413.pdf) ·
[Beyond the Context Window (arXiv:2603.04814)](https://arxiv.org/html/2603.04814v1)

Industry: [State of AI Agent Memory 2026 (Mem0)](https://mem0.ai/blog/state-of-ai-agent-memory-2026) ·
[ChatGPT Memory internals (Embrace the Red)](https://embracethered.com/blog/posts/2025/chatgpt-how-does-chat-history-memory-preferences-work/) ·
[Scalekit: Multi-Tenant Access Control](https://www.scalekit.com/blog/access-control-multi-tenant-ai-agents) ·
[Protecto: GDPR for AI Agents](https://www.protecto.ai/blog/gdpr-compliance-for-ai-agents-startup-guide/) ·
[EU AI Act Art. 12](https://artificialintelligenceact.eu/article/12/) ·
[EU AI Act Art. 19](https://artificialintelligenceact.eu/article/19/) ·
[Raconteur: EU AI Act audit guide](https://www.raconteur.net/global-business/eu-ai-act-compliance-a-technical-audit-guide-for-the-2026-deadline)

MemoryHub internal: `docs/design/context-compaction.md` (#169, shipped) ·
`docs/design/conversation-persistence.md` (#168, shipped) · `planning/session-persistence.md`
(#86/#104) · `planning/kagenti-integration/architecture.md` (Phase 3 — note: shipped design
supersedes the memory-node-branch approach).
