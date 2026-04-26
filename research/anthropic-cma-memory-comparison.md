# Anthropic CMA Memory: Competitive and Architectural Comparison with MemoryHub

**Date**: 2026-04-23
**Status**: Research analysis
**Context**: Anthropic announced "Memory on Claude Managed Agents" on April 23, 2026, entering public beta. This analysis informs an upcoming blog post and arXiv survey paper.

---

## 1. Executive Summary

Anthropic — the model provider — has entered the agent memory space with a filesystem-based memory layer for Claude Managed Agents. Memory is stored as files on a mounted filesystem, leveraging Claude's existing bash and code execution capabilities for reads and writes. Stores can be shared across agents with scoped permissions, changes are tracked with audit logs, and developers retain full export and programmatic control via the API. The announcement is accompanied by compelling customer results: Netflix carrying context across sessions, Rakuten cutting first-pass errors by 97%, Wisedocs speeding verification by 30%.

This is the most strategically significant announcement in the agent memory space to date — not because the architecture is the most sophisticated (Cloudflare's Project Think is more technically elaborate), but because the model provider is now vertically integrating memory into its own inference platform. Anthropic controls both the model and the memory layer, and has explicitly optimized the two together: "With filesystem-based memory, our latest models (Opus 4.7) save more comprehensive, well-organized memories and are more discerning about what to remember." No external memory service can replicate this co-optimization.

The architecture validates that persistent, cross-session, multi-agent memory is a first-class infrastructure concern. It also represents the strongest platform-coupling play yet: CMA Memory works with Claude Managed Agents and nothing else. An enterprise that accumulates months of agent memory on CMA faces both switching costs (data portability) and capability costs (the model-memory co-optimization disappears on any other platform). MemoryHub occupies the opposite end of this spectrum — platform-agnostic, protocol-based, structurally richer — and the two designs reflect fundamentally different answers to the question of who should own agent memory.

## 2. Where They Validate Our Approach

The model provider building memory into its own platform is the strongest possible validation that agent memory is not a nice-to-have but core infrastructure for production agents.

**Cross-session learning as a first-class capability.** Anthropic's framing — "agents that learn from every session" — matches MemoryHub's core thesis. The announcement treats memory not as a feature but as a prerequisite for production agents. The customer examples reinforce this: Netflix agents that carry context across sessions, Rakuten agents that avoid repeating mistakes. These are exactly the use cases MemoryHub was designed for, now validated by the model provider itself.

**Multi-agent memory sharing.** CMA Memory supports shared stores across multiple agents with different access scopes — "an org-wide store might be read-only, while per-user stores allow reads and writes." This validates MemoryHub's scope hierarchy design. The model provider has concluded that agents need to share memory, that shared memory needs scoped access control, and that read-only vs. read-write distinctions matter. MemoryHub has six scope tiers (user, project, campaign, role, organizational, enterprise) and SQL-level RBAC; CMA has a simpler model, but the architectural direction is the same.

**Concurrent multi-agent access.** "Multiple agents can work concurrently against the same store without overwriting each other." This validates MemoryHub's design for concurrent memory access. The concurrency problem is real — agents that share memory need to do so without data races — and the model provider has built for it.

**Audit and provenance.** CMA tracks "which agent and session a memory came from" with detailed audit logs. MemoryHub's version history and relationship types (derived_from, supersedes, conflicts_with) serve a similar purpose at finer granularity. The shared insight: in production deployments, knowing where a memory came from and being able to roll it back is not optional.

**Developer control and portability.** Memories are files that can be exported and managed via the API. This is a notable design choice — Anthropic could have made memories opaque and platform-locked (as Cloudflare effectively has with Durable Objects). Instead, they chose file-based portability. This validates the principle that organizations need to own their memory data, though the portability is limited to what files can express (no semantic search indices, no relationship graphs, no typed branches).

## 3. Where We Diverge

The differences between CMA Memory and MemoryHub reflect a fundamental split between platform-coupled and platform-agnostic memory.

**Filesystem-based vs. database-backed.** CMA Memory stores memories as files on a mounted filesystem, and Claude interacts with them using the same bash and code execution tools it uses for any file manipulation. This is elegant in its simplicity — no new tool interfaces to learn, no query language, just files. But files lack semantic search (you can grep, but you cannot find "memories about deployment patterns" when the word "deployment" doesn't appear), structured relationships (no derived_from chains, no contradiction links), typed branches (no rationale vs. provenance distinction), and transactional consistency guarantees. MemoryHub uses PostgreSQL + pgvector precisely because these capabilities require a query engine, not a filesystem.

**Platform-coupled vs. platform-agnostic.** CMA Memory is inseparable from Claude Managed Agents. An enterprise using Claude Code for development, LangGraph for data pipelines, and LlamaStack for on-premise inference has one memory silo that works with CMA and three agent harnesses that cannot access it. MemoryHub runs on any Kubernetes cluster and is accessed over MCP — any MCP client can connect. The memory follows the protocol, not the platform.

**Model-optimized vs. model-independent.** This is Anthropic's unique and unreplicable advantage. Because they control both the model and the memory layer, they can tune the model to be "more discerning about what to remember for a given task." This is not something MemoryHub or any external memory service can do — it requires coordinated changes to model weights and memory infrastructure. The co-optimization creates a genuine capability gap: CMA Memory with Opus 4.7 may simply produce better memory writes than any model using an external memory service, because the model was trained to use *this* memory system. The counterargument is that this optimization is narrow — it works for one model on one platform — while MemoryHub serves any model on any platform.

**Implicit structure vs. explicit structure.** CMA Memory's file-based approach relies on the model to impose structure through file naming, directory organization, and content formatting. The model decides how to organize its memories, and Opus 4.7 has been tuned to do this well. MemoryHub imposes structure at the platform level: tree-structured nodes with parent_id, typed branches, six scope tiers, relationship types. The tradeoff is flexibility vs. consistency — CMA lets the model organize memory however seems natural, while MemoryHub enforces a schema that makes memory queryable, governable, and interoperable across agents that did not create it.

**Scoped permissions vs. governed access.** CMA offers per-store access scopes (read-only, read-write) shared across agents. MemoryHub has six scope tiers with SQL-level RBAC, three-layer curation rules (system/org/user with override protection), and inline secrets/PII detection. CMA's model is sufficient for a single team's agents; MemoryHub's model targets organizations where memory governance is a compliance requirement.

## 4. What They Do Well That We Don't (Yet)

**Model-memory co-optimization.** This bears repeating because it is genuinely novel. Anthropic can tune Opus 4.7 to write better memories, retrieve more effectively, and be more selective about what to remember — all because they control the full stack from model weights to memory storage. The result, per their announcement, is models that "save more comprehensive, well-organized memories and are more discerning about what to remember for a given task." No external memory service can offer this. The closest MemoryHub can come is providing good memory tools with clear descriptions and letting the model's general tool-use capabilities do the rest, but this will always be a step behind a purpose-tuned model.

**Zero-friction agent integration.** Because CMA Memory mounts as a filesystem and Claude already knows how to use bash, there is no tool onboarding cost. Agents do not need to learn new MCP tools or memory APIs — they read and write files, something they already do well. MemoryHub requires agents to discover and use ten MCP tools (write_memory, search_memory, read_memory, etc.), which is a higher integration surface. The filesystem approach trades capability for simplicity, and for many use cases, simplicity wins.

**Production-validated customer results.** Rakuten's 97% reduction in first-pass errors and Wisedocs' 30% faster verification are powerful proof points. MemoryHub is deployed on OpenShift AI but does not yet have published customer metrics at this scale. These numbers validate the entire agent memory category, not just CMA, but the fact that they come from Anthropic's platform means CMA gets the credibility.

**Managed infrastructure.** CMA Memory is a managed service — Anthropic handles the storage, scaling, concurrency, and audit infrastructure. MemoryHub is self-hosted on Kubernetes, which gives organizations control but also means they bear the operational burden. For teams that do not want to run memory infrastructure, CMA's managed offering is a significant advantage.

**Console integration.** Memory updates surface in the Claude Console as session events, giving developers a visual trace of "what an agent learned and where it came from." MemoryHub has API-level audit trails but no visual console for memory inspection. Observability tooling is a gap.

## 5. What We Do That They Can't

Capabilities that are structurally impossible or deeply impractical in a filesystem-based, platform-coupled architecture.

**Semantic search.** MemoryHub uses pgvector embeddings (all-MiniLM-L6-v2, 384-dim), optional cross-encoder reranking (ms-marco-MiniLM-L12-v2), and RRF blending of rerank ranks with focus cosine ranks. CMA Memory's filesystem supports grep-style text search but has no semantic similarity capability. An agent looking for "memories about production rollback procedures" will not find a file about "reverting deployed services to the previous version" unless the exact keywords overlap. This gap grows with memory corpus size — keyword matching degrades as the number of memories scales, while embedding-based search maintains relevance.

**Structured memory relationships.** Four relationship types (derived_from, supersedes, conflicts_with, related_to) create a graph over the memory tree. An agent can ask "what does this memory conflict with?" or "what was the rationale chain behind this decision?" CMA's files have no structural relationships beyond directory hierarchy. Representing "Memory A conflicts with Memory B" requires either encoding it in file content (brittle, model-dependent) or not representing it at all.

**Contradiction detection and resolution.** MemoryHub's `report_contradiction` accumulates staleness signals against specific memories, and `conflicts_with` relationships link contradictory memories with merge metadata. CMA Memory has no mechanism for an agent to flag that it simultaneously "knows" two conflicting facts in different files. Without a query engine, detecting contradictions requires reading all potentially relevant files — a combinatorial problem that gets worse with scale.

**Inline curation pipeline.** MemoryHub's `write_memory` runs a three-tier inline curation pipeline: regex-based secrets/PII detection, embedding-based dedup (reject >0.95, flag 0.80-0.95), and configurable user rules. CMA Memory has no write-time curation — if an agent writes sensitive data to a file, that data persists until someone notices and redacts it. The announcement mentions the ability to "redact content from history," but this is reactive (clean up after the fact) rather than proactive (prevent sensitive data from being stored).

**Six scope tiers with hierarchical governance.** User, project, campaign, role, organizational, enterprise — each with distinct visibility rules and RBAC enforcement at the SQL level. CMA offers per-store scopes (read-only, read-write), which is sufficient for simple sharing but does not express "this memory is visible to all agents in the organization but only writable by project leads" or "this enterprise policy memory overrides any conflicting project-level memory."

**Cross-platform interoperability.** Any MCP client can connect to MemoryHub: Claude Code, kagenti, LangGraph, LlamaStack, custom agents. An enterprise using three different agent frameworks shares one memory service. CMA Memory serves Claude Managed Agents and nothing else.

**Budget-aware retrieval.** Three response modes (full, stub, index), `max_response_tokens` soft cap with graceful degradation to stubs, weight-based content control, `pivot_suggested` signal when the query drifts from the session focus. CMA's filesystem retrieval has no budget negotiation — agents read entire files or don't.

**Version history with full chain.** `update_memory` creates a new version while preserving the full version chain, accessible via `read_memory` with paginated `include_versions`. CMA Memory offers version rollback ("roll back to an earlier version"), which implies version history exists, but the filesystem model likely stores versions as file snapshots rather than as a queryable chain with diff semantics.

**Cache-optimized memory assembly.** Epoch-based stable ordering maximizes KV cache hit rates when memories are injected into prompts. The filesystem model provides no cache optimization for memory injection into context windows.

## 6. Implications for Our Publications

### Blog Post ("Everyone Is Trying to Own Agent Memory")

This is the announcement the blog was waiting for. The model provider — the company that builds the models agents run on — has built memory into its own platform. If the blog's thesis is "everyone is trying to own agent memory," Anthropic is the strongest possible example because they have the deepest moat: model-memory co-optimization that no external service can replicate.

The blog's core argument — that platform-native memory creates switching costs and vendor lock-in — is precisely illustrated by CMA Memory. An enterprise that accumulates months of agent memory in CMA's stores faces two switching costs: the data migration (files are exportable, so this is manageable) and the capability loss (the model-memory co-optimization disappears entirely on any other platform, and this is not portable). The second cost is new and unique to Anthropic's announcement — it is not just about data lock-in but about capability lock-in.

The "bridges not moats" conclusion is strengthened. CMA Memory is the deepest moat yet — the model itself is tuned to its own memory layer, creating a feedback loop that gets stronger over time as the model gets better at using its own memory system. This is the argument for protocol-level memory interoperability made concrete: if memory is platform-coupled and model-optimized, switching platforms means losing not just your data but your model's learned memory behaviors.

**Recommendation**: Add Anthropic as the culminating example in the "follow the money" or "moat thesis" section. This is the capstone data point: the model provider building memory into its own platform with model-level optimization that no external service can replicate. Something like: "Anthropic's Memory on Claude Managed Agents, announced April 23, goes further than any previous entrant: the model itself is tuned to produce better memories when using Anthropic's memory layer, creating a co-optimization that is structurally unavailable to external memory services. The switching cost is not just data portability — it is the loss of a model capability." Keep it to 2-3 sentences; the blog argues about the pattern, and Anthropic is the sharpest example, not the only one.

### arXiv Paper (Agent Memory Survey)

**Taxonomy (Section 3).** CMA Memory introduces a new architectural pattern: filesystem-as-memory-store. This sits between conversation buffer (Section 3.1) and structured key-value (Section 3.4) in the current taxonomy. The model reads and writes files using standard bash tools, imposing its own structure through file naming and content organization. The taxonomy should acknowledge this as a distinct pattern — it is not key-value (there are no typed fields, no schema), not a document store (no indexing, no query language), and not a conversation buffer (memories persist across sessions). It is closest to a project knowledge base or workspace context pattern, but one where the model is the sole author and curator.

**Model-memory co-optimization (Section 7 or Open Problems).** The paper should note the emergence of a new competitive dynamic: model providers tuning their models for their own memory layers. This has implications for the "external memory service" architectural position (MemoryHub's position) — external services must compete not just on features but against a model that was purpose-trained for a different memory system. This dynamic is worth a paragraph in the Open Problems section or Section 7.2 (where external services are discussed). The question is whether model-memory co-optimization produces a large enough advantage to make external services uncompetitive, or whether the platform-agnostic benefits (cross-platform, multi-model, governed) outweigh the co-optimization advantage.

**Architectural placement (Section 7 draft).** CMA Memory represents a fourth architectural position alongside harness-native (Cloudflare), external service (MemoryHub), and orchestration-mediated (Multica): **provider-native** memory, where the model provider owns the memory layer. This is distinct from harness-native because it is not a developer framework — it is a managed service tied to a specific model. The provider-native position has unique properties: the model can be co-optimized with the memory layer, the provider handles infrastructure, and the memory is structurally coupled to the model's capabilities. Add as a case study in Section 7.1 with cross-reference to the provider lock-in discussion.

**Filesystem-based memory as a pattern.** The filesystem approach is worth noting in the taxonomy as an under-explored design point. Files are maximally portable, require no specialized tooling, and leverage the model's existing code execution abilities. The limitations (no semantic search, no relationships, no schema) are real, but the simplicity advantage is genuine. A footnote or brief discussion in Section 3 would place this alongside the other storage paradigms (relational, vector, graph, key-value, document).

**Recommendation**: Add CMA Memory to the taxonomy as an example of filesystem-based memory in Section 3, discuss the model-memory co-optimization dynamic in Section 7 or Open Problems, and cite the provider-native architectural position alongside harness-native and external service. Two to three paragraphs total across the paper.

## 7. Strategic Assessment

Anthropic has done the most strategically significant thing any company in the agent memory space could do: the model provider has vertically integrated memory into its own platform and co-optimized the model for its own memory layer. This creates a feedback loop — better memory makes the model more effective, more effective models make the platform more attractive, more users generate more memory data to improve the model further — that external services cannot replicate.

And yet, this is precisely the scenario that makes MemoryHub's thesis stronger, not weaker. CMA Memory is the ultimate platform-coupled memory: it works with Claude Managed Agents and nothing else. The model-memory co-optimization that is its greatest strength is also its greatest limitation — it only works if you are all-in on Claude. An enterprise running Claude for some agents, open-source models for others, and LangGraph or LlamaStack for specialized pipelines needs memory that works across all of them. CMA Memory cannot serve that enterprise. MemoryHub can.

The filesystem-based approach is a deliberate simplicity choice that leverages Claude's existing strengths — the model is already good at reading and writing files, so make memory file-shaped. This is a smart short-term play that trades structural richness for immediate usability. It works well when the memory corpus is small, the number of agents is manageable, and the governance requirements are light. It starts to strain when the corpus grows (no semantic search), when many agents write concurrently (filesystem concurrency is harder than database concurrency), when governance matters (no inline curation, no scope hierarchy beyond read/read-write), and when the organization needs to answer questions like "what do all our agents believe about X, and are any of those beliefs contradictory?"

The customer results — 97% error reduction at Rakuten, 30% faster verification at Wisedocs — are validation for the entire agent memory category. They demonstrate that cross-session learning produces real, measurable improvements in agent performance. MemoryHub should cite these results (attributed to the category, not claimed for ourselves) as evidence that governed agent memory is infrastructure worth building.

The announcement changes the competitive landscape. The question is no longer "should agents have persistent memory?" — the model provider has answered yes. The question is "should memory be owned by the model provider, or should it be a platform-agnostic service?" MemoryHub's answer — memory follows the protocol, not the platform — is now a sharper and more consequential position than it was yesterday.
