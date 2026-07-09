# Knowledge and Graph Memory: Consolidated Research

**Abstract**: This document consolidates MemoryHub's research on structured knowledge for AI agents: graph-based agent memory (systems, databases, academic work, architecture patterns, governance, and the PostgreSQL question), the knowledge-graph vs. context-graph distinction that anchors MemoryHub's memory-vs-retrieval boundary, the Karpathy llm-wiki phenomenon and the compiled-knowledge product landscape, Google's Open Knowledge Format as a semantic-layer interchange spec, and ontology-aware contextualization of memories in terminology-divergent enterprises. The through-line: the industry has split "what things ARE" (semantic layer / knowledge graphs) from "how things HAPPEN" (procedural layer / agent memory), governance is the unclaimed differentiator on both sides, and MemoryHub's memory graph can evolve incrementally on PostgreSQL toward state-of-the-art graph memory.

**Status**: Section 6 is superseded by [docs/design/graph-enhanced-memory.md](../../docs/design/graph-enhanced-memory.md) (#170) — retained as rationale. Market snapshots (Sections 3, 7–8) are early-to-mid 2026 and will age. For the newcomer-facing conceptual framing, see [docs/guides/what-is-agent-memory.md](../../docs/guides/what-is-agent-memory.md).

---

## 1. The Core Distinction: Knowledge Graphs vs. Context Graphs

When someone says "we need to give our AI agents knowledge," two different infrastructure conversations collapse into one. Both involve graphs, both get filed under "AI grounding," but they solve different problems. **Knowledge graphs encode what things ARE. Context graphs encode how things HAPPEN.** An agent needs both, and they are not the same system.

A **knowledge graph** is a structured representation of domain entities and their relationships — the ontology: concepts, properties, constraints. "Customer places Order, Order contains Product, Product belongs_to Category." These are relatively static domain facts; deleting every operational record would leave the ontology valid. Standards: RDF, OWL, SPARQL, and the labeled property graph model (Neo4j). Gartner calls this the "semantic layer."

A **context graph** captures how an organization actually operates — decisions, workflows, reasoning traces, and institutional memory accumulated through experience: "We approved a 20% discount for Acme because their renewal was at risk and the regional VP signed off on 2026-03-15." "User prefers concise responses; learned over 12 interactions." Context graphs answer "how was a similar situation handled last time?", "why was this exception approved?", "what organizational knowledge exists about this workflow?". Gartner defines context graphs as purpose-built infrastructure for agentic AI, predicts that more than 50% of AI agent systems will use them by 2028, and is explicit that they augment rather than replace knowledge graphs (primary Gartner research is paywalled; summarized at https://atlan.com/know/gartner-context-graphs/).

The practical test: **is this fact about the domain, or about a decision/experience?** If the fact would survive deleting all operational history ("Products belong to Categories"), it's domain knowledge — knowledge graph. If it emerged from operational history ("we stopped recommending Category X after the Q3 complaints"; "last time we bulk-discounted this line, margin dropped 12%"), it's experiential memory — context graph. The knowledge graph gives an agent *understanding* (vocabulary, classification, entity structure); the context graph gives it *judgment* (precedent, preferences, rationale). The strongest systems combine both.

In MemoryHub terms this maps approximately onto the content_type split: knowledge-graph material is `knowledge` content; context-graph material is `experiential` and `behavioral` content.

### The four levels of agent memory (Mastra / Alex Booker framework)

Source: https://mastra.ai/articles/agent-memory and Booker's April 2026 video (https://www.youtube.com/watch?v=18iIHQtIPmc). All four are context-graph concerns — none require a knowledge graph, and having one gives you none of them:

1. **Conversation history** — send a window of previous messages. Works for 10–20 messages, then context drifts; no cross-session persistence, no selectivity.
2. **Working memory** — a structured scratch pad with predefined fields (user name, goal, stated preferences) carried through the session. Limitation: fields must be predefined, which isn't very agentic.
3. **Semantic recall** — vector search over past interactions, selectively injecting relevant history. This is where the KG/context-graph conflation is most tempting: the embedding+vector infrastructure is shared with knowledge-graph RAG, but the *content* searched is experiential, not ontological.
4. **Observational memory** — background Observer and Reflector agents continuously compress raw messages into dense, prioritized, temporally annotated observations, further compressed over time. Pure context-graph infrastructure; models institutional memory.

A useful counterweight to graph enthusiasm: Michael Sakhatsky, "You Probably Don't Need a Graph Database for Your Knowledge Graph" (April 2026, https://medium.com/@msakhatsky/you-probably-dont-need-a-graph-database-for-your-knowledge-graph-7178054fe3d3) — a critique of the assumption chain from ontology to graph database, arguing rules engines and logic programming fit some cases better.

---

## 2. Graph Memory for Agents: Concepts and Evidence

Vector memory retrieves facts by semantic similarity but loses *structure* — it cannot answer "what tool preferences does the user have, and which conflict with organizational policy?" because that requires traversing relationships, not computing distances. Graph memory encodes entities, relationships, and properties as first-class objects, enabling multi-hop reasoning, temporal reasoning ("preferred Docker in 2024, switched to Podman in 2025"), and contradiction detection across scopes.

The field's overlapping terms, roughly hierarchical:

- **Knowledge graphs**: semantic networks of typed entities/relationships, often ontology-driven; relatively static.
- **Memory graphs**: knowledge graphs optimized for agent persistence and temporal awareness — tracking how facts change, maintaining provenance, supporting both prescribed and learned ontology. Graphiti's "temporal context graphs" are the canonical example. (In MemoryHub usage, "memory graph" means the memory tree plus typed relationships — narrower than this survey usage.)
- **Property graphs**: the technical storage model (nodes/edges with arbitrary key-value properties: Neo4j, FalkorDB, Memgraph, Kuzu) underlying the semantic layers above.
- **Temporal knowledge graphs**: every fact has a validity window; Graphiti's bi-temporal model distinguishes when a fact was true in the world from when the system learned it.
- **Hypergraphs**: edges connecting more than two nodes, preserving n-ary relationships (MAGMA's orthogonal semantic/temporal/causal/entity graphs).

### Benchmark evidence — read with caution

The Mem0 paper (arXiv:2504.19413, ECAI 2025) quantifies the vector-vs-graph tradeoff on LOCOMO. Two labeling notes: the score is the LLM-as-a-Judge (J) metric, not exact-match accuracy, and latencies are p95 *total response* time (search + generation):

| Approach | J score (LOCOMO) | p95 total latency | Tokens/conversation |
|----------|-------------------|-------------------|---------------------|
| Full context | 72.9% | 17.12s | ~26,000 |
| Mem0g (graph+vector) | 68.4% | 2.59s | ~1,800 |
| Mem0 (vector only) | 66.9% | 1.44s | ~1,800 |

The LOCOMO methodology has been credibly criticized (Zep: https://blog.getzep.com/lies-damn-lies-statistics-is-mem0-really-sota-in-agent-memory/), and Mem0's own 2026 rewrite reports much higher numbers (LoCoMo 92.5, LongMemEval 94.4: https://mem0.ai/blog/state-of-ai-agent-memory-2026). Treat the table as evidence for the *shape* of the tradeoff — graph adds a little accuracy and a little latency over pure vector, and both crush full-context on cost — not for absolute rankings.

**LongMemEval** (ICLR 2025, arXiv:2410.10813 — 500 questions across information extraction, multi-session reasoning, temporal reasoning, knowledge updates, abstention) is the more demanding benchmark, and structured/graph-flavored systems lead it. Reported scores as of mid-2026: Observational Memory (Mastra) 94.87% with gpt-5-mini (https://mastra.ai/research/observational-memory); MemMachine 93.0% with gpt-4.1-mini (arXiv:2604.04853); Hindsight 91.4% (arXiv:2512.12818); EverMemOS 83.0% (arXiv:2601.02163). **These numbers are not directly comparable**: they use different answer models, ingestion models, and harnesses — Mastra's own leaderboard shows the same system moving 84.2→94.9 on answer-model choice alone — and vendor-reported scores for *competitors* are unreliable (EverMemOS reports Mem0 at 49.0%; Mem0 reports itself at 94.4%). Treat small deltas as noise and self-vs-competitor comparisons as marketing (see also the "Benchmark Theatre" critique: https://essays.bloo-mind.ai/posts/2026-05-20-mem-eval/). On the narrower DMR benchmark, Zep reports 94.8% vs. MemGPT's 93.4% (arXiv:2501.13956).

What the evidence does support: vector memory suffices for simple personalization; graph structure earns its complexity when entity relationships are central — medical patient contexts, enterprise account hierarchies, technical interdependencies, multi-agent coordination.

### GraphRAG vs. agent memory graphs

Microsoft GraphRAG (github.com/microsoft/graphrag; arXiv:2404.16130) builds entity-centric knowledge graphs from document corpora at index time (entity extraction → entity summarization → relationship extraction → Leiden community detection → community summarization; local vs. global search modes). It is a batch document-understanding pipeline, not agent memory: no native temporal reasoning, expensive incremental updates. But its community detection and summarization patterns are directly reused by agent memory systems in streaming/incremental form — Graphiti explicitly positions itself as "post-RAG."

---

## 3. Existing Graph Memory Implementations

**Zep / Graphiti** (arXiv:2501.13956; github.com/getzep/graphiti). The most technically ambitious production system. Three hierarchical subgraph tiers: **episode** (raw ingestion, provenance layer), **semantic entity** (LLM-extracted entities/relationships, with deduplication constrained to edges between the same entity pairs), and **community** (label propagation, chosen over Leiden because it extends incrementally). Its **bi-temporal model** puts four timestamps on every edge (`t_created`/`t_expired` for system knowledge; `t_valid`/`t_invalid` for world truth), enabling time-travel and forensic queries. Contradictions are resolved by LLM comparison and non-lossy edge invalidation — old facts stay queryable. Backends as of mid-2026: Neo4j 5.26+, FalkorDB 1.1.2+ (vendor-benchmarked for sub-10ms multi-agent workloads with per-agent graph isolation), Amazon Neptune, and Kuzu (deprecated).

**Mem0 / Mem0g** (docs.mem0.ai/open-source/features/graph-memory). Among the most widely deployed OSS memory layers. Mem0g builds a directed labeled KG alongside the vector store: entity extractor → relations generator → dual write. OSS graph backends: Neo4j, Memgraph, Neptune Analytics, Kuzu, Apache AGE; 23+ vector store backends. The hosted platform's 2026 rewrite dropped the external queryable graph in favor of a native store with entity-boosted vector retrieval. Scoping identifiers: user, agent, run, app, org (Mem0's vocabulary — distinct from MemoryHub's user/project/campaign/role/organizational/enterprise). Memory types now include procedural alongside episodic and semantic (compare MemoryHub content_types experiential/knowledge/behavioral).

**Neo4j Agent Memory** (github.com/neo4j-labs/agent-memory). The most comprehensive graph-native library, with a three-tier architecture: **short-term** (full conversation history, summaries), **long-term** (auto-built KG using the POLE+O entity model — Person, Object, Location, Event, Organization — with temporal validity, deduplication, geospatial), and **reasoning memory** (every thought, tool call, outcome; trace similarity search — unique among memory systems). Its three-stage extraction cascade is a production reference: spaCy (10–50ms CPU) → GLiNER zero-shot (200–500ms CPU, 50–100ms GPU) → LLM fallback with GLiREL relations (500–2000ms), per the official latency table (https://neo4j.com/labs/agent-memory/explanation/extraction-pipeline/), with five merge strategies (CONFIDENCE/UNION/INTERSECTION/FIRST/LAST), eight domain schemas, and background Wikipedia + Nominatim-geocoding enrichment. Broad framework integrations plus an MCP server with 16 tools. Requires Neo4j 5.x (5.11+ for vector indexes; Enterprise for fine-grained access control).

**Hindsight** (arXiv:2512.12818; github.com/vectorize-io/hindsight). Four separate networks: world (objective facts), bank (the agent's own first-person experiences), opinion (subjective judgments with confidence scores), observation (preference-neutral entity summaries). **TEMPR** retrieval runs four parallel searches (vector, BM25, entity-graph traversal, temporal filter) fused via Reciprocal Rank Fusion + neural reranker; **CARA** does preference-aware reflection with disposition parameters (skepticism, literalism, empathy). 91.4% on LongMemEval; on the hardest question types, multi-session went 21.1%→79.7% and temporal reasoning 31.6%→79.7% (https://github.com/vectorize-io/hindsight-benchmarks).

**Cognee** (github.com/topoteretes/cognee). Knowledge engine combining vector, graph, and cognitive-science approaches (consolidation, reinforcement, forgetting by usage). 500x pipeline-run growth in 2025; $7.5M seed Feb 2026, running live in 70+ companies per the funding announcement (https://www.cognee.ai/blog/cognee-news/cognee-raises-seven-million-five-hundred-thousand-dollars-seed); Neptune Analytics, LlamaIndex, and Google ADK integrations.

**MAGMA** (arXiv:2601.03236, accepted ACL 2026; github.com/FredJiang0324/MAGMA). Represents each memory item across orthogonal semantic, temporal, causal, and entity graphs; an intent-aware adaptive traversal policy selects and fuses relational views. Reports 18.6–45.5% higher reasoning accuracy over baselines on LoCoMo/LongMemEval with ~95% token reduction vs. full context.

**Others**: LlamaIndex **PropertyGraphIndex** (schema-guided extraction; a building block, not a memory system). **MemMachine** (ground-truth-preserving whole-episode storage, 93.0% LongMemEval_S). **Observational Memory** (Mastra; Observer + Reflector agents; the highest LongMemEval score recorded as of mid-2026). **Supermemory** (memory API/platform for developers). **LangMem** (LangGraph-coupled, namespace partitioning). **Letta**/MemGPT (agents directly edit memory blocks; white-box inspection).

---

## 4. Graph Databases for Agent Memory

| Feature | Neo4j | FalkorDB | Memgraph | Kuzu | Apache AGE | Neptune |
|---------|-------|----------|----------|------|------------|---------|
| Query language | Cypher | Cypher subset | Cypher | Cypher | openCypher subset | Gremlin/SPARQL/openCypher |
| Deployment | Standalone/K8s | Standalone/K8s | Standalone/K8s | Embedded | PG extension | AWS managed |
| Vector search | Built-in (GA 5.13) | Built-in | Built-in | Built-in | Via pgvector | Neptune Analytics |
| FIPS | Configurable | Unknown | Unknown | N/A | Inherits from PG | AWS FIPS endpoints |
| License | GPLv3/Commercial | SSPL | BSL 1.1 | MIT (archived) | Apache 2.0 | Proprietary |

(Latency comparisons are omitted deliberately: published figures are vendor benchmarks on incomparable workloads. The defensible ordering is embedded < in-memory/sparse-matrix engines < disk-backed servers < managed cloud round-trips.)

**Neo4j**: most mature ecosystem; the only option with graph-native fine-grained access control (Enterprise); GPLv3 community edition and commercial licensing are the drawbacks. **FalkorDB**: GraphBLAS sparse-matrix engine, very low latency in vendor benchmarks, proven with Graphiti for multi-tenant agent memory; smaller ecosystem, subset Cypher. **Memgraph**: in-memory C++, full Cypher, MCP client in Memgraph Lab; BSL license; more analytics- than memory-focused. **Kuzu**: embedded, MIT — but the original team archived the repo in October 2025 (https://www.theregister.com/2025/10/14/kuzudb_abandoned/); community forks exist (most actively Vela Engineering's), and it is unsuitable for a multi-tenant server architecture regardless. **Amazon Neptune**: managed, FIPS endpoints, Mem0/Cognee/Strands integrations — but AWS lock-in, no on-prem, not relevant for OpenShift-first MemoryHub. **ArangoDB**: multi-model with AutoGraph KG construction; not compelling vs. Neo4j + pgvector. Apache AGE is covered in Section 6.

---

## 5. Architecture Patterns and Governance

### Extraction, schema, hybrid retrieval, temporality, provenance

**Entity extraction** has converged on the multi-stage cascade (rule-based → zero-shot neural → LLM fallback; see Neo4j Agent Memory above), with write-time **deduplication** (fuzzy match, embedding similarity, or LLM comparison — Graphiti constrains the search to same-entity-pair edges) as the guard against graph fragmentation ("PostgreSQL"/"Postgres"/"PG"). For entity classification, POLE+O — Neo4j Agent Memory's default, extending the policing-domain POLE model with Organization (https://neo4j.com/labs/agent-memory/explanation/poleo-model/) — is a widely referenced scheme; other systems (Graphiti, Mem0) use open or learned entity types instead of a fixed taxonomy.

**Common schema**: node types Entity, Episode/Event, Memory/Fact, Community, Session, Agent; relationship types `MENTIONS`, `DERIVED_FROM`, `RELATED_TO`, `SUPERSEDES`, `CONFLICTS_WITH`, `MEMBER_OF`, `PART_OF`, `CAUSED_BY`. Edges carry temporal properties (`created_at`, `valid_from`, `valid_until`); nodes carry embeddings for hybrid retrieval.

**Hybrid vector+graph is the dominant 2026 pattern** — every major system pairs graph structure with vector retrieval, though "hybrid" spans a spectrum: full parallel graph traversal fused with vector search (Hindsight, Graphiti) down to graph-informed ranking over a vector store (Mem0's 2026 rewrite, which dropped its queryable graph). Write path: input → extraction → graph update + embedding storage. Read path: vector similarity and graph signals fused via RRF or neural reranking. Storage is either single-database (PostgreSQL + pgvector + graph tables/AGE) or dual (Neo4j + vectors).

**Temporal sophistication** comes in three levels: (1) timestamps only; (2) validity windows enabling "what was true at time T?" with invalidation instead of deletion (Graphiti, Neo4j Agent Memory); (3) full bi-temporal system-time vs. valid-time (Graphiti). Contradiction handling options: edge invalidation (Graphiti), explicit conflict edges (MemoryHub's current approach), confidence decay (Hindsight), LLM arbitration. Graph structure makes contradiction *detection* easier (including transitive contradictions that only emerge through multi-hop traversal) but *resolution* harder (cascades). Temporal change is evolution, not contradiction. For a formal treatment, see "Graph-Native Cognitive Memory for AI Agents" (arXiv:2603.17244), which grounds versioned memory in AGM belief-revision postulates.

**Provenance** is stored as traversable graph edges (Episode→Entity/Memory, Memory→Memory, Agent→Memory, Tool→Memory), so "why does the system believe X?" is a traversal back to source episodes.

### Governance

Graph databases add a dimension flat stores lack: **who can traverse which edges?** Neo4j Enterprise is the most mature — label-based, relationship-type, and property-level permissions with combined GRANT/DENY, and users cannot distinguish hidden from nonexistent data (https://neo4j.com/docs/operations-manual/current/authentication-authorization/privileges-reads/). FalkorDB has only Redis ACLs (per-graph key patterns and command permissions; no node/edge-level control). Apache AGE inherits PostgreSQL RBAC/RLS, which operates at the table (label) level, not the traversal level. Neptune uses IAM; node-level control is application-layer.

For MemoryHub, permissions scope by owner, scope, project, and role — already implemented via the scope model and service-layer RBAC. The open design question is whether these extend to traversal: can following a `RELATED_TO` edge from a user-scoped memory reach an organizational memory the user shouldn't see? On PostgreSQL this must be enforced in the application layer or RLS.

**Quality/curation challenges** unique to graph memory: entity drift, hallucinated relationships, graph bloat, community staleness. Production responses: automated write-time deduplication, similarity-based merge suggestions, confidence-based pruning, usage-based decay, human-in-the-loop review for high-stakes domains.

---

## 6. The PostgreSQL Question and MemoryHub's Evolution Path

> **Superseded note**: The recommendations here informed and are now superseded by docs/design/graph-enhanced-memory.md (#170). Retained as rationale.

MemoryHub uses PostgreSQL + pgvector with adjacency lists (`memory_relationships` table) and recursive CTEs. **Apache AGE** would add openCypher-in-SQL on existing infrastructure (Apache 2.0; a Top-Level Project since June 2022; FIPS inherited from PostgreSQL; Azure-supported) but: no automatic indexes (explicit BTREE/GIN per label), subset Cypher, no built-in graph-algorithms library (no PageRank/community detection), relational storage under the hood (one third-party benchmark measured a ~40x gap favoring plain recursive CTEs on a specific traversal workload: https://medium.com/@sjksingh/postgresql-showdown-complex-joins-vs-native-graph-traversals-with-apache-age-78d65f2fbdaa), and RLS-only access control. Verdict: a reasonable stepping stone for Cypher ergonomics, but it doesn't solve deep traversal or algorithm gaps — if those become requirements, a dedicated graph DB is needed anyway.

**Assessment: PostgreSQL without AGE is sufficient for current and near-term needs.** MemoryHub's trees are shallow (3–4 levels), relationship types are simple, and scale targets are thousands of memories per user, not millions of nodes. A dedicated graph DB would help for: traversals beyond ~5 hops, graph algorithms (community detection, centrality), latency-sensitive graph-enhanced retrieval on every `search_memory`, and graph-native access control. The recommended hybrid path: PostgreSQL stays the system of record, pgvector handles vectors, and an optional read-optimized graph projection (in-memory NetworkX, or Neo4j later) serves complex traversals — mutations go to PostgreSQL first.

Decision framework: shallow trees/simple relationships → recursive CTEs; entity extraction added → AGE or in-memory graph; community detection/algorithms → dedicated graph DB or in-memory library; >5-hop retrieval in the read path → dedicated graph DB; graph-native access control → Neo4j Enterprise; minimize ops complexity → in-memory projection.

**What MemoryHub already has** matching state-of-the-art patterns: memory tree with branching, typed relationships (derived_from, supersedes, conflicts_with, related_to, mentions), contradiction tracking with threshold escalation, the six-scope governance model, hybrid retrieval foundation, partial provenance via versioning.

**Gaps identified relative to state of the art** (as of the original survey; #170 has since addressed entity extraction and graph-enhanced retrieval): no entity extraction from conversations; no graph-enhanced retrieval in `search_memory`; no community detection; no temporal validity on relationships; no reasoning memory (agent traces); only manual entity deduplication.

**Recommended phases** (now designed in #170): Phase 1 — temporal validity on relationships plus graph-enhanced retrieval (vector top-N, then follow relationships and re-rank), all on existing PostgreSQL. Phase 2 — lightweight entity extraction at write time with write-time deduplication, creating a real knowledge graph without agent behavior changes. Phase 3 — a graph computation layer (NetworkX projection, AGE, or optional Neo4j backend) if algorithms/deep traversal become core.

Key takeaways: graph memory is production-ready in 2026; hybrid vector+graph is the dominant pattern; entity extraction is the prerequisite; temporal awareness is what differentiates agent memory from static KGs; PostgreSQL+pgvector is a viable base for incremental evolution; and governance — where Neo4j Enterprise is the only graph-native option — is a story MemoryHub's scope-based RBAC is well-positioned to tell, pending traversal-policy design work.

---

## 7. The LLM Wiki Phenomenon (Karpathy, April 2026)

In early April 2026, Andrej Karpathy posted about "LLM Knowledge Bases" (16M+ views; https://x.com/karpathy/status/2039805659525644595) and published the "llm-wiki" Gist (https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) — an idea file, not code, meant to be pasted into any LLM agent. Three layers: **raw sources** (immutable), **the wiki** (LLM-compiled markdown articles with cross-references and backlinks), and **the schema** (a CLAUDE.md/AGENTS.md defining the wiki's conventions) — plus two special files, `index.md` (master catalog; the agent reads it first, then drills in — Karpathy reports this "works surprisingly well at moderate scale (~100 sources, ~hundreds of pages)") and `log.md` (change history). Key insight: **knowledge is compiled once and kept current, not re-derived per query** — new sources get integrated into existing articles with contradictions noted. Karpathy reported ~100 articles / ~400K words without writing a word, and said: "I think there is room here for an incredible new product instead of a hacky collection of scripts." Coverage: https://venturebeat.com/data/karpathy-shares-llm-knowledge-base-architecture-that-bypasses-rag-with-an

**Direct implementations** (all early-stage, all personal-only, no governance): lucasastorian/llmwiki (most polished; MCP server, llmwiki.app, Show HN https://news.ycombinator.com/item?id=47656181), MehmetGoekce/llm-wiki (L1/L2 cache, Logseq/Obsidian), Pratiyush/llm-wiki, kfchou/wiki-skills, Astro-Han/karpathy-llm-wiki, ussumant/llm-wiki-compiler, CacheZero (https://news.ycombinator.com/item?id=47667723), hellohejinyu/llm-wiki. The most thoughtful extension is the **LLM Wiki v2 gist** (https://gist.github.com/rohitg00/2067ab416f7bbe447c1977edaaa681e2) — a design spec (not implementation) for multi-*agent* sync with last-write-wins conflict resolution; notably, it names access control as an open gap rather than solving it, which reinforces the governance-gap thesis below.

**Hacker News themes** (https://news.ycombinator.com/item?id=47640875): "this is just RAG" (the thread's most common objection); model-collapse worries (Shumailov et al., Nature 2024) countered by "it's organization, not training"; "10M-token contexts will make this obsolete"; PKM users defending the value of manual-synthesis friction; scaling concerns ("a critical point exists beyond which agents can't keep wikis updated"); and the ownership advantage of file-based knowledge vs. platform-controlled memory.

**Obsidian + AI agents** is where the most community energy is — all personal-only by design (Obsidian is local-first, single-user): kepano/obsidian-skills (published by Obsidian's CEO under his personal account; ~14k stars at the April snapshot, ~39k by July 2026; five portable skill rulebooks), m-rgba/obsidian-ai-agent, YishenTu/claudian, Cortex, hardbyte/obsidian-llm-plugin, ChatGPT MD.

**The broader knowledge-engineering trend**: "Agentic Knowledge Management" (Sebastien Dubois, dsebastien.net) — agents that proactively maintain knowledge bases; AI4PKM community (jykim.github.io/AI4PKM) evolving toward networks of connected second brains; KPMG positioning knowledge engineering as the bridge to agent value. The standout enterprise example is **Meta's Organizational Knowledge Mapping** (engineering.fb.com, April 2026): 50+ specialized agents read 4,100+ files across the data-pipeline repos, producing 59 structured context files encoding 50+ non-obvious patterns — research time cut from ~2 days to ~30 minutes, and a preliminary six-task test showed 40% fewer agent tool calls. The most compelling at-scale validation of the compile-knowledge pattern.

**Products**: established players (Notion AI — the most mature multi-user/governed offering in this space, in our assessment; Mem 2.0, Reflect, Capacities, Tana) plus new entrants (llmwiki.app, Dume.ai, Remio.ai, REM Labs, Waykee Cortex, CacheZero). **Waykee Cortex** (waykee.com) is the strongest multi-user candidate: hierarchical inheritance (System → Module → Screen), Knowledge + Work layers, open source announced (AGPL v3; repo not yet published) — but early. The enterprise-governed adjacents are Microsoft's governed agent workflows over SharePoint/Copilot (SharePoint Knowledge Agent: https://techcommunity.microsoft.com/blog/spblog/introducing-knowledge-agent-in-sharepoint/4454154) and **Databricks Agent Bricks Knowledge Assistant** (GA Jan 2026; Unity Catalog governance via the Agent Bricks platform) — but both are retrieval-based, not compilation-based.

**Academic multi-user memory**: Collaborative Memory (arXiv:2505.18279 — private+shared tiers, bipartite access-control graphs, immutable provenance, up to 61% resource reduction at 50% memory overlap); Memory as a Service (arXiv:2506.22815 — memory decoupled into governable service modules); A-MEM (NeurIPS 2025, arXiv:2502.12110 — Zettelkasten-style self-organizing memory).

**Gap analysis and MemoryHub relevance**: what does not exist — a production-quality multi-user LLM wiki with governance, access control, and audit trails; conflict resolution for concurrent agent edits (HN flagged filesystem race conditions as fundamental); anything bridging personal and team use; enterprise SSO/RBAC/compliance versions. Karpathy's architecture maps well onto MemoryHub's structured memory, versioning, and scoped access control. The community is validating demand; **nobody is filling the governed/multi-user niche** — which is exactly what MemoryHub builds. (See docs/design/knowledge-compilation.md, which took up this thread.)

---

## 8. Google's Open Knowledge Format (OKF)

OKF v0.1 is a draft Apache-2.0 spec from GoogleCloudPlatform/knowledge-catalog (Knowledge Catalog is the April 2026 rebrand of Dataplex Universal Catalog); OKF is its vendor-neutral interchange format. Data model: **Knowledge Bundle** (a directory of markdown files with YAML frontmatter — the unit of distribution), **Concept** (one markdown file; ID = path minus `.md`; tangible assets or abstract ideas), **Links and Citations** (standard markdown links as directed, *untyped* edges; semantics live in surrounding prose). Only `type` is required (free-form string); unknown extension keys must be preserved; consumers must NOT reject bundles for missing fields, unknown types, or broken links — a deliberately low conformance bar optimizing adoption over correctness. Reserved files: `index.md` (progressive disclosure) and `log.md` (change history); versioning via git + `okf_version`. A companion Gemini-based enrichment agent does a BigQuery-metadata pass and a web-crawl pass; a Cytoscape.js visualizer and sample bundles (GA4, Stack Overflow, Bitcoin) exist.

- Spec: https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md

**Positioning**: OKF is firmly a semantic-layer (knowledge graph) format — it describes what things ARE, never why decisions were made. It is the spec-level formalization of Karpathy's llm-wiki impulse (raw sources / compiled wiki / index map directly), but where llm-wiki is a personal workflow, OKF is an org-to-org interchange format — the Parquet-to-BigQuery / OCI-to-Docker play. Like the llm-wiki implementations, it adds no governance, access control, or multi-user support.

**Design contrasts with MemoryHub** (different purposes, not competing choices): OKF's single required free-form field vs. MemoryHub's required scope/content/authenticated identity — adoption friction vs. governance guarantees; untyped prose-semantics links vs. typed relationships with a traversal API (agents at runtime need "all dependencies of X" without reading prose); structurally public bundles vs. scope hierarchy and RBAC; tolerate-everything consumption vs. surface-and-resolve contradiction detection; git versioning vs. internal versioning with `is_current` flags and provenance chains; static `index.md` vs. dynamic search-with-focus-bias (same information-architecture principle, different mechanism).

**Implications**: OKF *validates* MemoryHub's memory-vs-retrieval boundary (see planning/knowledge-layer.md §7) — the industry is drawing the same semantic-vs-procedural line as Section 1. Concretely: (1) **OKF as import/export format** — its permissive extension model lets MemoryHub-specific fields (scope, governance metadata, provenance, curation status) ride alongside without breaking conformance; (2) **the enrichment agent is prior art** for the extraction pipeline (#240) — asynchronous observation of operational data, structured extraction, human-in-the-loop promotion, on the semantic side what MemoryHub builds on the procedural side; (3) **governance is the differentiator** — don't compete on format; consume OKF and add access control, curation, provenance, contradiction detection, and runtime query. Governed memory (experiential/behavioral) paired with a governed RAG layer (semantic/factual) serves regulated customers where ungoverned alternatives are disqualified.

---

## 9. Ontology-Aware Contextualization of Memories

Organizations redefine, overload, and invert standard terminology — the norm, not an edge case, in regulated enterprises. Four motivating cases at increasing difficulty:

1. **SIPOC vs COPIS**: customer-first orgs reverse the Lean framework's ordering (https://en.wikipedia.org/wiki/SIPOC). Same concept, different label — a term registry solves it.
2. **HL7 FHIR**: 157 resource types in R5 (~145 in R4), thousands of spec pages — no context window holds it, and most interactions need a small slice. This is **progressive unfolding**: load the relevant domain slice based on focus, pull more on pivot. MemoryHub's focus tracking and search-with-focus-bias support this mechanically; the gap is that FHIR's formal inter-resource relationships live in the spec, not in the memory graph.
3. **Cross-organizational care records**: mapping between coding systems (ICD-10 vs SNOMED CT, NDC vs RxNorm — NLM publishes mapping tools like I-MAGIC precisely because these don't align 1:1) with patient-safety stakes; *overlapping* concepts with partial equivalence ("office visit" vs "outpatient encounter" bundling different things).
4. **The ontology gap**: standard ontologies exist (SNOMED CT, LOINC, ICD-10; NIST/MITRE frameworks; Basel/IFRS), but organizations customize them in undocumented ways — and that customization is precisely what an agent needs. Universal across healthcare, defense, finance, government.

### Three-layer progression (independently useful, naturally composing)

**Layer 1 — Term registry** (near-term; zero new infrastructure). Project/org-scoped memories tagged with a `terminology` domain define local usage, e.g. `scope: organizational, domain: terminology, weight: 0.9, content: "In this organization, 'COPIS' refers to Customer-Output-Process-Input-Supplier — the reverse of standard SIPOC. All process documentation uses COPIS."` The only addition is a convention: treat retrieved terminology memories as definitional context injected alongside operational memories. Breaks down when the same term has different definitions in different scopes.

**Layer 2 — Ambiguity detection** (medium-term; rides on graph-enhanced memory #170). Curated known-ambiguous terms; inferred ambiguity when terminology memories across scopes define the same term differently (a variant of contradiction detection — both definitions can be correct within their scopes, but cross-scope communication needs translation); and **cross-scope term resolution** producing structured mappings ("Org A's 'encounter' maps to Org B's 'visit' with these differences: [...]") stored as campaign-scoped memories. Typed relationships between terminology memories (synonym-of, narrower-than, maps-to, superseded-by) form a lightweight domain ontology without formal ontology tooling.

**Layer 3 — Ontology mapping engine** (long-term; only if regulated verticals become significant). MemoryHub does not *build* ontologies — it becomes the governed persistence layer for *mappings* between existing ones, generated externally (terminology services, tuned models, manual curation) and stored with provenance, versioning, and scope. E.g.: "Community Provider X's 'cardiac event' corresponds to ICD-10 I21–I25 in their claims feed, but their usage excludes unstable angina (I20.0), which our system includes."

### Interactions with existing work

- **Graph-enhanced memory (#170)**: the natural foundation for Layer 2 — terminology relationships are just another edge type.
- **Context compaction (#169)**: the compactor must not discard definitional memories during summarization (losing the "COPIS" definition means the agent falls back to general knowledge and says "SIPOC"). Needs compaction-resistant or high-retention-priority marking; terminology memories are one class deserving it.
- **Extraction pipeline (#240)**: can propose terminology memories when definitions occur in conversation ("when we say 'sprint' here, we mean a two-week planning cycle"), with human validation.
- **The knowledge/experiential boundary**: MemoryHub is not the source of truth for "what does FHIR Patient mean" (semantic layer — RAG territory) but for "how does *this organization* use FHIR Patient, and how does that differ from the standard."

### Open questions

Compaction interaction with progressive unfolding (re-fetch vs. compacted summary on pivot-back); retrieval priority (always-inject risks token bloat, search-bias risks missing critical definitions — likely hybrid: always-inject for current-focus terms); Layer 1 scaling limits (tens easy, hundreds need tagging, ~thousands need hierarchy and disambiguation); temporal drift (versioning tracks *that* definitions changed, not that usage has informally moved past them — #240 could detect divergence; unsolved); federation governance (who owns cross-org mappings — operational, not technical; contradiction detection as the flagging mechanism, human resolution workflow).

**Non-goals**: MemoryHub is not becoming an ontology management system (Protege, TopBraid, UMLS, BioPortal exist); no OWL/RDF/SPARQL (the memory graph is a property graph, deliberately); no LoRA/fine-tuning in the memory layer (belongs in model serving). The insight is narrow: a lightweight, governed terminology-aware layer on existing memory primitives removes an adoption barrier no amount of model training fixes.

---

## 10. Sources

### Papers
- Zep: Temporal Knowledge Graph Architecture for Agent Memory — https://arxiv.org/abs/2501.13956
- Mem0: Building Production-Ready AI Agents (LOCOMO methodology) — https://arxiv.org/abs/2504.19413; Zep's critique of the methodology — https://blog.getzep.com/lies-damn-lies-statistics-is-mem0-really-sota-in-agent-memory/
- MAGMA: Multi-Graph Agentic Memory Architecture — https://arxiv.org/abs/2601.03236 (repo: https://github.com/FredJiang0324/MAGMA)
- Graph-based Agent Memory: Taxonomy, Techniques, and Applications — https://arxiv.org/html/2602.05665 (DEEP-PolyU; the definitive survey: five graph structures, four technique categories; companion list https://github.com/DEEP-PolyU/Awesome-GraphMemory)
- Hindsight is 20/20 — https://arxiv.org/abs/2512.12818 (benchmark detail: https://github.com/vectorize-io/hindsight-benchmarks)
- LongMemEval (ICLR 2025) — https://arxiv.org/abs/2410.10813
- MemMachine — https://arxiv.org/abs/2604.04853
- EverMemOS — https://arxiv.org/abs/2601.02163
- Graph-Native Cognitive Memory: Formal Belief Revision Semantics — https://arxiv.org/abs/2603.17244
- RAG Meets Temporal Graphs — https://arxiv.org/html/2510.13590v1
- Beyond the Context Window: Fact-Based Memory vs. Long-Context LLMs — https://arxiv.org/html/2603.04814v1 (nuanced result: long-context recalls more; structured memory competitive with a structurally cheaper cost profile)
- Graphs Meet AI Agents — https://arxiv.org/html/2506.18019v1
- Graph Retrieval-Augmented Generation: A Survey — https://dl.acm.org/doi/10.1145/3777378
- KG construction from LLMs: Scientific Reports Feb 2026 — https://www.nature.com/articles/s41598-026-38066-w; Applied Sciences Mar 2025 — https://www.mdpi.com/2076-3417/15/7/3727; LLM-empowered KG construction survey — https://arxiv.org/html/2510.20345v1
- Awesome-Memory-for-Agents paper list (Tsinghua C3I) — https://github.com/TsinghuaC3I/Awesome-Memory-for-Agents
- Collaborative Memory — https://arxiv.org/abs/2505.18279; Memory as a Service — https://arxiv.org/abs/2506.22815; A-MEM — https://arxiv.org/abs/2502.12110
- GraphRAG: From Local to Global — https://arxiv.org/abs/2404.16130

### Repositories and documentation
- Graphiti — https://github.com/getzep/graphiti
- Neo4j Agent Memory — https://github.com/neo4j-labs/agent-memory / https://neo4j.com/labs/agent-memory/ (POLE+O: https://neo4j.com/labs/agent-memory/explanation/poleo-model/; extraction pipeline: https://neo4j.com/labs/agent-memory/explanation/extraction-pipeline/)
- Mem0 Graph Memory — https://docs.mem0.ai/open-source/features/graph-memory
- Microsoft GraphRAG — https://github.com/microsoft/graphrag
- FalkorDB — https://github.com/FalkorDB/FalkorDB
- Cognee — https://github.com/topoteretes/cognee
- Hindsight — https://github.com/vectorize-io/hindsight
- MemMachine — https://github.com/MemMachine/MemMachine
- LlamaIndex PropertyGraphIndex — https://www.llamaindex.ai/blog/introducing-the-property-graph-index-a-powerful-new-way-to-build-knowledge-graphs-with-llms
- Apache AGE — https://github.com/apache/age / https://age.apache.org/ (Top-Level Project announcement: https://news.apache.org/foundation/entry/the-apache-software-foundation-announces83)
- Kuzu archival — https://www.theregister.com/2025/10/14/kuzudb_abandoned/ (forks overview: https://szarnyasg.org/posts/kuzu-forks/)
- Neo4j read privileges (hidden vs nonexistent) — https://neo4j.com/docs/operations-manual/current/authentication-authorization/privileges-reads/
- OKF / knowledge-catalog — https://github.com/GoogleCloudPlatform/knowledge-catalog / https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md

### Industry reports and posts
- Mem0 State of AI Agent Memory 2026 — https://mem0.ai/blog/state-of-ai-agent-memory-2026
- Gartner context graphs (paywalled; via Atlan) — https://atlan.com/know/gartner-context-graphs/; Atlan: LLM Wiki vs RAG — https://atlan.com/know/llm-wiki-vs-rag-knowledge-base/
- Mastra: agent memory levels — https://mastra.ai/articles/agent-memory (video: https://www.youtube.com/watch?v=18iIHQtIPmc); Observational Memory — https://mastra.ai/research/observational-memory
- Sakhatsky: You Probably Don't Need a Graph Database — https://medium.com/@msakhatsky/you-probably-dont-need-a-graph-database-for-your-knowledge-graph-7178054fe3d3
- Zep: Stop Using RAG for Agent Memory — https://blog.getzep.com/stop-using-rag-for-agent-memory/
- "Benchmark Theatre" (memory benchmark criticism) — https://essays.bloo-mind.ai/posts/2026-05-20-mem-eval/
- Apache AGE vs recursive CTE benchmark — https://medium.com/@sjksingh/postgresql-showdown-complex-joins-vs-native-graph-traversals-with-apache-age-78d65f2fbdaa; AGE on Azure performance guidance — https://learn.microsoft.com/en-us/azure/postgresql/azure-ai/generative-ai-age-performance
- Graphiti + FalkorDB — https://www.falkordb.com/blog/graphiti-falkordb-multi-agent-performance/
- AWS: Mem0 + ElastiCache + Neptune — https://aws.amazon.com/blogs/database/build-persistent-memory-for-agentic-ai-applications-with-mem0-open-source-amazon-elasticache-for-valkey-and-amazon-neptune-analytics/
- Karpathy llm-wiki: gist + tweet + VentureBeat + HN threads (linked in Section 7)
- Obsidian ecosystem: https://github.com/kepano/obsidian-skills and the repos linked in Section 7
- AKM / knowledge engineering: https://www.dsebastien.net/agentic-knowledge-management-the-next-evolution-of-pkm/, https://jykim.github.io/AI4PKM/, Meta organizational knowledge — https://engineering.fb.com/2026/04/06/developer-tools/how-meta-used-ai-to-map-tribal-knowledge-in-large-scale-data-pipelines/, KPMG — https://kpmg.com/us/en/articles/2026/why-knowledge-engineering-is-the-key-to-ai-agent-value.html
- Enterprise products: SharePoint Knowledge Agent — https://techcommunity.microsoft.com/blog/spblog/introducing-knowledge-agent-in-sharepoint/4454154, Databricks Knowledge Assistant GA — https://www.databricks.com/blog/agent-bricks-knowledge-assistant-now-generally-available-turning-enterprise-knowledge-answers (governance platform: https://www.databricks.com/blog/agent-bricks-governed-enterprise-agent-platform), Waykee Cortex — https://waykee.com/
- llm-wiki implementations: https://github.com/lucasastorian/llmwiki (https://llmwiki.app/), https://github.com/MehmetGoekce/llm-wiki, https://github.com/Pratiyush/llm-wiki, https://github.com/kfchou/wiki-skills, https://github.com/Astro-Han/karpathy-llm-wiki, https://github.com/ussumant/llm-wiki-compiler, https://github.com/hellohejinyu/llm-wiki
