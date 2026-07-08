# Ontology-Aware Contextualization of Agent Memories

**Date**: June 2026
**Purpose**: Explore how MemoryHub could support terminology-aware memory retrieval and cross-organizational concept mapping
**Status**: Research exploration

---

## 1. The Problem: Terminology Diverges Across Organizations

AI agents trained on general knowledge inherit general assumptions about terminology. Those assumptions break in practice because organizations redefine, overload, and invert standard terms to match their internal culture, regulatory context, or operational philosophy. This is not an edge case; it is the norm in regulated enterprises.

Four examples illustrate the pattern at different scales.

### 1.1 SIPOC vs COPIS

Lean and Six Sigma practitioners widely use SIPOC (Supplier, Input, Process, Output, Customer) as a process mapping framework. Some organizations that embrace "customer-first" thinking reverse the order to COPIS, considering the same five elements but starting from the Customer and working backward to the Supplier. The framework is identical; the mental model and the vocabulary are inverted. An agent advising on process improvement needs to know which convention the organization uses, or it will produce deliverables that feel foreign and are quietly ignored.

This is the simplest version of the problem: same concept, different name. There is no ambiguity about meaning, only about labeling. A term registry solves it.

### 1.2 FHIR in Healthcare

HL7 FHIR defines roughly 150 resource types (Patient, Observation, Condition, Coverage, Claim, Encounter, etc.), each with deep nested structures, extensions, and profiles. The full specification runs to thousands of pages. No single context window can hold it, and most interactions only need a small slice.

An agent helping a developer build a patient-facing portal needs Patient, Condition, and MedicationRequest resources in detail. If the conversation pivots to claims processing, the agent needs Coverage, Claim, and ExplanationOfBenefit instead. This is progressive unfolding: load the relevant slice of a large domain model based on current focus, pull in more when focus shifts.

MemoryHub's existing focus tracking and search-with-focus-bias already support this pattern mechanically. The gap is that the agent does not know *which* memories constitute a coherent domain slice. FHIR resources have formal relationships (a Claim references a Coverage, which references a Patient), but those relationships are in the FHIR spec, not in MemoryHub's memory graph.

### 1.3 VA and Community Care Records

When veterans receive care from community providers and later transition back to VA healthcare, their records carry terminology from two different systems. A medication name, diagnosis code, or procedure description may use different coding systems (ICD-10 vs SNOMED CT, NDC vs RxNorm), different granularity, or different clinical conventions. The same clinical reality gets two different textual representations.

This is a cross-organizational terminology mapping problem with patient safety implications. An agent summarizing a veteran's care history needs to know that Community Provider A's "office visit" maps to the VA's "outpatient encounter," but with differences in what gets bundled into that concept (the community provider may include lab draws; the VA may code them separately).

This is harder than SIPOC/COPIS because the terms are not interchangeable labels for the same concept. They are *overlapping* concepts with partial equivalence, and getting the mapping wrong has clinical consequences.

### 1.4 The Ontology Gap

A recurring observation from physicians and clinical informaticists working on AI adoption: many healthcare organizations lack a formal ontology for their domain-specific work. Standard ontologies exist (SNOMED CT, LOINC, ICD-10), but the mapping from an organization's actual clinical workflows and documentation practices to those ontologies is often incomplete, inconsistent, or nonexistent.

This gap is not unique to healthcare. Defense organizations layer mission-specific terminology on top of standard frameworks. Financial services firms develop internal risk taxonomies that diverge from Basel/IFRS standards. Government agencies redefine terms across administrations. The pattern is universal: standard ontologies exist, but organizations customize them in undocumented ways, and that customization is precisely the knowledge an AI agent needs to be useful.

---

## 2. Three-Layer Progression

These layers are independently useful. Each can be implemented without the others, though they compose naturally.

### Layer 1: Term Registry

**Scope**: Near-term. Fits entirely within MemoryHub's existing model.

The simplest version is a convention: project or org-scoped memories tagged with a `terminology` domain that define what specific terms mean in a given context. When the retrieval layer encounters a term that has a registry entry, it includes the definition alongside whatever memories it would normally return.

An example memory:

```
scope: organizational
domain: terminology
content: "In this organization, 'COPIS' refers to the Customer-Output-Process-
Input-Supplier framework. This is the reverse of the standard SIPOC ordering.
All process documentation uses COPIS, not SIPOC."
weight: 0.9
```

No new infrastructure is required. The retrieval layer already searches by scope and can bias by domain tags. The only addition is a convention that agents follow: when a search result includes a `terminology` memory, treat it as definitional context that should be injected alongside the operational memories.

This is immediately useful for any organization with specialized vocabulary. The cost is near-zero: a few well-written terminology memories per project or org.

Where Layer 1 breaks down: when the same term has different definitions in different scopes, and the agent does not know which scope applies. A term that means one thing at the project level and something different at the organizational level requires disambiguation, not just lookup. That is Layer 2.

### Layer 2: Ambiguity Detection

**Scope**: Medium-term. Ties to graph-enhanced memory (#170).

Layer 2 adds the ability for an agent to recognize that a term could have multiple meanings and to avoid silently picking one. This requires two capabilities:

**Known-ambiguous terms.** A curated set of terms that are flagged as overloaded. When the agent encounters one, it checks which scope-specific definition applies (or asks for clarification if the scope is ambiguous). This is still fundamentally a lookup, but with a branching path.

**Inferred ambiguity.** When terminology memories from different scopes define the same term differently, the system detects the conflict. This is a variant of MemoryHub's existing contradiction detection, applied specifically to terminology. Two definitions for "encounter" at different scopes are not a contradiction in the general sense (both may be correct within their scope), but they are a signal that cross-scope communication about "encounters" requires translation.

**Cross-scope term resolution.** When two organizations share a campaign or federated context in MemoryHub, the system can surface where their terminologies diverge. The output is not just "these terms differ" but a structured mapping: "Org A's 'encounter' maps to Org B's 'visit' with these differences: [...]." This mapping itself becomes a memory, stored at the campaign scope, that agents can retrieve when operating in the cross-org context.

Graph-enhanced memory (#170) is the natural vehicle for Layer 2. Typed relationships between terminology memories (synonyms, partial overlaps, scope-specific definitions, superseded definitions) start to look like a lightweight domain ontology without requiring formal ontology tooling.

### Layer 3: Ontology Mapping Engine

**Scope**: Long-term. Worth building only if medical, defense, or other regulated verticals become a significant part of the user base.

Layer 3 does not build ontologies. It helps map between existing ones. Standard ontologies already exist for many regulated domains: SNOMED CT, ICD-10, LOINC, and HL7 FHIR in healthcare; NIST and MITRE frameworks in cybersecurity; Basel and IFRS in financial services. The gap is not the absence of ontologies but the absence of tooling that maps an organization's actual terminology to the relevant standard ontology and keeps that mapping current.

MemoryHub could serve as the persistence and retrieval layer for those mappings. The mapping itself might be generated by an external tool (a LoRA-tuned model, a clinical terminology service, or manual curation), but the mappings would be stored as memories with full provenance, versioning, and scope governance.

The VA/community care case is the clearest illustration. A mapping memory might state: "Community Provider X's discharge summary term 'cardiac event' corresponds to ICD-10 codes I21-I25 in the VA system, but their usage excludes unstable angina (I20.0), which the VA includes." That mapping has provenance (who created it, when, based on what evidence), versioning (it may change as either system updates its coding practices), and scope (it applies to the specific federated context between these two organizations).

This layer is architecturally ambitious but does not require MemoryHub to become an ontology management system. It requires MemoryHub to be a good persistence layer for ontology *mappings*, with the governance, versioning, and access control that regulated environments demand.

---

## 3. Relationship to Existing Work

**Graph-enhanced memory (#170)** is the natural foundation for Layer 2. The richer entity-relationship model being designed there can represent terminology relationships (synonym-of, narrower-than, maps-to, superseded-by) without special-casing. Terminology relationships are just another type of edge in the memory graph.

**Context compaction (#169)** interacts with terminology in a critical way. If the compactor does not understand that a memory tagged `terminology` is definitional context, it might compact or discard it during summarization. A compacted context that loses the definition of "COPIS" forces the agent to fall back on its general knowledge, which says "SIPOC." The compaction policy needs a way to mark certain memories as compaction-resistant, or at least as high-priority for retention. Terminology memories are one class of memory that deserves this treatment; there are likely others.

**Extraction pipeline (#240)** could feed Layer 1 semi-automatically. When an agent encounters a term being defined in conversation ("When we say 'sprint' here, we mean a two-week planning cycle, not the Scrum ceremony"), the extraction pipeline could propose a terminology memory. The human still validates, but the extraction reduces the manual curation burden.

**Focus tracking** already supports the progressive unfolding pattern that FHIR and similar large domain models require. The gap is connecting focus declarations to domain-specific memory slices. If the agent declares focus on "claims processing," the retrieval layer should know to pull in Coverage, Claim, and ExplanationOfBenefit terminology alongside whatever operational memories match the query.

**The episodic/semantic boundary** matters here. Terminology definitions look like semantic knowledge (facts about what terms mean). But an organization's specific usage of those terms, the drift over time, the exceptions and edge cases, these are experiential knowledge that agents accumulate through interaction. MemoryHub's role is not to be the source of truth for "what does FHIR Patient mean" (that belongs in the semantic/library-RAG layer), but to be the source of truth for "how does *this organization* use FHIR Patient, and how does that differ from the standard."

---

## 4. Open Questions

**Compaction interaction.** How does progressive unfolding interact with context compaction (#169)? If the compactor runs while FHIR Coverage definitions are loaded, does it preserve them? If the agent pivots back to Coverage later, does it re-fetch from MemoryHub or work from the compacted summary? The answer likely depends on compaction policy, but the policy needs to be terminology-aware.

**Retrieval priority.** Should terminology memories receive special retrieval priority (always injected when a matching term appears in the query), or is tagging plus search-bias sufficient? Special priority risks token bloat if the terminology registry grows large. Search-bias risks missing critical definitions when the query does not happen to surface them. There may be a hybrid: always inject for terms in the current focus domain, search-bias for everything else.

**Layer 1 scaling limits.** At what scale does the convention-based approach (Layer 1) break down and require structural support (Layer 2)? Ten terminology memories per project are easy to manage. A hundred are manageable with good tagging. A thousand probably need hierarchy, search facets, and disambiguation logic. The threshold likely depends on how many scopes are in play and how much terminology overlaps between them.

**Temporal drift.** How do you handle terminology that evolves over time within an organization? MemoryHub's versioning tracks *that* a definition changed, but detecting *when* a definition has drifted from actual usage is harder. An agent might continue applying a definition that the organization has informally moved past. The extraction pipeline (#240) could help by detecting usage patterns that diverge from stored definitions, but this is an unsolved problem.

**Federation governance.** In the cross-org scenario (VA/community care, multi-agency defense programs), who owns the terminology mappings? MemoryHub's scope model supports multi-org campaigns, but the governance question is operational, not technical. Both organizations need to trust the mappings, and both need a way to flag when a mapping is wrong. The existing contradiction detection mechanism could serve as the flagging mechanism, but the resolution workflow needs human involvement.

---

## 5. What This Is Not

This exploration is not proposing that MemoryHub become an ontology management system. Tools like Protege, TopBraid, and domain-specific terminology servers (UMLS, BioPortal) exist for that purpose and are far more capable at managing formal ontologies.

It is not proposing OWL, RDF, or SPARQL infrastructure. MemoryHub's memory graph is a property graph, not a semantic web triple store, and that is the right choice for its mission.

It is not proposing LoRA training or model fine-tuning as a MemoryHub feature. Domain-specific model tuning is valuable but belongs in the model serving layer (OpenShift AI, vLLM), not in the memory layer.

The insight is narrower and more practical: a lightweight terminology-aware layer, built on existing memory primitives with minimal new infrastructure, solves a real and recurring problem in regulated enterprises. Organizations that adopt AI agents will immediately run into terminology divergence. Giving them a simple, governed way to teach their agents the local dialect, using memories they already know how to create, removes a barrier to adoption that no amount of model training will fix.
