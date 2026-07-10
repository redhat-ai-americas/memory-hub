# Agent Memory Protocol: A Proposal for Standardized Agent Memory

RFC-AMP-001 | Draft 2 | July 2026 (revises the April 2026 draft; argument reframed, implementation claims aligned with shipped code)
Authors: Wes Jackson

## Abstract

Every production agent memory system today (Mem0, Zep, Letta, LangMem, MemoryHub) exposes memory through MCP tools with incompatible schemas, incompatible semantics, and no shared governance model. This document proposes standardizing not the tool names but the **semantic contract** of agent memory: session-scoped identity, tree-structured memory with typed branches, budget-aware retrieval that never silently drops results, mandatory write-time curation with structured feedback, contradiction reporting, scope-based governance enforced at the query level, and preserved version history supporting forensic reconstruction. The contract can be carried three ways — a fourth MCP primitive, a companion protocol, or an MCP extension — and this document argues the packaging matters less than the contract, while recommending the primitive as the best ergonomic outcome if MCP governance permits. The design is grounded in operational experience from MemoryHub, a Kubernetes-native agent memory system deployed on OpenShift with a profile-based MCP tool surface, OAuth 2.1 authentication, and a production curation pipeline.

## 1. Motivation

### 1.1 The interoperability wall

An agent that works with MemoryHub's `search_memory(query, max_results, mode, max_response_tokens, focus, include_branches)` cannot use Zep's memory API without rewriting its integration layer. Mem0's `add_memory`/`search_memory` pair, Letta's tier management, and LangMem's namespace operations all differ in names, parameters, response shapes, and — more importantly — semantic contracts. "Supports MCP memory" today means "was tested against one vendor's tool schemas." Switching memory backends means changing tool descriptions, parameter mappings, response parsing, and instruction text. That is vendor lock-in at the integration layer — the exact problem MCP was designed to solve for tools.

### 1.2 The convention problem

Protocol-level concerns are today disguised as usage instructions. In MemoryHub, the consuming agent's rule file instructs it to establish a session first, pass `project_id` on searches, and call the contradiction-reporting operation when observations conflict with stored memories. These are correctness requirements expressed as natural language, and the failure mode is silent omission: an agent that forgets `project_id` silently misses project-scoped memories. When correctness depends on an LLM reliably following markdown instructions, integrations are brittle in ways that specifications can fix.

### 1.3 What standardization can and cannot fix — an honest accounting

The April draft of this RFC argued that a tool-schema convention "cannot solve" session ordering, governance enforcement, and transport differentiation, and that only a protocol change could. On reflection, that overstated the case, and the argument deserves an honest restatement, because the proposal is stronger without the weak claims.

**Session establishment is already a solved protocol problem.** MemoryHub's `register_session` shim exists because early MCP clients could not reliably send HTTP Authorization headers — a client-implementation gap, not a protocol-design gap. MCP puts identity on the transport via OAuth 2.1; when clients implement that correctly, the ordering problem disappears without any new primitive. What remains genuinely missing is the *handshake payload*: a standard way for the server to return the caller's resolved scopes, capabilities, curation rules, and limits (Section 5).

**Governance enforcement lives in the server regardless of packaging.** A tool-based server rejects unauthorized calls exactly as a primitive-based one would. What a specification adds is not enforcement power but **conformance requirements**: a conforming server MUST run write-time curation, MUST apply scope filtering at the query level, MUST preserve version history. Those MUSTs are equally expressible in a rigorous tool convention. The value is in specifying them at all — today, no two systems agree on what a memory server must guarantee.

**Access-pattern differences are real but do not, by themselves, require a new primitive.** Memory reads are high-frequency (nearly every conversational turn in MemoryHub's production traffic, versus sporadic calls for other tools), latency-sensitive, and budget-constrained. These facts justify contract features — token budgets, stub degradation, stateless focus — not necessarily transport changes.

**What, then, does protocol-level packaging actually buy?** Three things a convention delivers only weakly. **Capability negotiation:** a client that sees a `memory` capability in the handshake knows the full contract is available, versioned, and conformant — versus inspecting tool lists and guessing. **Contract enforcement surface:** client libraries can implement the memory contract once (budget handling, stub expansion, curation-feedback interpretation) instead of per-vendor glue. **A schema authority:** conventions without an owner fragment; a primitive or named extension has a specification to conform to and a test suite to pass.

So the proposal, precisely stated: **standardize the semantic contract of agent memory (Sections 5–10), and carry it in whichever packaging the ecosystem can adopt (Section 11), preferring a first-class MCP primitive for ergonomics.** The contract is the contribution; the packaging is logistics.

## 2. Background

### 2.1 MCP today

The Model Context Protocol defines three primitives. **Tools** are functions agents call to act on their environment. **Resources** are read-only data sources. **Prompts** are reusable templates. Transport is streamable-HTTP; authentication is OAuth 2.1. MCP has achieved broad adoption as the standard interface between agents and external capabilities, but it does not define a memory primitive: the specification treats context as something provided through tools and resources rather than as a distinct concern with its own lifecycle, governance, and access patterns.

### 2.2 The agent memory landscape (April 2026 snapshot)

Five systems represent the state of the art, and all expose memory through MCP tools or vendor SDKs.

**Mem0** provides a hybrid architecture (vector, graph, key-value) with automatic memory extraction. **Zep/Graphiti** implements a bi-temporal knowledge graph distinguishing when events occurred from when they were ingested, enabling explicit fact invalidation and temporal queries. **Letta** (formerly MemGPT) uses an OS-inspired hierarchy where the agent itself manages transitions between core, archival, and recall memory. **LangMem** organizes memory into semantic, episodic, and procedural categories. **MemoryHub** is a Kubernetes-native system with tree-structured memories, six governance scopes, inline curation (secrets/PII detection, embedding dedup), cross-encoder reranking with stateless session focus, OAuth 2.1 authentication, and a profile-based MCP tool surface (a compact action-dispatch profile by default; flat-tool profiles for smaller models).

These systems have independently converged on hybrid storage and similar lifecycle stages (write, store, retrieve, use, decay). The convergence in architecture has not produced convergence in interface — which is precisely the situation a contract specification exists to fix.

### 2.3 What memory is not

**Memory is not a tool** — operationally, not philosophically. Tools are invoked deliberately for specific purposes; memory is consulted pervasively as part of reasoning. Tools have clear success/failure semantics; memory retrieval is a matter of degree. Tools are stateless between invocations; memory is inherently stateful and temporally ordered. None of this makes carrying memory operations over tool-shaped messages impossible (MemoryHub does exactly that in production); it means the *contract* governing those messages must address concerns — budgets, scopes, versions, contradictions — that the generic tool contract does not.

**Memory is not a resource.** MCP resources are read-only; memory is read-write, and the write path carries governance requirements (curation, scope enforcement, dedup) that resources do not contemplate.

**Memory is not caching.** Caches have mechanical invalidation strategies (TTL, LRU). Memory relevance is contextual, semantic, and temporal: a memory written six months ago may beat one written yesterday, depending on the query. No TTL captures "still relevant during deployment work, irrelevant while writing tests" — which is why staleness handling requires contradiction reporting (Section 7.7) rather than expiry alone.

## 3. Design Principles

Six principles guide the contract. Each emerged from operational experience building and running MemoryHub.

**Memory is cognitive state, not environment action.** Treat memory operations as modifications to and queries against the agent's belief state. In MemoryHub's production traffic, memory search runs on nearly every turn while other tools run sporadically — the access pattern is categorically different, and the contract (budgets, stubs, focus) exists to serve it.

**Curation is mandatory, not optional.** Without write-time quality gates, memory stores fill with garbage within weeks. MemoryHub's inline pipeline — regex secrets/PII detection, embedding-based dedup — runs on every write in single-digit milliseconds. A conforming server must implement a curation pipeline and report outcomes to the caller. Optional curation is absent curation: no implementation prioritizes it without a specification requirement.

**Retrieval must be budget-aware.** Returning top-K without regard to the consumer's context window wastes tokens (K too large) or misses context (K too small). The caller declares a token budget; the server packs results in relevance order, degrades to stubs when the budget is exhausted, and reports `has_more`. Every memory consumer faces context-window scarcity; leaving budget management to ad-hoc convention produces brittle integrations.

**Governance is structural, not bolted on.** Scope-based access control, audit trails, and version history are correctness requirements for any multi-user or multi-agent deployment, not enterprise upsells. In MemoryHub, every operation passes authorization before touching the service layer, and search applies the authorized-scope filter at the SQL level — violations are impossible by construction rather than merely unlikely. Retrofitting access control onto a system that launched without it leaves gaps that are hard to close.

**Statelessness where possible.** MemoryHub passes the session-focus string per call rather than storing it server-side, which eliminated every coordination question about pod-local state, distributed caching, and session affinity. The cost — re-embedding the focus string per call, ~50ms warm — is negligible against the operational complexity of session state in a horizontally scaled deployment. The contract prefers stateless designs and requires explicit justification for server-side state.

**No human-in-the-loop friction on the hot path.** MemoryHub's curation pipeline initially included LLM sampling for ambiguous dedup decisions; under MCP's HITL-approval requirement for sampling, that would have put an approval dialog on every ambiguous write. Instead, the write response returns structured curation feedback (similar count, nearest match, score) and the calling agent's own LLM — which has full conversational context — decides. HITL belongs on policy-tier memory creation and explicit review workflows, not on the write and search hot paths.

## 4. Protocol Overview

The Agent Memory Protocol defines the interface between an agent and its memory backend, in three layers, independent of packaging (Section 11).

**Transport and session layer.** Identity claims, scope resolution, and capability negotiation. Who is the agent, what tenant does it belong to, what does this server guarantee?

**Operations layer.** The core operations: write, read, search, update, delete, relate, contradict, curate. Each has defined request/response schemas, error semantics, and governance hooks. This is where backends differentiate — a graph-backed and a vector-backed server expose the same operations with different performance characteristics.

**Governance layer.** Scope-based access control, curation rules, audit requirements, version management. This layer defines what a conforming server must enforce regardless of backend.

The relationship to MCP is additive, not competitive: MCP continues to handle tools, resources, and prompts; this contract handles the distinct concerns of persistent, governed, agent-owned knowledge.

## 5. Session and Identity

MemoryHub's `register_session` tool is a compatibility shim that should not exist, and its existence is instructive. It was created because early MCP clients could not reliably send HTTP Authorization headers, so agents establish identity by calling a tool — which means an agent can forget to call it, call it wrong, or call it late, and every other operation implicitly depends on it having happened. Tools are supposed to be independently invocable; session establishment creates ordering that the tool abstraction does not model.

The fix has two parts, only one of which is new. **Identity belongs on the transport**: OAuth 2.1 bearer tokens, exactly as MCP already specifies — this is a client-implementation obligation, not a protocol gap. **Capability exchange belongs in the handshake**, and this is the genuinely missing piece: on connection, the server should resolve the caller's tenant, accessible scopes, and applicable curation rules, and return a session descriptor containing the accessible scopes, the server's supported operations and optional capabilities, the active curation rules that will apply to writes, and server-imposed limits (max results, rate limits). Today that information is discoverable only by trial and error or by reading vendor docs.

This maps naturally onto OAuth 2.1: the token carries `sub`, `tenant_id`, and operational scopes; the server resolves access-tier scopes from its RBAC configuration. MemoryHub already does the resolution at JWT-validation time; the proposal is to standardize the descriptor it returns.

## 6. Data Model

### 6.1 Memory structure

A memory is a tree-structured node with typed branches. The flat-list model used by most systems cannot represent the relationship between a memory and its justification, provenance, or approval chain without overloading the content field or maintaining parallel structures.

Each node carries: **content** (the memory text), **weight** (a float 0–1 controlling injection priority — not relevance), **scope** (who can access it), **branch_type** (for non-root nodes: rationale, provenance, description, evidence, approval are the conventional core set), **metadata** (timestamps, version info, curation flags, domain tags), and an **embedding**. The contract defines the node structure but leaves the branching taxonomy extensible; the core requirement is that branches are structurally linked to their parent, not stored as separate memories with a string-typed relationship field.

Weight deserves emphasis because it is commonly misunderstood. **Weight is not relevance.** A weight-0.5 memory that is highly relevant to a query still ranks high in search; weight controls whether it is injected as full content or as a stub. This separation of relevance (query-dependent, computed at search time) from priority (memory-dependent, set at write time) is essential for context-window management: enterprise policy memories carry weight 1.0 and always inject in full; low-priority preferences appear as stubs unless expanded.

### 6.2 Scopes

Scopes form a hierarchy determining both visibility and governance. MemoryHub's hierarchy is user, project, campaign, role, organizational, enterprise. The contract should define a minimum set (user, project, organizational, enterprise) and allow servers to extend it (campaign, role, domain-specific tiers). Enterprise is in the minimum set because the governance argument (Section 10) depends on a highest-authority tier where human approval is mandatory.

Key semantic contracts: **user-scope memories are private to one identity** — this is a security property, not a convenience, because an actor who can modify a user's memories can alter that user's agents' behavior and attribute the consequences to the user. **Project-scope memories are shared within a project context**, and the contract must define how membership is determined (identity-token claim, server-side lookup, or both). **Organizational and enterprise scopes carry escalating governance**: enterprise/policy creation requires human approval; organizational memories should support provenance back to the observations that motivated them.

### 6.3 Versioning

Every memory node must carry version metadata. MemoryHub uses an `is_current` flag with a version chain: updates create a new node, mark the old one not-current, and link the versions; the full chain is preserved and traversable.

This is not optional, because two capabilities are impossible without it. **Forensic reconstruction** — determining exactly what an agent knew at a point in time — requires answering "which version of memory M was current on March 15th?" When an agent takes an unexpected action, the version history shows what beliefs influenced it. **Staleness detection** requires comparing the current version against accumulated contradiction reports, which only makes sense if versions persist. A conforming server must preserve version history and support temporal queries against it; the storage mechanism is implementation-dependent, the capability is not.

### 6.4 Relationships

Memories do not exist in isolation. MemoryHub defines five relationship types between nodes: `derived_from` (provenance), `supersedes` (a broader-scope memory replaces a narrower one on the same topic), `conflicts_with` (contradiction), `related_to` (general association), and `mentions` (a memory references an extracted entity). The contract should define relationship operations and a minimum type set; graph-backed implementations will support richer semantics, and vector-backed ones can meet the minimum with a relationships table. The requirement is that relationships are first-class and queryable — not metadata fields on nodes, which are unqueryable and fragile.

## 7. Core Operations

### 7.1 Write

`memory.write` creates a node. Request: content, scope, weight, optional parent_id (for branches), branch_type, domain tags, metadata. The server must run its curation pipeline before persisting — at minimum, secrets detection and dedup checking.

The response must include the created memory and structured curation feedback in three categories: **duplicate detection** (similar-memory count, nearest match ID and score), **content flags** (secrets, PII, policy violations), and **disposition** (accepted, flagged, or blocked). Field names may vary; the semantic categories must be present. This feedback shifts ambiguous-case judgment to the calling agent's LLM, which has conversational context no isolated curation check can match. A blocked write returns a structured error with the reason and, for duplicates, a pointer to the existing memory.

Scope governance applies at write time: the server verifies write authorization at the requested scope before running curation; enterprise/policy writes require elevated authorization.

### 7.2 Read

`memory.read` retrieves a node by ID: full content, metadata, branch indicators (`has_rationale`, `has_children`), and optionally version history and branches. Version history must be paginated — MemoryHub added `history_offset`/`history_max_versions` after observing agents trigger history requests on memories with dozens of versions.

### 7.3 Search

`memory.search` is the most complex and most important operation: semantic retrieval subject to scope filtering, token budgets, and optional focus biasing.

Required: `query`. Optional: `max_results`, `max_response_tokens` (budget for the whole response), `mode` (full/index/full_only), `scope` filters, `project_id`, `include_branches`, `focus` (a string biasing retrieval toward a topic), `session_focus_weight`, and `domains` (crosscutting tags for boosting).

The response is an ordered result list, each entry annotated with `result_type` (full or stub), `relevance_score`, and branch indicators, plus pagination metadata (`total_matching`, `has_more`). With focus provided, the response includes `pivot_suggested` (the query has drifted from the focus beyond a threshold) and `focus_fallback_reason` when reranking degraded to plain cosine.

The token-budget contract is the detail that matters most to agent developers: results pack in relevance order, and when the budget is exhausted, remaining results degrade to stubs **but are still included** — the agent never silently misses a ranked match, and can expand any stub via `memory.read`. This is strictly better than hard-cutoff top-K.

### 7.4 Update

`memory.update` creates a new version, preserving the old one in the chain. The server verifies scope authorization, runs curation on the new content, and links the versions. Update is not in-place mutation — the previous version persists with `is_current=false`. This is a forensics correctness requirement, not an implementation preference.

### 7.5 Delete

`memory.delete` soft-deletes with an audit record: the memory and its version chain are marked deleted, not physically removed. Hard deletion exists as a separate operation for GDPR right-to-erasure, and it too is audit-logged — the entry records that a memory existed and was erased, without preserving content.

### 7.6 Relate

`memory.relate` creates or queries relationships. Creation requires authorization on both source and target. Queries return relationships filtered by the caller's access scope; edges pointing at inaccessible memories are omitted with an `omitted_count`, so the caller learns the graph is incomplete without seeing hidden data.

### 7.7 Contradict

`memory.contradict` reports an observed contradiction: memory ID, the conflicting observation, optional confidence. The server accumulates reports and surfaces the count in the memory's metadata; MemoryHub flags a memory for curation when the count crosses a configurable threshold (default 5).

Contradiction reporting is first-class because staleness is the most insidious failure mode in agent memory. A stale memory is not structurally wrong — valid embedding, plausible content, genuine query similarity — only its temporal relationship to reality makes it unreliable. Without a formal channel for "this memory doesn't match what I'm seeing," stale memories persist indefinitely and silently degrade behavior.

### 7.8 Curate

`memory.curate` covers rule management and similarity inspection. Rules are layered — system > organizational > user — with system rules markable as unoverridable: a user can raise their own dedup threshold; they cannot disable secrets scanning. Similarity inspection returns paged memories similar to a given ID, supporting agent-driven dedup: write, see `similar_count: 3` in the feedback, inspect, and decide whether to update an existing memory instead of creating a near-duplicate.

## Wire Format Examples

Illustrative request/response pairs for the two most critical operations; a formal JSON Schema would accompany the final specification.

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

Visible in the examples: curation feedback on write (one similar memory at 0.82 — the caller can update it instead), budget-aware search (2 of 12 matches returned, one full, one stub, nothing silently dropped), and scope tagging on every result.

## 8. Retrieval Contracts

The contract between a memory server and its consumers for result shaping — the section that most directly affects context engineering.

**Full vs. stub.** Every result is full content or a stub (compressed summary with metadata). Weight sets the default; the caller can override with `index` mode (all stubs, for exploration) or `full_only` (zero-round-trip answers). Stubs must carry enough to decide whether to expand — a topic label is too lossy; a preview with metadata is the minimum.

**Token budgets.** `max_response_tokens` is a soft cap on the whole response. Results pack in relevance order; past the budget, results degrade to stubs; nothing is silently dropped. Soft cap, not hard limit — the server may slightly exceed it rather than split a result.

**Branch handling.** By default, branches whose parent is in the result set are omitted; the parent's `has_rationale`/`has_children` flags signal their existence and the agent expands on demand. With `include_branches`, branches nest under their parent rather than ranking as siblings. Branches whose parent is absent return as top-level entries. Lean by default, deep on demand.

**Focus-aware retrieval.** With a focus string, the server biases retrieval toward that topic. MemoryHub implements this as two-vector retrieval: pgvector cosine recall, cross-encoder reranking, reciprocal-rank fusion of rerank and focus-cosine ranks. The focus path is stateless (passed per call), optional (absent focus falls through to plain cosine), and graceful (reranker unreachable → documented fallback). The contract defines the focus parameter and the `pivot_suggested` signal; ranking implementation is the server's.

**Cache-optimized ordering.** For agents that periodically rebuild full context, stable result ordering across identical calls enables KV-cache reuse in the serving layer. Recommended, not required — the benefit depends on the agent framework's architecture.

## 9. Curation and Quality

Curation is the difference between a memory system that works for weeks and one that degrades into noise within days. MemoryHub's operational experience: without write-time curation, stores fill with duplicates, secrets, PII, and trivia that drown the useful memories.

**Write-time, inline, not async.** MemoryHub's pipeline runs in the write path: Tier 1 regex scanning (secrets, PII — microseconds) and Tier 2 embedding similarity within the owner/scope (milliseconds); total overhead is single-digit milliseconds. Async curation creates a window where uncurated memories are served, defeating the purpose.

**Three-layer rules.** System (platform defaults, some unoverridable), organizational (admin-configured), user (agent-adjustable). Users tune their own dedup sensitivity; nobody weakens security scanning.

**No LLM sampling on the write path.** Structured feedback instead (Section 3, sixth principle; Section 7.1). The calling agent's LLM, with full conversational context, makes better ambiguous-case decisions than an isolated curation prompt — and without HITL friction.

## 10. Governance

Governance is a structural requirement for any deployment where more than one agent or user shares a memory backend, not an enterprise feature added later.

**RBAC model.** Every memory has a scope; every caller has authorized scopes; the server filters all operations accordingly. The contract requires scope filtering **at the query level** — in MemoryHub, search builds the authorized-scope filter into the SQL, making violations impossible by construction — not as a post-fetch filter that leaks information through timing or result counts.

**Audit trails.** Every operation must be audit-logged: operation type, actor identity, target memory, governance decision, and before/after states for writes. The trail must be append-only — unmodifiable even by administrators. Implementation status in MemoryHub, stated plainly: structured audit events are emitted on every tool call site today; the durable append-only store is in progress (the design targets PostgreSQL row-level security with an INSERT-only writer role). The contract specifies the requirement; MemoryHub is partway through meeting it.

**Forensic reconstruction.** Version history plus audit trail enables reconstructing exactly what an agent knew at any point in time. "Why did the agent deploy to production without running tests?" is answerable by reconstructing the memory state that influenced the decision and the trail of which memories were served. Conforming servers must support temporal queries against version history.

**The attribution problem.** If memories influence agent behavior and agent behavior has real consequences, whoever controls the memories controls the outcome. The contract enforces that user-scope memories are writable only by the owning user's agents, that all writes are logged with actor identity, and that version history preserves the provenance of every change. This does not make tampering impossible — direct database access bypasses any application-level control — but it makes tampering *detectable*, which is the practical standard for enterprise compliance.

## 11. Packaging Options

Three ways to carry the contract. The contract (Sections 5–10) is identical in all three.

### 11.1 Option A: New MCP primitive

Memory becomes a fourth primitive alongside tools, resources, and prompts, discovered through capability negotiation. Advantages: single protocol, transport, and auth model; client libraries implement the memory contract once; the strongest schema authority. Disadvantages: requires Anthropic's buy-in and adds real complexity to a deliberately simple protocol; every MCP client library carries an implementation burden; a migration window (clients without `memory` support falling back to the tool facade of Section 13) adds ecosystem complexity for a while.

### 11.2 Option B: Companion protocol (AMP)

A standalone protocol with its own governance, bridgeable to MCP through a standard adapter. Advantages: independent evolution, memory-specific design freedom, adoptable by non-MCP agent stacks. Disadvantages: agents speak two protocols; the bridge adds latency and complexity; auth must be coordinated or duplicated.

### 11.3 Option C: MCP extension

Namespaced operations (`amp/memory.write`, `amp/memory.search`) discovered via capability negotiation, using whatever extension mechanism MCP formalizes. Advantages: lightest-weight path; no core changes; opt-in on both sides. Disadvantages: depends on the maturity of MCP's extension story at adoption time, and un-owned extensions tend toward fragmentation.

### 11.4 Recommendation

Option A is the best ecosystem outcome if MCP governance permits: memory is not a niche capability — every production agent system needs it and every one is currently building an ad-hoc version — and a first-class primitive gives clients one coherent contract. If A is not feasible on a reasonable timeline, Option B is the fallback: implementable without waiting on anyone, at the price of a bridge. Option C is a pragmatic interim wherever a formalized extension mechanism exists. In all three cases the work that matters — agreeing on the contract — is the same, which is why this document spends its pages there.

## 12. Security Considerations

Agent memory introduces concerns that stateless tool invocation does not have.

**Memory poisoning.** An agent that persists information from untrusted inputs (processed documents, web content) can have false beliefs injected into long-term storage. Write-time scanning (Section 9) is the first line of defense but cannot detect semantically plausible falsehoods. Defense in depth: provenance tracking (every memory records its source), scope isolation (untrusted inputs land in a sandboxed scope), and contradiction reporting (agents flag memories that contradict observation).

**Cascade corruption.** In multi-agent systems, Agent A's hallucination written to shared memory becomes Agent B's ground truth, and B's derived conclusions propagate it. The scope hierarchy limits blast radius (a user-scope hallucination cannot reach organizational scope without curated promotion), and provenance chains allow tracing corrupted beliefs to their source. The fundamental problem — distinguishing agent-generated beliefs from externally verified facts — remains open.

**Scope isolation.** Enforcement at the query level, not post-fetch (Section 10), prevents timing-based leakage and ensures cross-scope reads require explicit authorization.

**Secret and PII detection.** Required of conforming servers, not suggested: a memory store that ingests API keys and SSNs from agent conversations is a liability regardless of other measures. MemoryHub's scanning covers cloud credentials, tokens, private-key headers, SSNs, emails, and phone numbers, under system-layer rules administrators cannot disable.

**OAuth 2.1 alignment.** `client_credentials` for agents and SDKs, `authorization_code`+PKCE for humans in browsers, RFC 8693 token exchange for platform-integrated agents, short-lived JWTs (5–15 minutes) to bound token-leak blast radius. Deliberately the same model as MCP — memory should not introduce a divergent auth story.

## 13. Migration Path

Existing memory-as-tools implementations migrate incrementally.

**Adapter pattern.** A conforming server exposes its operations through MCP tools as a compatibility layer. MemoryHub's tool surface is essentially this adapter already — its flat tools map one-to-one onto the contract operations (`write_memory` → `memory.write`, `search_memory` → `memory.search`), and its compact action-dispatch profile demonstrates that the operation set also survives repackaging into a different tool shape without semantic change. That survivability is itself evidence the contract, not the tool schema, is the stable layer.

**Gradual adoption.** Servers implement the contract alongside their existing tool surface; contract-aware clients use it directly; others continue on the facade until it is deprecated. MemoryHub's `register_session` shim already demonstrates the pattern: JWT-authenticated clients skip it entirely while API-key clients keep using it.

**Schema mapping.** The contract defines canonical schemas; existing implementations map onto them. Richer schemas (MemoryHub's branch types, Zep's temporal metadata, Letta's tiers) pass extra fields through as metadata extensions; simpler ones (a bare vector store) report reduced capabilities at handshake and the client adapts.

## 14. Open Questions

**Multi-cluster federation.** Conflict resolution across servers, synchronous vs. eventual cross-cluster search, whether organizational scopes span clusters. MemoryHub's single-cluster deployment does not yet force these decisions.

**Standard evaluation benchmarks.** The field measures conversation-history recall and little else. Needed: temporal reasoning (recent preferred over stale?), curation quality (are secrets and dupes actually caught?), multi-agent consistency (do agents converge on coherent beliefs?), and governance compliance (are scope restrictions enforced under test?).

**Memory compilation and synthesis.** The compiled-knowledge pattern (Karpathy's llm-wiki) suggests servers should support periodic synthesis. The contract does not yet define how a "compiled" memory differs from a "raw" one, nor how compilation epochs interact with version history.

**Agent-to-agent sharing.** The scope hierarchy does not cleanly model Agent A sharing one memory with Agent B without exposing it to the whole project. Per-memory ACLs would add substantial complexity; the right abstraction is open.

**Weight calibration.** Agent-set weights with scope defaults work; whether weights should decay with disuse is an empirical question awaiting more production data.

**Formal consistency models.** Multi-agent memory consistency lacks formal treatment. Cache-coherence work (MESI/MOESI) inspires, but memory conflict is semantic, not bitwise — detecting it requires understanding meaning. Formal models for semantic consistency are a prerequisite for provably correct multi-agent memory.

## 15. Prior Art and References

**Systems.** Mem0 (hybrid multi-tier architecture, https://mem0.ai; arXiv:2504.19413). Zep/Graphiti (bi-temporal knowledge graph, https://www.getzep.com/; arXiv:2501.13956). Letta/MemGPT (OS-inspired memory hierarchy, https://www.letta.com/; arXiv:2310.08560). LangMem (semantic/episodic/procedural memory, https://blog.langchain.com/langmem-sdk-launch/). MemoryHub (tree-structured governed memory, deployed on OpenShift AI; this repository).

**Foundational work.** Karpathy on the LLM memory problem and the operating-system analogy (YC AI Startup School, June 2025); on context engineering (X, June 2025); on system prompt learning (X, May 2025); the llm-wiki compiled-knowledge pattern (GitHub Gist, April 2026).

**Research.** "Multi-Agent Memory from a Computer Architecture Perspective" (arXiv:2603.10062) — consistency challenges and cache-coherence parallels. "Governing Evolving Memory in LLM Agents: SSGM Framework" (arXiv:2603.11768) — structured governance with retention, decay, and write validation. MAGMA (arXiv:2601.03236) — multi-graph memory architecture. Liu et al., "Lost in the Middle" (TACL 2024; arXiv:2307.03172) — attention degradation in long contexts. Lewis et al., "Retrieval-Augmented Generation" (NeurIPS 2020; arXiv:2005.11401).

**Standards.** Model Context Protocol specification. OAuth 2.1. RFC 8693 (Token Exchange). RFC 9728 (OAuth Protected Resource Metadata).

**Regulatory.** EU AI Act (enforcement begins August 2026). GDPR right to erasure. HIPAA Security Rule.
