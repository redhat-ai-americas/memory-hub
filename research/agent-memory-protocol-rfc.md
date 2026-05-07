# Agent Memory Protocol: A Proposal for Standardized Agent Memory

RFC-AMP-001 | Draft | April 2026
Authors: Wes Jackson

## Abstract

This document proposes that agent memory should be a first-class protocol primitive rather than a set of application-specific tools exposed over existing transport layers. The Model Context Protocol (MCP) provides three primitives -- tools, resources, and prompts -- but every production memory system today (Mem0, Zep, Letta, LangMem, MemoryHub) exposes memory through MCP tools with incompatible schemas, incompatible semantics, and no shared governance model. This creates an interoperability problem that cannot be solved by tool-schema standardization alone: memory operations have fundamentally different access patterns (high-frequency reads, budget-aware responses), lifecycle requirements (versioning, contradiction detection, curation), and governance needs (scope-based RBAC, audit trails) from tool invocations, and treating them identically in protocol design leads to preventable integration failures. We propose either a fourth MCP primitive (`memory`) or a companion Agent Memory Protocol (AMP) that standardizes session-scoped identity, tree-structured memory with typed branches, budget-aware retrieval, inline curation, contradiction detection, scope-based governance, and version history. The design is grounded in operational experience from MemoryHub, a Kubernetes-native agent memory system deployed on OpenShift with 13 MCP tools, OAuth 2.1 authentication, and a production curation pipeline.

## 1. Motivation

Every production agent memory system today exposes memory as MCP tools. MemoryHub exposes 13 tools. Mem0 exposes a different set. Zep, Letta, and LangMem each have their own schemas, parameter names, and response shapes. An agent that works with MemoryHub's `search_memory(query, max_results, mode, max_response_tokens, focus, include_branches)` cannot use Zep's memory API without rewriting its integration layer. The tool names differ, the parameters differ, the response structures differ, and the semantic contracts differ.

This is not merely an inconvenience. Three categories of problem emerge from treating memory as tools.

**The semantic mismatch.** MCP tools model actions an agent takes on its environment: send an email, query a database, create a file. Memory is not an environmental action. When an agent writes a memory, it is modifying its own cognitive state -- adding a belief, recording a preference, capturing a decision. When it searches memory, it is consulting its own knowledge, not querying an external system. The distinction matters because memory operations have fundamentally different access patterns from tool invocations. Memory reads are high-frequency (potentially every conversational turn), latency-sensitive, and context-dependent in ways that tool calls are not. A tool call to "send email" has clear inputs and outputs; a memory search must account for scope, recency, token budget, contradiction state, and relevance -- none of which are concerns for typical tool invocations.

**The convention problem.** Protocol-level concerns are disguised as usage instructions. In MemoryHub, the consuming agent's CLAUDE.md file contains a paragraph instructing the agent to call `register_session` at conversation start, to pass `project_id` on every `search_memory` call, and to use `report_contradiction` when observations conflict with stored memories. These are not optional best practices -- they are correctness requirements. An agent that forgets to pass `project_id` silently misses project-scoped memories. An agent that skips `register_session` gets authentication errors on every subsequent call. When protocol-level behavior depends on natural-language instructions in a markdown file, the failure mode is silent omission, and the only defense is hoping the LLM follows instructions reliably. Protocol primitives enforce contracts that instructions cannot.

**The interoperability wall.** An agent framework that supports "MCP memory" today means it has been tested against one specific memory server's tool schemas. Switching memory backends requires changing tool descriptions, adjusting parameter mappings, rewriting response parsing, and updating all instruction text. There is no abstract "memory" capability that an agent can depend on the way it depends on "tools" as an MCP primitive. The result is vendor lock-in at the integration layer -- the exact problem MCP was designed to solve for tools.

**Why not just standardize the tool schemas?** The obvious lighter-weight alternative is to publish a standard set of MCP tool schemas for memory operations -- a "memory tool convention" -- without touching the protocol. This would help with interoperability but cannot solve three structural problems. First, session establishment ordering: a tool convention can document that `register_session` must be called first, but it cannot enforce it -- the agent's LLM must remember to follow the convention, and silent failure when it doesn't is the predictable result. Second, governance enforcement: tools are independently invocable by design, but memory operations require pre-conditions (authenticated session, authorized scope, curation pipeline) that must be guaranteed by the transport layer, not hoped for by the application layer. Third, transport-level differentiation: memory operations have fundamentally different access patterns from tools (high-frequency reads on nearly every turn, budget-aware responses, stateless focus biasing) that a protocol can optimize for but a tool convention cannot. A convention standardizes the message format; a protocol standardizes the contract. Memory needs the latter.

## 2. Background

### 2.1 MCP Today

The Model Context Protocol defines three primitives. **Tools** are functions that agents can call to act on their environment -- reading files, querying APIs, executing commands. **Resources** are read-only data sources that provide context without side effects. **Prompts** are reusable prompt templates that structure agent interactions. Transport is streamable-HTTP; authentication is OAuth 2.1. MCP has achieved significant adoption as the standard interface between agents and external capabilities.

MCP does not define a memory primitive. The specification acknowledges that agents need context, but treats it as something provided through tools and resources rather than as a distinct concern with its own lifecycle, governance, and access patterns.

### 2.2 The Agent Memory Landscape

As of April 2026, five systems represent the state of the art in agent memory, and all expose memory through MCP tools.

**Mem0** provides a hybrid three-tier architecture (vector, graph, key-value) with automatic memory extraction and retrieval. It reports accuracy improvements over OpenAI's built-in memory on vendor-published benchmarks.

**Zep/Graphiti** implements a bi-temporal knowledge graph that distinguishes when events occurred from when they were ingested, enabling explicit fact invalidation and temporal queries.

**Letta** (formerly MemGPT) uses an OS-inspired memory hierarchy where the agent itself manages tier transitions between core memory (always in context), archival memory (vector-searchable), and recall memory (conversation history).

**LangMem** organizes memory into semantic (facts), episodic (past experiences), and procedural (self-modifying instructions) categories, implementing Karpathy's system prompt learning concept.

**MemoryHub** is a Kubernetes-native system with tree-structured memories, six scope tiers with governance rules, inline curation (secrets/PII detection, embedding-based dedup), cross-encoder reranking with session focus, OAuth 2.1 authentication, and 13 MCP tools deployed on OpenShift.

These systems have independently converged on hybrid architectures and similar lifecycle stages (write, store, retrieve, use, decay). Yet each exposes a different tool surface. An agent built for Mem0's `add_memory` / `search_memory` pair cannot use MemoryHub's richer interface without rework, and vice versa. The convergence in architecture has not produced convergence in interface.

### 2.3 What Memory Is Not

Memory is not a tool. The distinction is operational, not philosophical. Tools are invoked deliberately for specific purposes; memory is consulted pervasively as part of reasoning -- in MemoryHub's production data, `search_memory` is called on nearly every conversational turn while other tools are called sporadically. Tools have clear success/failure semantics; memory retrieval is a matter of degree (more relevant, less relevant, missing context). Tools are stateless between invocations; memory is inherently stateful and temporally ordered. Tools have uniform latency expectations; memory operations require budget-aware responses that shape their output to fit the consumer's context window. These differences mean that memory benefits from protocol-level treatment -- transport priority, session-scoped identity, capability negotiation -- that the tool abstraction cannot provide.

Memory is not a resource. MCP resources are read-only data sources. Memory is read-write, and the write path has governance requirements (curation, scope enforcement, dedup) that resources do not contemplate. Resources are static or externally updated; memory is updated by the agent itself as a consequence of its operation.

Memory is not caching. Caches have straightforward invalidation strategies (TTL, LRU). Memory relevance is contextual, semantic, and temporal. A memory written six months ago may be more relevant than one written yesterday, depending on the query. There is no TTL that captures "still relevant when the agent is doing deployment work, irrelevant when writing tests."

## 3. Design Principles

Six principles guide this proposal. Each emerged from operational experience building and running MemoryHub.

**Memory is cognitive state, not environment action.** The protocol should treat memory operations as modifications to and queries against the agent's belief state, not as generic function calls. This means memory operations can have different transport-level treatment: higher priority, lower latency budgets, and tighter integration with the agent's reasoning loop. In MemoryHub, the observation that agents call `search_memory` on nearly every turn while calling other tools sporadically confirmed that memory access patterns are categorically different from tool access patterns.

**Curation is mandatory, not optional.** Without write-time quality gates, memory stores fill with garbage within weeks. MemoryHub's inline curation pipeline -- regex-based secrets detection, PII scanning, embedding-based dedup -- runs on every write in single-digit milliseconds. The protocol should require that conforming servers implement a curation pipeline and report curation outcomes to the caller. Making curation optional is equivalent to making it absent, because no implementation will prioritize it without a specification requirement.

**Retrieval must be budget-aware.** Returning the top-K most similar memories without regard to the consumer's context window is a recipe for either wasted tokens (K too large) or missed context (K too small). MemoryHub's `max_response_tokens` parameter lets the caller declare a token budget; the server packs results in relevance order, degrades to stubs when the budget is exhausted, and reports `has_more` so the caller knows what it missed. The protocol should standardize this contract because every memory consumer faces the same context-window scarcity, and leaving budget management to ad-hoc convention produces brittle integrations.

**Governance is structural, not bolted on.** Scope-based access control, audit trails, and version history are not enterprise upsells -- they are correctness requirements for any multi-user or multi-agent deployment. In MemoryHub, every tool call passes through `authorize_read()` or `authorize_write()` before touching the service layer, and RBAC violations in `search_memory` are prevented by SQL-level scope filtering (impossible by construction, not merely unlikely). The protocol should define governance as a required layer, not an optional extension, because retrofitting access control onto a system that launched without it creates security gaps that are difficult to close.

**Statelessness where possible.** MemoryHub's session focus mechanism passes the focus string per call rather than storing it on a server-side session. This eliminated every coordination question about pod-local state, distributed caching, and session affinity. The protocol should prefer stateless designs and require explicit justification for server-side state. The cost of a per-call focus re-embed (~50ms) is negligible compared to the operational complexity of session state management in a horizontally scaled deployment.

**No human-in-the-loop friction on the hot path.** The MCP specification requires HITL approval for sampling requests. MemoryHub's curation pipeline initially included LLM sampling for ambiguous dedup decisions; this was removed when it became clear that a HITL approval dialog on every ambiguous write would make the system unusable. Instead, `write_memory` returns curation feedback (similar_count, nearest_id, nearest_score) and the calling agent's existing LLM decides what to do. The protocol should not require HITL involvement for standard memory operations. HITL is appropriate for policy-tier memory creation and explicit review workflows, not for the write and search hot paths.

## 4. Protocol Overview

The Agent Memory Protocol defines the interface between an agent and its memory backend. It can be realized as a new MCP primitive (Section 11.1), a companion protocol (Section 11.2), or an MCP extension (Section 11.3). Regardless of realization, the protocol has three layers.

**Transport and session layer.** Session establishment, identity claims, scope resolution, and capability negotiation. This layer answers: who is the agent, what tenant does it belong to, and what memory capabilities does the server offer?

**Operations layer.** The core memory operations: write, read, search, update, delete, relate, contradict, and curate. Each operation has defined request/response schemas, error semantics, and governance hooks. This layer is where memory backends differentiate -- a graph-backed server and a vector-backed server expose the same operations with different performance characteristics.

**Governance layer.** Scope-based access control, curation rules, audit requirements, and version management. This layer defines what the server must enforce regardless of backend implementation. A conforming server must implement scope filtering, curation pipelines, and version history; the specific mechanisms are backend-dependent.

The relationship to MCP is additive, not competitive. MCP continues to handle tools, resources, and prompts. The memory protocol handles the distinct concerns of persistent, governed, agent-owned knowledge.

## 5. Session and Identity

### The Problem with register_session

MemoryHub's `register_session` tool is a compatibility shim that should not exist. It was created because MCP clients (including Claude Code) could not reliably send HTTP Authorization headers in early implementations, so the agent calls `register_session(api_key="...")` as its first tool invocation to establish identity. This works but is wrong in three ways.

First, session identity is a protocol concern, not an application concern. Every memory operation depends on knowing who the caller is. Encoding this as a tool call means the agent can forget to call it, call it with wrong parameters, or call it at the wrong time. MemoryHub's integration instructions include a paragraph reminding agents to call `register_session` before doing anything else -- a protocol-level requirement expressed as a natural-language instruction.

Second, it conflates authentication with capability discovery. The agent needs to know not just "am I authenticated?" but "what scopes can I access? What memory capabilities does this server offer? What curation rules apply to me?" A protocol handshake can exchange this information; a tool call returns a single response and hopes the agent parses it correctly.

Third, it creates a temporal dependency in the tool invocation sequence. Every other tool call must happen after `register_session`. Tools are supposed to be independently invocable; session establishment creates implicit ordering that the tool abstraction does not model.

### Protocol-Level Session Establishment

The protocol should define session establishment as part of the connection handshake, not as a tool call. During handshake, the client presents identity claims (JWT, API key, or platform token). The server validates the claims, resolves the caller's tenant, scopes, and applicable curation rules, and returns a session descriptor that includes the caller's accessible scopes, the server's capabilities (which optional operations it supports), the active curation rules that will apply to writes, and any server-imposed limits (max results, rate limits).

This maps naturally to OAuth 2.1. The identity token carries `sub`, `tenant_id`, and operational scopes. The server resolves access-tier scopes from its RBAC configuration. MemoryHub already does this at the JWT validation layer; the proposal is to formalize it as a protocol exchange rather than leaving it to implementation-specific auth flows.

## 6. Data Model

### 6.1 Memory Structure

A memory is a tree-structured node with typed branches. The flat-list model (used by most memory systems) was rejected in MemoryHub's design because it cannot represent the relationship between a memory and its justification, provenance, or approval chain without overloading the content field or maintaining parallel data structures.

Each memory node carries: **content** (the memory text), **weight** (a float between 0 and 1 controlling injection priority -- not relevance, but importance), **scope** (who can access it), **branch_type** (for non-root nodes: rationale, provenance, approval, description, tech-stack), **metadata** (timestamps, version info, curation flags, domain tags), and an **embedding** (vector representation for semantic search).

The protocol should define the node structure but leave the branching taxonomy extensible. MemoryHub's branch types (rationale, provenance, approval) are useful defaults, but other implementations may need domain-specific branch types. The core requirement is that branches are structurally linked to their parent -- not stored as separate memories with a string-typed relationship field.

Weight deserves emphasis because it is commonly misunderstood. Weight is not relevance. A memory with weight 0.5 that is highly relevant to a query still gets a high relevance score in search; the weight controls whether it is injected as full content or as a stub. This separation of relevance (query-dependent, computed at search time) from priority (memory-dependent, set at write time) is essential for context window management. Enterprise policy memories carry weight 1.0 and are always injected in full; low-priority user preferences carry lower weights and appear as stubs unless the agent explicitly requests full content.

### 6.2 Scopes

Scopes form a hierarchy that determines both visibility and governance. MemoryHub's hierarchy is: user, project, campaign, role, organizational, enterprise. Each scope tier has different rules for who can read, who can write, and what governance applies.

The protocol should define a minimum scope set (user, project, organizational, enterprise) and allow servers to extend it with additional tiers (campaign, role, domain-specific scopes). Enterprise scope is in the minimum set because the governance argument for memory-as-protocol (Section 10) depends on having a highest-authority tier where human approval is mandatory. The key semantic contracts are:

User-scope memories are private to one identity. Only the owning identity's agents can read or write them. This is a security property, not just a convenience: if another actor could modify a user's memories, they could alter the agent's behavior and attribute the consequences to the user.

Project-scope memories are shared within a project context. Any authorized agent working in the project can read and write them. The protocol must define how project membership is determined (claim in the identity token, server-side lookup, or both).

Organizational and enterprise scopes have escalating governance requirements. Enterprise/policy memories should require human approval for creation and modification. Organizational memories should support provenance tracking back to the source observations that motivated them.

### 6.3 Versioning

Every memory node must carry version metadata. MemoryHub uses an `isCurrent` flag with a version chain: updating a memory creates a new node, marks the old one as not current, and links the new version to the old one. The full chain is preserved and traversable.

This is not optional. Without version history, two critical capabilities are impossible. **Forensic reconstruction** -- determining exactly what an agent knew at a given point in time -- requires being able to query "which version of memory M was current on March 15th?" This matters for incident investigation: when an agent takes an unexpected action, the version history shows what beliefs influenced the decision. **Staleness detection** -- identifying memories that no longer reflect reality -- requires comparing the current version against accumulated contradiction reports, which only makes sense if versions are preserved rather than overwritten.

The protocol should require that conforming servers preserve version history and support temporal queries against it. The storage mechanism is implementation-dependent; the capability is not.

### 6.4 Relationships

Memories do not exist in isolation. MemoryHub defines four relationship types between memory nodes: `derived_from` (provenance -- this memory was produced from that one), `supersedes` (an organizational memory replaces a user memory on the same topic), `conflicts_with` (two memories contradict each other), and `related_to` (general association). These are stored as directed edges in a relationships table and are queryable through `get_relationships` and `create_relationship`.

The protocol should define relationship operations and a minimum set of relationship types. Graph-backed implementations will naturally support richer relationship semantics; vector-backed implementations can support the minimum set through a relationships table. The key requirement is that relationship operations are first-class -- not encoded as metadata fields on memory nodes, which makes them unqueryable and fragile.

## 7. Core Operations

### 7.1 Write

`memory.write` creates a memory node. The request includes content, scope, weight, optional parent_id (for branches), optional branch_type, optional domain tags, and optional metadata. The server must run its curation pipeline before persisting: at minimum, secrets detection and dedup checking.

The response must include the created memory and curation feedback. The protocol should define three categories of curation feedback: **duplicate detection** (how many similar memories exist, the nearest match identifier and similarity score), **content flags** (any policy violations detected -- secrets, PII, profanity), and **disposition** (whether the write was accepted, flagged for review, or blocked). MemoryHub implements these as `similar_count`, `nearest_id`, `nearest_score`, and `flags`; other implementations may use different field names, but the semantic categories must be present. This feedback is essential because it shifts ambiguous-case judgment to the calling agent's LLM, which has full conversational context and can make better decisions than any isolated curation check. A write that is blocked (secrets detected, exact duplicate) returns a structured error with the blocking reason and, for duplicates, a pointer to the existing memory.

Scope-based governance applies at write time. The server must verify that the caller is authorized to write at the requested scope before executing the curation pipeline. Writes to enterprise/policy scope must require elevated authorization (human approval or a designated service identity).

### 7.2 Read

`memory.read` retrieves a memory by ID. The response includes the full node content, metadata, branch indicators (`has_rationale`, `has_children`), and optionally version history and branches.

MemoryHub's `read_memory` supports paginated version history (`history_offset`, `history_max_versions`) so the caller can traverse the version chain without loading the entire history. This pagination was added after observing that agents sometimes trigger version history requests on memories with dozens of versions, which would blow out the response if returned unpaginated.

### 7.3 Search

`memory.search` is the most complex and most important operation. It performs semantic retrieval against the memory store, subject to scope filtering, token budget constraints, and optional focus biasing.

Required parameters: `query` (the search text). Optional parameters: `max_results` (page size), `max_response_tokens` (token budget for the entire response), `mode` (full/index/full_only -- controlling stub behavior), `scope` (filter to specific scope tiers), `project_id` (for project and campaign scope inclusion), `include_branches` (whether to nest branches under parents), `focus` (a string biasing retrieval toward a topic), `session_focus_weight` (how strongly the focus biases results), and `domains` (crosscutting knowledge tags for boosting).

The response includes an ordered list of results, each annotated with `result_type` (full or stub), `relevance_score`, `has_rationale`, and `has_children`. Pagination metadata (`total_matching`, `has_more`) tells the caller whether more results exist. When focus is provided, the response includes `pivot_suggested` (a boolean indicating the query has drifted far from the focus) and optionally `focus_fallback_reason` (if the reranker was unreachable and retrieval fell back to plain cosine).

The token budget contract is the most important detail for agent developers. Results are packed in relevance order. When the budget is exhausted, remaining results degrade to stubs but are still included so the agent never silently misses a ranked match. The agent sees both the full results it can use immediately and the stubs it could expand with `memory.read` if needed. This is strictly better than hard-cutoff top-K, which silently discards potentially relevant results.

### 7.4 Update

`memory.update` creates a new version of an existing memory, preserving the previous version in the history chain. The request includes the memory ID and the fields to update (content, weight, scope, domain tags). The server must verify the caller is authorized to write at the memory's scope, run the curation pipeline on the new content, and create the version link.

Importantly, update is not an in-place mutation. The previous version persists with `isCurrent=false`. This is a correctness requirement for forensics and staleness detection, not an implementation preference.

### 7.5 Delete

`memory.delete` performs a soft delete with an audit trail. The memory and its entire version chain are marked as deleted but not physically removed. The audit log records who deleted what, when, and (if provided) why.

Hard deletion should be available as a separate operation for GDPR right-to-erasure compliance, but it must also be audit-logged. The audit entry for a hard delete records that the memory existed and was erased, without preserving the content.

### 7.6 Relate

`memory.relate` creates or queries relationships between memories. Creation requires the source ID, target ID, relationship type, and optional metadata. The server must verify the caller is authorized to write on both source and target memories.

Querying returns all relationships for a given memory, filtered by the caller's access scope. Relationships pointing to memories the caller cannot access are omitted, with an `omitted_count` reported so the caller knows the graph is incomplete. This design (from MemoryHub's `get_relationships`) balances transparency with access control: the caller learns that hidden relationships exist without seeing the underlying data.

### 7.7 Contradict

`memory.contradict` reports an observed contradiction against a stored memory. The request includes the memory ID, the observed behavior that conflicts, and an optional confidence score. The server accumulates contradiction reports and surfaces the count as part of the memory's metadata.

Contradiction detection is a first-class operation because staleness is the most insidious failure mode in agent memory. A stale memory is not structurally wrong -- it has a valid embedding, a plausible content, and a genuine similarity to relevant queries. Only its temporal relationship to reality makes it unreliable. Without a formal mechanism for agents to report "this memory doesn't match what I'm seeing," stale memories persist indefinitely and silently degrade agent behavior.

MemoryHub triggers a curation flag when the contradiction count for a memory exceeds a configurable threshold (default 5). The protocol should standardize the contradiction reporting interface and leave the threshold and response to server configuration.

### 7.8 Curate

`memory.curate` encompasses two sub-operations: setting curation rules and querying similar memories for manual dedup assessment.

Rule-setting allows users (within their scope) to adjust curation parameters. MemoryHub's three-layer rules engine (system > organizational > user) enforces that system-layer rules marked as `override=true` cannot be weakened by user rules. A user can raise their dedup similarity threshold if their memories are intentionally similar; they cannot disable secrets scanning.

Similar-memory querying (`get_similar_memories` in MemoryHub) returns paged results of memories similar to a given memory ID, with similarity scores. This supports agent-driven dedup: the agent writes a memory, sees `similar_count: 3` in the curation feedback, calls `memory.curate` to inspect the similar memories, and decides whether to update an existing memory instead of creating a near-duplicate.

## Wire Format Examples

To make the protocol concrete, here are representative request/response pairs for the two most critical operations. Field names are illustrative; a formal JSON Schema would accompany the final specification.

**memory.write request:**
```json
{
  "op": "memory.write",
  "content": "This project uses FastAPI with Pydantic v2 for all API endpoints",
  "scope": "project",
  "weight": 0.85,
  "domains": ["FastAPI", "Pydantic"],
  "metadata": { "source": "architectural-decision", "date": "2026-04-14" }
}
```

**memory.write response:**
```json
{
  "memory_id": "a1b2c3d4-...",
  "version": 1,
  "scope": "project",
  "weight": 0.85,
  "curation": {
    "disposition": "accepted",
    "duplicate_detection": { "similar_count": 1, "nearest_id": "e5f6g7h8-...", "nearest_score": 0.82 },
    "content_flags": []
  }
}
```

**memory.search request:**
```json
{
  "op": "memory.search",
  "query": "what web framework does this project use",
  "max_results": 10,
  "max_response_tokens": 4000,
  "mode": "full",
  "project_id": "memory-hub",
  "focus": "API development",
  "session_focus_weight": 0.4
}
```

**memory.search response:**
```json
{
  "results": [
    {
      "memory_id": "a1b2c3d4-...",
      "content": "This project uses FastAPI with Pydantic v2 for all API endpoints",
      "result_type": "full",
      "relevance_score": 0.91,
      "weight": 0.85,
      "scope": "project",
      "has_rationale": false,
      "has_children": false,
      "domains": ["FastAPI", "Pydantic"]
    },
    {
      "memory_id": "b2c3d4e5-...",
      "stub": "MCP servers are the preferred integration pattern for AI agent capabilities...",
      "result_type": "stub",
      "relevance_score": 0.74,
      "weight": 0.85,
      "scope": "user",
      "has_rationale": false,
      "has_children": false
    }
  ],
  "total_matching": 12,
  "has_more": true,
  "pivot_suggested": false
}
```

The key elements visible in these examples: curation feedback on write (the caller sees 1 similar memory at 0.82 similarity and can decide whether to update it instead), budget-aware search (2 of 12 matches returned, one as full content, one as stub), and scope tagging on every result.

## 8. Retrieval Contracts

This section defines the contract between a memory server and its consumers for search result shaping. It is the most important section for agent developers because it directly affects context engineering -- what goes into the agent's context window and in what form.

**Full vs. stub.** Every search result is either full (complete content) or a stub (compressed summary with metadata). The weight on the memory controls the default: high-weight memories are full, low-weight memories are stubs. The caller can override this with mode control: `index` mode returns all stubs (for exploration), `full_only` mode returns all full (for zero-round-trip answers). Stubs must include enough information for the agent to decide whether to expand -- a topic label alone is too lossy; a first-paragraph preview with metadata is the minimum.

**Token budgets.** The `max_response_tokens` parameter is a soft cap on the entire response payload. The server packs results in relevance order. When the budget is reached, remaining results degrade to stubs. No result is silently dropped. The budget mechanism must be documented as a soft cap (the server may slightly exceed it to avoid splitting a result) rather than a hard limit.

**Branch handling.** By default, branches whose parent is also in the result set are omitted -- the parent's `has_rationale` and `has_children` flags signal that branches exist, and the agent can expand them via `memory.read`. When `include_branches` is true, branches are nested under their parent in a `branches` field rather than ranked as siblings. Branches whose parent is not in the result set are always returned as top-level entries. This design keeps default responses lean while making depth available on demand.

**Focus-aware retrieval.** When the caller provides a focus string, the server biases retrieval toward that topic. MemoryHub implements this as a two-vector retrieval pipeline: pgvector cosine recall, cross-encoder reranking, and reciprocal-rank fusion of rerank scores with focus-cosine scores. The focus path is stateless (focus is passed per call), optional (omitting focus falls through to plain cosine), and graceful-fallback (if the reranker is unreachable, the response documents the fallback). The protocol should define the focus parameter and the `pivot_suggested` signal (indicating the query has drifted from the focus) but leave the ranking implementation to the server.

**Cache-optimized ordering.** For agents that use compilation epochs (periodic full-context rebuilds), search results should have stable ordering across calls with the same parameters. This enables KV cache reuse in the language model. The protocol should recommend but not require stable ordering, since it is an optimization that depends on the agent framework's architecture.

## 9. Curation and Quality

Curation is the difference between a memory system that works for weeks and one that degrades into noise within days. MemoryHub's operational experience confirmed that without write-time curation, memory stores fill with duplicates, secrets, PII, and trivial observations that drown out useful memories.

**Write-time pipeline.** Curation must be inline, not async. MemoryHub's pipeline runs in the write path: Tier 1 (regex scanning for secrets and PII patterns, microseconds) and Tier 2 (embedding similarity against existing memories in the same owner/scope, milliseconds). The total curation overhead is single-digit milliseconds. Async curation (scanning memories after they are persisted and retrievable) creates a window where uncurated memories can be served to agents, which defeats the purpose.

**Three-layer rules.** Curation rules are scoped to three layers: system (platform defaults, some marked unoverridable), organizational (admin-configured), and user (agent-adjustable). The system layer includes secrets scanning and hard dedup thresholds. Users can tune their own dedup sensitivity but cannot weaken security scanning. This layering balances platform security with user autonomy.

**No LLM sampling for curation.** The MCP specification requires HITL approval for sampling requests. Applying this to write-time dedup decisions would mean popping an approval dialog on every ambiguous write -- unacceptable friction for a hot-path operation. MemoryHub's solution is to return similarity information in the write response and let the calling agent's existing LLM handle the judgment. The agent has full conversational context and makes better decisions than an isolated curation prompt could. The protocol should prohibit LLM sampling on the write path and require structured curation feedback instead.

**Curation feedback.** The write response must include: the number of similar existing memories above the flag threshold, the ID and similarity score of the nearest match, any curation flags applied, and whether the write was blocked. This information enables agent-driven memory hygiene without additional tool calls and without HITL friction.

## 10. Governance

Governance in a memory protocol is not an enterprise feature to be added later. It is a structural requirement for any deployment where more than one agent or user shares a memory backend.

**RBAC model.** The protocol defines scope-based access control: every memory has a scope, every caller has authorized scopes, and the server filters all operations accordingly. In MemoryHub, `search_memory` builds the authorized-scopes filter at the SQL level -- RBAC violations are impossible by construction, not prevented by post-hoc checks. The protocol should require that search operations apply scope filtering at the query level, not as a post-fetch filter that leaks information through timing or result count.

**Audit trails.** Every memory operation must be audit-logged with the operation type, actor identity, target memory, governance decision (permitted or denied), and for write operations, the before and after states. The audit trail must be append-only: entries cannot be modified or deleted, even by administrators. MemoryHub's audit schema uses PostgreSQL row-level security with a dedicated `audit_writer` role that has INSERT-only permissions.

**Forensic reconstruction.** The combination of version history and audit trails enables reconstruction of exactly what an agent knew at any point in time. This capability matters for incident investigation: "Why did the agent deploy to production without running tests?" can be answered by reconstructing the memory state that influenced the decision and the audit trail showing which memories were served. The protocol should require that conforming servers support temporal queries ("what did memory M say at time T?") against the version history.

**The attribution problem.** If agent memories influence agent behavior, and agent behavior has real consequences, then whoever controls the memories controls the outcome. The protocol must enforce that user-scope memories can only be written by the owning user's agents, that all writes are audit-logged with actor identity, and that version history preserves the provenance of every change. This does not make tampering impossible (direct database access bypasses any application-level control), but it makes tampering detectable, which is the practical standard for enterprise compliance.

## 11. Transport and Compatibility

### 11.1 Option A: New MCP Primitive

Memory becomes a fourth primitive alongside tools, resources, and prompts. MCP clients discover memory capability through the existing capability negotiation mechanism. When a server advertises `memory` capability, the client knows it can issue `memory.write`, `memory.search`, and other memory operations using standardized schemas.

Advantages: single protocol, single transport, single auth model. Agents that already speak MCP gain memory capability without additional integration. Server implementers extend their existing MCP servers rather than running a second service.

Disadvantages: MCP is governed by Anthropic, and adding a primitive requires their buy-in. The memory primitive's governance layer (scope-based RBAC, curation pipelines, audit trails) adds substantial complexity to a protocol that currently has a clean, simple design. Memory operations have different latency profiles and access patterns from tools, which may strain MCP's transport assumptions. The implementation burden on MCP client libraries (Claude Code, Cursor, Zed, Continue, and others) is non-trivial -- each must implement the memory primitive alongside tools, resources, and prompts. A phased rollout (clients that do not implement `memory` fall back to the tool facade described in Section 13) mitigates this, but the migration window adds ecosystem complexity.

### 11.2 Option B: Companion Protocol (AMP)

A standalone Agent Memory Protocol with its own transport, authentication, and governance layer, bridgeable to MCP through a standard adapter. AMP-aware agents connect to memory directly; legacy MCP agents access memory through an MCP tool facade that translates between protocols.

Advantages: independent governance -- AMP can evolve on its own release cadence without coordinating with MCP's roadmap. The protocol can be designed specifically for memory's access patterns (high-frequency reads, budget-aware responses, stateless focus) without compromising MCP's simplicity. Multiple agent protocols (not just MCP) could adopt AMP.

Disadvantages: agents must speak two protocols. The bridge adapter adds latency and complexity. Auth must be coordinated between AMP and MCP, or agents must authenticate twice.

### 11.3 Option C: MCP Extension

Use MCP's extension mechanism (if one exists or is created) to define memory as a capability that extends the base protocol without modifying it. Extensions would be namespaced (`amp/memory.write`, `amp/memory.search`) and discovered through capability negotiation.

Advantages: lightest-weight integration path. No changes to MCP core. Servers opt in by registering the extension; clients opt in by recognizing the namespace.

Disadvantages: depends on MCP having a robust extension mechanism, which as of this writing does not exist in a formalized way. Risk of fragmentation if multiple memory extensions emerge without coordination.

### 11.4 Recommendation

Option A (new MCP primitive) is the best outcome for the ecosystem if Anthropic is willing. It gives agents a single, coherent protocol with memory as a first-class concern. The complexity increase is justified because memory is not a niche use case -- every production agent system needs it, and every one is currently building ad-hoc solutions.

If Option A is not feasible, Option B (companion protocol) is the fallback. AMP as a standalone protocol has the advantage of being implementable without waiting for MCP governance decisions. The bridge adapter cost is real but manageable, and the independent evolution path means memory-specific concerns do not need to compete for MCP roadmap priority.

Option C is acceptable as a short-term measure but is not a long-term solution. Extensions without formal specification tend toward fragmentation.

## 12. Security Considerations

Agent memory introduces security concerns that do not exist for stateless tool invocations.

**Memory poisoning.** If an agent persists information from untrusted inputs (processed documents, web scrapes), an attacker can inject false beliefs into long-term storage. The protocol's curation pipeline (Section 9) provides a first line of defense through content scanning, but content-level scanning cannot detect semantically plausible false statements. Defense in depth requires provenance tracking (every memory records its source), scope isolation (untrusted inputs go to a sandboxed scope), and contradiction detection (agents can flag memories that do not match observed reality).

**Cascade corruption.** In multi-agent systems, Agent A hallucinating a fact and writing it to shared memory means Agent B reads it as ground truth and may write derived conclusions, propagating the hallucination. The protocol's scope hierarchy limits blast radius (a user-scope hallucination cannot reach organizational scope without curator promotion), and provenance chains enable tracing corrupted beliefs back to their source. But the fundamental problem -- distinguishing agent-generated beliefs from externally verified facts -- remains an open problem.

**Scope isolation.** The protocol requires that scope enforcement happens at the query level, not as a post-fetch filter. This prevents timing-based information leakage (where the presence or absence of hidden results changes response latency) and ensures that cross-scope reads require explicit authorization.

**Secret and PII detection.** The protocol requires that conforming servers implement content scanning for common secret and PII patterns. This is a protocol requirement, not an implementation suggestion, because a memory store that ingests API keys and social security numbers from agent conversations is a liability regardless of what other security measures are in place. MemoryHub's regex-based scanning catches AWS keys, GitHub tokens, private key headers, SSNs, email addresses, and phone numbers, with curation rules that system administrators cannot disable.

**OAuth 2.1 alignment.** The protocol's authentication model is OAuth 2.1, supporting `client_credentials` for agents and SDKs, `authorization_code` with PKCE for browser-based humans, and token exchange (RFC 8693) for platform-integrated agents. Short-lived JWTs (5-15 minute TTL) limit blast radius from token leakage. This alignment is deliberate: OAuth 2.1 is already the MCP authentication standard, and memory should not introduce a divergent auth model.

## 13. Migration Path

Existing memory-as-tools implementations can migrate incrementally.

**Adapter pattern.** A conforming AMP server can expose its operations through MCP tools as a backward-compatibility layer. MemoryHub's current 13-tool surface is essentially this adapter: `write_memory` maps to `memory.write`, `search_memory` maps to `memory.search`, and so on. The adapter adds protocol-level session establishment, standardized response schemas, and capability negotiation on top of the existing tool implementations.

**Gradual adoption.** Servers implement the protocol alongside their existing tool surface. Clients that understand the protocol use it directly; clients that do not continue using the tool facade. Over time, as client support matures, the tool facade can be deprecated. MemoryHub's existing `register_session` compatibility shim demonstrates this pattern at a smaller scale: JWT-authenticated clients skip it entirely, while API-key clients continue using it until they migrate.

**Schema mapping.** The protocol defines canonical schemas for all operations. Existing implementations map their current schemas to the canonical ones. Where the existing schema is richer (MemoryHub's branch types, Zep's temporal metadata, Letta's tier management), the extra fields pass through as metadata extensions. Where the existing schema is simpler (a basic vector store with write/search), the implementation reports reduced capabilities during handshake and the client adapts.

## 14. Open Questions

Several significant questions remain unresolved.

**Multi-cluster federation.** How do memory operations work across multiple memory servers in different clusters or regions? MemoryHub's current single-cluster deployment does not address this. Federation requires decisions about conflict resolution (which server's version wins?), latency tolerance (is cross-cluster search synchronous or eventual?), and scope mapping (do organizational scopes span clusters?).

**Standard evaluation benchmarks.** The field lacks benchmarks for agent memory beyond conversation-history recall. Needed: benchmarks for temporal reasoning (does the agent prefer recent over stale?), curation quality (does the pipeline catch secrets and dedup effectively?), multi-agent consistency (do agents converge on coherent beliefs?), and governance compliance (does the system correctly enforce scope restrictions?).

**Memory compilation and synthesis.** Karpathy's LLM Wiki pattern -- agents maintaining compiled, structured knowledge rather than raw interaction logs -- suggests that memory systems should support periodic synthesis operations. The protocol does not yet define how a server would signal that a memory is "compiled" versus "raw," or how compilation epochs interact with version history.

**Agent-to-agent memory sharing.** The current scope model assumes a hierarchy (user, project, organizational). It does not cleanly model peer-to-peer memory sharing where Agent A wants to share a specific memory with Agent B without making it visible to the entire project or organization. Adding per-memory ACLs would increase complexity substantially; the right abstraction is an open question.

**Memory weight calibration.** MemoryHub uses agent-set weights with scope-based defaults. The optimal weight assignment strategy -- and whether weights should decay over time based on access patterns -- remains an empirical question that requires more production data to answer.

**Formal consistency models.** Multi-agent memory consistency lacks formal models. The computer architecture community's work on cache coherence (MESI, MOESI) provides tools and inspiration, but agent memory conflict is semantic rather than bitwise, and detecting conflict requires understanding meaning, not just comparing values. Developing formal models for semantic consistency is a prerequisite for provably correct multi-agent memory systems.

## 15. Prior Art and References

This proposal draws on operational experience and published research from the following sources.

**Systems.** Mem0 (hybrid multi-tier architecture, https://mem0.ai). Zep/Graphiti (bi-temporal knowledge graph, https://www.getzep.com/; arXiv:2501.13956). Letta/MemGPT (OS-inspired memory hierarchy, https://www.letta.com/; arXiv:2310.08560). LangMem (semantic/episodic/procedural memory, https://blog.langchain.com/langmem-sdk-launch/). MemoryHub (tree-structured governed memory, deployed on OpenShift AI).

**Foundational work.** Karpathy on the LLM memory problem and the operating system analogy (YC AI Startup School, June 2025). Karpathy on context engineering (X, June 2025). Karpathy on system prompt learning (X, May 2025). Karpathy's LLM Wiki / compiled knowledge base pattern (GitHub Gist, April 2026).

**Research.** "Multi-Agent Memory from a Computer Architecture Perspective" (arXiv:2603.10062, March 2026) -- catalogs consistency challenges and draws parallels to hardware cache coherence. "Governing Evolving Memory in LLM Agents: SSGM Framework" (arXiv:2603.11768, 2026) -- proposes structured governance including retention policies, temporal decay, and write validation. MAGMA multi-graph architecture (arXiv:2601.03236, 2026) -- multi-graph approach with separate episodic, semantic, and procedural graphs. Liu et al., "Lost in the Middle" (TACL, 2024; arXiv:2307.03172) -- attention degradation in long contexts. Lewis et al., "Retrieval-Augmented Generation" (NeurIPS, 2020; arXiv:2005.11401) -- foundational RAG work. Salesforce Engineering, "How Agentic Memory Enables Durable, Reliable AI Agents" (2026) -- production-scale multi-agent memory.

**Standards.** Model Context Protocol (MCP) specification. OAuth 2.1 (RFC in progress). RFC 8693 (Token Exchange). RFC 9728 (OAuth Protected Resource Metadata).

**Regulatory.** EU AI Act (enforcement August 2026). GDPR right to erasure. HIPAA Security Rule. Deloitte "State of Generative AI in the Enterprise" (Q3 2025).
