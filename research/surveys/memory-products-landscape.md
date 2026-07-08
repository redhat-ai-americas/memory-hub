# Memory Products Landscape

**Abstract:** Consolidated survey of the agent-memory product landscape and MemoryHub's position in it. Covers external analyses (Every's field report, Gartner context graphs, Sakhatsky's graph-database critique) and direct product comparisons (Neo4j Agent Memory, MemPalace, OpenViking, Perplexity Brain), with per-product takeaways, comparison conclusions, and the issues each analysis produced.

Consolidated 2026-07-08 from: `research/surveys/agent-memory-landscape-2026.md`, `research/comparisons/mempalace-comparison.md`, `research/comparisons/openviking-comparison.md`, `research/comparisons/perplexity-brain-analysis.md`. Originals removed; full text in git history.

**Status:** Landscape snapshot as of mid-2026. Product versions, star counts, feature sets, and performance claims are date-sensitive and will drift — verify before citing externally.

**Note on scopes:** MemoryHub's canonical scope roster is **user / project / campaign / role / organizational / enterprise**. Some source documents described 4- or 5-scope variants or imported foreign scopes (agent/session/global); those references are corrected here. Competitor scope models are reported as-is.

---

## Part 1: External Analyses

### 1.1 Every's "Plus One" Field Report (May 2026)

*"We Gave Every Employee an AI Agent. Here's What We're Doing Differently Now"* — Brandon Gell (COO) and Willie Williams (Head of Platform), Every. Field report on deploying personal AI agents company-wide, and the pivot to shared team agents.

**Key findings:**

- **Platform instability destroyed accumulated context.** Built on OpenClaw ("powerful and inherently unstable"); harness updates risked "forgetting everything you've told them and trained them to do." Agent knowledge was coupled to a specific harness version. Failures included agents sending "Terminated" messages, denying live app connections, and one agent (Zosia) interjecting in Slack after months of silence because she was "inevitable, apparently."
- **Maintenance burden on individuals.** "Every time an agent broke, the person it belonged to had to fix it themselves." "For every tinkerer, there are a lot of people who want the benefits of an agent without the obligation of having to manage and mend it." The personal-agent model failed the non-tinkerer majority.
- **Context isolation.** "A one-on-one employee only builds up context on your work, often missing out on what the rest of the organization is doing." Personal agents could not "absorb information from across the company to accrue tribal knowledge" by construction.
- **Knowledge fragility.** "A personal agent's value is tied to whomever trained it, and disappears if that employee leaves." No continuity mechanism.
- **Their pivot:** shared team agents with defined jobs (e.g., a weekly engineering skill spanning Intercom → GitHub → Linear → Slack), exploring Claude Managed Agents, keeping per-user connections inside shared agents. Open questions: permissions for shared agents, per-department vs. company-wide agents, superagent vs. specialist roster.

**Mapping to MemoryHub** (some capabilities design-stage at time of writing — entity extraction #170 Phase 2, extraction pipeline #240, conversation persistence #168, governed compaction #169; scope hierarchy, RBAC, contradiction detection, versioning, and provenance shipped):

- Context isolation → scope hierarchy (user/project/campaign/role/organizational/enterprise). Team agents read at project/organizational scope; individual contributions persist at user scope.
- Knowledge fragility → externalized, governed memory: project/org/enterprise-scoped knowledge survives user churn; versioning + provenance record who contributed what; GDPR Art. 17 erasure applies to user scope.
- Shared-agent permissions → RBAC with operational scopes (memory:read/write/admin) crossed with access tiers; client_credentials + scoped JWT claims.
- Platform instability → harness-agnostic design: memory substrate is independent of the execution layer, so switching harnesses does not forfeit knowledge.
- Multi-user conflicting instructions → contradiction detection in the curation subsystem.
- Compliance (EU AI Act Art. 12 audit trails, GDPR erasure) — not Every's pain point, but the regulated-enterprise differentiator.

**Gaps the report surfaced (issues filed):**

1. Memory promotion/graduation workflow, user → project/org, with provenance preserved (#235)
2. Team agent identity model with delegated user access (token_exchange / RFC 8693 pattern undocumented) (#236)
3. Behavioral memory as a first-class, restorable memory type — reconstruct an agent from memory alone (#237)
4. Workflow checkpoint state for recurring automated tasks (distinct from thread persistence #168) (#238)
5. Convergent learning — near-duplicate detection plus merge-and-strengthen when multiple users teach the same lesson (#239)

**Strategic implications:** The industry is moving from personal agents to team agents; model labs are absorbing the harness layer, leaving the memory/context layer open; regulated enterprises need self-hosted memory; Claude Managed Agents and MemoryHub are complementary (execution vs. governed memory); both superagent and specialist-roster topologies work on the same scope model.

### 1.2 Gartner Context Graphs (via Atlan, March/April 2026)

*"Gartner on Context Graphs: Top Insights, Capabilities & Implementation Recommendations for 2026"* — Emily Winks, Atlan.

**The distinction:** Knowledge graphs are the semantic layer (entities, ontologies — what things ARE). Context graphs are the procedural layer (decision traces, workflow logic, tribal knowledge — how things HAPPEN). Context graphs augment, not replace, knowledge graphs. Gartner predicts 50%+ of AI agent systems will use context graphs by 2028.

**MemoryHub is a context graph:**

- Decision traces ("searchable, replayable records of how situations have been handled before") = rationale branches + versioning + provenance.
- Institutional memory gap = the scope hierarchy: organizational-scope memories encode how the org works, project-scope how teams work.
- Continuous learning = versioning, contradiction detection, curation.
- Gartner's "four pillars" (guardrails, observability, evaluation, self-learning) map to provenance/audit/EU AI Act posture, curation, and the extraction pipeline (#240).

| Gartner capability | MemoryHub status (at time of analysis) |
|---|---|
| Capture decision traces | Implemented (rationale branches, versioning, provenance) |
| Context-aware lineage graphs | Partial (relationships, parent/child); #170 enriches |
| AI observability | Implemented (audit trails, EU AI Act compliance) |
| Continuous learning | Partial (curation); #240 completes |

**Naming:** In Gartner's framing, "agent memory" (experiences, decisions) is correct for MemoryHub; "agent knowledge" would misposition it as a knowledge graph.

### 1.3 The Case Against Graph Databases (Sakhatsky, April 2026)

*"You Probably Don't Need a Graph Database for Your Knowledge Graph"* — Michael Sakhatsky. Challenges the chain "institutional knowledge → ontology → RDF → graph database."

**Argument:** Graph databases excel at one narrow thing — recursive traversal of unknown depth. RDBMS recursive CTEs handle known-depth traversal. Three conflated senses of "relationships matter": existence, traversal, semantics — graph DBs handle the first two; semantics is logic, not graph theory. Graph DBs store A-Boxes (facts) but not T-Boxes (rules); SPARQL/Cypher/Gremlin can't infer. Path-based security is non-monotonic and messy. Alternative: expose existing enterprise rules via MCP; use Datalog/Prolog where inference is needed.

**Why this validates MemoryHub's PostgreSQL + pgvector choice over Neo4j:**

- Memory-tree traversal is shallow and bounded — recursive CTEs suffice.
- Scope isolation at the SQL level is clean; no path-traversal visibility ambiguity.
- No extra graph-DB operational dependency (PostgreSQL ships with OpenShift).
- Vector similarity + governed explicit relationships + scope-based access beats Cypher-over-property-graph for agent memory.

**Design guardrails for #170 (graph-enhanced memory):** DO pursue richer edge metadata, shallow-tree traversal (2–3 hops), entity extraction for cross-referencing. DO NOT build a general graph query engine, Cypher-like syntax, or Neo4j analytics (centrality, community detection) — no "Neo4j lite" drift.

---

## Part 2: Product Comparisons

### 2.1 Neo4j Agent Memory (neo4j-labs/agent-memory, v0.2–0.3)

**What it is:** The most direct open-source competitor at the time of review. Graph-native memory with three memory types: short-term (conversations), long-term (knowledge graph, POLE+O model), reasoning memory (traces and tool usage).

**They have, MemoryHub doesn't (yet):** automatic entity extraction pipeline (spaCy → GLiNER → LLM); reasoning traces as first-class memory; short-term/conversation memory (#168 designed); 8+ framework integrations (LangChain, PydanticAI, Google ADK, Strands, CrewAI, LlamaIndex, OpenAI Agents, Microsoft Agent); entity resolution/dedup strategies; an eval harness for labelled regression tests.

**MemoryHub has, they don't:** scope hierarchy with RBAC (they have only `user_identifier` multi-tenancy); contradiction detection and curation; compliance posture (their `:TOUCHED` audit edges are Labs-experimental); no graph-DB dependency; governed compaction (#169); versioned, branching memory trees with provenance (theirs is flat entities with edges); campaign system for cross-project sharing.

**Conclusion:** Neo4j Agent Memory is graph-first and happens to support agents; MemoryHub is governance-first and happens to use graph structures. They optimize traversal expressiveness; MemoryHub optimizes access control, provenance, compliance — the right priorities for regulated enterprises.

### 2.2 MemPalace (v3.5.0, v4.0.0-alpha imminent; researched 2026-07-08 vs. MemoryHub v0.10.0)

**What it is:** Local-first AI memory for individual developers using AI coding tools (Claude Code, Cursor, Codex CLI). Stores verbatim conversation history, retrieves via semantic search, organized by a spatial metaphor (wings/rooms/drawers, Zettelkasten-inspired). 57k GitHub stars, MIT, Python 3.9+. Philosophy: store everything verbatim, retrieve associatively, nothing leaves your machine unless opted in.

**Memory model:** flat drawers within a spatial hierarchy; verbatim transcripts, never summarized; temporal entity-relationship graph with validity windows (SQLite); agent diary system (each specialist agent gets its own wing).

**Differentiators over MemoryHub:**

- Verbatim storage with published, reproducible benchmarks: 96.6% R@5 on LongMemEval, 98.4% with the hybrid pipeline (keyword boosting, temporal-proximity boosting, preference-pattern extraction) — no LLM required.
- Local-first, zero-API: on-device embeddings (embeddinggemma-300m multilingual, all-MiniLM-L6-v2), GPU Docker variant.
- Pluggable storage backends: ChromaDB (default), SQLite, Qdrant, pgvector; v4 adds LanceDB and PostgreSQL with pg_sorted_heap.
- IDE auto-save hooks for Claude Code/Cursor/Codex CLI; 35 MCP tools; massive community (7.4k forks, active Discord).

**MemoryHub differentiators over MemPalace:** multi-tenant RBAC (OAuth 2.1, JWT, scope isolation, tenant_id, OBO); governance and audit (structured audit logging, actor_id/driver_id, quarantine/restore/hard-delete, legal hold, spill response); curation pipeline (regex scanning, embedding dedup, spaCy NER POLE+O entity extraction, PII blocking, rules engine) and autonomous curation agents (Fact Checker, Trace Reviewer, Curator, Statistician on Valkey queues with leader election); memory tree with rationale/provenance/checkpoint branches and weight-based injection; governed conversation threads with retention, extraction, fork/handoff, A2A compatibility; temporal awareness (`relevant_until`, temporal classifier, expiry filtering); content-type classification (experiential/knowledge/behavioral) with graduation and `reconstruct`; scope hierarchy (user < project < campaign < role < organizational < enterprise) with promotion; campaign framework; pattern surfacing (`pattern_signals`); dashboard UI (React + PatternFly 6); cross-encoder reranking with RRF; Kubernetes-native deployment; typed PyPI SDK; contradiction detection; workflow checkpoints.

**Head-to-head conclusions:** MemPalace wins on published retrieval proof, privacy-sensitive solo use, and community maturity; MemoryHub wins on multi-user/RBAC, entity extraction (shipped vs. their v4 roadmap), and agent-friendly compact MCP profile (3 tools vs. their 35); storage/embedding tradeoffs depend on context; knowledge-graph capability is comparable on different substrates.

**Conclusion:** Not really competitors — MemPalace is a developer productivity tool (Zettelkasten for your AI pair programmer); MemoryHub is enterprise agent infrastructure. A cluster could run both. Indirect risk: MemPalace's Qdrant/pgvector backends already support namespace isolation; lightweight multi-user features plus 57k stars and MIT could make it a "good enough" team choice before governance pain is felt.

**Gaps worth closing (from MemPalace):** publish LongMemEval-comparable retrieval benchmarks; evaluate keyword/hybrid search fallback; add time-decay/recency weighting to search scoring; consider IDE auto-save ergonomics (vs. #240's explicit integration); local/offline embedding fallback for air-gapped environments.

### 2.3 OpenViking (ByteDance Volcano Engine, Jan 2026; analyzed 2026-04-27)

**What it is:** Open-source "context database" for AI agents ([github.com/volcengine/OpenViking](https://github.com/volcengine/OpenViking)), AGPL-3.0, ~23k stars. From the Viking team (prior art: VikingDB since 2019, Viking Knowledge/Memory Base commercial products, MineContext). A productized memory stack that has been opened. Red Hat Developer published an OpenShift deployment guide ([Fridman, 2026-04-23](https://developers.redhat.com/articles/2026/04/23/deploy-openviking-openshift-ai-improve-ai-agent-memory)).

**Memory model — filesystem-as-API:** everything (memories, resources, skills, sessions) is a `viking://` URI in a hierarchical namespace (`resources/{project}`, `user/{user_id}`, `agent/{agent_id}`, `session/{user_space}/{session_id}`). Standard verbs (`ls`, `mkdir`, `rm`, `mv`, `tree`, `stat`, `read`, `grep`, `glob`) plus semantic ops (`abstract`, `overview`, `find`, `search`, `link`, `unlink`). Three context types — Resource (static knowledge), Memory (agent-learned, eight subcategories with explicit merge rules), Skill (auto-converted to MCP tools). The bet: LLMs already understand filesystem semantics.

**Notable engineering:**

- **L0/L1/L2 tiered loading:** `.abstract.md` (~100 tokens, vector filtering) / `.overview.md` (~2k, rerank/navigation) / originals on demand — parallel to Project Think's loadable providers and MemoryHub's `mode: "index"`.
- **Dual-layer storage:** vector index (URIs, dense+sparse vectors, scalar fields, no content) over AGFS content store (localfs/s3fs/memory; Rust rewrite RAGFS). "The index is reconstructible; the content is sacred." Design rule: "Better to miss a search result than to return a bad one."
- **Two-stage retrieval:** `find()` fast single-query; `search()` runs an IntentAnalyzer (0–5 typed queries) then a HierarchicalRetriever tree-walk with score propagation (`final = 0.5 * embedding + 0.5 * parent_score`) and three-round convergence. More sophisticated than flat top-k.
- **Two-phase session commit** with idempotent async memory extraction and a structured dedup matrix: per-candidate `skip`/`create`/`none`, per-existing-item `merge`/`delete` — the LLM answers structured questions, not a similarity threshold.
- **Crash-safe path locks + RedoLog:** POINT/SUBTREE lock modes, fencing tokens with TOCTOU double-check, livelock prevention, stale-lock expiry, lifecycle locks with refresh loops. Real distributed-systems engineering for a store without transactions.
- **Three-layer envelope encryption:** Root Key (KMS) → per-account HKDF-derived Account Key (never stored) → per-write AES-256-GCM File Key. KMS providers: local file, HashiCorp Vault Transit, Volcengine KMS.
- **Multi-tenancy:** account/user/agent boundaries, ROOT/ADMIN/USER roles, `api_key` and `trusted` (gateway-header) auth modes.
- **Observability:** Prometheus `/metrics` with allowlisted `account_id` labels (cardinality discipline), observer and stats APIs.

**Validations of MemoryHub decisions (independent convergence):** tiered context loading is structural (third independent appearance); storage/index separation (source-of-truth vs. rebuildable index); layered multi-tenant identity boundaries — their account/user/agent triple parallels MemoryHub's user/project/campaign/role/organizational/enterprise scope hierarchy, and both show a single `tenant_id` is insufficient; memory typing beyond "vector blob"; skills as first-class context; compaction as first-class infrastructure.

**Divergences:** filesystem-as-API vs. typed-graph-as-API (intuitive mental model vs. expressible governance); per-account isolation vs. cross-scope read with authorization-aware filtering and `omitted_count` transparency; implicit governance (tenant isolation, encryption, metrics) vs. explicit governance (per-memory audit, contradiction detection, inline curation); HTTP-only client (no MCP server at release) vs. MCP-native; Volcengine-leaning defaults (Doubao, doubao-seed-rerank, VikingDB, Volcengine KMS — though OpenAI/GLM/Kimi/Codex/Ollama are supported) vs. provider-neutral.

**What MemoryHub does that they can't (yet):** cross-scope authorized search with omission transparency; branch-typed memory (rationale vs. provenance as semantically distinct — their relations are flat link-with-reason); lifecycle contradiction detection; MCP-native interface; RBAC enforced at the SQL level (defense-in-depth).

**Borrow:** at-rest envelope encryption pattern (envelope + pluggable KMS + magic-number backward compat), structured 2-axis dedup decisions, tree-sitter AST skeleton extraction for code resources, score-propagation retrieval idea, Prometheus metrics with cardinality discipline. **Don't borrow:** the filesystem URI shape or account-isolation tenancy (both incompatible with the typed-graph, cross-scope model).

**Framing:** Red Hat's guide calls it "an experiment worth running, not a production dependency" — fair, and not to be contradicted. OpenViking is the strongest external memory service seen so far that ships as a daemon; it is MemoryHub's first real peer, and its existence strengthens the platform-memory-as-its-own-tier thesis. Strategic takeaway: articulate *why* typed-graph + cross-scope authorization is right for governed enterprise memory rather than treating it as obvious, since the filesystem model can win on "simpler mental model" even when requirements favor governance. For publications: cite in the hybrid-architectures section (three-context-type, L0/L1/L2), name filesystem-as-memory-API as an emergent pattern (alongside Letta and the markdown-files convergence), cite the account/user/agent model as shipped multi-tenant access control, and quote the "better to miss" heuristic.

### 2.4 Perplexity Brain (announced June 18, 2026)

**What it is:** Memory layer for Perplexity's "Computer" agent ([blog post](https://www.perplexity.ai/hub/blog/self-improving-memory-for-agents)). Research Preview, Max ($200/mo) and Enterprise Max only. Distinguishing framing: memory about the *agent's work* (what it did, what worked, what failed, what the user corrected), not the user's preferences — agent performance improvement, not personalization.

**Architecture:**

- **Context graph:** after each task, records connectors used, sources validated, user corrections, failed attempts, and relationships between projects/decisions/files/sources. Fed by sessions, connectors, and files.
- **LLM wiki:** structured pages for entities/concepts in the user's work context, auto-loaded into the agent sandbox at session start. No published schema, format, or API.
- **Overnight synthesis:** batch loop — execute → record → synthesize overnight (extract patterns, update wiki) → load next session. Coverage calls it "a micro fine-tuning loop disguised as a memory feature"; the model itself doesn't change, the harness context improves.
- **Automatic injection** of relevant subgraph context at task start; **source traceability** with per-memory inspect and delete.

**Performance claims (first-party, unverified):** +25% answer correctness on previously-seen tasks, +16% recall, −13% cost per task requiring historical context. Gains concentrate on context-dependent tasks; compound over time. Not published: storage tech, embedding strategy, wiki schema, token budgets, retrieval algorithm, retention, privacy architecture, multi-user support.

**Convergences with MemoryHub:** graph over flat list (tree + branch types serve the same provenance purpose); source traceability (= provenance/rationale branches); harness-layer intelligence ("intelligence shifts from the model layer to the harness layer" — MemoryHub's thesis for regulated environments); automatic injection over manual retrieval (= fipsagents `self.memory` zero-tool-token prefix injection); correction-driven learning (= `report_contradiction` + curation).

**Divergences:** batch overnight synthesis vs. real-time write/retrieve; cloud SaaS vs. self-hosted data sovereignty; work memory vs. governed memory — Brain has no visible multi-tenant or scope-isolation story vs. MemoryHub's user/project/campaign/role/organizational/enterprise hierarchy with curation, RBAC, versioning; lossy wiki synthesis vs. versioned tree (`isCurrent` flags preserve auditable evolution); personal-only vs. team/organizational sharing (Every's report documents why personal-only fails).

**Gaps Brain highlights for MemoryHub:** automated synthesis/compaction — Brain is production proof for ACE (#169) and raises its urgency; connector/document ingestion beyond agent traces (beyond #240's scope); a feedback-loop measurement framework tying memory to downstream task quality.

**Positioning:** Brain validates agent memory as a distinct layer — but as a consumer/prosumer SaaS feature, not enterprise infrastructure. MemoryHub's differentiators are the usual ones against cloud memory: data sovereignty, scope isolation, editorial governance, audit trails, deployment flexibility. If overnight synthesis demonstrably improves agents, it creates demand that #169/#240 answer self-hosted.

**Key quotes:** "Most AI memory systems remember what *you* said. Brain remembers what *it* did." / "A mediocre model with a great Brain could outperform a superior model with no memory." / "Intelligence shifts from the model layer to the harness layer."

**References:** [Perplexity Blog](https://www.perplexity.ai/hub/blog/self-improving-memory-for-agents), [MarkTechPost](https://www.marktechpost.com/2026/06/18/perplexity-launches-brain/), [Decrypt](https://decrypt.co/371584/perplexity-ai-agent-brain), [ExplainX](https://explainx.ai/blog/perplexity-brain-computer-memory-system-2026), [FourWeekMBA](https://fourweekmba.com/perplexity-brain-self-improving-agent-memory/).

---

## Synthesis

Three independent 2026 sources (Every, Gartner, Sakhatsky) converge: enterprise agents need governed, externalized memory with explicit relationships — but the path there is not "buy a graph database." Every's pivot to shared team agents validates the scope hierarchy; Gartner's context-graph definition matches MemoryHub's decision-trace architecture; Sakhatsky validates PostgreSQL + pgvector over Neo4j. Product comparisons segment the market: MemPalace owns solo-developer local recall, OpenViking is the first true open-source platform-memory peer (filesystem paradigm, tenant-isolation governance), Perplexity Brain proves demand for self-improving synthesis as SaaS, and Neo4j Agent Memory shows what graph-first-without-governance looks like. MemoryHub's defensible position throughout: governance-first, self-hosted, cross-scope-authorized memory for regulated enterprises.

**Issues filed from these analyses:**

| Issue | Title | Source |
|---|---|---|
| #235 | Memory promotion workflow (user → project/org scope) | Every |
| #236 | Team agent identity model with delegated user access | Every |
| #237 | Behavioral memory for agent reconstruction | Every |
| #238 | Workflow checkpoint state for recurring tasks | Every |
| #239 | Convergent learning to consolidate duplicate memories | Every |
| #240 | SDK extraction pipeline for agent trace observation | Neo4j comparison, Gartner |

#170 (graph-enhanced memory) was prioritized to near-term with Sakhatsky's guardrails applied. Perplexity Brain validates ACE (#169) and #240 urgency with production metrics (+25% correctness, −13% cost on context-dependent tasks).
