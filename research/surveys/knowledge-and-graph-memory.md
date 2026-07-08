# Knowledge and Graph Memory: Consolidated Research

**Abstract**: This document consolidates MemoryHub's research on structured knowledge for AI agents: graph-based agent memory (systems, databases, academic work, architecture patterns, governance, and the PostgreSQL question), the knowledge-graph vs. context-graph distinction that anchors the MemoryHub/RetrievalHub strategy, the Karpathy llm-wiki phenomenon and the compiled-knowledge product landscape, Google's Open Knowledge Format as a semantic-layer interchange spec, and ontology-aware contextualization of memories in terminology-divergent enterprises. The through-line: the industry has split "what things ARE" (semantic layer / knowledge graphs) from "how things HAPPEN" (procedural layer / agent memory), governance is the unclaimed differentiator on both sides, and MemoryHub's memory graph can evolve incrementally on PostgreSQL toward state-of-the-art graph memory.

**Consolidated 2026-07-08 from:**
- research/surveys/graph-memory-survey.md (April 2026)
- research/comparisons/knowledge-graphs-vs-context-graphs.md
- research/surveys/llm-wiki-landscape.md (April 2026)
- research/surveys/ontology-contextualization.md (June 2026)
- research/comparisons/okf-open-knowledge-format.md (June 2026)

Originals removed; full text in git history.

**Status**: Partially superseded. The graph-memory evolution recommendations (Section 6) have been taken up by docs/design/graph-enhanced-memory.md (issue #170), which is now the authoritative design; treat Section 6 as background and rationale. The knowledge/semantic-layer positioning feeds planning/knowledge-layer.md (RetrievalHub) and docs/design/knowledge-compilation.md. Market snapshots (Sections 3, 7–8) reflect early-to-mid 2026 and will age. Terminology notes: sources predate full canonical scope vocabulary — see flags inline.

---

## 1. The Core Distinction: Knowledge Graphs vs. Context Graphs

When someone says "we need to give our AI agents knowledge," two different infrastructure conversations collapse into one. Both involve graphs, both get filed under "AI grounding," but they solve different problems. **Knowledge graphs encode what things ARE. Context graphs encode how things HAPPEN.** An agent needs both, and they are not the same system.

A **knowledge graph** is a structured representation of domain entities and their relationships — the ontology: concepts, properties, constraints. "Customer places Order, Order contains Product, Product belongs_to Category." These are relatively static domain facts; deleting every operational record would leave the ontology valid. Standards: RDF, OWL, SPARQL, and the labeled property graph model (Neo4j). Gartner calls this the "semantic layer."

A **context graph** captures how an organization actually operates — decisions, workflows, reasoning traces, and institutional memory accumulated through experience: "We approved a 20% discount for Acme because their renewal was at risk and the regional VP signed off on 2026-03-15." "User prefers concise responses; learned over 12 interactions." Context graphs answer "how was a similar situation handled last time?", "why was this exception approved?", "what tribal knowledge exists about this workflow?". Gartner defines context graphs as purpose-built infrastructure for agentic AI, predicting more than 50% of AI agent systems will use them by 2028, and is explicit that they augment rather than replace knowledge graphs.

The practical test: **is this fact about the domain, or about a decision/experience?** If the fact would survive deleting all operational history ("Products belong to Categories"), it's domain knowledge — knowledge graph. If it emerged from operational history ("we stopped recommending Category X after the Q3 complaints"; "last time we bulk-discounted this line, margin dropped 12%"), it's experiential memory — context graph. The knowledge graph gives an agent *understanding* (vocabulary, classification, entity structure); the context graph gives it *judgment* (precedent, preferences, rationale). The strongest systems combine both.

In canonical MemoryHub terms this maps roughly to the content_type split: knowledge-graph material is `knowledge` content; context-graph material is `experiential` and `behavioral` content. (Source used "experiential/decisions" framing without the canonical trichotomy — mapping is ours, flagged.)

### The four levels of agent memory (Mastra / Alex Booker framework)

All four are context-graph concerns — none require a knowledge graph, and having one gives you none of them:

1. **Conversation history** — send a window of previous messages. Works for 10–20 messages, then context drifts; no cross-session persistence, no selectivity.
2. **Working memory** — a structured scratch pad with predefined fields (user name, goal, stated preferences) carried through the session. Limitation: fields must be predefined, which isn't very agentic.
3. **Semantic recall** — vector search over past interactions, selectively injecting relevant history. This is where the KG/context-graph conflation is most tempting: the embedding+vector infrastructure is shared with knowledge-graph RAG, but the *content* searched is experiential, not ontological.
4. **Observational memory** — background Observer and Reflector agents continuously compress raw messages into dense, prioritized, temporally annotated observations, further compressed over time. Pure context-graph infrastructure; models institutional memory.

Also noted from this thread: Michael Sakhatsky's "You Probably Don't Need a Graph Database for Your Knowledge Graph" (April 2026) — a critique of the assumption chain from ontology to graph database, arguing for rules engines and logic programming in some cases.

---

## 2. Graph Memory for Agents: Concepts and Evidence

Vector memory retrieves facts by semantic similarity but loses *structure* — it cannot answer "what tool preferences does the user have, and which conflict with organizational policy?" because that requires traversing relationships, not computing distances. Graph memory encodes entities, relationships, and properties as first-class objects, enabling multi-hop reasoning, temporal reasoning ("preferred Docker in 2024, switched to Podman in 2025"), and contradiction detection across scopes.

The field's overlapping terms, roughly hierarchical:

- **Knowledge graphs**: semantic networks of typed entities/relationships, often ontology-driven; relatively static.
- **Memory graphs**: knowledge graphs optimized for agent persistence and temporal awareness — tracking how facts change, maintaining provenance, supporting both prescribed and learned ontology. Graphiti's "temporal context graphs" are the canonical example. (Note: in canonical MemoryHub usage, "memory graph" = the memory tree plus typed relationships — narrower than this survey usage; flagged.)
- **Property graphs**: the technical storage model (nodes/edges with arbitrary key-value properties: Neo4j, FalkorDB, Memgraph, Kuzu) underlying the semantic layers above.
- **Temporal knowledge graphs**: every fact has a validity window; Graphiti's bi-temporal model distinguishes when a fact was true in the world from when the system learned it.
- **Hypergraphs**: edges connecting more than two nodes, preserving n-ary relationships (MAGMA's orthogonal semantic/temporal/causal/entity graphs).

### Benchmark evidence

Mem0's 2026 State of AI Agent Memory report quantifies the vector-vs-graph tradeoff on LOCOMO:

| Approach | Accuracy (LOCOMO) | p95 Latency | Tokens/Query |
|----------|-------------------|-------------|--------------|
| Full context | 72.9% | 17.12s | ~26,000 |
| Mem0g (graph+vector) | 68.4% | 2.59s | ~1,800 |
| Mem0 (vector only) | 66.9% | 1.44s | ~1,800 |
| RAG baseline | 61.0% | 0.70s | — |

On the more demanding **LongMemEval** (ICLR 2025, arXiv:2410.10813 — 500 questions across information extraction, multi-session reasoning, temporal reasoning, knowledge updates, abstention), structured/graph systems dominate. Top scores as of April 2026: Observational Memory (Mastra) 94.87% with gpt-5-mini; MemMachine 93.0% with gpt-4.1-mini; Hindsight 91.4%; EverMemOS 83.0%; Mem0 49.0%. On DMR, Zep scored 94.8% vs. MemGPT's 93.4%.

Consensus as of early 2026: **vector memory suffices for simple personalization; graph memory becomes essential for complex entity relationships** — medical patient contexts, enterprise account hierarchies, technical interdependencies, multi-agent coordination.

### GraphRAG vs. agent memory graphs

Microsoft GraphRAG (github.com/microsoft/graphrag) builds entity-centric knowledge graphs from document corpora at index time (entity extraction → entity summarization → relationship extraction → Leiden community detection → community summarization; local vs. global search modes). It is a batch document-understanding pipeline, not agent memory: no native temporal reasoning, expensive incremental updates. But its community detection and summarization patterns are directly reused by agent memory systems in streaming/incremental form — Graphiti explicitly positions itself as "post-RAG."

---

## 3. Existing Graph Memory Implementations

**Zep / Graphiti** (arXiv:2501.13956; github.com/getzep/graphiti). The most technically ambitious production system. Three hierarchical subgraph tiers: **episode** (raw ingestion, provenance layer), **semantic entity** (LLM-extracted entities/relationships, with deduplication constrained to edges between the same entity pairs), and **community** (label propagation, chosen over Leiden for incremental dynamic updates). Its **bi-temporal model** puts four timestamps on every edge (`t_created`/`t_expired` for system knowledge; `t_valid`/`t_invalid` for world truth), enabling time-travel and forensic queries. Contradictions are resolved by LLM comparison and non-lossy edge invalidation — old facts stay queryable. 94.8% on DMR. Backends: Neo4j and FalkorDB (the latter for multi-agent, sub-10ms, per-agent graph isolation).

**Mem0 / Mem0g** (docs.mem0.ai/open-source/features/graph-memory). Most widely deployed (70+ companies). Mem0g builds a directed labeled KG alongside the vector store: entity extractor → relations generator → dual write. Graph backends Neo4j and Kuzu; 19 vector store backends. Multi-scope model (user, agent, session, org-level — note this is Mem0's scope vocabulary, not MemoryHub's canonical user/project/campaign/role/organizational/enterprise). Guidance: enable graph memory only when relationships matter; the 68.4% vs 66.9% accuracy gain costs 2.59s vs 1.44s p95. Recent: procedural memory as a third type alongside episodic and semantic (compare MemoryHub content_types experiential/knowledge/behavioral), metadata filtering, reranking, actor-aware multi-agent memory.

**Neo4j Agent Memory** (github.com/neo4j-labs/agent-memory). The most comprehensive graph-native library, with a three-tier architecture: **short-term** (full conversation history, summaries), **long-term** (auto-built KG using the POLE+O entity model — Person, Object, Location, Event, Organization — with temporal validity, deduplication, geospatial), and **reasoning memory** (every thought, tool call, outcome; trace similarity search — unique among memory systems). Its three-stage extraction cascade is the production reference: spaCy (~5ms) → GLiNER2 zero-shot (~50ms) → LLM fallback with GLiREL relations (~500ms), with 5 merge strategies, 8 domain schemas, background Wikidata/geocoding enrichment. Broad framework integrations plus an MCP server with 16 tools. Requires Neo4j 5.20+ (Enterprise for fine-grained access control).

**Hindsight** (arXiv:2512.12818; github.com/vectorize-io/hindsight). Four separate networks: world (objective facts), bank (the agent's own first-person experiences), opinion (subjective judgments with confidence scores), observation (preference-neutral entity summaries). **TEMPR** retrieval runs four parallel searches (vector, BM25, entity-graph traversal, temporal filter) fused via Reciprocal Rank Fusion + neural reranker; **CARA** does preference-aware reflection with disposition parameters (skepticism, literalism, empathy). 91.4% on LongMemEval; multi-session and temporal-reasoning questions jumped from ~21–32% to ~80%.

**Cognee** (github.com/topoteretes/cognee). Knowledge engine combining vector, graph, and cognitive-science approaches (consolidation, reinforcement, forgetting by usage). 500x pipeline-run growth in 2025; $7.5M seed Feb 2026; Neptune Analytics, LlamaIndex, Google ADK integrations.

**MAGMA** (arXiv:2601.03236; research). Represents each memory item across orthogonal semantic, temporal, causal, and entity graphs; an intent-aware Adaptive Traversal Policy selects and fuses relational views. Up to 45.5% higher reasoning accuracy on LoCoMo/LongMemEval with >95% token reduction and 40% faster queries.

**Others**: LlamaIndex **PropertyGraphIndex** (schema-guided extraction; a building block, not a memory system). **MemMachine** (ground-truth-preserving whole-episode storage, 93.0% LongMemEval_S). **Observational Memory** (Mastra; Observer + Reflector agents, 94.87% LongMemEval — highest recorded as of April 2026). **Supermemory** (consumer, local-first). **LangMem** (LangGraph-coupled, namespace partitioning). **Letta**/MemGPT (agents directly edit memory blocks; white-box inspection).

---

## 4. Graph Databases for Agent Memory

| Feature | Neo4j | FalkorDB | Memgraph | Kuzu | Apache AGE | Neptune |
|---------|-------|----------|----------|------|------------|---------|
| Query language | Cypher | Cypher subset | Cypher | Cypher | openCypher subset | Gremlin/SPARQL/openCypher |
| Deployment | Standalone/K8s | Standalone/K8s | Standalone/K8s | Embedded | PG extension | AWS managed |
| Vector search | Built-in (5.20+) | Built-in | Built-in | Built-in | Via pgvector | Neptune Analytics |
| Latency (agent workload) | ~10–50ms | Sub-10ms | Sub-10ms | Sub-3ms | PG-dependent | ~50–100ms |
| FIPS | Configurable | Unknown | Unknown | N/A | Inherits from PG | AWS FIPS endpoints |
| License | GPLv3/Commercial | SSPL | BSL 1.1 | MIT (archived) | Apache 2.0 | Proprietary |

**Neo4j**: most mature ecosystem; only option with graph-native fine-grained access control (Enterprise); GPLv3 community edition and commercial licensing are the drawbacks. **FalkorDB**: GraphBLAS-based, extremely low latency, proven with Graphiti for multi-tenant agent memory; smaller ecosystem, subset Cypher. **Memgraph**: in-memory C++, full Cypher, MCP client in Memgraph Lab; BSL license; more analytics- than memory-focused. **Kuzu**: embedded, MIT, sub-3ms — but the original team archived it in October 2025 (Vela Partners maintains a fork); unsuitable for multi-tenant server architecture. **Amazon Neptune**: managed, FIPS endpoints, Mem0/Cognee/Strands integrations — but AWS lock-in, no on-prem, not relevant for OpenShift-first MemoryHub. **ArangoDB**: multi-model with AutoGraph KG construction; not compelling vs. Neo4j + pgvector. Apache AGE is covered in Section 6.

---

## 5. Architecture Patterns and Governance

### Extraction, schema, hybrid retrieval, temporality, provenance

**Entity extraction** has converged on the multi-stage cascade (rule-based → zero-shot neural → LLM fallback; see Neo4j Agent Memory above), with write-time **deduplication** (fuzzy match, embedding similarity, or LLM comparison — Graphiti constrains the search to same-entity-pair edges) as the guard against graph fragmentation ("PostgreSQL"/"Postgres"/"PG"). POLE+O is the dominant entity classification schema, extended with domain types where needed.

**Common schema**: node types Entity, Episode/Event, Memory/Fact, Community, Session, Agent; relationship types `MENTIONS`, `DERIVED_FROM`, `RELATED_TO`, `SUPERSEDES`, `CONFLICTS_WITH`, `MEMBER_OF`, `PART_OF`, `CAUSED_BY`. Edges carry temporal properties (`created_at`, `valid_from`, `valid_until`); nodes carry embeddings for hybrid retrieval.

**Hybrid vector+graph is the consensus 2026 architecture** — no production system uses graph-only retrieval. Write path: input → extraction → graph update + embedding storage. Read path: parallel vector similarity + graph traversal, fused via RRF or neural reranking. Storage is either single-database (PostgreSQL + pgvector + graph tables/AGE) or dual (Neo4j + vectors).

**Temporal sophistication** comes in three levels: (1) timestamps only; (2) validity windows enabling "what was true at time T?" with invalidation instead of deletion (Graphiti, Neo4j Agent Memory); (3) full bi-temporal system-time vs. valid-time (Graphiti). Contradiction handling options: edge invalidation (Graphiti), explicit conflict edges (MemoryHub's current approach), confidence decay (Hindsight), LLM arbitration. Graph structure makes contradiction *detection* easier (including transitive contradictions that only emerge through multi-hop traversal) but *resolution* harder (cascades). Temporal change is evolution, not contradiction. See also "Graph-Native Cognitive Memory for AI Agents" (arXiv:2603.17244) for AGM-postulate belief-revision formalization.

**Provenance** is stored as traversable graph edges (Episode→Entity/Memory, Memory→Memory, Agent→Memory, Tool→Memory), so "why does the system believe X?" is a traversal back to source episodes.

### Governance

Graph databases add a dimension flat stores lack: **who can traverse which edges?** Neo4j Enterprise is the most mature — label-based, relationship-type, and property-level permissions with combined GRANT/DENY, and users cannot distinguish hidden from nonexistent data. FalkorDB has only Redis ACLs. Apache AGE inherits PostgreSQL RBAC/RLS, which operates at the table (label) level, not the traversal level. Neptune uses IAM; node-level control is application-layer.

For MemoryHub, permissions scope by owner, scope, project, and role — already implemented via the scope model and service-layer RBAC. The open design question is whether these extend to traversal: can following a `RELATED_TO` edge from a user-scoped memory reach an organizational memory the user shouldn't see? On PostgreSQL this must be enforced in the application layer or RLS.

**Quality/curation challenges** unique to graph memory: entity drift, hallucinated relationships, graph bloat, community staleness. Production responses: automated write-time deduplication, similarity-based merge suggestions (MemoryHub's `suggest_merge`), confidence-based pruning, usage-based decay, human-in-the-loop review for high-stakes domains.

---

## 6. The PostgreSQL Question and MemoryHub's Evolution Path

> **Superseded note**: The recommendations here informed and are now superseded by docs/design/graph-enhanced-memory.md (#170). Retained as rationale.

MemoryHub uses PostgreSQL + pgvector with adjacency lists (`memory_relationships` table) and recursive CTEs. **Apache AGE** would add openCypher-in-SQL on existing infrastructure (Apache 2.0, FIPS inherited from PostgreSQL, Azure-supported) but: no automatic indexes (explicit BTREE/GIN per label), subset Cypher, no built-in graph algorithms (no PageRank/community detection/shortest path), relational storage under the hood (one benchmark showed a 40x gap favoring recursive CTEs on a specific workload), RLS-only access control, and Apache Incubator status. Verdict: a reasonable stepping stone for Cypher ergonomics, but it doesn't solve deep traversal or algorithm gaps — if those become requirements, a dedicated graph DB is needed anyway.

**Assessment: PostgreSQL without AGE is sufficient for current and near-term needs.** MemoryHub's trees are shallow (3–4 levels), relationship types are simple, and scale targets are thousands of memories per user, not millions of nodes. A dedicated graph DB would help for: traversals beyond ~5 hops, graph algorithms (community detection, centrality), latency-sensitive graph-enhanced retrieval on every `search_memory`, and graph-native access control. The recommended hybrid path: PostgreSQL stays the system of record, pgvector handles vectors, and an optional read-optimized graph projection (in-memory NetworkX, or Neo4j later) serves complex traversals — mutations go to PostgreSQL first.

Decision framework: shallow trees/simple relationships → recursive CTEs; entity extraction added → AGE or in-memory graph; community detection/algorithms → dedicated graph DB or in-memory library; >5-hop retrieval in the read path → dedicated graph DB; graph-native access control → Neo4j Enterprise; minimize ops complexity → in-memory projection.

**What MemoryHub already has** matching state-of-the-art patterns: memory tree with branching (hierarchical tree structure), typed relationships (derived_from, supersedes, conflicts_with, related_to), contradiction tracking with threshold escalation, multi-scope model, hybrid retrieval foundation, partial provenance via versioning. (Source listed scopes as "user, project, organizational, enterprise" — canonical set also includes campaign and role; flagged, not a conflict, just predates the additions.)

**Gaps identified relative to state of the art**: no entity extraction from conversations; no community detection; no graph-enhanced retrieval in `search_memory`; no temporal validity on relationships; no reasoning memory (agent traces); only manual entity deduplication.

**Recommended phases** (now designed in #170): Phase 1 — temporal validity on relationships plus graph-enhanced retrieval (vector top-N, then follow relationships and re-rank), all on existing PostgreSQL. Phase 2 — lightweight entity extraction at `write_memory` time with write-time deduplication, creating a real knowledge graph without agent behavior changes. Phase 3 — a graph computation layer (NetworkX projection, AGE, or optional Neo4j backend) if algorithms/deep traversal become core.

Key takeaways: graph memory is production-ready in 2026; hybrid vector+graph is the consensus; entity extraction is the prerequisite; temporal awareness is what differentiates agent memory from static KGs; PostgreSQL+pgvector is a viable base for incremental evolution; and governance — where Neo4j Enterprise is the only graph-native option — is a story MemoryHub's scope-based RBAC is well-positioned to tell, pending traversal-policy design work.

---

## 7. The LLM Wiki Phenomenon (Karpathy, April 2026)

On April 3, 2026, Andrej Karpathy posted about "LLM Knowledge Bases" (16M+ views) and published the "llm-wiki" Gist — an idea file, not code, meant to be pasted into any LLM agent. Three-layer architecture: `raw/` (immutable sources), `wiki/` (LLM-compiled markdown articles with cross-references and backlinks), `index.md` (master catalog fitting one context window; read first, then drill in). Key insight: **knowledge is compiled once and kept current, not re-derived per query** — new sources get integrated into existing articles with contradictions noted. Karpathy built ~100 articles / ~400K words without writing a word, and said: "I think there is room here for an incredible new product instead of a hacky collection of scripts."

- Tweet: https://x.com/karpathy/status/2039805659525644595
- Gist: https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f
- VentureBeat: https://venturebeat.com/data/karpathy-shares-llm-knowledge-base-architecture-that-bypasses-rag-with-an

**Direct implementations** (all early-stage, all personal-only, no governance): lucasastorian/llmwiki (most polished; MCP server, llmwiki.app, Show HN https://news.ycombinator.com/item?id=47656181), MehmetGoekce/llm-wiki (L1/L2 cache, Logseq/Obsidian), Pratiyush/llm-wiki, kfchou/wiki-skills, Astro-Han/karpathy-llm-wiki, ussumant/llm-wiki-compiler, CacheZero (https://news.ycombinator.com/item?id=47667723), hellohejinyu/llm-wiki. The exception in spirit: the **LLM Wiki v2 gist** (https://gist.github.com/rohitg00/2067ab416f7bbe447c1977edaaa681e2) — a design spec (not implementation) addressing multi-user sync, conflict resolution, access control, and governance/auditing; the most thoughtful multi-user extension found.

**Hacker News themes** (https://news.ycombinator.com/item?id=47640875): "this is just RAG with extra steps"; model-collapse worries (Shumailov et al., Nature 2024) countered by "it's organization, not training"; "10M-token contexts will make this obsolete"; PKM users defending the value of manual-synthesis friction; scaling concerns ("a critical point exists beyond which agents can't keep wikis updated"); and the ownership advantage of file-based knowledge vs. platform-controlled memory.

**Obsidian + AI agents** is where the most community energy is — all personal-only by design (Obsidian is local-first, single-user): kepano/obsidian-skills (official, 13.9k stars, five portable skill rulebooks), m-rgba/obsidian-ai-agent, YishenTu/claudian, Cortex, hardbyte/obsidian-llm-plugin, ChatGPT MD.

**The broader knowledge-engineering trend**: "Agentic Knowledge Management" (Sebastien Dubois, dsebastien.net) — agents that proactively maintain knowledge bases; AI4PKM community (jykim.github.io/AI4PKM) evolving toward networks of connected second brains; KPMG positioning knowledge engineering as the bridge to agent value. The standout enterprise example is **Meta's Tribal Knowledge Mapping** (engineering.fb.com, April 2026): 50+ specialized agents read 4,100+ files across three repos, producing 59 structured context files encoding 50+ non-obvious patterns — research time cut from ~2 days to ~30 minutes, 40% fewer agent tool calls per task. The most compelling at-scale validation of the compile-knowledge pattern.

**Products**: established players (Notion AI — the only mature multi-user/governed one; Mem 2.0, Reflect, Capacities, Tana) plus new entrants (llmwiki.app, Dume.ai, Remio.ai, REM Labs, Waykee Cortex, CacheZero). **Waykee Cortex** (waykee.com) is the strongest multi-user candidate: hierarchical inheritance (System → Module → Screen), Knowledge + Work layers, open source — but early. Microsoft's 2026 KM roadmap (governed agent workflows over SharePoint/Copilot) and **Databricks Agent Bricks Knowledge Assistant** (GA Jan 2026, Unity Catalog governance) are the enterprise-governed adjacents — but Databricks is RAG-based, not compilation-based.

**Academic multi-user memory**: Collaborative Memory (arXiv:2505.18279 — private+shared tiers, bipartite access-control graphs, immutable provenance, 61% resource reduction); Memory as a Service (arXiv:2506.22815 — memory decoupled into governable service modules); A-MEM (NeurIPS 2025, arXiv:2502.12110 — Zettelkasten-style self-organizing memory).

**Gap analysis and MemoryHub relevance**: what does not exist — a production-quality multi-user LLM wiki with governance, access control, and audit trails; conflict resolution for concurrent agent edits (HN flagged filesystem race conditions as fundamental); anything bridging personal and team use; enterprise SSO/RBAC/compliance versions. Karpathy's three-layer architecture maps well onto MemoryHub's structured memory, versioning, and scoped access control. The community is validating demand; **nobody is filling the governed/multi-user niche** — which is exactly what MemoryHub builds. (See also docs/design/knowledge-compilation.md, which took up this thread.)

---

## 8. Google's Open Knowledge Format (OKF)

OKF v0.1 is a draft Apache-2.0 spec from GoogleCloudPlatform/knowledge-catalog (Knowledge Catalog = rebranded Dataplex); OKF is its vendor-neutral interchange format. Data model: **Knowledge Bundle** (a directory of markdown files with YAML frontmatter — the unit of distribution), **Concept** (one markdown file; ID = path minus `.md`; tangible assets or abstract ideas), **Links and Citations** (standard markdown links as directed, *untyped* edges; semantics live in surrounding prose). Only `type` is required (free-form string); unknown extension keys must be preserved; consumers must NOT reject bundles for missing fields, unknown types, or broken links — a deliberately low conformance bar optimizing adoption over correctness. Reserved files: `index.md` (progressive disclosure) and `log.md` (change history); versioning via git + `okf_version`. A companion ADK/Gemini enrichment agent does a BigQuery-metadata pass and a web-crawl pass; a Cytoscape.js visualizer and sample bundles (GA4, Stack Overflow, Bitcoin) exist.

- Spec: https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md

**Positioning**: OKF is firmly a semantic-layer (knowledge graph) format — it describes what things ARE, never why decisions were made. It is the spec-level formalization of Karpathy's llm-wiki impulse (his raw/wiki/index maps directly), but where llm-wiki is a personal workflow, OKF is an org-to-org interchange format — the Parquet-to-BigQuery / OCI-to-Docker play. Like the llm-wiki implementations, it adds no governance, access control, or multi-user support.

**Design contrasts with MemoryHub** (different purposes, not competing choices): OKF's single required free-form field vs. MemoryHub's required scope/content/authenticated identity — adoption friction vs. governance guarantees; untyped prose-semantics links vs. typed relationships with a traversal API (agents at runtime need "all dependencies of X" without reading prose); structurally public bundles vs. scope hierarchy and RBAC; tolerate-everything consumption vs. surface-and-resolve contradiction detection; git versioning vs. internal versioning with `isCurrent` flags and provenance chains; static `index.md` vs. dynamic search-with-focus-bias (same information-architecture principle, different mechanism).

**Implications**: OKF *validates* the MemoryHub/RetrievalHub split (see planning/knowledge-layer.md §7) — the industry is drawing the same semantic-vs-procedural line as Section 1. Concretely for the RetrievalHub: (1) **OKF as import/export format** — its permissive extension model lets MemoryHub-specific fields (scope, governance metadata, provenance, curation status) ride alongside without breaking conformance; (2) **the enrichment agent is prior art** for the extraction pipeline (#240) — asynchronous observation of operational data, structured extraction, human-in-the-loop promotion, on the semantic side what MemoryHub builds on the procedural side; (3) **governance is the differentiator** — don't compete on format; consume OKF and add access control, curation, provenance, contradiction detection, and runtime query. The two hubs together offer governed memory (experiential/behavioral) and governed knowledge (semantic/factual) for regulated customers where ungoverned alternatives are disqualified.

---

## 9. Ontology-Aware Contextualization of Memories

Organizations redefine, overload, and invert standard terminology — the norm, not an edge case, in regulated enterprises. Four motivating cases at increasing difficulty:

1. **SIPOC vs COPIS**: customer-first orgs reverse the Lean framework's ordering. Same concept, different label — a term registry solves it.
2. **HL7 FHIR**: ~150 resource types, thousands of spec pages — no context window holds it, and most interactions need a small slice. This is **progressive unfolding**: load the relevant domain slice based on focus, pull more on pivot. MemoryHub's focus tracking and search-with-focus-bias support this mechanically; the gap is that FHIR's formal inter-resource relationships live in the spec, not in the memory graph.
3. **VA / community care records**: cross-organizational mapping with patient-safety stakes — different coding systems (ICD-10 vs SNOMED CT, NDC vs RxNorm), *overlapping* concepts with partial equivalence ("office visit" vs "outpatient encounter" bundling different things).
4. **The ontology gap**: standard ontologies exist (SNOMED CT, LOINC, ICD-10; NIST/MITRE; Basel/IFRS), but organizations customize them in undocumented ways — and that customization is precisely what an agent needs. Universal across healthcare, defense, finance, government.

### Three-layer progression (independently useful, naturally composing)

**Layer 1 — Term registry** (near-term; zero new infrastructure). Project/org-scoped memories tagged with a `terminology` domain define local usage, e.g. `scope: organizational, domain: terminology, weight: 0.9, content: "In this organization, 'COPIS' refers to Customer-Output-Process-Input-Supplier — the reverse of standard SIPOC. All process documentation uses COPIS."` The only addition is a convention: treat retrieved terminology memories as definitional context injected alongside operational memories. Breaks down when the same term has different definitions in different scopes.

**Layer 2 — Ambiguity detection** (medium-term; rides on graph-enhanced memory #170). Curated known-ambiguous terms; inferred ambiguity when terminology memories across scopes define the same term differently (a variant of contradiction detection — both definitions can be correct within their scopes, but cross-scope communication needs translation); and **cross-scope term resolution** producing structured mappings ("Org A's 'encounter' maps to Org B's 'visit' with these differences: [...]") stored as campaign-scoped memories. Typed relationships between terminology memories (synonym-of, narrower-than, maps-to, superseded-by) form a lightweight domain ontology without formal ontology tooling.

**Layer 3 — Ontology mapping engine** (long-term; only if regulated verticals become significant). MemoryHub does not *build* ontologies — it becomes the governed persistence layer for *mappings* between existing ones, generated externally (terminology services, tuned models, manual curation) and stored with provenance, versioning, and scope. E.g.: "Community Provider X's 'cardiac event' corresponds to ICD-10 I21–I25 in the VA system, but their usage excludes unstable angina (I20.0), which the VA includes."

### Interactions with existing work

- **Graph-enhanced memory (#170)**: the natural foundation for Layer 2 — terminology relationships are just another edge type.
- **Context compaction (#169)**: the compactor must not discard definitional memories during summarization (losing the "COPIS" definition means the agent falls back to general knowledge and says "SIPOC"). Needs compaction-resistant or high-retention-priority marking; terminology memories are one class deserving it.
- **Extraction pipeline (#240)**: can propose terminology memories when definitions occur in conversation ("when we say 'sprint' here, we mean a two-week planning cycle"), with human validation.
- **The knowledge/experiential boundary**: MemoryHub is not the source of truth for "what does FHIR Patient mean" (semantic/library-RAG layer — RetrievalHub territory) but for "how does *this organization* use FHIR Patient, and how does that differ from the standard." (Source framed this as "episodic/semantic"; canonical content_type terms are experiential/knowledge — flagged.)

### Open questions

Compaction interaction with progressive unfolding (re-fetch vs. compacted summary on pivot-back); retrieval priority (always-inject risks token bloat, search-bias risks missing critical definitions — likely hybrid: always-inject for current-focus terms); Layer 1 scaling limits (tens easy, hundreds need tagging, ~thousands need hierarchy and disambiguation); temporal drift (versioning tracks *that* definitions changed, not that usage has informally moved past them — #240 could detect divergence; unsolved); federation governance (who owns cross-org mappings — operational, not technical; contradiction detection as the flagging mechanism, human resolution workflow).

**Non-goals**: MemoryHub is not becoming an ontology management system (Protege, TopBraid, UMLS, BioPortal exist); no OWL/RDF/SPARQL (the memory graph is a property graph, deliberately); no LoRA/fine-tuning in the memory layer (belongs in model serving). The insight is narrow: a lightweight, governed terminology-aware layer on existing memory primitives removes an adoption barrier no amount of model training fixes.

---

## 10. Sources

### Papers
- Zep: Temporal Knowledge Graph Architecture for Agent Memory — https://arxiv.org/abs/2501.13956
- MAGMA: Multi-Graph Agentic Memory Architecture — https://arxiv.org/abs/2601.03236 (repo: https://github.com/FredJiang0324/MAMGA)
- Graph-based Agent Memory: Taxonomy, Techniques, and Applications — https://arxiv.org/html/2602.05665 (DEEP-PolyU; the definitive survey: five graph structures — KGs, hierarchical trees, temporal graphs, hypergraphs, hybrids; four technique categories — extraction, retrieval [six operator types], evolution, storage; companion list https://github.com/DEEP-PolyU/Awesome-GraphMemory)
- Hindsight is 20/20 — https://arxiv.org/abs/2512.12818
- LongMemEval (ICLR 2025) — https://arxiv.org/abs/2410.10813
- MemMachine — https://arxiv.org/abs/2604.04853
- Graph-Native Cognitive Memory: Formal Belief Revision Semantics — https://arxiv.org/html/2603.17244v1
- RAG Meets Temporal Graphs — https://arxiv.org/html/2510.13590v1
- Beyond the Context Window: Fact-Based Memory vs. Long-Context LLMs — https://arxiv.org/html/2603.04814v1 (structured memory more cost-effective at scale)
- Graphs Meet AI Agents — https://arxiv.org/html/2506.18019v1
- Graph Retrieval-Augmented Generation: A Survey — https://dl.acm.org/doi/10.1145/3777378
- KG construction from LLMs: Scientific Reports Feb 2026 — https://www.nature.com/articles/s41598-026-38066-w; Applied Sciences Mar 2025 — https://www.mdpi.com/2076-3417/15/7/3727; SF-GPT (2025, 89.7% precision / 92.3% recall triple extraction); LLM-empowered KG construction survey — https://arxiv.org/html/2510.20345v1
- Memory in the Age of AI Agents survey (Tsinghua C3I) — https://github.com/TsinghuaC3I/Awesome-Memory-for-Agents
- Collaborative Memory — https://arxiv.org/abs/2505.18279; Memory as a Service — https://arxiv.org/abs/2506.22815; A-MEM — https://arxiv.org/abs/2502.12110

### Repositories and documentation
- Graphiti — https://github.com/getzep/graphiti
- Neo4j Agent Memory — https://github.com/neo4j-labs/agent-memory / https://neo4j.com/labs/agent-memory/
- Mem0 Graph Memory — https://docs.mem0.ai/open-source/features/graph-memory
- Microsoft GraphRAG — https://github.com/microsoft/graphrag
- FalkorDB — https://github.com/FalkorDB/FalkorDB
- Cognee — https://github.com/topoteretes/cognee
- Hindsight — https://github.com/vectorize-io/hindsight
- MemMachine — https://github.com/MemMachine/MemMachine
- LlamaIndex PropertyGraphIndex — https://www.llamaindex.ai/blog/introducing-the-property-graph-index-a-powerful-new-way-to-build-knowledge-graphs-with-llms
- Apache AGE — https://github.com/apache/age / https://age.apache.org/overview/
- Kuzu — https://github.com/kuzudb/kuzu / Vela fork: https://www.vela.partners/blog/kuzudb-ai-agent-memory-graph-database
- OKF / knowledge-catalog — https://github.com/GoogleCloudPlatform/knowledge-catalog / https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md

### Industry reports and posts
- Mem0 State of AI Agent Memory 2026 — https://mem0.ai/blog/state-of-ai-agent-memory-2026; Top 5 graph memory solutions — https://mem0.ai/blog/graph-memory-solutions-ai-agents
- Neo4j blog: Graphiti — https://neo4j.com/blog/developer/graphiti-knowledge-graph-memory/; Lenny's Memory context graphs — https://neo4j.com/blog/developer/meet-lennys-memory-building-context-graphs-for-ai-agents/; security — https://neo4j.com/product/neo4j-graph-database/security/; Microsoft Agent Framework + Neo4j — https://medium.com/neo4j/building-an-ai-agent-with-memory-microsoft-agent-framework-neo4j-e3eab8f09694
- Zep: Stop Using RAG for Agent Memory — https://blog.getzep.com/stop-using-rag-for-agent-memory/
- Mastra Observational Memory — https://mastra.ai/research/observational-memory
- Hindsight benchmark manifesto — https://hindsight.vectorize.io/blog/2026/03/23/agent-memory-benchmark
- Apache AGE performance (Azure) — https://learn.microsoft.com/en-us/azure/postgresql/azure-ai/generative-ai-age-performance
- Graph-based security & entitlements — https://enterprise-knowledge.com/graph-based-security-entitlements-transforming-access-control-for-the-modern-enterprise/
- AWS: Mem0 + ElastiCache + Neptune — https://aws.amazon.com/blogs/database/build-persistent-memory-for-agentic-ai-applications-with-mem0-open-source-amazon-elasticache-for-valkey-and-amazon-neptune-analytics/
- Graphiti + FalkorDB — https://www.falkordb.com/blog/graphiti-falkordb-multi-agent-performance/
- Gartner context graphs (via Atlan, March 2026); Atlan: LLM Wiki vs RAG — https://atlan.com/know/llm-wiki-vs-rag-knowledge-base/
- Mastra four levels of agent memory (Alex Booker, 2026)
- Karpathy llm-wiki ecosystem: gist, tweet, VentureBeat, and HN threads (linked in Section 7); MindStudio — https://www.mindstudio.ai/blog/andrej-karpathy-llm-wiki-knowledge-base-claude-code; Analytics Vidhya — https://www.analyticsvidhya.com/blog/2026/04/llm-wiki-by-andrej-karpathy/
- Obsidian ecosystem: https://github.com/kepano/obsidian-skills, https://github.com/m-rgba/obsidian-ai-agent, https://github.com/YishenTu/claudian, https://github.com/hardbyte/obsidian-llm-plugin, https://forum.obsidian.md/t/plugin-cortex-an-ai-obsidian-vault-agent-powered-by-claude-code/112430, ChatGPT MD — https://www.blog.brightcoding.dev/2026/03/25/chatgpt-md-the-ai-assistant-your-obsidian-vault-needs
- AKM / knowledge engineering: https://www.dsebastien.net/agentic-knowledge-management-the-next-evolution-of-pkm/, https://jykim.github.io/AI4PKM/, Meta tribal knowledge — https://engineering.fb.com/2026/04/06/developer-tools/how-meta-used-ai-to-map-tribal-knowledge-in-large-scale-data-pipelines/, KPMG — https://kpmg.com/us/en/articles/2026/why-knowledge-engineering-is-the-key-to-ai-agent-value.html, The New Stack agentic KB patterns — https://thenewstack.io/agentic-knowledge-base-patterns/
- Enterprise products: Microsoft 2026 KM roadmap — https://windowsnews.ai/article/enterprise-ai-knowledge-management-2026-microsofts-shift-from-search-to-governed-agent-workflows.410816, Databricks Knowledge Assistant — https://www.databricks.com/blog/agent-bricks-knowledge-assistant-now-generally-available-turning-enterprise-knowledge-answers, Waykee Cortex — https://waykee.com/, Dume.ai — https://www.dume.ai/blog/what-is-andrej-karpathys-llm-wiki-how-to-get-the-same-results-without-code-using-dume-cowork, Remio — https://www.remio.ai/, REM Labs — https://remlabs.ai/blog/ai-knowledge-management-2026
- llm-wiki implementations: https://github.com/lucasastorian/llmwiki (https://llmwiki.app/), https://github.com/MehmetGoekce/llm-wiki (build writeup: https://mehmetgoekce.substack.com/p/i-built-karpathys-llm-wiki-with-claude), https://github.com/Pratiyush/llm-wiki, https://github.com/kfchou/wiki-skills, https://github.com/Astro-Han/karpathy-llm-wiki, https://github.com/ussumant/llm-wiki-compiler, https://github.com/hellohejinyu/llm-wiki
