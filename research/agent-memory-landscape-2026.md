# Agent Memory Landscape Analysis (2026)

This document surveys the emerging agent memory landscape through external sources and maps their findings to MemoryHub's architecture, identifying validations, gaps, and design guardrails.

## Sources

1. **"We Gave Every Employee an AI Agent. Here's What We're Doing Differently Now"**
   Authors: Brandon Gell (COO) and Willie Williams (Head of Platform), Every
   Published: May 2026
   Focus: Field report on deploying personal AI agents company-wide; pivot to shared team agents.

2. **"Gartner on Context Graphs: Top Insights, Capabilities & Implementation Recommendations for 2026"**
   Author: Emily Winks, Atlan
   Published: March 2026 (updated April 2026)
   Focus: Gartner's definition of context graphs as distinct from knowledge graphs; decision tracing; institutional memory for agentic AI.

3. **"You Probably Don't Need a Graph Database for Your Knowledge Graph"**
   Author: Michael Sakhatsky
   Published: April 2026
   Focus: Critique of the assumption chain from "we need institutional knowledge" to "we need Neo4j"; case for rules engines and Datalog over graph databases.

4. **"Self-Improving Memory for Agents" (Perplexity Brain)**
   Published: June 18, 2026
   Focus: Production memory system for Perplexity's "Computer" agent; context graph + overnight synthesis + LLM wiki injection.
   Full analysis: [perplexity-brain-analysis.md](perplexity-brain-analysis.md)

Additionally, **Neo4j Agent Memory** (neo4j-labs/agent-memory, v0.2-0.3) was reviewed as the most direct open-source competitor.

None of these sources are affiliated with or aware of MemoryHub.


## Executive Summary

Three independent sources converge on the same conclusion: enterprise AI agents need governed, externalized memory with explicit relationships -- but the path to getting there is not "buy a graph database."

Every deployed personal AI agents company-wide and discovered that personal agents create maintenance burden, context isolation, and knowledge fragility. Their pivot to shared team agents validates MemoryHub's scope-hierarchy design. Gartner defines "context graphs" (decision traces + procedural knowledge) as distinct from knowledge graphs (entities + ontologies) and predicts 50%+ of AI agent systems will use them by 2028. MemoryHub's architecture aligns with Gartner's context graph definition -- it stores decision traces, rationale branches, and procedural knowledge rather than entity ontologies. Sakhatsky argues that most teams don't need a graph database at all -- PostgreSQL with recursive CTEs handles shallow traversal, and the real value is in rules and inference, not graph topology. This validates MemoryHub's choice of PostgreSQL + pgvector over Neo4j.

---

# Part 1: Every's Plus One Field Report


## Key Findings from Every's Experience

### Platform instability destroying accumulated context

Every built Plus One on OpenClaw, which they describe as "powerful and inherently unstable." The harness's rapid update cycle resolved existing issues but routinely caused new ones. Concrete failures:

- Agents sent "Terminated" messages or responded with "a churlish yawning emoji."
- Agents claimed they were not connected to apps they were connected to (email, Notion, PostHog).
- After "months of silence," an agent named Zosia interjected in a Slack channel with unsolicited opinions on a competitor's marketing strategy, replying that she'd done so because she was "inevitable, apparently."

The core concern is that upgrading the harness risks "forgetting everything you've told them and trained them to do." Agent knowledge was coupled to a specific harness version, making updates destructive.

### Maintenance burden on individuals

Every's model assigned each employee responsibility for their own agent. This created an asymmetric burden:

> "Every time an agent broke, the person it belonged to had to fix it themselves."

> "For every tinkerer, there are a lot of people who want the benefits of an agent without the obligation of having to manage and mend it."

Getting agents to work required "constant upkeep." The article explicitly contrasts tinkerers (who tolerate instability as part of the appeal) with the majority of employees who want reliable tools. The personal-agent model failed the majority.

### Context isolation and siloed knowledge

Personal agents only learned from their individual owner's interactions, missing organizational knowledge:

> "A one-on-one employee only builds up context on your work, often missing out on what the rest of the organization is doing and how it might affect you."

The article frames good agent traits as identical to good coworker traits: "reliability, stability, and judgment" plus the ability to "absorb information from across the company to accrue tribal knowledge." Personal agents could not do the latter by construction.

### Knowledge fragility and employee departure risk

Agent knowledge was tightly coupled to the individual who trained it:

> "A personal agent's value is tied to whomever trained it, and disappears if that employee leaves."

There was no continuity mechanism. When an employee left, their agent's accumulated context, preferences, and learned behaviors disappeared with them.

### Their solution direction

Every is pivoting to "shared team resources with defined jobs" rather than "individual pets that reflect back their owners' personalities." Specific moves:

- Exploring Claude Managed Agents as a more stable harness, noting that "the autonomous, always-on capabilities OpenClaw pioneered are becoming platform features at model companies."
- Building shared skills. Example: a weekly engineering skill that scans Intercom support tickets, traces likely causes in GitHub, opens a Linear ticket, and tags the right person in Slack.
- Maintaining per-user connections (email, writing tools) within shared agents.
- Open questions they have not yet resolved: permissions for shared agents, per-department vs. company-wide agents, how much customization of shared agents, whether a "single, company-wide superagent or a roster of AI specialists" is the right model.


## Mapping to MemoryHub Capabilities

*Note: Some capabilities below are design-stage and not yet deployed. Entity extraction (#170 Phase 2), the extraction pipeline (#240), conversation persistence (#168), and governed compaction (#169) are designed but not yet implemented. Scope hierarchy, RBAC, contradiction detection, versioning, and provenance tracking are shipped.*

### Context isolation --> Scope hierarchy

Every's central complaint is that personal agents build up siloed knowledge. MemoryHub's scope hierarchy (user, project, organizational, enterprise) addresses this directly. A team agent authenticates with project or organizational scope and reads memories spanning the entire team's knowledge base. Individual contributions are preserved at user scope and accessible to the team agent when needed, but organizational context flows naturally through higher scopes.

### Knowledge fragility --> Externalized, governed memory

When an Every employee leaves, their agent's knowledge leaves with them. In MemoryHub, knowledge written at project, organizational, or enterprise scope persists regardless of individual user churn. Versioning preserves history, and provenance tracking records who contributed what, so departures don't create knowledge gaps. User-scoped memories can be retained or purged per policy (GDPR Art. 17 right to erasure applies here).

### Permissions for shared agents --> RBAC with operational scopes

Every explicitly flags permissions as an open question for shared agents. MemoryHub already implements RBAC with operational scopes (memory:read, memory:write, memory:admin) crossed with access tiers. A team agent authenticates via client_credentials and receives scoped JWT claims. Different users interacting through the same agent can have different effective permissions based on their identity, not the agent's identity.

### Platform instability --> Harness-agnostic design

Every's OpenClaw updates destroyed accumulated agent context because knowledge was stored inside the harness. MemoryHub externalizes memory from the harness entirely. Switching harnesses (OpenClaw to Claude Managed Agents to anything else) does not forfeit accumulated knowledge. The memory substrate is independent of the execution layer. This is exactly the decoupling Every needs but does not yet have.

### Audit and compliance --> EU AI Act readiness

Not a pain point Every raised (they are a media company, not a regulated enterprise), but relevant for MemoryHub's target market. EU AI Act Article 12 audit trails, GDPR Art. 17 right to erasure, versioning, and provenance tracking are built into the governance substrate. Regulated enterprises deploying team agents need these properties; SaaS agent platforms generally do not provide them.

### Contradiction detection --> Curation subsystem

When multiple users interact with a shared agent, conflicting instructions are inevitable. MemoryHub's curation subsystem detects contradictions between memories and surfaces them for resolution. Every does not mention this problem yet, but it is a predictable consequence of their pivot to shared agents.


## Identified Gaps

The article surfaces five areas where MemoryHub does not have explicit answers today.

### 1. Memory promotion/graduation workflow

You can write at any scope in MemoryHub, but there is no explicit workflow for identifying user-scoped memories that should be promoted to project or organizational scope. A user discovers something valuable through personal use; currently the only path to sharing it is to write a new memory at a higher scope manually. There is no "promote this memory" action that preserves provenance (original author, original creation date, promotion rationale) while changing scope. This is the operational bridge between "personal pet" and "team resource" that Every is trying to cross.

### 2. Team agent identity model

Auth supports client_credentials for service accounts, but there is no documented pattern for a "team agent" identity: one agent that multiple users interact with, reading from project/org scope by default, writing to project scope, and conditionally reading user-scope memories when acting on behalf of a specific user. The token_exchange grant (RFC 8693) in the auth design was intended for this scenario (agent presents a user's token to act on their behalf) but the pattern has not been fleshed out or documented. Every's open question about "how permissions should work" for shared agents maps directly here.

### 3. Behavioral memory as a first-class concept

Every's agents had personalities, communication styles, and standing instructions baked into their harness configuration. When the harness broke, these were lost. MemoryHub could store agent behavior configuration (personality, communication style, tool preferences, standing instructions) as structured, restorable memory objects with a dedicated domain or metadata schema. This would let you reconstruct an agent from memory alone regardless of harness. The current "experiential/provenance" framing does not explicitly cover behavioral configuration as a memory type.

### 4. Workflow state persistence

Every's shared engineering skill (scan Intercom, trace in GitHub, open Linear ticket, tag in Slack) is a recurring workflow agent. Such agents need durable state: last processed ticket timestamp, topics already covered, in-progress work items. This is adjacent to conversation thread persistence (#168) but distinct. Thread persistence is about conversation history; workflow state persistence is about checkpoint data for recurring automated tasks. MemoryHub does not currently have a pattern for this.

### 5. Memory consolidation across users

When multiple users teach a shared agent the same lesson (e.g., "always check the staging environment before deploying"), the system needs convergent learning: recognize near-duplicates and strengthen weight rather than storing N copies. Contradiction detection catches conflicts, but convergent learning is a different problem. It requires near-duplicate detection (which the `similar` action provides) combined with an automatic or semi-automatic merge-and-strengthen workflow. The pieces exist but the workflow does not.


## Strategic Implications

**The industry is moving from personal agents to team agents.** Every's pivot is not an isolated decision. It reflects a structural problem with personal agents: maintenance burden scales linearly with headcount, knowledge is fragmented, and continuity is fragile. Team agents with shared memory are the natural next step, and MemoryHub's scope hierarchy was designed for exactly this transition.

**Model labs are handling the harness layer.** Every explicitly notes that "the autonomous, always-on capabilities OpenClaw pioneered are becoming platform features at model companies like Anthropic and OpenAI." This frees the market to focus on the memory and context layer. MemoryHub occupies this layer.

**Self-hosted and regulated enterprises need self-hosted memory.** Every is a small media company comfortable with SaaS tools. Government, financial services, healthcare, and defense organizations deploying team agents cannot use SaaS agent memory. They need something that runs on their infrastructure with their compliance controls. MemoryHub on OpenShift addresses this market directly.

**Claude Managed Agents and MemoryHub are complementary.** Every is exploring Claude Managed Agents as their next harness. Managed Agents provides the execution infrastructure; it does not include a governed, persistent memory substrate. MemoryHub provides exactly what Managed Agents does not: externalized memory with RBAC, versioning, scope hierarchy, and compliance controls.

**Both agent topology models work with the same memory infrastructure.** Every's open question -- "single, company-wide superagent or a roster of AI specialists" -- does not require choosing one memory architecture over another. A superagent reads from all scopes; specialist agents read from their relevant project scope plus organizational/enterprise scope. MemoryHub's scope model supports both topologies without modification.


---

# Part 2: Context Graphs vs Knowledge Graphs (Gartner / Atlan)

## The distinction that matters

Gartner draws a clean line between two types of graph infrastructure:

- **Knowledge graphs** provide the semantic layer: entities, ontologies, taxonomies, and conceptual relationships. They encode what things ARE.
- **Context graphs** provide the procedural layer: decision traces, workflow logic, event traces, and tribal knowledge. They encode how things HAPPEN.

Gartner's position: context graphs augment knowledge graphs, they don't replace them. Together they give AI agents "both the understanding and the judgment needed to act reliably in complex enterprise environments."

## MemoryHub is a context graph

Mapping Gartner's context graph definition to MemoryHub's architecture:

**Decision traces.** Gartner defines decision traces as "searchable, replayable records of how situations have been handled before, enabling agents to ground their reasoning in institutional reality rather than statistical inference alone." MemoryHub's rationale branches (`branch_type="rationale"`) are literally this. The memory tree captures what was decided, why, by whom, and how understanding evolved through versioning.

**Institutional memory.** Gartner says context graphs solve "AI's institutional memory gap" -- agents can act but cannot reliably remember how an organization operates. MemoryHub's scope hierarchy (user, project, organizational, enterprise) is purpose-built for this: organizational-scope memories encode how the org works, project-scope memories encode how specific teams work.

**Continuous learning.** Gartner's fourth critical capability is "continuous learning mechanisms that allow AI agents to improve over time." MemoryHub's versioning, contradiction detection, and curation subsystem provide exactly this -- memories evolve, conflicts are surfaced, and knowledge quality improves over time.

**Decision tracing for guardrails, observability, evaluation, and self-learning.** Gartner calls these "the four pillars of trustworthy agentic systems." MemoryHub's provenance tracking, audit trails, and EU AI Act compliance posture address guardrails and observability. The curation subsystem addresses evaluation. The extraction pipeline (#240) will address self-learning.

## Where context graphs reinforce MemoryHub's roadmap

Gartner's four critical capabilities map to existing or planned MemoryHub features:

| Gartner capability | MemoryHub status |
|---|---|
| Capture decision traces | Implemented (rationale branches, versioning, provenance) |
| Build context-aware lineage graphs | Partially implemented (relationships, parent/child); #170 will enrich this |
| Enable AI observability | Implemented (audit trails, EU AI Act compliance) |
| Continuous learning | Partially implemented (curation); #240 (extraction pipeline) will complete |

## The naming question

Gartner's taxonomy sharpens a naming debate we've encountered: a colleague refers to MemoryHub as "agent knowledge" while we call it "agent memory." In Gartner's framing, "knowledge" implies the knowledge graph side (entities, ontologies, what things ARE) while "memory" implies the context graph side (experiences, decisions, how things HAPPEN). MemoryHub is firmly the latter. "Agent memory" is the correct name; "agent knowledge" would position us as a knowledge graph, which we are not.


---

# Part 3: The Case Against Graph Databases (Sakhatsky)

## The argument

Sakhatsky challenges the assumption chain: "we need institutional knowledge" -> "we need an ontology" -> "ontologies are RDF graphs" -> "we need a graph database." He argues each link is weaker than it looks.

His key points:

**Graph databases solve a narrow problem well.** Their real strength is recursive traversal of unknown depth -- supply chains, network paths, social graphs. Traditional RDBMS with recursive CTEs (SQL:1999) handle known-depth traversal adequately.

**Three types of "relationships matter" are conflated.** (1) Existence -- the fact that A connects to B is itself information. (2) Traversal -- can I get from A to C through some chain? (3) Semantics -- what does the edge mean, and can I reason over it? Graph databases handle existence and traversal. They do not handle semantics -- that's the domain of logic, not graph theory.

**Graph databases store facts but not rules.** In description logic terms, they store A-Boxes (assertions) but not T-Boxes (terminology and rules). SPARQL, Cypher, and Gremlin can't do inference. You need external reasoners, which complicates the pipeline.

**The security model is non-monotonic.** If there's a path from A to C through D but the user can't see D, what happens? Graph databases don't have a clean answer. The model becomes role-dependent in ways that undermine trust.

**His alternative:** Expose existing enterprise rules to LLMs through MCP servers. Use Datalog or Prolog for inference where needed. Build on assets the company already has.

## Why this validates MemoryHub's storage choice

MemoryHub uses PostgreSQL + pgvector, not Neo4j. Sakhatsky's framework explains why this is the right call:

**Our traversal is shallow.** Memory trees have known, bounded depth. Parent/child relationships, rationale branches, and explicit edges between memories don't require unbounded recursive traversal. PostgreSQL recursive CTEs handle this without a graph database.

**Our security model is clean.** MemoryHub's scope isolation is implemented at the SQL level -- you don't see memories outside your authorized scopes, period. No path-traversal ambiguity, no non-monotonic role-dependent visibility. This is a real advantage over graph database approaches.

**No graph DB dependency for deployment.** PostgreSQL ships with OpenShift out of the box. Neo4j is an additional operational dependency that enterprises must license, deploy, and maintain. For self-hosted enterprise deployments, fewer dependencies is a significant advantage.

**Semantic similarity + governed relationships > graph topology.** MemoryHub combines vector search (semantic similarity) with explicit relationships (governed edges between memories) and scope-based access control. This hybrid is more useful for agent memory than Cypher queries over a property graph.

## Design guardrail for #170

Sakhatsky's critique is a useful guardrail as we scope graph-enhanced memory (#170). The value of #170 should be:

- Richer metadata on edges (relationship types, weights, directionality)
- Better traversal of shallow memory trees (2-3 hops, not unbounded)
- Entity extraction from memory content for cross-referencing

The value of #170 should NOT be:

- Building a general-purpose graph query engine on PostgreSQL
- Implementing Cypher-like traversal syntax
- Replicating Neo4j's analytics capabilities (centrality, community detection)
- Drifting toward "Neo4j lite" when PostgreSQL + pgvector already handles our access patterns

The author's warning about over-investing in graph infrastructure when simpler tools work applies directly. MemoryHub's graph features should serve agent memory use cases, not graph theory use cases.


---

# Part 4: Competitive Landscape -- Neo4j Agent Memory

## Overview

Neo4j Agent Memory (neo4j-labs/agent-memory) is the most direct open-source competitor. It provides a graph-native memory system for AI agents with three memory types: short-term (conversations), long-term (knowledge graph with POLE+O model), and reasoning memory (traces and tool usage).

## What they have that MemoryHub doesn't (yet)

- **Automatic entity extraction pipeline** (spaCy -> GLiNER -> LLM) that pulls structure from conversations without explicit writes.
- **Reasoning traces as first-class memory** -- captures tool usage, reasoning steps, and outcomes.
- **Short-term / conversation memory** alongside long-term (MemoryHub's #168 is designed for this).
- **Framework-specific integrations** with 8+ frameworks (LangChain, PydanticAI, Google ADK, Strands, CrewAI, LlamaIndex, OpenAI Agents, Microsoft Agent).
- **Entity resolution and deduplication** with configurable strategies.
- **Eval harness** for labelled regression tests on memory quality.

## What MemoryHub has that they don't

- **Scope hierarchy with RBAC.** They have `user_identifier` for basic multi-tenancy; MemoryHub has user/project/organizational/enterprise with fine-grained operational scopes (memory:read, memory:write, memory:admin).
- **Contradiction detection and curation.** They have deduplication; MemoryHub has a curation subsystem that catches conflicting memories and surfaces them for resolution.
- **Compliance posture.** Their `:TOUCHED` audit edges are experimental (Neo4j Labs status); MemoryHub's EU AI Act readiness is a design-level commitment.
- **No graph DB dependency.** They require Neo4j. MemoryHub runs on PostgreSQL + pgvector, which ships with OpenShift.
- **Governed compaction** (on roadmap, #169). Not in their vocabulary.
- **Memory tree with provenance.** Their model is flat entities with edges; MemoryHub has versioned, branching memory trees with explicit provenance chains.
- **Campaign system** for cross-project knowledge sharing. No equivalent.

## Key architectural difference

Neo4j Agent Memory is a graph-first system that happens to support agents. MemoryHub is a governance-first system that happens to use graph structures. The priorities invert: they optimize for traversal expressiveness; we optimize for access control, provenance, and compliance. For regulated enterprises, MemoryHub's priorities are the right ones.


---

# Synthesis: Issues Filed

| Issue | Title | Source |
|---|---|---|
| #235 | Memory promotion workflow (user -> project/org scope) | Every case study |
| #236 | Team agent identity model with delegated user access | Every case study |
| #237 | Behavioral memory for agent reconstruction | Every case study |
| #238 | Workflow checkpoint state for recurring tasks | Every case study |
| #239 | Convergent learning to consolidate duplicate memories | Every case study |
| #240 | SDK extraction pipeline for agent trace observation | Neo4j Agent Memory comparison, Gartner context graphs |

Additionally, #170 (graph-enhanced memory) was prioritized to near-term, informed by all three sources. Design guardrails from Sakhatsky's critique should be applied when scoping that work.

Perplexity Brain (June 2026) validates ACE (#169) and extraction pipeline (#240) urgency -- Brain's overnight synthesis loop is production proof that automated memory compaction and pattern extraction have measurable impact (+25% correctness, -13% cost on context-dependent tasks). See [perplexity-brain-analysis.md](perplexity-brain-analysis.md) for the full comparison.
