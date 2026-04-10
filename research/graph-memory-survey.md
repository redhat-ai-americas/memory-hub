# Graph-Based Memory for AI Agents: State of the Art Survey

**Date**: April 2026
**Author**: Wes Jackson
**Purpose**: Strategic planning for MemoryHub graph memory capabilities

## Table of Contents

1. [What Graph Memory Means in the Agent Context](#1-what-graph-memory-means-in-the-agent-context)
2. [Existing Implementations](#2-existing-implementations)
3. [Graph Databases for Agent Memory](#3-graph-databases-for-agent-memory)
4. [Academic Research](#4-academic-research)
5. [Architecture Patterns](#5-architecture-patterns)
6. [Governance](#6-governance)
7. [The PostgreSQL Angle](#7-the-postgresql-angle)
8. [Implications for MemoryHub](#8-implications-for-memoryhub)
9. [Sources](#9-sources)

---

## 1. What Graph Memory Means in the Agent Context

### The Problem with Flat Memory

Vector memory retrieves facts by semantic similarity. If an agent stores "Wes prefers Podman over Docker" and later queries "container runtime preferences," cosine similarity will surface the right fact. But vector memory loses *structure*. It cannot answer "what tool preferences does Wes have, and which ones conflict with organizational policy?" because answering that requires traversing relationships, not computing distances.

Key-value memory (session state, user profiles) is fast but rigid. It stores what you anticipate needing; it cannot surface emergent connections.

Graph memory encodes entities, relationships, and properties as first-class objects. An agent's memory becomes a traversable network where facts connect to other facts through typed, directed edges. This enables multi-hop reasoning ("Wes works on MemoryHub, which uses PostgreSQL, which has the AGE extension, which supports Cypher"), temporal reasoning ("Wes preferred Docker in 2024 but switched to Podman in 2025"), and contradiction detection ("user memory says Docker, org policy says Podman").

### Types of Graph Memory

The field uses several overlapping terms. The distinction is essentially hierarchical:

**Knowledge graphs** are semantic networks of entities connected by typed relationships, often following an ontology. They represent objective world knowledge (facts, entities, taxonomies). In the agent context, a knowledge graph might store "PostgreSQL *has_extension* pgvector," "pgvector *enables* vector_search," and "MemoryHub *uses* PostgreSQL." Knowledge graphs tend to be relatively static and schema-driven.

**Memory graphs** are knowledge graphs specifically optimized for agent persistence and temporal awareness. Unlike static knowledge graphs, memory graphs track how facts change over time, maintain provenance to source data, and support both prescribed and learned ontology. Graphiti's "temporal context graphs" are the canonical example: every edge carries validity intervals, and contradictions are resolved by invalidating old edges rather than deleting them.

**Relationship graphs** focus specifically on connections between entities without necessarily carrying the rich property/attribute model of a full knowledge graph. Social graphs, dependency graphs, and organizational hierarchy graphs fall here.

**Property graphs** are the technical storage model underlying all of the above. Nodes and edges carry arbitrary key-value properties. Neo4j, FalkorDB, Memgraph, and Kuzu all implement property graph models. Property graphs are the implementation layer; knowledge graphs and memory graphs are the semantic application layer built on top.

**Temporal knowledge graphs** extend standard knowledge graphs with explicit time dimensions. Every fact has a validity window. Graphiti's bi-temporal model distinguishes *when a fact was true in the world* from *when the system learned about it*, enabling time-travel queries and forensic analysis.

**Hypergraphs** allow a single edge to connect more than two nodes, preserving n-ary relationships. MAGMA (arXiv:2601.03236) uses orthogonal semantic, temporal, causal, and entity graphs to represent each memory item across multiple relational dimensions simultaneously.

### Graph Memory vs. Vector Memory vs. Hybrid

The Mem0 team's 2026 State of AI Agent Memory report quantifies the tradeoff:

| Approach | Accuracy (LOCOMO) | p95 Latency | Tokens/Query |
|----------|-------------------|-------------|--------------|
| Full context | 72.9% | 17.12s | ~26,000 |
| Mem0g (graph+vector) | 68.4% | 2.59s | ~1,800 |
| Mem0 (vector only) | 66.9% | 1.44s | ~1,800 |
| RAG baseline | 61.0% | 0.70s | — |

Graph memory improves accuracy on multi-hop and relationship-dependent queries at the cost of higher latency (2.59s vs 1.44s p95). The accuracy gap is modest on general benchmarks but widens significantly on complex, multi-hop questions where relationship reasoning matters.

On the more demanding LongMemEval benchmark (ICLR 2025), the picture is starker: Hindsight's graph-structured four-network architecture achieved 91.4% overall accuracy, while Mem0 scored 49.0% on the same benchmark. The systems that score highest on LongMemEval consistently use structured memory with graph or multi-network architectures.

The consensus as of early 2026: **vector memory is sufficient for simple personalization** (user preferences, session context). **Graph memory becomes essential for complex entity relationships** — medical patient contexts, enterprise account hierarchies, technical system interdependencies, multi-agent coordination where relationship reasoning matters.

---

## 2. Existing Implementations

### 2.1 Zep / Graphiti

**Paper**: arXiv:2501.13956 (January 2025)
**Repository**: [github.com/getzep/graphiti](https://github.com/getzep/graphiti)
**Status**: Production, open-source core + commercial Zep Cloud

Graphiti is the most technically ambitious graph memory system in production. Its architecture has three hierarchical subgraph tiers:

**Episode subgraph**: Raw data ingestion. Every conversation turn, document chunk, or structured data record enters as an episode node. Episodes are the provenance layer — every derived entity and relationship traces back to its source episodes.

**Semantic entity subgraph**: Entities and relationships extracted from episodes. Entity extraction uses LLM-based pipelines. Entity deduplication uses hybrid search constrained to edges between the same entity pairs, preventing erroneous combinations and limiting the search space. Relationship extraction creates typed, directed edges between entities.

**Community subgraph**: Community detection via label propagation (not Leiden) groups related entities into communities. Label propagation was chosen over Leiden because of its straightforward dynamic extension — as new data enters the graph, communities can be incrementally updated without full recomputation.

The **bi-temporal model** is Graphiti's most distinctive feature. Every edge carries four timestamps:
- `t_created` / `t_expired`: when the system learned/invalidated the fact
- `t_valid` / `t_invalid`: when the fact was true in the world

This enables time-travel queries ("what did we know about X as of date Y?") and forensic analysis. When new information contradicts existing facts, the old edge is invalidated (not deleted), preserving full history.

**Contradiction resolution**: An LLM compares new edges against semantically related existing edges. When temporally overlapping contradictions are found, affected edges are invalidated by setting their temporal validity to the validity of the invalidating edge. This is non-lossy — the old fact remains queryable for historical analysis.

**Performance**: 94.8% on the DMR benchmark vs. 93.4% for MemGPT (previous SOTA). Graphiti now supports both Neo4j and FalkorDB backends. The FalkorDB integration targets multi-agent environments with sub-10ms query performance and per-agent graph isolation.

### 2.2 Mem0 / Mem0g

**Documentation**: [docs.mem0.ai/open-source/features/graph-memory](https://docs.mem0.ai/open-source/features/graph-memory)
**Repository**: Open-source + Mem0 Cloud
**Status**: Production (used by 70+ companies as of early 2026)

Mem0 is the most widely deployed agent memory system. Mem0g is its graph-enhanced variant that builds a directed, labeled knowledge graph alongside the vector store during the extraction phase:

1. An **entity extractor** identifies nodes from conversation text
2. A **relations generator** infers labeled edges connecting those nodes
3. Embeddings land in the vector store; nodes and edges flow into the graph backend

Supported graph backends: **Neo4j** (established) and **Kuzu** (added September 2025, embedded, no separate server process). Mem0 supports 19 vector store backends (Qdrant, Chroma, Weaviate, FAISS, Pinecone, MongoDB, etc.).

The **multi-scope memory model** (user, agent, session, org-level) provides flexible retrieval granularity. Async memory writes became default in 2025, preventing write operations from increasing response latency.

Key tradeoff: Mem0g achieves 68.4% vs 66.9% accuracy over vector-only Mem0 on LOCOMO, but at 2.59s vs 1.44s p95 latency. The graph benefit is real but comes at a cost. Mem0's guidance: enable graph memory when your use case involves complex entity relationships; for simpler personalization, vector-only performs adequately with lower latency.

**Recent additions**: Procedural memory (third type alongside episodic and semantic), metadata filtering for structured queries beyond semantic search, reranking layers, actor-aware memory in multi-agent systems.

### 2.3 Microsoft GraphRAG

**Repository**: [github.com/microsoft/graphrag](https://github.com/microsoft/graphrag)
**Status**: Open-source, actively maintained

GraphRAG builds entity-centric knowledge graphs at index time through an LLM-driven pipeline:

1. **Entity extraction**: LLM extracts named entities and descriptions from each text unit
2. **Entity summarization**: Descriptions for every instance of an entity across text units are combined into a single summary
3. **Relationship extraction**: LLM identifies relationships between entities
4. **Community detection**: Entities are grouped into thematic clusters using the Leiden algorithm
5. **Community summarization**: LLM summarizes entity and relationship information within each community

Two retrieval modes: **Local search** (entity-centric, good for specific questions) and **Global search** (community-centric, good for broad thematic questions).

**Limitations for agent memory**: GraphRAG is designed for batch indexing of document corpora, not real-time conversational memory. It doesn't do temporal reasoning natively — if an older document contradicts a newer one, both are surfaced without temporal ordering. It also re-processes everything at index time, which is expensive for incremental updates. GraphRAG is better understood as a document understanding pipeline that produces knowledge graphs, rather than an agent memory system per se.

However, GraphRAG's community detection and summarization patterns are directly applicable to agent memory. The concept of grouping related entities into communities and generating summaries for each community is used by Graphiti and other systems.

### 2.4 Neo4j Agent Memory

**Repository**: [github.com/neo4j-labs/agent-memory](https://github.com/neo4j-labs/agent-memory)
**Documentation**: [neo4j.com/labs/agent-memory](https://neo4j.com/labs/agent-memory/)
**Status**: Production, open-source (Neo4j Labs)

The most comprehensive graph-native agent memory library, with a three-tier architecture:

**Short-term memory**: Full conversation history with sequential message chains, session management, metadata-based search, and LLM-generated conversation summaries.

**Long-term memory**: A knowledge graph of entities (people, places, orgs), preferences, facts, and relationships built automatically from conversations. Uses the **POLE+O entity model** (Person, Object, Location, Event, Organization) for entity classification. Includes temporal validity tracking, deduplication, and geospatial query capabilities.

**Reasoning memory**: Records how the agent solved problems — every thought, tool call, and outcome. Enables trace similarity search (finding similar past reasoning patterns), tool statistics, and streaming trace recording. This is unique among agent memory systems.

**Entity extraction pipeline** uses a three-stage cascade with configurable merge strategies:
1. **spaCy**: Fast rule-based extraction (~5ms)
2. **GLiNER2**: Zero-shot transformer-based extraction (~50ms) with custom entity types
3. **LLM fallback**: GPT-4o-mini for complex cases (~500ms) with relationship extraction via GLiREL

The system supports 8 domain schemas (podcast, news, medical, legal, etc.), 5 merge strategies, and handles 100K+ token documents through streaming extraction. Background enrichment includes Wikipedia descriptions, images, Wikidata IDs, and geocoding for locations.

**Framework integrations**: LangChain, Pydantic AI, LlamaIndex, Google ADK, Strands, CrewAI, OpenAI Agents, Microsoft Agent Framework. Also provides an MCP server with 16 tools.

**Requirements**: Neo4j 5.20+ (Enterprise Edition recommended for fine-grained access control), Python 3.10+, OpenAI API key for embeddings/LLM extraction.

### 2.5 Hindsight

**Paper**: arXiv:2512.12818 (December 2025)
**Repository**: [github.com/vectorize-io/hindsight](https://github.com/vectorize-io/hindsight)
**Status**: Open-source, production

Hindsight organizes agent memory into **four separate networks**:

1. **World network**: Objective facts about the external environment
2. **Bank network**: The agent's own experiences and actions (written in first person)
3. **Opinion network**: Subjective judgments with confidence scores that update as new evidence arrives
4. **Observation network**: Preference-neutral summaries of entities synthesized from underlying facts

Two key components drive the system:

**TEMPR** (Temporal Entity Memory Priming Retrieval) handles memory retention and recall through four parallel searches: semantic vector similarity, BM25 keyword matching, graph traversal through shared entities, and temporal filtering. Results are merged using Reciprocal Rank Fusion and a neural reranker.

**CARA** (Coherent Adaptive Reasoning Agents) handles preference-aware reflection with configurable disposition parameters: skepticism, literalism, and empathy. This addresses inconsistent reasoning across sessions.

**Performance**: 91.4% on LongMemEval (highest recorded score at time of publication). Multi-session questions improved from 21.1% to 79.7%. Temporal reasoning jumped from 31.6% to 79.7%. Knowledge update questions improved from 60.3% to 84.6%.

### 2.6 Cognee

**Repository**: [github.com/topoteretes/cognee](https://github.com/topoteretes/cognee)
**Status**: Production (70+ companies, including Bayer), $7.5M seed round (February 2026)

Cognee is a knowledge engine that combines vector search, graph databases, and cognitive science approaches. The pipeline flows from ingestion (30+ supported sources), to enrichment (embeddings and graph "memify" steps), to retrieval (combining time filters, graph traversal, and vector similarity).

Cognee went from ~2,000 pipeline runs to over 1 million in 2025 — 500x growth in a single year. It integrates with Amazon Neptune Analytics, LlamaIndex, and Google ADK.

Key differentiator: Cognee approaches memory from a cognitive science angle rather than pure knowledge graph construction, treating memories as things that should be consolidated, reinforced, and forgotten based on usage patterns.

### 2.7 LlamaIndex PropertyGraphIndex

**Documentation**: [llamaindex.ai/blog/introducing-the-property-graph-index](https://www.llamaindex.ai/blog/introducing-the-property-graph-index-a-powerful-new-way-to-build-knowledge-graphs-with-llms)
**Status**: Production

LlamaIndex's PropertyGraphIndex replaced the older KnowledgeGraphIndex with richer modeling capabilities. Key features:

- **Schema-guided extraction**: Define allowed entity types, relationship types, and their connections. The LLM only extracts graph data conforming to the schema.
- **Multiple extraction methods**: Including implicit extraction (LLM identifies entities/relationships) and explicit extraction (rule-based).
- **In-memory graph store**: `SimplePropertyGraphStore` for development; Neo4j, FalkorDB, Nebula for production.
- **Flexible memory blocks**: For various agent memory approaches including fact extraction and vector memory.

PropertyGraphIndex is a building block rather than a complete agent memory system. It provides the graph construction and querying primitives that can be composed into a memory layer.

### 2.8 MAGMA

**Paper**: arXiv:2601.03236 (January 2026)
**Repository**: [github.com/FredJiang0324/MAMGA](https://github.com/FredJiang0324/MAMGA)
**Status**: Research

MAGMA (Multi-Graph based Agentic Memory Architecture) represents each memory item across **orthogonal semantic, temporal, causal, and entity graphs**. This multi-graph representation is the key innovation — rather than a single monolithic knowledge graph, MAGMA maintains parallel graph views of the same memory items.

A hierarchical, intent-aware query mechanism selects relevant relational views, traverses them independently, and fuses the resulting subgraphs into a compact, type-aligned context for generation. An Adaptive Traversal Policy routes retrieval based on query intent, enabling efficient pruning of irrelevant graph regions.

**Performance**: Up to 45.5% higher reasoning accuracy on long-context benchmarks (LoCoMo, LongMemEval) while reducing token consumption by over 95% and demonstrating 40% faster query latency compared to prior methods.

### 2.9 Other Notable Systems

**MemMachine** ([github.com/MemMachine/MemMachine](https://github.com/MemMachine/MemMachine)): Ground-truth-preserving memory system that stores entire conversational episodes rather than lossy LLM-extracted summaries. Achieves 93.0% on LongMemEval_S with gpt-4.1-mini.

**Observational Memory** (Mastra Research): Two background agents — an Observer and a Reflector — watch conversations and maintain a dense observation log. Achieves 94.87% on LongMemEval with gpt-5-mini (highest recorded score as of April 2026).

**Supermemory** ([supermemory.ai](https://supermemory.ai)): Open-source personal knowledge vault with cross-application retrieval. Privacy-focused, local-first. Consumer-oriented rather than enterprise/multi-tenant.

**LangMem** (LangChain): Tool-based integration with LangGraph workflows using embedding-supported persistent storage. Namespace partitioning for multi-tenant scenarios. Requires LangGraph framework.

**Letta** (formerly MemGPT): Agent runtime with agents directly editing memory blocks through specialized tools. White-box memory inspection, explicit agent control over storage decisions.

---

## 3. Graph Databases for Agent Memory

### 3.1 Comparison Matrix

| Feature | Neo4j | FalkorDB | Memgraph | Kuzu | Apache AGE | Amazon Neptune |
|---------|-------|----------|----------|------|------------|---------------|
| **Model** | Property graph | Property graph | Property graph | Property graph | Property graph on PG | Property + RDF |
| **Query language** | Cypher | Cypher subset | Cypher | Cypher | openCypher subset | Gremlin, SPARQL, openCypher |
| **Deployment** | Standalone / K8s | Standalone / K8s | Standalone / K8s | Embedded (in-process) | PG extension | AWS managed |
| **Vector search** | Built-in (5.20+) | Built-in | Built-in | Built-in | Via pgvector | Neptune Analytics |
| **Latency (agent workload)** | ~10-50ms | Sub-10ms (claimed) | Sub-10ms (in-memory) | Sub-3ms (embedded) | Varies (PG-dependent) | ~50-100ms |
| **FIPS compliance** | Configurable TLS/auth | Unknown | Unknown | N/A (embedded) | Inherits from PG | AWS FIPS endpoints |
| **K8s/OpenShift story** | Helm chart, operator | Helm chart | Helm chart | N/A (library) | N/A (PG extension) | AWS managed |
| **License** | GPLv3 / Commercial | Server Side PL | BSL 1.1 | MIT (archived) | Apache 2.0 | Proprietary |
| **Agent memory integrations** | Neo4j Agent Memory, Graphiti, Mem0, LangChain | Graphiti, Mem0 | LangChain, MCP Lab | Mem0 | Azure GraphRAG sample | Mem0, Cognee, Strands |

### 3.2 Neo4j

The most mature graph database with the richest ecosystem for AI agent memory. Neo4j Agent Memory is the only library offering three-tier memory (short-term, long-term, reasoning) natively. Graphiti uses Neo4j as its primary backend.

**Strengths**: Most comprehensive Cypher support, fine-grained RBAC (Enterprise Edition) with label-level and relationship-type-level permissions, largest ecosystem of integrations, vector search built into the database (5.20+), well-documented K8s deployment via Helm.

**Weaknesses**: Enterprise features (fine-grained access control, clustering) require commercial license. GPLv3 community edition has copyleft implications. Resource-heavy for simple use cases. Separate infrastructure to manage.

**Agent workload fit**: Excellent. The combination of native graph traversal, vector search, and the Neo4j Agent Memory library provides the most complete agent memory solution available. The three-stage entity extraction pipeline (spaCy -> GLiNER -> LLM) is production-tested.

### 3.3 FalkorDB

Redis-compatible graph database using GraphBLAS for sparse adjacency matrix operations. Originally RedisGraph, now independent.

**Strengths**: Extremely low latency (sub-10ms for graph queries, sub-140ms for full agent memory operations). Graphiti integration for multi-agent environments with per-agent graph isolation. Good fit for real-time agent workloads where latency matters.

**Weaknesses**: Smaller ecosystem than Neo4j. Cypher support is a subset, not full compatibility. Less mature tooling. Enterprise governance features are less developed.

**Agent workload fit**: Strong for latency-sensitive multi-agent deployments. The Graphiti+FalkorDB combination is production-proven for multi-tenant agent memory.

### 3.4 Memgraph

In-memory graph database written in C++ with full Cypher support. Positions itself for real-time graph analytics and AI memory.

**Strengths**: In-memory performance, full Cypher support, SQL2Graph and Unstructured2Graph tooling for data ingestion, MCP Client in Memgraph Lab. Three types of long-term memory (semantic, episodic, procedural) stored as a unified graph.

**Weaknesses**: BSL 1.1 license (not fully open source). Smaller community than Neo4j. Less proven in agent memory specifically — more focused on graph analytics.

**Agent workload fit**: Viable, especially if real-time analytics on the memory graph is important. The MCP client integration is interesting for our context.

### 3.5 Kuzu

Embedded property graph database — runs in-process, no separate server. Implements full Cypher.

**Strengths**: Zero operational overhead (embedded), sub-3ms recall latency, MIT license. Mem0 supports it as a graph backend. Good for development and testing. Good for single-agent or small-scale deployments.

**Weaknesses**: The original KuzuDB team archived the project in October 2025. Vela Partners maintains a fork with concurrent multi-writer support. No server mode means no shared access across processes. Not suitable for multi-tenant production deployments.

**Agent workload fit**: Good for embedded scenarios (CLI tools, single-agent applications) where operational simplicity matters. Not suitable for our multi-tenant server architecture.

### 3.6 Apache AGE (PostgreSQL Extension)

Adds openCypher-compatible graph queries to PostgreSQL.

**Strengths**: Runs on existing PostgreSQL infrastructure — no new database to manage. Cypher queries alongside SQL. ACID guarantees inherited from PostgreSQL. Azure Database for PostgreSQL supports it natively. FIPS compliance inherited from PostgreSQL.

**Weaknesses**: Not a native graph database — uses relational storage under the hood. No automatic index creation for graphs (must be created explicitly). Some queries don't use indexes (particularly those without WHERE clauses). Performance for complex multi-hop traversals can lag behind native graph databases. Cypher support is a subset of openCypher. Still Apache Incubator stage. Limited graph algorithm support. One benchmark showed 40x speed difference favoring SQL recursive CTEs for a specific use case.

**Agent workload fit**: See [Section 7](#7-the-postgresql-angle) for detailed analysis. The short answer: adequate for shallow graphs and simple traversals, but dedicated graph databases provide materially better performance and features for deeper graph workloads.

### 3.7 Amazon Neptune

AWS-managed graph database supporting Gremlin, SPARQL, and openCypher.

**Strengths**: Fully managed, no operational burden. Neptune Analytics provides in-memory graph processing for complex queries. FIPS endpoints available. Integrates with Mem0, Cognee, and AWS Strands Agent SDK. GenAI Agents for Neptune (February 2026) assist with prototyping.

**Weaknesses**: AWS lock-in. Higher latency than self-managed alternatives (~50-100ms). No on-premises deployment option. Not suitable for OpenShift-native architecture.

**Agent workload fit**: Good for AWS-native deployments. Not relevant for MemoryHub's OpenShift-first architecture.

### 3.8 ArangoDB

Multi-model database supporting document, graph, and key-value in a single engine.

**Strengths**: Multi-model means one database for multiple data patterns. AutoGraph for automatic knowledge graph construction from raw text. Per-domain RAG partitions with intelligent query routing.

**Weaknesses**: Jack-of-all-trades risk — graph performance doesn't match dedicated graph databases. Smaller AI agent memory ecosystem. Complex operational model.

**Agent workload fit**: Interesting multi-model story but not compelling enough versus Neo4j + pgvector for our use case.

---

## 4. Academic Research

### 4.1 Surveys and Taxonomies

**"Graph-based Agent Memory: Taxonomy, Techniques, and Applications"** (arXiv:2602.05665, February 2026, DEEP-PolyU). The definitive survey as of early 2026. Establishes a taxonomy of five primary graph structures for agent memory:

1. **Knowledge graphs**: Triple-based (entity-relation-entity) structures
2. **Hierarchical trees**: Multi-level DAG organization
3. **Temporal graphs**: Quad-tuple representations with bi-temporal modeling
4. **Hypergraphs**: N-ary relations for complex multi-entity interactions
5. **Hybrid architectures**: Combining static knowledge graphs with dynamic vector stores

The survey identifies four key technique categories:
- **Extraction**: Transforms raw observations into structured memory (entity-relation triple extraction, semantic embeddings, summarization, event segmentation, multimodal description generation)
- **Retrieval**: Six operator categories (similarity-based, rule-based, temporal-based, graph-based, RL-adaptive, agent-based)
- **Evolution**: Consolidation (abstracting patterns), reasoning (deriving implicit relationships), reorganization (restructuring topology), external exploration (environmental grounding)
- **Storage**: Property graph databases, in-memory graphs, hybrid vector+graph stores

Companion resource list: [github.com/DEEP-PolyU/Awesome-GraphMemory](https://github.com/DEEP-PolyU/Awesome-GraphMemory)

**"Graphs Meet AI Agents: Taxonomy, Progress, and Future Opportunities"** (arXiv:2506.18019, June 2025). Broader survey covering graphs in agent planning, execution, memory, and multi-agent coordination. Establishes that graph structures empower four core agent functionalities.

**"Memory in the Age of AI Agents: A Survey"** (Tsinghua C3I, December 2025). Covers memory types (episodic, semantic, procedural), memory operations, and evaluation benchmarks. Companion paper list: [github.com/TsinghuaC3I/Awesome-Memory-for-Agents](https://github.com/TsinghuaC3I/Awesome-Memory-for-Agents)

### 4.2 Knowledge Graph Construction from Conversations

**"The construction and refined extraction techniques of knowledge graph based on large language models"** (Scientific Reports, February 2026). Proposes a framework integrating domain-adapted LLMs with multimodal knowledge fusion. Fine-tunes general-purpose LLMs on domain-specific corpora to enhance entity and relationship identification.

**"Knowledge Graph Construction: Extraction, Learning, and Evaluation"** (Applied Sciences, March 2025). Comprehensive review of KG construction along three dimensions: extraction techniques, learning paradigms, and evaluation methodology.

**SF-GPT** (2025). Three-module pipeline for knowledge triple extraction: Entity Extraction Filter, Entity Alignment Generator (enhancing semantic richness), and Self-Fusion Subgraph strategy (reducing noise). Achieved 89.7% precision and 92.3% recall in entity extraction.

**"LLM-empowered knowledge graph construction: A survey"** (arXiv:2510.20345, October 2025). Comprehensive survey of LLM-based approaches to KG construction, covering entity recognition, relation extraction, and schema generation.

### 4.3 Graph-Enhanced Agent Memory

**Zep paper** (arXiv:2501.13956, January 2025). Establishes the temporal knowledge graph architecture for agent memory. Demonstrates that dynamic KG construction from conversations outperforms static RAG approaches.

**MAGMA** (arXiv:2601.03236, January 2026). Multi-graph approach with orthogonal semantic, temporal, causal, and entity graphs. Up to 45.5% higher reasoning accuracy while reducing token consumption by 95%.

**Hindsight** (arXiv:2512.12818, December 2025). Four-network structured memory (world, bank, opinion, observation) with TEMPR retrieval and CARA reflection. 91.4% on LongMemEval.

**"Graph-Native Cognitive Memory for AI Agents: Formal Belief Revision Semantics for Versioned Memory Architectures"** (arXiv:2603.17244, March 2026). Formalizes belief revision in graph-based agent memory using AGM postulates. Addresses how agents should update beliefs when new evidence contradicts existing knowledge.

**"RAG Meets Temporal Graphs: Time-Sensitive Modeling and Retrieval for Evolving Knowledge"** (arXiv:2510.13590, October 2025). Addresses temporal reasoning in GraphRAG systems, modeling how knowledge evolves over time.

**"Beyond the Context Window: A Cost-Performance Analysis of Fact-Based Memory vs. Long-Context LLMs for Persistent Agents"** (arXiv:2603.04814, March 2026). Compares fact-based memory systems against simply using large context windows. Finds that structured memory is more cost-effective at scale.

### 4.4 Benchmarks

**LongMemEval** (ICLR 2025, arXiv:2410.10813). 500 manually created questions testing five core memory abilities: information extraction, multi-session reasoning, temporal reasoning, knowledge updates, and abstention. The standard benchmark for agent memory evaluation as of 2026.

Top scores (as of April 2026):
| System | LongMemEval Score | Model |
|--------|-------------------|-------|
| Observational Memory | 94.87% | gpt-5-mini |
| MemMachine | 93.0% | gpt-4.1-mini |
| Hindsight | 91.4% | — |
| EverMemOS | 83.0% | — |

**LOCOMO** (earlier benchmark). Used by Mem0 for their State of Agent Memory reports. Less demanding than LongMemEval.

**DMR** (Deep Memory Retrieval). Used by Zep. Zep scored 94.8% vs. MemGPT's 93.4%.

### 4.5 GraphRAG vs. Agent Memory Graphs

GraphRAG and agent memory graphs are related but serve different purposes:

**GraphRAG** builds knowledge graphs from document corpora at index time. It's a batch process designed for document understanding and question answering over static collections. The graph is rebuilt when documents change.

**Agent memory graphs** are built incrementally from conversations, tool interactions, and observations in real-time. They must handle streaming updates, temporal reasoning, contradiction resolution, and per-agent/per-session scoping.

The relationship: GraphRAG pioneered techniques (entity extraction, community detection, summarization) that agent memory systems now use in streaming/incremental form. Graphiti explicitly positions itself as the "post-RAG" solution — using GraphRAG-style extraction but with temporal awareness and incremental updates.

---

## 5. Architecture Patterns

### 5.1 Entity Extraction Pipelines

The production pattern for entity extraction has converged on a **multi-stage cascade** with cost-performance tradeoffs at each stage:

**Stage 1 — Rule-based (spaCy)**: ~5ms latency. Fast pattern matching for common entity types (person names, locations, organizations, dates). Good recall for well-structured text, misses domain-specific entities.

**Stage 2 — Zero-shot neural (GLiNER2)**: ~50ms latency. Transformer-based extraction that accepts custom entity type descriptions. No training required for new entity types. Good balance of speed and accuracy for domain-specific entities.

**Stage 3 — LLM fallback**: ~500ms latency. Full language model extraction for complex cases. Highest accuracy but highest cost. Used for relationship extraction (GLiREL) and cases where stages 1-2 miss entities.

**Merge strategies**: Different stages may extract overlapping or conflicting entities. Neo4j Agent Memory supports 5 merge strategies. The simplest is "prefer later stage" (LLM results override GLiNER, which overrides spaCy). More sophisticated strategies use confidence scores and entity type matching.

**Entity deduplication**: Critical for preventing graph bloat. Approaches include fuzzy string matching, embedding similarity, and LLM-based comparison. Graphiti constrains deduplication search to edges between the same entity pairs, significantly reducing computational complexity.

**Entity classification**: The POLE+O model (Person, Object, Location, Event, Organization) is the dominant schema. Some systems extend this with domain-specific types (Medical: Condition, Medication, Procedure; Legal: Case, Statute, Party).

### 5.2 Graph Schema Design for Agent Memory

Common schema patterns across production systems:

**Core node types**:
- **Entity**: Represents a real-world thing (person, place, organization, concept)
- **Episode/Event**: A discrete interaction or observation (conversation turn, document chunk, tool call)
- **Memory/Fact**: A derived statement extracted from episodes
- **Community**: A cluster of related entities (from community detection)
- **Session**: A bounded interaction context
- **Agent**: The AI agent that created or interacted with memories

**Core relationship types**:
- `MENTIONS` (Episode -> Entity): An episode references an entity
- `DERIVED_FROM` (Memory -> Episode): Provenance tracking
- `RELATED_TO` (Entity -> Entity): General semantic association
- `SUPERSEDES` (Memory -> Memory): Newer fact replaces older
- `CONFLICTS_WITH` (Memory -> Memory): Contradiction tracking
- `MEMBER_OF` (Entity -> Community): Community membership
- `PART_OF` (Entity -> Entity): Hierarchical containment
- `CAUSED_BY` (Event -> Event): Causal chains

**Temporal properties on edges**: Every relationship carries `created_at`, `valid_from`, `valid_until` (or equivalent). This enables time-travel queries and temporal filtering without requiring a separate temporal layer.

**Embedding properties on nodes**: Entity and memory nodes carry vector embeddings for semantic search. This enables hybrid retrieval: graph traversal for structural queries + vector similarity for semantic queries.

### 5.3 Hybrid Approaches (Vector + Graph)

The consensus architecture for 2026 is **hybrid vector+graph**, not either/or:

1. **Write path**: Raw input -> entity extraction -> graph update + vector embedding storage. Both happen in the same transaction or with eventual consistency guarantees.

2. **Read path**: Query -> parallel execution of (a) vector similarity search and (b) graph traversal -> result fusion via Reciprocal Rank Fusion or neural reranking.

3. **Storage**: Single database (PostgreSQL with pgvector and graph tables/AGE) or dual database (Neo4j for graph + dedicated vector store, or Neo4j 5.20+ with built-in vectors).

Mem0g, Graphiti, Hindsight, and Neo4j Agent Memory all implement this hybrid pattern. The specific fusion strategy varies but RRF (Reciprocal Rank Fusion) is the most common.

### 5.4 Temporal Aspects

Three levels of temporal sophistication in agent memory graphs:

**Level 1 — Timestamps only**: Every node/edge has `created_at`. Enables "most recent" filtering but not temporal reasoning. (Most basic systems.)

**Level 2 — Validity windows**: Edges carry `valid_from` / `valid_until`. Enables "what was true at time T?" queries. Old facts are invalidated, not deleted. (Graphiti, Neo4j Agent Memory.)

**Level 3 — Bi-temporal**: Separate tracking of *system time* (when the system learned something) and *valid time* (when the fact was true in the world). Enables forensic queries like "what did the system believe about X at time T?" (Graphiti specifically.)

**Contradiction handling in graph structures**: When new information contradicts existing facts, production systems use one of:
- **Edge invalidation** (Graphiti): Set `valid_until` on the old edge, create new edge. Old fact remains queryable.
- **Conflict edges** (MemoryHub current approach): Create explicit `CONFLICTS_WITH` relationships between contradicting memories.
- **Confidence decay** (Hindsight): Reduce confidence scores on contradicted facts in the opinion network.
- **LLM arbitration** (Graphiti, others): Use an LLM to determine whether new information truly contradicts or merely supplements existing facts.

### 5.5 Provenance Tracking

Every production graph memory system maintains provenance chains:

- **Episode -> Entity/Memory**: Which raw input produced which derived facts
- **Memory -> Memory**: Which facts informed which derived insights
- **Agent -> Memory**: Which agent created or modified which memories
- **Tool -> Memory**: Which tool invocations produced which observations

This provenance is stored as graph edges, making it traversable. "Why does the system believe X?" can be answered by traversing provenance edges back to source episodes.

---

## 6. Governance

### 6.1 Graph Traversal Access Control

Graph databases add a dimension to access control that flat data stores lack: **who can traverse which edges?** Reading a node might be permitted, but following its relationships to reach other nodes might not be.

**Neo4j Enterprise Edition** provides the most mature graph access control:
- **Label-based permissions**: Control read/write access per node label. A user might read `:Person` nodes but not `:MedicalRecord` nodes.
- **Relationship-type permissions**: Control which relationship types can be traversed. Block traversal of `:HAS_DIAGNOSIS` while allowing `:WORKS_AT`.
- **Property-level permissions**: Hide specific properties on nodes or edges the user can otherwise see.
- **Combined allowlist/denylist**: GRANT and DENY privileges combine — a user can access a resource if they have a GRANT and do not have a DENY. Users cannot distinguish between hidden data and nonexistent data.

**FalkorDB**: Basic access control through Redis ACLs. Less granular than Neo4j.

**Apache AGE**: Inherits PostgreSQL's RBAC. Row-level security (RLS) policies can be applied to the underlying graph tables, but this operates at the relational level, not the graph semantic level. You can restrict access to specific vertex or edge tables (effectively restricting by label), but cross-cutting traversal policies are harder to express.

**Amazon Neptune**: IAM-based access control with condition keys for fine-grained restrictions. Can restrict by graph, but node/relationship-level access control requires application-layer enforcement.

### 6.2 Entity-Level Permissions

For agent memory specifically, permissions often need to be scoped by:

- **Owner**: Only the memory's creator can read/modify it
- **Scope**: User-scoped memories are private; organizational memories are shared
- **Project**: Memories tagged to a project are visible to project members
- **Role**: Administrators can read all memories; regular users only their own scope

MemoryHub already implements this through its scope model and service-layer RBAC. The question for graph memory is whether these permissions need to extend to graph traversal — can following a `RELATED_TO` edge from a user-scoped memory reach an organizational memory the user shouldn't see?

The pattern used by Neo4j Enterprise is the cleanest: define permissions on node labels and relationship types, and the database enforces them during traversal. With PostgreSQL-based approaches (AGE or custom tables), this must be enforced in the application layer or via RLS policies.

### 6.3 Knowledge Graph Quality and Curation

Graph memory introduces quality challenges that vector memory doesn't have:

**Entity drift**: The same real-world entity may be extracted with different names across sessions ("PostgreSQL," "Postgres," "PG," "psql"). Without deduplication, the graph fragments.

**Relationship quality**: LLM-extracted relationships may be imprecise, missing, or hallucinated. Quality improves with larger models but at higher cost.

**Graph bloat**: Without curation, graphs grow indefinitely. Inactive or low-value nodes and edges accumulate.

**Community staleness**: Community assignments become stale as the graph evolves. Community detection must be re-run periodically or incrementally updated.

Production approaches to curation:
- **Automated deduplication** at write time (Graphiti, Neo4j Agent Memory)
- **Similarity-based merge suggestions** (MemoryHub's current `suggest_merge` tool)
- **Confidence-based pruning** (remove low-confidence entities/relationships after a grace period)
- **Usage-based decay** (reduce weight of unused memories over time)
- **Human-in-the-loop review** for high-stakes domains

### 6.4 Contradiction Resolution in Graph Structures

Contradictions in graph memory are more complex than in flat memory because they can propagate through relationships:

1. **Direct contradiction**: Memory A says "user prefers Docker," Memory B says "user prefers Podman"
2. **Transitive contradiction**: Memory A says "MemoryHub uses PostgreSQL," Memory B says "PostgreSQL doesn't support graph queries," Memory C says "MemoryHub uses graph queries" — the contradiction only emerges through multi-hop traversal
3. **Temporal contradiction**: A fact was true at time T1 but not at T2 — this isn't a contradiction, it's temporal evolution

Production systems handle these differently:
- **Graphiti**: LLM-based comparison of new edges against existing edges, temporal invalidation of contradicted facts
- **Hindsight**: Confidence scores in the opinion network, updated as evidence accumulates
- **MemoryHub (current)**: Contradiction reports table, threshold-based escalation, explicit `conflicts_with` relationships

The graph structure makes contradiction *detection* easier (traverse related facts and check for inconsistencies) but *resolution* harder (changes may cascade through the graph).

---

## 7. The PostgreSQL Angle

### 7.1 Current State

MemoryHub uses PostgreSQL with pgvector for relational data, vector similarity search, and graph relationships in a single database. The graph model uses adjacency lists with a `memory_relationships` table and recursive CTEs for traversal. The existing architecture explicitly calls out Apache AGE as a future option but chose not to adopt it for v1 because of its incubator-stage status.

### 7.2 Apache AGE: Is It Good Enough?

**What AGE provides**:
- openCypher-compatible queries embedded in SQL via the `cypher()` function
- Vertex and edge tables stored in PostgreSQL with standard indexing
- Runs on existing PostgreSQL infrastructure (no new database)
- Supported by Azure Database for PostgreSQL natively
- Apache 2.0 license
- FIPS compliance inherited from PostgreSQL

**What AGE lacks compared to Neo4j**:
- **No automatic indexes**: Must explicitly create BTREE and GIN indexes for each label and property
- **Subset of Cypher**: Not all Cypher features are supported
- **No built-in graph algorithms**: No PageRank, community detection, shortest path, etc. Must be implemented in application code or as PL/pgSQL functions
- **Performance on deep traversals**: One benchmark showed 40x speed difference favoring recursive CTEs for specific workloads. AGE uses relational storage under the hood, so large join operations can become bottlenecks
- **No native graph access control**: Relies on PostgreSQL RLS, which operates at the table (label) level, not the traversal level
- **Incubator status**: Still Apache Incubator (as of April 2026), meaning API stability is not guaranteed

**Specific to MemoryHub's needs**:
- Our trees are shallow (3-4 levels) — recursive CTEs handle this efficiently today
- Our relationship types are simple (derived_from, supersedes, conflicts_with, related_to) — these don't require deep graph algorithms
- Our scale target is hundreds of agents and thousands of memories per user — not millions of nodes
- We already have the relationships table and recursive CTE infrastructure working

### 7.3 The "Good Enough" Assessment

For MemoryHub's current and near-term needs, **PostgreSQL without AGE is likely sufficient**. Here's why:

**What we already have that works**: Adjacency lists, relationships table, recursive CTEs for shallow traversal, pgvector for semantic search, and ACID guarantees across all operations. This handles the v1 requirements.

**Where a dedicated graph DB would help**:
1. **Multi-hop traversals deeper than 3-4 levels**: If we add richer entity extraction and relationship types, traversal depth increases. Recursive CTEs become expensive beyond 5-6 hops.
2. **Graph algorithms**: Community detection (for grouping related memories), centrality analysis (for identifying key entities), similarity/path algorithms. These are non-trivial to implement on raw SQL.
3. **Real-time graph queries in the read path**: If we want to do graph-enhanced retrieval (combining vector similarity with graph traversal) on every `search_memory` call, latency from recursive CTEs may become a bottleneck.
4. **Graph-native access control**: Neo4j's label/relationship-type permissions are more expressive than what we can do with PostgreSQL RLS.

**The hybrid path (recommended)**:

Rather than choosing between PostgreSQL and a dedicated graph DB, the pattern that most production systems converge on is:

1. **PostgreSQL remains the system of record**: Relational data, memory nodes, version history, contradiction reports, scope metadata, ACID transactions
2. **pgvector continues to handle vector search**: Collocated with relational data, no synchronization overhead
3. **Optional graph database as a read-optimized projection**: Load the entity/relationship graph into Neo4j (or an in-memory graph library) for complex traversals, community detection, and graph-enhanced retrieval. Write mutations go to PostgreSQL first, then propagate to the graph projection.

This is essentially the "in-memory graph" evolution path already described in MemoryHub's storage-layer.md, but with a proper graph database instead of NetworkX.

### 7.4 What AGE Buys If We Adopt It

If we decide to add graph query capabilities without a separate database, AGE is the lowest-friction option:

**Benefits**:
- Cypher syntax for graph queries instead of recursive CTEs (developer ergonomics)
- Single database to operate
- No data synchronization between stores
- FIPS compliance for free

**Costs**:
- New PostgreSQL extension to manage and validate with the OpenShift PostgreSQL operator
- Explicit index management (every label needs BTREE and GIN indexes)
- Performance ceiling lower than dedicated graph databases
- Graph algorithm gaps (community detection, centrality) still need application-level implementation

**Verdict**: AGE is a reasonable stepping stone if we want Cypher query ergonomics on our existing PostgreSQL, but it doesn't solve the fundamental limitations for deep traversals or graph algorithms. If we eventually need those, we'll need a dedicated graph database anyway.

### 7.5 Decision Framework

| Scenario | Recommendation |
|----------|---------------|
| Current MemoryHub (shallow trees, simple relationships) | Stay with recursive CTEs on PostgreSQL |
| Adding entity extraction from conversations | Consider AGE for Cypher ergonomics, or in-memory graph (NetworkX) for algorithms |
| Adding community detection / graph algorithms | Dedicated graph DB (Neo4j) or in-memory graph library |
| Multi-hop retrieval in read path (>5 hops) | Dedicated graph DB for performance |
| Graph-native access control requirements | Neo4j Enterprise Edition |
| Minimize operational complexity | In-memory graph projection from PostgreSQL data |

---

## 8. Implications for MemoryHub

### 8.1 What We Already Have

MemoryHub's existing architecture already implements several patterns identified in this survey:

- **Memory tree with branching** (adjacency lists, parent_id) — equivalent to hierarchical tree graph structure
- **Typed relationships** (derived_from, supersedes, conflicts_with, related_to) — matches production graph memory schemas
- **Contradiction tracking** with threshold-based escalation — aligns with Hindsight's confidence-based approach
- **Multi-scope model** (user, project, organizational, enterprise) — matches Mem0's multi-scope pattern
- **Hybrid retrieval** (vector similarity via pgvector + relational filtering) — foundation for full hybrid vector+graph retrieval
- **Provenance** (version history, created_by tracking) — partial provenance graph

### 8.2 Gaps Relative to State of the Art

1. **No entity extraction from conversations**: Production systems (Graphiti, Neo4j Agent Memory) automatically extract entities and relationships from every interaction. MemoryHub stores what agents explicitly write, not what can be automatically derived.

2. **No community detection**: No way to group related memories into thematic clusters or generate cluster-level summaries.

3. **No graph-enhanced retrieval**: `search_memory` uses vector similarity. It doesn't combine graph traversal (follow relationships from high-similarity results to find connected relevant memories).

4. **No temporal validity on relationships**: Relationships don't carry validity windows. We can't answer "what relationships existed at time T?"

5. **No reasoning memory**: We don't capture agent reasoning traces (tool calls, decision chains). Neo4j Agent Memory's reasoning tier is unique but increasingly recognized as valuable.

6. **Limited entity deduplication**: The `suggest_merge` tool is manual. Production systems do automated deduplication at write time.

### 8.3 Potential Evolution Path

**Phase 1 (Low lift, high value)**: Add temporal validity to the relationships table (`valid_from`, `valid_until`). Add graph-enhanced retrieval to `search_memory` — after vector search returns top-N results, follow their relationships to find connected memories and re-rank the combined set. Both can be done with existing PostgreSQL infrastructure.

**Phase 2 (Medium lift)**: Add lightweight entity extraction. When `write_memory` is called, extract entities from the content and create entity nodes + `MENTIONS` relationships automatically. Deduplication at write time. This creates a real knowledge graph from existing memory operations without requiring agents to change their behavior.

**Phase 3 (Higher lift, strategic decision)**: Add a graph computation layer. Options: (a) In-memory graph projection using NetworkX, loaded from PostgreSQL at startup, for community detection and graph algorithms. (b) Apache AGE for Cypher query ergonomics. (c) Neo4j as an optional graph backend for advanced use cases. The choice depends on whether graph algorithms and deep traversals become core requirements.

### 8.4 Key Takeaways

1. **Graph memory is production-ready in 2026.** This is no longer experimental. Mem0g, Graphiti, Cognee, Neo4j Agent Memory, and Hindsight are all in production use.

2. **Hybrid vector+graph is the consensus architecture.** No production system uses graph-only retrieval. Every successful system combines vector similarity with graph traversal.

3. **Entity extraction is the prerequisite.** Graph memory is only as good as the entities and relationships you extract. The multi-stage cascade (fast rule-based -> zero-shot neural -> LLM fallback) is the production pattern.

4. **Temporal awareness differentiates agent memory from static knowledge graphs.** Validity windows, bi-temporal modeling, and non-destructive contradiction resolution are what make graph memory useful for agents specifically.

5. **PostgreSQL with pgvector is a viable base for incremental evolution.** We don't need to adopt a dedicated graph database today. The recommended path is to add graph capabilities incrementally, starting with temporal relationships and graph-enhanced retrieval on existing PostgreSQL, and evaluating a dedicated graph DB when graph algorithms or deep traversals become requirements.

6. **The governance story matters.** Neo4j Enterprise is the only option with graph-native access control. For PostgreSQL-based approaches, access control must be enforced in the application layer. MemoryHub's existing scope-based RBAC is well-positioned for this, but extending it to graph traversal policies requires design work.

---

## 9. Sources

### Papers

- [Zep: A Temporal Knowledge Graph Architecture for Agent Memory](https://arxiv.org/abs/2501.13956) (arXiv:2501.13956, January 2025)
- [MAGMA: A Multi-Graph based Agentic Memory Architecture for AI Agents](https://arxiv.org/abs/2601.03236) (arXiv:2601.03236, January 2026)
- [Graph-based Agent Memory: Taxonomy, Techniques, and Applications](https://arxiv.org/html/2602.05665) (arXiv:2602.05665, February 2026)
- [Hindsight is 20/20: Building Agent Memory that Retains, Recalls, and Reflects](https://arxiv.org/abs/2512.12818) (arXiv:2512.12818, December 2025)
- [LongMemEval: Benchmarking Chat Assistants on Long-Term Interactive Memory](https://arxiv.org/abs/2410.10813) (ICLR 2025)
- [MemMachine: A Ground-Truth-Preserving Memory System for Personalized AI Agents](https://arxiv.org/abs/2604.04853) (arXiv:2604.04853, April 2026)
- [Graph-Native Cognitive Memory for AI Agents: Formal Belief Revision Semantics](https://arxiv.org/html/2603.17244v1) (arXiv:2603.17244, March 2026)
- [RAG Meets Temporal Graphs: Time-Sensitive Modeling and Retrieval](https://arxiv.org/html/2510.13590v1) (arXiv:2510.13590, October 2025)
- [Beyond the Context Window: Cost-Performance Analysis of Fact-Based Memory vs. Long-Context LLMs](https://arxiv.org/html/2603.04814v1) (arXiv:2603.04814, March 2026)
- [Graphs Meet AI Agents: Taxonomy, Progress, and Future Opportunities](https://arxiv.org/html/2506.18019v1) (arXiv:2506.18019, June 2025)
- [Graph Retrieval-Augmented Generation: A Survey](https://dl.acm.org/doi/10.1145/3777378) (ACM TOIS, 2025)
- [The construction and refined extraction techniques of knowledge graph based on large language models](https://www.nature.com/articles/s41598-026-38066-w) (Scientific Reports, February 2026)
- [Knowledge Graph Construction: Extraction, Learning, and Evaluation](https://www.mdpi.com/2076-3417/15/7/3727) (Applied Sciences, March 2025)
- [LLM-empowered knowledge graph construction: A survey](https://arxiv.org/html/2510.20345v1) (arXiv:2510.20345, October 2025)

### Repositories and Documentation

- [Graphiti - Build Real-Time Knowledge Graphs for AI Agents](https://github.com/getzep/graphiti)
- [Neo4j Agent Memory](https://github.com/neo4j-labs/agent-memory) / [Documentation](https://neo4j.com/labs/agent-memory/)
- [Mem0 Graph Memory](https://docs.mem0.ai/open-source/features/graph-memory)
- [Microsoft GraphRAG](https://github.com/microsoft/graphrag)
- [FalkorDB](https://github.com/FalkorDB/FalkorDB)
- [Cognee](https://github.com/topoteretes/cognee)
- [Hindsight](https://github.com/vectorize-io/hindsight)
- [MAGMA / MAMGA](https://github.com/FredJiang0324/MAMGA)
- [MemMachine](https://github.com/MemMachine/MemMachine)
- [LlamaIndex PropertyGraphIndex](https://www.llamaindex.ai/blog/introducing-the-property-graph-index-a-powerful-new-way-to-build-knowledge-graphs-with-llms)
- [Awesome-GraphMemory](https://github.com/DEEP-PolyU/Awesome-GraphMemory) (survey companion resource list)
- [Awesome-Memory-for-Agents](https://github.com/TsinghuaC3I/Awesome-Memory-for-Agents) (Tsinghua C3I paper list)
- [Apache AGE](https://github.com/apache/age) / [Documentation](https://age.apache.org/overview/)
- [Kuzu](https://github.com/kuzudb/kuzu) / [Vela Fork](https://www.vela.partners/blog/kuzudb-ai-agent-memory-graph-database)

### Industry Reports and Blog Posts

- [State of AI Agent Memory 2026](https://mem0.ai/blog/state-of-ai-agent-memory-2026) (Mem0, 2026)
- [Graph-Based Memory Solutions for AI Context: Top 5 Compared](https://mem0.ai/blog/graph-memory-solutions-ai-agents) (Mem0, January 2026)
- [Graphiti: Knowledge Graph Memory for an Agentic World](https://neo4j.com/blog/developer/graphiti-knowledge-graph-memory/) (Neo4j Blog)
- [Meet Lenny's Memory: Building Context Graphs for AI Agents](https://neo4j.com/blog/developer/meet-lennys-memory-building-context-graphs-for-ai-agents/) (Neo4j Blog)
- [Stop Using RAG for Agent Memory](https://blog.getzep.com/stop-using-rag-for-agent-memory/) (Zep Blog)
- [Observational Memory: 95% on LongMemEval](https://mastra.ai/research/observational-memory) (Mastra Research)
- [Neo4j Graph Database Security: Fine-Grained Access Control](https://neo4j.com/product/neo4j-graph-database/security/)
- [Graph-Based Security & Entitlements: Transforming Access Control](https://enterprise-knowledge.com/graph-based-security-entitlements-transforming-access-control-for-the-modern-enterprise/)
- [Apache AGE Performance Best Practices (Azure)](https://learn.microsoft.com/en-us/azure/postgresql/azure-ai/generative-ai-age-performance)
- [Agent Memory Benchmark: A Manifesto](https://hindsight.vectorize.io/blog/2026/03/23/agent-memory-benchmark) (Hindsight / Vectorize)
- [Build persistent memory with Mem0, ElastiCache, and Neptune](https://aws.amazon.com/blogs/database/build-persistent-memory-for-agentic-ai-applications-with-mem0-open-source-amazon-elasticache-for-valkey-and-amazon-neptune-analytics/) (AWS Blog)
- [Graphiti + FalkorDB: Integration for Multi-Agent Systems](https://www.falkordb.com/blog/graphiti-falkordb-multi-agent-performance/)
- [Building an AI Agent with Memory: Microsoft Agent Framework + Neo4j](https://medium.com/neo4j/building-an-ai-agent-with-memory-microsoft-agent-framework-neo4j-e3eab8f09694) (April 2026)
