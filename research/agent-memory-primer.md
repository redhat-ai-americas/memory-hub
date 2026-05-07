# Agent Memory: A Primer for Contributors

This primer orients new contributors to the concepts MemoryHub builds on. It assumes you know what an LLM agent is, that you have used local agent harnesses like Claude Code or Cursor, and that you understand how a single agent reads and writes files. It does not assume any background in shared, multi-agent, or platform-tier memory.

If you have a deeper interest in the broader research landscape (failure modes, governance frameworks, comparison surveys), see the [Memory Systems for LLM-Based Agents survey](https://arxiv.org/abs/2603.10062) (referenced in our own survey work) and the technical surveys in this `research/` directory.

## The terms

**Agent.** A running system built around an LLM that has tools, memory, and some lifecycle. The LLM does inference; the agent is the broader thing that reads input, calls tools, manages state, and produces useful work over time.

**Harness.** The runtime scaffolding around the LLM that turns inference calls into an agent. The harness is responsible for assembling the prompt for each turn, routing tool calls, maintaining the conversation lifecycle, and managing whatever local state the agent needs. Claude Code, Cursor, Copilot, and the various agent SDKs (LangChain, LangGraph, Letta, the OpenAI Agents SDK, the Claude Agent SDK) are all harnesses.

**Working memory.** The state the model is reasoning over right now. In practice this is the prompt the harness assembles for the current inference call: system prompt, prior turns, tool results, retrieved documents, and the current user message. Working memory has exactly one place to live, the assembled prompt for this turn, because that is the only thing the model sees.

**Durable memory.** State that survives across sessions. Facts the agent learned, preferences it accumulated, decisions it made, experiences it can recall. Unlike working memory, durable memory can live anywhere, and where it lives is a real architectural choice. A markdown file. A SQLite database. A vector store. A managed memory service. A graph database. The choice has trade-offs.

**Platform tier vs harness tier.** A pattern that shows up as agent systems mature. Some responsibilities stay close to the inference loop (working memory, prompt assembly, immediate tool routing) because they need to be fast and local. Others move to platform services that any harness can call (durable memory, conversation persistence, audit logs) because they need to be governed, multi-tenant, and shared. The line between the two is the central architectural concern of MemoryHub. The earlier blog post [When Agent Memory Becomes a Platform Concern](https://medium.com/@wjackson_63436/when-agent-memory-becomes-a-platform-concern-4b6cd23af47f) lays out the case for treating memory as a platform-tier concern at scale.

## What MemoryHub is

MemoryHub is a governed durable-memory service for AI agents. It runs as a Kubernetes-native component on OpenShift AI. It exposes its capabilities through the Model Context Protocol (MCP), so any MCP-compatible agent harness can read and write through a standard interface. It also ships a Python SDK for direct integration.

Concretely, MemoryHub provides:

- **Scope-based access control.** Memories are tagged with a scope (user, project, role, organizational, enterprise). Authorization rules determine who can read or write each scope. An agent in one project cannot accidentally read another project's memories.
- **Audit and provenance.** Memory writes, updates, and deletes are recorded. A reviewer can reconstruct what an agent learned, when, and from what evidence.
- **Branch-typed memory nodes.** A memory can have rationale and provenance branches that capture the why and the evidence behind the memory, separately from the memory content itself.
- **Contradiction detection and curation.** When an agent reports that a stored memory contradicts observed behavior, the curation pipeline records and surfaces the conflict.
- **Multi-tenant isolation.** Tenancy boundaries are enforced at the database level (PostgreSQL row-level security plus explicit grants), not only in application code.
- **Versioning.** Memory updates create new versions; older versions are preserved for history.

MemoryHub does not own working memory. The agent harness owns working memory by definition, since working memory is the prompt the harness builds.

## What MemoryHub does not do

MemoryHub focuses narrowly on durable governed memory. Other parts of an agent platform live next to MemoryHub but are not part of it:

- **Conversation persistence and resume.** Storing chat threads so an agent can pick up where it left off. The interesting unit there is a conversation, not a fact, and the access patterns are different (chronological, threaded). In our platform plans this lives in orchestration services like kagenti or LlamaStack rather than in MemoryHub. See the [conversation-persistence survey](conversation-persistence-survey.md) for a deeper look.
- **Context compaction.** Summarizing long-running threads to fit them in a model's context window. The decision to compact lives near the harness; the algorithm benefits from inference-engine awareness (vLLM/KV-cache strategy, model-family specifics) and may run in a platform service that any harness can call. See the [context-compaction survey](context-compaction-survey.md).
- **Working-memory forensics and sandbox logging.** Reconstructing what an agent reasoned over at a given moment, what code it executed in a sandbox, what tools it called, what data it read. These are governance requirements on harness-owned state, captured to a separate forensics store. They are not durable memory.
- **Knowledge / RAG corpora.** Retrieval-augmented generation over external document corpora. RAG retrieves information from outside the agent system. Memory tracks information from inside the agent system. They overlap mechanically (both can use vector search) but answer different questions.

When you find yourself wanting MemoryHub to do one of these jobs, that is usually a signal that a different platform component is the right home.

## How to navigate this directory

Files that contributors most often need:

- [`agent-memory-protocol-rfc.md`](agent-memory-protocol-rfc.md): the protocol shape MemoryHub exposes, including MCP tools and SDK semantics.
- [`agent-memory-ergonomics/`](agent-memory-ergonomics/): UX research for agents using MemoryHub: pivot detection, two-vector retrieval, FastMCP 3 push notifications.
- [`context-compaction-survey.md`](context-compaction-survey.md): survey of approaches to context compaction.
- [`conversation-persistence-survey.md`](conversation-persistence-survey.md): survey of approaches to durable conversation state.
- [`graph-memory-survey.md`](graph-memory-survey.md): survey of graph-based memory architectures (Zep / Graphiti, MAGMA, etc.).
- [`llm-wiki-landscape.md`](llm-wiki-landscape.md): landscape analysis of Karpathy's LLM Wiki pattern and community responses.
- [`fips-storage.md`](fips-storage.md): FIPS-relevant storage analysis for compliance-heavy deployments.
- [`claude-code-jwt-limitations.md`](claude-code-jwt-limitations.md): JWT limitations relevant to Claude Code integrations.
- [`vllm-cache-optimization.md`](vllm-cache-optimization.md) and [`vllm-prefix-cache-validation/`](vllm-prefix-cache-validation/): KV-cache optimization research relevant to agents using MemoryHub-injected memories.

Some research and positioning material lives in a private peer repository. Ask if you need access to specific competitive analyses, blog drafts, or the in-progress survey paper.

## Where to start as a contributor

For most contributors, the most useful starting point depends on what you are working on:

- Building a new feature in MemoryHub: read the project's [`docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md) and [`docs/SYSTEMS.md`](../docs/SYSTEMS.md), then the protocol RFC if available.
- Integrating MemoryHub into a harness or agent: read the SDK README and the [`agent-memory-ergonomics/`](agent-memory-ergonomics/) directory.
- Evaluating MemoryHub against alternative memory systems: the surveys above plus the published [v2 blog post](https://medium.com/@wjackson_63436/when-agent-memory-becomes-a-platform-concern-4b6cd23af47f) cover the landscape and the design choices.
- Working on related platform concerns (conversation persistence, compaction, forensics): the relevant survey in this directory plus the project's planning documents in [`planning/`](../planning/).

The harness/platform line is the orienting concept. If you keep that in mind while reading, the rest of the architecture follows.
