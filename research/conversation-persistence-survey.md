# Conversation Persistence for AI Agent Systems: State of the Art

**Date:** 2026-04-10
**Status:** Research survey for strategic planning
**Author:** Wes Jackson

---

## 1. What Conversation Persistence Means in the Agent Context

Conversation persistence and memory are related but architecturally distinct concerns. The distinction matters for positioning and design.

**Conversation persistence** is the storage, retrieval, and resumption of raw dialog threads -- the chronological sequence of messages, tool calls, tool outputs, and artifacts exchanged between a user (or agent) and a system. It answers: "What was said?"

**Memory** is extracted, consolidated knowledge derived from conversations (and other sources) -- discrete facts, preferences, entities, relationships, and procedures stored in a searchable, updateable form. It answers: "What was learned?"

The industry has converged on treating these as separate architectural layers:

- **Session/thread layer**: Current conversation state. Working memory. Lost when the session ends unless persisted.
- **Memory extraction layer**: Durable knowledge. Survives across sessions. Subject to governance (who wrote it, who can read it, is it still true).
- **Conversation archive**: The raw transcript, stored for audit, replay, or forensics. Not injected into prompts wholesale.

Google ADK formalizes this as three concepts: **Session** (single conversation thread), **State** (key-value pairs scoped to that session), and **Memory** (searchable cross-session knowledge). Letta/MemGPT uses an OS metaphor: **Core Memory** (in-context, like RAM), **Recall Memory** (searchable conversation history, like disk cache), and **Archival Memory** (long-term extracted knowledge, like cold storage). Mem0's 2026 State of Agent Memory report confirms the field has shifted from "shoving conversation history into context windows" to treating memory as a distinct extraction-and-consolidation pipeline.

### Key operations in conversation persistence

| Operation | Description |
|---|---|
| **Thread creation** | Allocate a new conversation identifier |
| **Append** | Add messages, tool calls, artifacts to the thread |
| **Retrieve** | Load thread history (full or windowed) |
| **Resume** | Continue a conversation from a prior point |
| **Fork/branch** | Create a divergent copy of a thread from a specific point |
| **Handoff** | Transfer a conversation thread between agents or systems |
| **Compact/summarize** | Reduce thread size while preserving essential context |
| **Expire/delete** | Remove threads per retention policy |
| **Search** | Find threads by content, metadata, or participant |

### How this differs from memory

Conversation persistence is **append-only by nature** (you can't un-say something). Memory is **mutable** -- facts get updated, contradicted, deprecated. Conversation persistence is **high-fidelity** (exact words matter for audit). Memory is **lossy by design** (extraction discards noise, consolidates duplicates). Conversation persistence is **per-thread**. Memory is **cross-thread** (a preference learned in conversation A should be available in conversation B).

The relationship between them is a pipeline: conversations produce the raw material from which memory is extracted. The Mem0 paper (arXiv:2504.19413) describes this as an ADD/UPDATE/DELETE/NOOP extraction pipeline that runs over new conversational content to identify discrete, durable facts. Zep's Graphiti engine (arXiv:2501.13956) takes a similar approach, processing conversation episodes into a temporal knowledge graph through entity extraction, relationship inference, and conflict resolution.

---

## 2. Existing Approaches and Implementations

### 2.1 LangGraph

LangGraph has the most mature conversation persistence system among open-source agent frameworks.

**Architecture:** Automatic checkpointing saves graph state at every "super-step" (a single execution cycle where scheduled nodes run). Checkpoints are organized by `thread_id`. The `BaseCheckpointSaver` interface defines `put()`, `get_tuple()`, `list()`, and `put_writes()` operations.

**Thread management:** Each thread "contains the accumulated state of a sequence of runs." Threads are the primary key for all state retrieval. Subgraphs get nested checkpoint namespaces (`"outer_node:uuid|inner_node:uuid"`).

**Cross-thread memory:** A separate `Store` interface provides namespaced key-value storage that persists across threads. Namespaces are tuples like `(user_id, "memories")`. Supports semantic search when configured with an embedding model.

**Backends:** InMemorySaver (dev), SqliteSaver, PostgresSaver, CosmosDBSaver. Encryption via `EncryptedSerializer` with AES.

**Time travel:** Any checkpoint can be replayed or forked. `get_state_history()` returns chronologically-ordered snapshots. `update_state()` creates new checkpoints with modified values (passes through reducer functions).

**Production adoption:** 92% of production LangGraph deployments use checkpointing for conversation continuity.

**Ref:** [LangGraph Persistence Docs](https://docs.langchain.com/oss/python/langgraph/persistence), [langgraph-checkpoint PyPI](https://pypi.org/project/langgraph-checkpoint/)

### 2.2 OpenAI

OpenAI offers two distinct layers:

**Conversations API** (developer platform): Works with the Responses API to create persistent, multi-turn interactions. A conversation is "a long-running object with its own durable identifier" that persists across sessions, devices, and jobs. Conversations store items (messages, tool calls, tool outputs). Conversation objects are **not subject to the 30-day TTL** that applies to regular Response objects -- they persist indefinitely. Alternative: `previous_response_id` chaining links responses sequentially without explicit conversation objects.

**ChatGPT Memory** (consumer product): As of April 2025, ChatGPT references all past conversations. Uses a four-layer architecture: User Memory (permanent extracted facts), Recent Conversation Summaries, and Current Session Messages. "Saved Memories" are discrete extracted facts ("user is building a compliance tool"). Chat History uses an opaque retrieval system surfacing details from past conversations without full transcript injection. Notably, ChatGPT does **not** use traditional RAG for conversation history -- it keeps lightweight recent conversation summaries.

**Key distinction:** The Conversations API is raw thread persistence (the platform stores everything). ChatGPT Memory is extracted knowledge (the system decides what to remember). These are separate systems serving different purposes.

**Ref:** [OpenAI Conversation State Guide](https://developers.openai.com/api/docs/guides/conversation-state), [OpenAI Conversations API](https://www.arielsoftwares.com/openai-conversations-api/)

### 2.3 Google ADK

Google's Agent Development Kit structures conversation context through three interconnected layers:

**Session** represents a single ongoing interaction. Contains chronological events (messages + tool calls) and a mutable `state` dictionary. The `SessionService` manages lifecycle: create, retrieve, update (append events, modify state), delete.

**State** (`session.state`) stores key-value pairs relevant to the active conversation (shopping cart items, user preferences mentioned during the exchange). Updated by the agent during execution.

**Memory** is searchable cross-session information. The `MemoryService` manages long-term knowledge ingestion and search.

**Implementations:**
- `InMemorySessionService` / `InMemoryMemoryService` -- dev only, lost on restart
- `DatabaseSessionService` -- SQL-backed (PostgreSQL, MySQL, SQLite) with async drivers
- `VertexAISessionService` -- Google Cloud managed, scalable production
- `VertexAIMemoryBankService` -- managed long-term memory with intelligent extraction

**Ref:** [ADK Sessions Docs](https://adk.dev/sessions/), [Google Cloud Blog: Agent State and Memory](https://cloud.google.com/blog/topics/developers-practitioners/remember-this-agent-state-and-memory-with-adk)

### 2.4 Microsoft Agent Framework (Semantic Kernel + AutoGen)

Released in public preview October 2025, merges AutoGen's multi-agent orchestration with Semantic Kernel's enterprise foundations.

**AgentThread abstraction:** The abstract `AgentThread` class serves as the core conversation state container. It "abstracts away the different ways in which conversation state may be managed for different agents." Stateful agent services store conversation state in the service; stateless agents require the entire chat history to be passed on each invocation.

**Serialization:** `AgentThread` is serializable -- you can dump it to persist state and reload to resume. This enables long-running agent scenarios.

**Azure AI Agent Thread:** The `AzureAIAgentThread` implementation manages conversation history server-side, "reducing the overhead of maintaining state."

**AutoGen history:** AutoGen stores conversation history in-memory by default. The v0.4 redesign (January 2025) added asynchronous, event-driven architecture but still does not provide built-in checkpointing for Team abstractions -- "any persistence or recovery mechanisms must be implemented externally."

**Ref:** [Agent Architecture - Microsoft Learn](https://learn.microsoft.com/en-us/semantic-kernel/frameworks/agent/agent-architecture), [Microsoft Agent Framework Overview](https://learn.microsoft.com/en-us/agent-framework/overview/)

### 2.5 CrewAI

CrewAI's memory system evolved into a unified `Memory` class (replacing separate short-term, long-term, entity, and external memory types) with an LLM analyzing content when saving to infer scope, categories, and importance.

**Storage:** ChromaDB for short-term vector memory, SQLite for recent task results, separate SQLite table for long-term memory. Uses `/{entity_type}/{identifier}` namespace patterns for scoping.

**Multi-agent:** Memory is managed per agent (short-term buffer, long-term vector index). Agents can use crew-shared memory (default) or receive a scoped private view.

**No thread persistence per se:** CrewAI's memory is extraction-oriented, not conversation-archival. There's no thread replay or resume capability.

**Ref:** [CrewAI Memory Docs](https://docs.crewai.com/en/concepts/memory), [Deep Dive into CrewAI Memory Systems](https://sparkco.ai/blog/deep-dive-into-crewai-memory-systems)

### 2.6 Claude Code

Claude Code provides file-based conversation persistence with explicit session management:

**Storage:** Each message, tool use, and result is written to a plaintext JSONL file under `~/.claude/projects/<encoded-cwd>/*.jsonl`.

**Resumption:** `claude --continue` resumes the last session. `claude --resume` opens a session picker. `/resume` works from inside an active session. New messages append to the existing conversation.

**Forking:** Creates a new session that starts with a copy of the original's history but diverges from that point. Fork gets its own session ID; original stays unchanged.

**Compaction:** Automatic summarization when approaching context window limits. Creates a summary and replaces older messages. Persistent instructions in CLAUDE.md survive compaction.

**Governance model:** None beyond file permissions. Sessions are local to the developer's machine. No multi-user access control, no audit trail, no retention policies. The `CLAUDE.md` / `.claude/` system provides project-level instruction persistence but not conversation governance.

**Ref:** [How Claude Code Works](https://code.claude.com/docs/en/how-claude-code-works), [Claude Code Session Management](https://stevekinney.com/courses/ai-development/claude-code-session-management)

### 2.7 A2A Protocol (Agent-to-Agent)

Google's Agent2Agent protocol (donated to Linux Foundation, April 2025) provides conversation continuity through two identifiers:

**`contextId`:** Logically groups multiple related Task and Message objects. Represents a conversation thread that can span multiple tasks. Agents generate new contextIds when processing messages that lack one; clients include contextId in subsequent messages to continue the conversation.

**`taskId`:** Identifies individual units of work within a context. Clients can send subsequent messages referencing the same taskId to continue or refine tasks.

**History retrieval:** The `historyLength` parameter controls how much conversation history is returned (unset = server default, 0 = none, positive integer = N recent messages).

**No direct handoff mechanism:** Agents share context through explicit contextId/taskId references combined with message history retrieval. The protocol emphasizes agents collaborating "based on declared capabilities and exchanged information, without needing to share their internal thoughts, plans, or tool implementations."

**Conversation state ownership:** A2A is deliberately lightweight about persistence -- the protocol defines the wire format for conversation continuity but delegates storage entirely to the participating agents.

**Ref:** [A2A Protocol Specification](https://a2a-protocol.org/latest/specification/), [A2A GitHub](https://github.com/a2aproject/A2A)

### 2.8 MCP (Model Context Protocol)

MCP explicitly does **not** own conversation persistence:

> "Session state is a transport convenience, not a workflow ledger."

MCP standardizes context exchange but leaves ownership of persistence entirely to the host application. The spec notes that if the socket dies, recovery is "not catastrophic" because no durable data is lost. Implementation guides direct developers to store anything that must outlive the socket in their own database, queue, or object store.

This means conversation persistence in MCP-based systems is always the responsibility of the host application or a purpose-built service -- which is exactly the gap a governed memory platform fills.

**Ref:** [MCP Introduction](https://modelcontextprotocol.io/docs/getting-started/intro), [IBM: What is MCP](https://www.ibm.com/think/topics/model-context-protocol)

### 2.9 Kagenti

Kagenti's conversation persistence model is shallow by design:

**ContextStore Protocol:** Defines three operations -- `load_history()`, `store()`, `delete_history_from_id()`. The interface is a Protocol (structural typing), not an ABC.

**Implementations:**
- `InMemoryContextStore` -- TTL-based cache, lost on pod restart (the default)
- `PlatformContextStore` -- durable but still append-only

**VectorStore:** Scoped per-agent for semantic search. No cross-agent sharing.

**Gaps:** No cross-session memory, no cross-agent memory sharing, no contradiction detection, no provenance tracking, no governance layer. This is intentional -- Kagenti is an infrastructure platform, not a memory platform.

**MemoryHub integration path:** Phase 3 of the MemoryHub-Kagenti integration implements `MemoryHubContextStore` satisfying the `ContextStoreInstance` Protocol, persisting conversation history to MemoryHub's storage layer with conversation turns stored as child nodes under a context root (weight=0.3 to prevent search pollution). See `planning/kagenti-integration/architecture.md`.

**Ref:** [Kagenti GitHub](https://github.com/kagenti/kagenti), [Red Hat Emerging Tech: Zero Trust Agents on Kagenti](https://next.redhat.com/2026/03/05/zero-trust-ai-agents-on-kubernetes-what-i-learned-deploying-multi-agent-systems-on-kagenti/)

### 2.10 Letta (formerly MemGPT)

Letta introduces an OS-inspired memory hierarchy that blurs the line between conversation persistence and memory:

**Three-tier model:**
- **Core Memory** -- small block in the context window (like RAM). Self-edited by the agent.
- **Recall Memory** -- searchable conversation history stored outside context (like disk cache). Automatically saved to disk.
- **Archival Memory** -- long-term extracted knowledge queried via tool calls (like cold storage).

**Self-editing memory:** The key innovation. Agents actively manage their own memory using tools -- they can read, write, search, and update their memory stores. The agent loop itself decides what to remember and what to discard.

**Conversations API:** Allows building agents that maintain shared memory across parallel user experiences.

**Ref:** [Letta MemGPT Concepts](https://docs.letta.com/concepts/memgpt/), [Letta Agent Memory Blog](https://www.letta.com/blog/agent-memory)

### 2.11 Zep (Graphiti)

Zep contributes the most sophisticated conversation-to-knowledge extraction architecture:

**Temporal knowledge graph:** Three hierarchical tiers -- Episode Subgraph (raw events/messages with timestamps), Semantic Entity Subgraph (entities and facts extracted from episodes, embedded in 1024D space), Community Subgraph (clustered entity groups).

**Bi-temporal model:** Timeline T (chronological event ordering) and Timeline T' (data ingestion order). T' serves traditional database auditing; T models the dynamic nature of conversational data.

**Extraction pipeline:** Entity extraction processes current message plus last n=4 messages (two conversation turns) for context. Uses a reflection technique inspired by Reflexion to minimize hallucinations and enhance extraction coverage.

**Performance:** 94.8% on Deep Memory Retrieval benchmark (vs MemGPT's 93.4%). Up to 18.5% accuracy improvement on LongMemEval with 90% latency reduction.

**Ref:** [Zep Paper (arXiv:2501.13956)](https://arxiv.org/abs/2501.13956), [Graphiti GitHub](https://github.com/getzep/graphiti)

### 2.12 Amazon Bedrock AgentCore

AWS's managed memory service for agents:

**Two memory types:** Short-term (turn-by-turn within a single session) and Long-term (automatically extracts key insights across sessions -- preferences, facts, summaries).

**Session isolation:** Ephemeral runtime state exists only within the active session lifecycle. For persistent data, AgentCore Memory provides both short-term and long-term abstractions that maintain histories and behavioral patterns across session boundaries.

**Memory strategies:** Configurable strategies determine what types of information to extract from raw conversations. Async mode is default in production (memory writes don't block response latency).

**Framework integration:** Works with LangChain, LangGraph, and other frameworks.

**Ref:** [AgentCore Memory Docs](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/memory.html), [AgentCore Memory Types](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/memory-types.html)

### 2.13 Mem0

Mem0 contributes the clearest articulation of the memory extraction pipeline:

**Architecture:** A memory orchestration layer sitting between AI agents and storage systems. Manages the full lifecycle from extraction to storage to retrieval.

**Extraction pipeline:** LLM pass over conversational content to identify discrete facts. Four operations: ADD, UPDATE, DELETE, NOOP. This pipeline is what keeps the store accurate over time. An enhanced variant uses graph-based representations (Mem0g) for relational structures.

**Scoping:** Four-scope model -- `user_id` (cross-session), `agent_id` (agent instance), `run_id`/`session_id` (single conversation), `app_id`/`org_id` (organizational).

**Actor-aware memories (June 2025):** Tags each stored memory with its source actor, preventing one agent's inferences from being treated as ground truth by another.

**Performance (LOCOMO benchmark):**

| Approach | LLM Score | P95 Latency | Tokens/Query |
|---|---|---|---|
| Full-context (raw history) | 72.9% | 17.12s | ~26,000 |
| Mem0g (graph) | 68.4% | 2.59s | ~1,800 |
| Mem0 (vector) | 66.9% | 1.44s | ~1,800 |
| RAG | 61.0% | 0.70s | -- |
| OpenAI Memory | 52.9% | -- | -- |

Selective extraction trades 6 percentage points of accuracy for 91% lower latency and 90% fewer tokens.

**Ref:** [Mem0 Paper (arXiv:2504.19413)](https://arxiv.org/abs/2504.19413), [State of AI Agent Memory 2026](https://mem0.ai/blog/state-of-ai-agent-memory-2026)

---

## 3. Academic and Industry Research

### 3.1 Key Papers

**"Memory in the Age of AI Agents: A Survey"** (2025) -- Comprehensive survey cataloging memory mechanisms in LLM-based agents. Distinguishes episodic (what happened), semantic (what is known), and procedural (how to do things) memory. Identifies shared memory patterns: blackboard-style shared stores, orchestrator-level hosting (central coordinator as memory hub), and agent-level private stores.

**"Zep: A Temporal Knowledge Graph Architecture for Agent Memory"** (Rasmussen, 2025, arXiv:2501.13956) -- Introduces bi-temporal knowledge graphs for agent memory. The episode subgraph preserves raw conversational data as ground truth while the semantic entity subgraph captures extracted knowledge.

**"A-MEM: Agentic Memory for LLM Agents"** (2025, arXiv:2502.12110) -- Proposes agents that manage their own memory lifecycle, echoing Letta's self-editing memory concept.

**"Mem0: Building Production-Ready AI Agents with Scalable Long-Term Memory"** (2025, arXiv:2504.19413) -- Formalizes the extraction/consolidation/retrieval pipeline and benchmarks against full-context baselines.

**"Memoria: A Scalable Agentic Memory Framework for Personalized Conversational AI"** (2025, arXiv:2512.12686) -- Integrates dynamic session-level summarization with a weighted knowledge graph for incremental user modeling.

**"In Prospect and Retrospect: Reflective Memory Management for Long-term Personalized Dialogue Agents"** (ACL 2025) -- Applies reflection techniques to conversation memory management.

**"Beyond the Context Window: A Cost-Performance Analysis of Fact-Based Memory vs. Long-Context LLMs for Persistent Agents"** (2026, arXiv:2603.04814) -- Directly compares raw conversation injection against extracted fact stores for cost and performance.

### 3.2 Standardization Efforts

**A2A Protocol:** Provides conversation continuity through contextId/taskId but delegates persistence. Under Linux Foundation governance. Expected improvements include formal authorization schemes and dynamic UX negotiation within tasks.

**MCP:** Explicitly out of scope. Session state is a transport convenience, not a persistence layer.

**No conversation persistence standard exists.** Neither A2A nor MCP nor any other protocol specifies how conversation threads should be stored, governed, or shared. This is an explicitly unoccupied space in the standardization landscape.

### 3.3 Industry Convergence Points

The Mem0 State of Agent Memory 2026 report identifies several areas of convergence:

- **Four-scope model** for memory (user, agent, session, org) is becoming standard across frameworks
- **Three memory types** (episodic, semantic, procedural) formalized across research and production
- **Async extraction** as default in production (memory writes don't block response latency)
- **Actor-aware provenance** emerging as a requirement for multi-agent systems
- **Graph-enhanced memory** moving from experimental to production status

---

## 4. Governance Angles

### 4.1 Thread Ownership

No framework has a satisfying answer to "who owns a conversation thread?" Most systems treat threads as belonging to the creating user or the platform operator. In multi-agent scenarios, this breaks down:

- If Agent A starts a conversation and hands it to Agent B, who owns the thread?
- If a user talks to a team of agents, is the thread owned by the user, the team, or the orchestrator?
- If an enterprise agent handles conversations for multiple customers, who owns the data -- the enterprise, the customer, or the agent operator?

**Current patterns:**
- OpenAI: Platform owns threads. Developers access via API keys. No user-level ownership.
- LangGraph: Application-level ownership. Thread access is whatever the application code permits.
- A2A: No ownership model. contextId is a wire-format identifier, not an ownership claim.
- Kagenti: Namespace-scoped ownership via Kubernetes RBAC. Agents in different namespaces are isolated.

### 4.2 Access Control

**Multi-tenant isolation** is the most critical governance requirement. Key patterns:

- **Tenant-per-namespace** (Kagenti, AWS AgentCore): Tenant boundary enforced by infrastructure. Cross-tenant access requires explicit trust relationships.
- **Tenant-in-JWT** (MemoryHub, Azure OpenAI): Tenant ID carried in authentication token. Cross-tenant reads return MemoryNotFoundError (indistinguishable from nonexistent).
- **Channel-owned authorization**: Roles flow from org structure to conversation access. Channel membership acts as role assignment.

**Five identity layers** (per Scalekit research): trigger identity, execution identity, authorization identity, tenant identity, and data identity. All need explicit modeling or "access control bugs surface silently months later."

**Data bleed risks:** When warm pool pods recycle between tenants, state can survive and leak. Unscoped queries from agents can inadvertently combine data from multiple tenants.

**Ref:** [Access Control for Multi-Tenant AI Agents](https://www.scalekit.com/blog/access-control-multi-tenant-ai-agents)

### 4.3 Retention Policies

**Current state:** Most frameworks store conversation logs indefinitely with no built-in retention management.

**GDPR vulnerabilities (per industry analysis):**
- 47% of cases: absence of explicit consent before processing personal data
- 39%: indefinite conversation storage without defined retention policy
- 31%: absence of mechanisms for right to erasure or portability

**Best practice pattern:** Configurable retention policies at the workspace/tenant level with automatic deletion schedules, data minimization by design, and purpose limitation on stored conversation data.

### 4.4 Audit Trails

**EU AI Act requirements (effective August 2, 2026 for high-risk systems):**
- High-risk AI systems must "technically allow for the automatic recording of events (logs) over the lifetime of the system"
- Organizations must produce a complete list of every AI system, what it does, what data it touches, and a continuous audit trail of every action
- Logs must link outputs to source data, model versions, and user prompts
- Penalties: up to 7% of global annual revenue or EUR 35 million

**Current gaps:** No agent framework provides EU AI Act-ready audit trails out of the box. Most store conversation logs for debugging but don't structure them as compliance artifacts with the required metadata (data transmitted, purpose, sensitivity classification).

### 4.5 GDPR Compliance Implications

Storing full conversation transcripts creates significant GDPR obligations:

- **Right to erasure (Article 17):** Must be able to delete all conversation data for a specific data subject, including any memories extracted from those conversations
- **Right to portability (Article 20):** Must be able to export conversation data in a machine-readable format
- **Purpose limitation (Article 5):** Conversation data collected for one purpose cannot be repurposed without consent
- **Data minimization:** Store only what's necessary. Full transcript retention must be justified.
- **Cross-border transfer:** Conversation data stored in different jurisdictions faces transfer restrictions.

**Ref:** [GDPR Compliance for AI Agents](https://www.protecto.ai/blog/gdpr-compliance-for-ai-agents-startup-guide/), [EU AI Act Article 12: Record-Keeping](https://artificialintelligenceact.eu/article/12/), [EU AI Act Article 19: Automatic Logs](https://artificialintelligenceact.eu/article/19/)

---

## 5. Architecture Patterns

### 5.1 Append-Only Log vs. Summarized Store

| Dimension | Append-Only Log | Summarized/Extracted Store |
|---|---|---|
| Fidelity | Exact transcript | Lossy (extracted facts) |
| Retrieval quality | Degrades as log grows | Stable (deduplicated, indexed) |
| Storage cost | Linear growth | Sub-linear (consolidation) |
| Audit value | High (ground truth) | Low (derived, not original) |
| Prompt injection cost | High (~26K tokens for full context) | Low (~1.8K tokens per query) |
| Latency (p95) | 17.12s (Mem0 LOCOMO benchmark) | 1.44-2.59s |
| Mutability | Append-only | ADD/UPDATE/DELETE/NOOP |
| Governance | Simple (immutable) | Complex (version tracking needed) |

**Production pattern:** Use both. The append-only log serves as the audit trail and ground truth. The extracted store serves as the working memory for agents. Memory extraction runs as a pipeline from log to store.

### 5.2 Relationship Between Conversation Persistence and Memory Extraction

The relationship is a pipeline with clear stages:

```
Conversation    →    Raw Archive    →    Extraction    →    Memory Store
(real-time)          (append-only)       (LLM pipeline)     (mutable, governed)
                                              ↓
                                    Entity identification
                                    Relationship inference
                                    Conflict detection
                                    Deduplication
                                    Scope assignment
                                    Weight/importance scoring
```

Key design decisions at each stage:

- **When to extract:** Synchronous (blocking, higher latency) vs. asynchronous (non-blocking, eventual consistency). Production systems default to async.
- **What to extract:** Facts, preferences, procedures, entities, relationships. The extraction prompt determines the memory's character.
- **Granularity:** Per-message extraction vs. sliding-window extraction vs. end-of-session batch. Zep uses a sliding window of 4 messages (2 turns) for context. Mem0 processes messages as they arrive.
- **Conflict resolution:** When extracted facts contradict existing memory, who wins? Zep uses temporal ordering. Mem0 uses LLM-based conflict detection. MemoryHub has explicit `report_contradiction` tooling.

### 5.3 Thread Branching and Forking

Thread branching creates a divergent copy of a conversation from a specific point. This is valuable for:

- **Exploration:** Try different approaches from the same starting point
- **Human-in-the-loop:** Fork before a critical decision, explore both paths
- **A/B testing:** Run the same conversation through different agent configurations
- **Error recovery:** Fork from before the error, try again

**Implementation patterns:**
- **LangGraph:** Fork by replaying from a specific checkpoint. `update_state()` creates new checkpoints with modified values. Full time-travel support.
- **Claude Code:** Explicit `--fork-session` creates a new session starting with a copy of the original's history. Fork gets its own session ID.
- **OpenAI Conversations API:** No built-in forking. You'd create a new conversation and replay messages.
- **A2A:** No thread branching. contextId is linear.

**Observation:** Thread branching is a developer tool (debugging, exploration) more than an end-user feature. Most users expect linear conversation flow. The exception is multi-agent orchestration, where branching happens implicitly when an orchestrator fans out work to multiple agents.

### 5.4 Cross-Agent Conversation Sharing

How does one agent share conversation context with another?

**Pattern 1: Shared thread (LangGraph, Azure AI)** -- Multiple agents read/write the same thread. Simple but creates tight coupling and raises access control questions.

**Pattern 2: Context injection (A2A, Kagenti Phase 2)** -- The sending agent attaches context identifiers or summaries to outgoing messages. The receiving agent resolves these to load relevant information. Loose coupling, but requires agreement on the context format.

**Pattern 3: Shared memory store (MemoryHub, Mem0)** -- Agents read/write to a shared memory service. No direct conversation sharing; instead, extracted knowledge is shared. The conversation itself stays private to each agent.

**Pattern 4: Orchestrator-mediated (CrewAI, AutoGen GroupChat)** -- A central orchestrator maintains the shared conversation context and distributes it to participating agents. Every agent turn in a GroupChat involves a full LLM call with accumulated history.

**Pattern 5: Blackboard (MedAgents, PC-Agent)** -- A shared workspace where agents post intermediate results. A report-assistant agent compresses multi-agent conversations into persistent context for the next round.

### 5.5 Summary of Architecture Tradeoffs

| Pattern | Coupling | Governance | Scalability | Typical Use |
|---|---|---|---|---|
| Shared thread | Tight | Hard | Limited | Small agent teams |
| Context injection | Loose | Medium | Good | A2A cross-org |
| Shared memory store | Loose | Good | Good | Platform-level memory |
| Orchestrator-mediated | Medium | Centralized | Limited | Multi-agent orchestration |
| Blackboard | Medium | Centralized | Medium | Research workflows |

---

## 6. What Makes This a "Killer Feature" in a Governed Memory Platform

The competitive landscape reveals a clear pattern: everyone does conversation persistence, but no one governs it. LangGraph checkpoints are powerful but have no access control. OpenAI's Conversations API persists indefinitely but has no retention policies. A2A delegates persistence entirely. MCP explicitly disclaims it. Kagenti's ContextStore is append-only with no governance.

A governed memory platform that treats conversation persistence as a first-class, governed artifact -- not just a debugging convenience -- would differentiate on several axes:

### 6.1 What exists everywhere (table stakes)

- Store conversation threads
- Resume from prior point
- Search conversation history
- Basic multi-turn continuity

### 6.2 What exists in some places (differentiators today, table stakes tomorrow)

- Thread forking/branching (LangGraph, Claude Code)
- Cross-thread memory extraction (Mem0, Zep, Letta)
- Multi-backend persistence (LangGraph, Google ADK)
- Encrypted checkpoint storage (LangGraph)

### 6.3 What exists nowhere (genuine whitespace)

**Governed conversation persistence with enterprise-grade controls:**

- **Thread-level RBAC**: Who can read, write, fork, or delete a specific conversation thread? No framework provides this. LangGraph threads are application-controlled. OpenAI threads are API-key-scoped. Kagenti threads are namespace-scoped but with no finer granularity.

- **Auditable conversation-to-memory pipeline**: The full chain from "this was said in conversation X" to "this became memory Y" to "this memory influenced decision Z" -- with immutable provenance at each step. EU AI Act Article 12 requires this for high-risk systems. No current system provides it end-to-end.

- **Retention policy enforcement**: Automatic expiration of conversation threads per tenant/scope/classification policy, with cascade to extracted memories (if a conversation must be deleted, what happens to the memories extracted from it?). GDPR Article 17 compliance requires this.

- **Cross-agent conversation handoff with governance**: Agent A hands a conversation to Agent B, and the system records: who authorized the handoff, what context was shared, what was redacted, and what access the receiving agent has. A2A provides the wire format for this but zero governance.

- **Tenant-isolated conversation archives**: Conversation threads as first-class tenant-scoped resources with the same isolation guarantees as memories. Cross-tenant conversation access returns "not found" (not "access denied"), matching MemoryHub's existing tenant isolation pattern.

- **Conversation-scoped session identity**: A session ID that represents a conversation, not a transport connection. Currently (as noted in `planning/session-persistence.md` issue #86), session IDs are tied to MCP transport connections. A conversation-scoped identity would survive transport reconnections, pod restarts, and even platform migrations.

### 6.4 Strategic positioning

The key insight from this research is that **conversation persistence is the raw material; memory extraction is the refined product; governance is the differentiator.** Everyone has the raw material and most have some extraction. Almost no one has governance.

For a platform targeting regulated industries (government, financial services, healthcare, defense), the conversation persistence layer needs to answer questions that no current system answers:

1. **Provenance**: "This memory came from conversation X, turn Y, between agent A and user B, on date Z." Zep's bi-temporal model comes closest but has no access control.

2. **Right to be forgotten**: "Delete everything from user X's conversations and cascade to any extracted memories." No framework handles this automatically.

3. **Audit**: "Show me every conversation that influenced this decision." Requires linking conversation archives to memory extraction to agent actions. EU AI Act makes this mandatory for high-risk systems by August 2026.

4. **Scope isolation**: "This conversation happened in the context of Project Alpha. Its extracted memories should be scoped to Project Alpha, not visible to Project Beta." MemoryHub's existing scope model (user/project/role/organizational/enterprise) maps naturally here.

5. **Contradiction resolution with conversation evidence**: "Memory X contradicts memory Y. Here are the original conversation turns where each was established." MemoryHub's `report_contradiction` plus conversation-linked provenance would enable this.

The compound effect of these capabilities -- not any single one -- is what makes the feature "killer." Any individual capability could be bolted onto an existing system. The integration of conversation persistence with memory extraction with governance with scope isolation, all under a single coherent model, is what no one else provides.

### 6.5 Relationship to existing MemoryHub architecture

MemoryHub's existing architecture already has most of the substrate:

- **Memory tree with branch types** can represent conversation threads (branch_type="conversation_history") as designed in the Kagenti Phase 3 plan
- **Scope model** (user/project/role/organizational/enterprise) provides the access boundary
- **Versioning** (isCurrent) provides temporal tracking
- **Tenant isolation** provides hard multi-tenant boundaries
- **Contradiction detection** provides the conflict resolution mechanism
- **Weight system** allows conversation turns to be stored at low weight (0.3) so they don't pollute semantic search

What's missing is the **conversation-specific abstractions**: a first-class Thread entity (not just a memory node with branch_type), conversation-scoped session identity (#86), retention policy enforcement, and the auditable extraction pipeline linking conversations to memories.

---

## Sources

### Framework Documentation
- [LangGraph Persistence Docs](https://docs.langchain.com/oss/python/langgraph/persistence)
- [OpenAI Conversation State Guide](https://developers.openai.com/api/docs/guides/conversation-state)
- [Google ADK Sessions Documentation](https://adk.dev/sessions/)
- [CrewAI Memory Documentation](https://docs.crewai.com/en/concepts/memory)
- [Microsoft Agent Framework Architecture](https://learn.microsoft.com/en-us/semantic-kernel/frameworks/agent/agent-architecture)
- [A2A Protocol Specification](https://a2a-protocol.org/latest/specification/)
- [MCP Introduction](https://modelcontextprotocol.io/docs/getting-started/intro)
- [Letta/MemGPT Concepts](https://docs.letta.com/concepts/memgpt/)
- [Amazon Bedrock AgentCore Memory](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/memory.html)
- [Claude Code: How It Works](https://code.claude.com/docs/en/how-claude-code-works)

### Papers
- [Zep: A Temporal Knowledge Graph Architecture for Agent Memory (arXiv:2501.13956)](https://arxiv.org/abs/2501.13956)
- [Mem0: Building Production-Ready AI Agents with Scalable Long-Term Memory (arXiv:2504.19413)](https://arxiv.org/abs/2504.19413)
- [A-MEM: Agentic Memory for LLM Agents (arXiv:2502.12110)](https://arxiv.org/abs/2502.12110)
- [Memoria: A Scalable Agentic Memory Framework (arXiv:2512.12686)](https://arxiv.org/abs/2512.12686)
- [Memory in the Age of AI Agents: A Survey](https://github.com/Shichun-Liu/Agent-Memory-Paper-List)
- [Memory in LLM-based Multi-agent Systems (TechRxiv)](https://www.techrxiv.org/users/1007269/articles/1367390)
- [In Prospect and Retrospect: Reflective Memory Management (ACL 2025)](https://aclanthology.org/2025.acl-long.413.pdf)
- [Beyond the Context Window: Fact-Based Memory vs Long-Context LLMs (arXiv:2603.04814)](https://arxiv.org/html/2603.04814v1)

### Industry Reports and Analysis
- [State of AI Agent Memory 2026 (Mem0)](https://mem0.ai/blog/state-of-ai-agent-memory-2026)
- [ChatGPT Memory: How It Works (Embrace the Red)](https://embracethered.com/blog/posts/2025/chatgpt-how-does-chat-history-memory-preferences-work/)
- [Access Control for Multi-Tenant AI Agents (Scalekit)](https://www.scalekit.com/blog/access-control-multi-tenant-ai-agents)
- [GDPR Compliance for AI Agents (Protecto)](https://www.protecto.ai/blog/gdpr-compliance-for-ai-agents-startup-guide/)
- [EU AI Act Article 12: Record-Keeping](https://artificialintelligenceact.eu/article/12/)
- [EU AI Act Article 19: Automatic Logs](https://artificialintelligenceact.eu/article/19/)
- [EU AI Act Compliance: Technical Audit Guide 2026 (Raconteur)](https://www.raconteur.net/global-business/eu-ai-act-compliance-a-technical-audit-guide-for-the-2026-deadline)

### MemoryHub Internal References
- `planning/session-persistence.md` -- Session persistence across MCP server restarts (skeleton)
- `planning/kagenti-integration/overview.md` -- Kagenti integration overview
- `planning/kagenti-integration/architecture.md` -- Kagenti integration architecture (ContextStore design)
- `planning/kagenti-integration/integration-phases.md` -- Three-phase integration plan
