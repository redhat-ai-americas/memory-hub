# Google's Open Knowledge Format (OKF): Analysis for MemoryHub

**Date**: June 2026
**Purpose**: Analyze Google's Open Knowledge Format v0.1 spec and its implications for MemoryHub's MemoryHub/RetrievalHub strategy
**Status**: Research analysis

---

## 1. What OKF Is

Open Knowledge Format (OKF) v0.1 is a draft specification from Google, released under the GoogleCloudPlatform/knowledge-catalog repository (Apache 2.0). Knowledge Catalog is Google Cloud's rebranded Dataplex, their AI-powered data catalog and metadata management platform. OKF is the interchange format for that product, but designed to be vendor-neutral.

The core data model has three concepts:

- **Knowledge Bundle**: A self-contained, hierarchical collection of knowledge documents. The unit of distribution. A bundle is a directory of markdown files with YAML frontmatter, no schema registry, no required tooling.
- **Concept**: A single unit of knowledge, represented as one markdown file. Concepts can describe tangible assets (BigQuery tables, REST APIs) or abstract ideas (business metrics, operational playbooks). The concept ID is the file path with `.md` removed.
- **Links and Citations**: Standard markdown links between concepts express relationships. Links from concepts to external sources are citations. Link semantics are conveyed by surrounding prose, not by link metadata. Consumers treat all links as directed edges of untyped relationships.

The spec is aggressively minimal. The only required field is `type` (a free-form string, not drawn from a central registry). Recommended fields include title, description, resource URI, tags, and timestamp. Any additional YAML keys are allowed as extensions, and consumers must preserve unknown keys.

Two reserved files provide structure: `index.md` (directory listing for progressive disclosure) and `log.md` (change history). Versioning uses major.minor via an `okf_version` field in the root index. Distribution is via git repo (recommended), tarball, or subdirectory of a larger repo.

The conformance model is notable for what it does not enforce: consumers must not reject bundles for missing optional fields, unknown types, unknown extension keys, or broken links. This is a deliberately low bar designed for adoption over correctness.

A companion enrichment agent, built on Google's Agent Development Kit (ADK) with Gemini, does two passes over source data: a BigQuery metadata pass and a web-crawl pass. A separate visualizer generates self-contained HTML with a force-directed graph (Cytoscape.js). Sample bundles exist for GA4, Stack Overflow, and Bitcoin datasets.

---

## 2. Positioning: Where OKF Sits in the Landscape

OKF is clearly a semantic-layer format. It describes what things ARE: tables, APIs, metrics, playbooks, business definitions. It does not capture what happened, why decisions were made, or how understanding evolved. In the taxonomy established in [knowledge-graphs-vs-context-graphs.md](knowledge-graphs-vs-context-graphs.md), OKF is firmly on the knowledge graph side: domain vocabulary, entity descriptions, and structural relationships.

**Relative to Karpathy's llm-wiki.** OKF is the spec-level formalization of the same impulse Karpathy described. His three-layer architecture (raw sources, compiled wiki, index) maps directly: OKF bundles are the compiled wiki layer with a formal schema. The key difference is ambition. Karpathy proposed a personal workflow; OKF proposes an interchange format. The llm-wiki gist is "here's how I organize knowledge for my agent." OKF is "here's how organizations exchange knowledge between systems."

**Relative to Knowledge Catalog/Dataplex.** OKF is the open interchange format for Google's proprietary catalog product. The same relationship as Parquet to BigQuery, or OCI to Docker: a vendor publishes an open spec for their internal format to encourage ecosystem adoption. The enrichment agent (ADK + Gemini) is the proprietary layer that produces OKF bundles from Google Cloud metadata.

**Relative to the llm-wiki implementations.** The [landscape analysis](llm-wiki-landscape.md) surveyed a wave of personal-only implementations. OKF adds exchangeability (a spec that multiple producers and consumers can target) but does not add governance, access control, or multi-user support. The llm-wiki implementations are personal knowledge tools. OKF is a data catalog interchange format. Neither addresses the governed, multi-user memory problem.

---

## 3. Design Decisions Worth Noting

**Minimal required fields.** Only `type` is required, and it is a free-form string. MemoryHub requires scope, content, and authenticated identity on every write, with optional but meaningful fields for weight, domain, parent relationships, and branch type. OKF optimizes for adoption friction; MemoryHub optimizes for governance guarantees. These are not competing choices, they reflect different purposes. A knowledge interchange format should be easy to produce. A governed memory system should be hard to misuse.

**Untyped relationships.** OKF uses standard markdown links with no typed semantics. A link from concept A to concept B is a directed edge, but whether it means "depends on," "is a subtype of," or "contradicts" is left to the prose surrounding the link. MemoryHub's relationship model has explicit types, directionality, and a traversal API. OKF's approach is appropriate for a file-based format where humans read the prose. It is insufficient for runtime graph queries where an agent needs to traverse "all dependencies of X" without reading every document.

**No access control.** Knowledge within a bundle is structurally public. There is no scope hierarchy, no RBAC, no concept of restricted visibility. This is fine for a data catalog interchange format (you share a bundle with people who should see it), but it means OKF bundles cannot carry sensitive organizational knowledge without external access control wrapping them.

**Permissive consumption.** The requirement that consumers tolerate broken links, unknown types, and missing fields is an interesting durability choice. It prioritizes partial information over correctness. MemoryHub's contradiction detection and curation subsystem take the opposite stance: conflicts and inconsistencies should be surfaced and resolved, not silently tolerated.

**Progressive disclosure via index.md.** The index file that lists bundle contents with summaries parallels MemoryHub's search-with-focus-bias: show the agent what exists, let it drill into what it needs. The mechanism differs (static file vs dynamic search), but the information architecture principle is the same.

**Git as versioning.** OKF leans on git for distribution and version history. MemoryHub uses internal versioning with `isCurrent` flags, provenance chains, and branch types. Git versioning is appropriate for a file-based format that changes infrequently. Internal versioning is necessary for a runtime system where memories evolve continuously through agent interaction.

---

## 4. Implications for MemoryHub

**OKF validates the MemoryHub/RetrievalHub strategy.** OKF sits squarely on the semantic/factual side of MemoryHub's deliberate scope boundary. It describes domain assets and their relationships. MemoryHub stores decisions, experiences, procedures, and their provenance. The existence of a vendor-neutral spec for the semantic layer confirms that there is real demand for structured, exchangeable knowledge formats, and that it is a different thing from what MemoryHub does. The [knowledge-graphs-vs-context-graphs analysis](knowledge-graphs-vs-context-graphs.md) drew this line; OKF provides concrete evidence that the industry is drawing it too. (For the MemoryHub/RetrievalHub boundary definition, see [planning/knowledge-layer.md](../planning/knowledge-layer.md) section 7.)

**The RetrievalHub could speak OKF.** OKF's permissive extension model means MemoryHub-specific fields (scope, governance metadata, provenance, curation status) could ride alongside OKF's required fields without breaking conformance. The RetrievalHub could consume OKF bundles as an import format (ingest a data catalog and make it queryable with governance) and produce OKF bundles as an export format (share curated knowledge with systems that do not need MemoryHub's governance). The extension mechanism makes this interoperable without forking the spec.

**OKF's governance gap is the RetrievalHub's value proposition.** OKF has no access control, no curation, no provenance, no contradiction detection. For a file-based interchange format, that is fine. But organizations that need to govern their semantic knowledge (who can see this definition? when did it change? does it conflict with another definition?) need something on top of OKF. The RetrievalHub should carry governance where OKF does not, just as MemoryHub carries governance where flat vector stores do not. The [ontology-contextualization analysis](ontology-contextualization.md) identified terminology governance as a key gap in regulated enterprises; OKF bundles carrying organizational terminology would need exactly the governance layers that analysis proposed.

**The enrichment agent pattern is prior art.** OKF's enrichment agent (observe BigQuery metadata and web content, produce structured knowledge bundles) parallels MemoryHub's extraction pipeline design (#240: observe agent traces, produce candidate memories). The source material differs (data catalog metadata vs agent conversation traces), but the architectural pattern is identical: asynchronous observation of operational data, structured extraction into a governed format, human-in-the-loop validation before promotion. Google built this for their semantic layer. MemoryHub is building it for the procedural layer. The pattern validates itself across both sides of the semantic/episodic boundary.

**Cross-linking is simpler but weaker.** OKF's markdown links are human-readable and tool-agnostic, which is the right tradeoff for an interchange format. But they cannot support the kind of queries agents need at runtime: "find all concepts that depend on this API," "trace the provenance of this metric definition," "what changed since last quarter." MemoryHub's typed relationships and traversal API exist precisely because runtime agents need structured traversal, not prose parsing.

---

## 5. What This Means for RetrievalHub

OKF informs the RetrievalHub design in three concrete ways.

**Import/export format.** OKF could serve as the interchange format for the RetrievalHub, allowing organizations to import knowledge from OKF-producing tools (Google's enrichment agent, future third-party generators) and export governed knowledge back to OKF-consuming systems. The RetrievalHub's value-add over raw OKF is governance, access control, runtime query, and scope isolation.

**Enrichment pipeline precedent.** Google's two-pass enrichment agent (metadata extraction, then web-crawl enrichment) is directly applicable to the RetrievalHub's ingestion pipeline. Observe the organization's data assets, extract structured knowledge, surface it for curation. The RetrievalHub would add what Google's agent does not: governed storage with provenance, contradiction detection when extracted knowledge conflicts with existing definitions, and scope-based visibility so different teams see different slices.

**Governance as the differentiator.** OKF proves that a minimal, governance-free format can gain adoption for knowledge interchange. The RetrievalHub should not compete on format; it should consume OKF and add the governance layer. This mirrors MemoryHub's relationship to flat vector stores on the episodic/procedural side: we do not compete on storage or retrieval mechanics, we compete on governance, provenance, and access control. The two hubs together provide governed memory (episodic/procedural) and governed knowledge (semantic/factual) for the same regulated customers where unstructured alternatives are disqualified.

---

## References

- [GoogleCloudPlatform/knowledge-catalog](https://github.com/GoogleCloudPlatform/knowledge-catalog) (OKF spec, enrichment agent, visualizer)
- [OKF Specification v0.1](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md)
- [knowledge-graphs-vs-context-graphs.md](knowledge-graphs-vs-context-graphs.md) (semantic vs procedural layer taxonomy)
- [llm-wiki-landscape.md](llm-wiki-landscape.md) (Karpathy's llm-wiki and implementation survey)
- [ontology-contextualization.md](ontology-contextualization.md) (terminology governance exploration)
- [agent-memory-landscape-2026.md](agent-memory-landscape-2026.md) (context graph positioning, Neo4j comparison)
