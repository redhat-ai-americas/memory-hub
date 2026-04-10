# Enterprise Requirements Findings

What enterprises say they need in an agent memory layer that academic benchmarks do not measure. Cross-referenced against MemoryHub's governance subsystem.

**This is the primary value story for MemoryHub.** The discussion this research supported (2026-04-08) confirmed the team's direction: MemoryHub is aimed at regulated customers — government, financial services, healthcare, defence — for whom flat vector memory is structurally disqualified. The items in this file are not a wish list of features to borrow from; they are the set of concrete governance requirements that the enterprise literature already names and that a memory layer without first-class scope, versioning, provenance, curation, and audit trails cannot deliver. MemoryHub ships several of them already and has the right architectural homes for most of the rest.

**Scoping note.** MemoryHub covers the **episodic and procedural** memory layer — time-indexed, private, experiential, and behaviour-shaping. It is deliberately not the semantic layer. A separate hub project in planning targets the semantic side (facts, shared knowledge, library-style RAG) with a matching governance posture. Together they form a two-hub stack for agents operating in regulated environments. Reading this file, keep the scoping in mind: "memory poisoning" and "staleness" are not being claimed as problems MemoryHub will solve for the entire corpus of enterprise knowledge — only for the episodic/procedural layer that no other system in this research covers.

Sources for this file (full details in `sources.md`):

- Atlan "AI Agent Memory Governance: Why Ungoverned Memory Is an Enterprise Risk" (April 2026)
- Oracle "Introducing Oracle AI Agent Memory" (December 2025)
- Hindsight / Vectorize AMB launch post (March 2026)
- "Anatomy of Agentic Memory" survey (February 2026)
- Letta's "Benchmarking AI Agent Memory" blog (2025)
- HN thread on Mozilla Cq (practitioner skepticism about shared agent memory)
- "Governed Memory: A Production Architecture for Multi-Agent Workflows" arxiv 2603.17787 (March 2026)

---

## The central tension

Every source reviewed agrees on this: **memory layer tools solve a retrieval problem; enterprise memory requires a governance layer on top.** Atlan states it most bluntly — "memory tools solve one question: 'what is semantically similar to this query?' That is a useful capability. It is not governance." Oracle's launch post frames the same gap as "architectural sprawl" and pitches a unified converged-DB approach. Hindsight's framing is pragmatic cost-benefit: accuracy alone is not enough.

Academic benchmarks evaluate the retrieval half. The governance half has no equivalent.

---

## Enterprise requirements taxonomy

Grouped by the themes that repeat across sources.

### 1. Auditability

**What is needed.** An operator must be able to reconstruct, at an arbitrary past time, what the agent "knew" — which memories it could see, which it actually retrieved, and which decisions those memories influenced. This maps to:

- **EU AI Act Article 12** (record-keeping for high-risk AI systems). Enforceable **August 2, 2026**. Penalties up to 3% of global turnover or €15M.
- **EU AI Act Article 13** (transparency). Up to 4% of global turnover.
- **SOX IT General Controls** for any agent affecting financial reporting.
- **FINRA SR 11-7** (model risk management in financial services).
- **GDPR Article 25** (data protection by design).

**What memory layers typically provide.** Last-write-wins storage with embedding + timestamp. No record of which policy was active at retrieval time. No record of which retrieval was actually fed into which generation. Atlan: "decision traces — which capture reasoning paths, policies applied, precedents referenced, and approvals obtained — are a distinct architectural component that no memory layer tool provides natively."

**MemoryHub status.** Partial. The memory-tree model has versioning (`isCurrent`, version history via `get_memory_history`), provenance branches, and RBAC attributes on every read path. **Audit log is still a stub interface (#67), not wired through.** This is the gap between "we record version history" and "we can produce a regulator-ready audit trail". Closing #67 is the single highest-leverage governance item in our backlog.

### 2. Access control at content level (not query level)

**What is needed.** Authorization cannot be "who is allowed to call `search_memory`". It must be "which specific memories is this caller allowed to see". Databricks AI Security Framework (DASF v3.0) cites OWASP AI Agent Security guidance: **per-user memory namespacing as a mandatory control**.

**Risk that memory layers fail on.** A shared enterprise assistant serves both general employees and HR executives. Executive compensation data retrieved during an HR session is stored in the agent's memory. A standard employee's next session surfaces it. The access-control flag in the memory tool controls "who can query the store"; it does not control "which content appears in which user's response". These are different problems.

**MemoryHub status.** **Shipped** — #46 Phase 4 landed 2026-04-08. Tenant isolation is enforced at the SQL level in every read path: `memory.py` (read / filter / count / search / search-with-focus / get-history), `graph.py get_relationships`, `curation` similarity + rules + pipeline. Cross-tenant reads raise `MemoryNotFoundError` indistinguishable from nonexistent. Scope system goes further than tenant — user / project / role / organizational / enterprise are all first-class on every memory.

This is MemoryHub's strongest governance story and it is **directly aligned with DASF v3.0 and Atlan Risk #3.** It would be worth calling this out explicitly in any external-facing material.

### 3. Provable deletion for regulated data

**What is needed.** GDPR Article 17 (right to erasure) requires on-request deletion of personal data. HIPAA retention rules require predictable minimum-necessary access and defined retention windows. Auditors will ask operators to demonstrate that data was deleted when requested — not just marked deleted, but actually unrecoverable.

**Hard problem the industry has not solved.** Atlan: "no commercially available vector database provides a provable deletion mechanism for embedded personal data." IAPP 2025 guidance asks for "deletion as a callable operation with captured evidence" — callable exists almost everywhere, captured evidence is the hard part. Cloud Security Alliance (April 2025) has documented that source-free unlearning for embeddings remains experimental.

**MemoryHub status.** `delete_memory` exists as an MCP tool. Whether delete is tombstone or hard-delete needs verification in code. Even a hard-delete does not constitute "proof" in a regulatory sense unless we capture evidence. **Gap: we do not currently produce a deletion receipt.** The audit-log stub (#67) is again the right home for this.

### 4. Staleness and source-change invalidation

**What is needed.** When upstream data changes — a schema update, an ownership transfer, a metric definition revision — the memory layer must detect it and invalidate affected entries before an agent acts on stale context. Atlan's example: a finance agent's memory contains the pre-restatement definition of "net revenue"; three months of board reporting use the wrong number before anyone notices.

**What memory layers provide.** Append-only or recency-ranked storage with no temporal validity model. No freshness signals pushed from upstream sources.

**MemoryHub status.** **Never contemplated** as an architectural property. MemoryHub has an `expires_at` field for opt-in TTL (agent sets it at write time), but no push mechanism from an upstream data source. This is not blocking today because MemoryHub's current corpus is agent-authored text, not derived from upstream structured data. **It will become blocking the day org-ingestion ships** — the moment memory is derived from Slack, wikis, Jira, or any upstream source, the problem lands in our lap. The org-ingestion design should include freshness signals from day one.

### 5. Cost controls

**What is needed.** Enterprises treat AI memory as they treat any other infrastructure cost center. "A system that scores 90% accuracy but costs $10 per user per day is not better than one that scores 82% and costs $0.10" (Hindsight). Atlan frames cost as part of governance — operators must be able to demonstrate that the memory layer does not drive runaway token bills.

**Signals in the benchmarks.** AMB tracks token cost alongside accuracy. Letta Context-Bench publishes dollar cost per run as a first-class column. "Anatomy of Agentic Memory" survey: "system-level costs are frequently overlooked" — this is one of the paper's main critiques of the field.

**MemoryHub status.** **Not measured.** We don't instrument per-query embedding token cost, per-write token cost, cross-encoder rerank cost, or generation cost (when agents feed retrieved memory into LLMs). There is no dashboard for "dollars per user per day". This is one of the few gaps where "governance" overlaps cleanly with "run a benchmark" — if we run AMB, the cost column comes for free, and we get at least a lower bound on what a production answer looks like.

### 6. Poisoning resistance and integrity

**What is needed.** The memory layer must resist attacker-injected memories being returned as authoritative facts. PoisonedRAG (2024) showed that **five malicious documents in a corpus of millions cause 90% attack success on targeted queries.** Microsoft Security Blog (February 2026) documented "AI Recommendation Poisoning" at enterprise scale, including via stealthy URL parameters injected into agent memory on a single click.

**HN Cq thread — practitioner signal.** The top-comment skepticism in the Mozilla Cq thread was entirely about this: supply-chain attacks on shared knowledge, compounding hallucination, inability to verify correctness at scale, sybil-resistance gaps. Practitioners do not trust shared agent memory until poisoning is solved.

**What memory layers provide.** Almost nothing. Atlan: "vector databases store embeddings ranked by semantic similarity. They have no concept of 'this fact was wrong when stored' or 'this entry conflicts with a certified source'. There is no integrity check, no provenance model, no mechanism to detect that a stored entry was injected rather than legitimately retrieved."

**MemoryHub status.** **Never contemplated.** Authenticated writes (JWT + RBAC) block *unauthorized* writes, but an authorized agent or user can write anything. The curator-agent's regex scanning and embedding dedup are the only defenses, and they are tuned for quality, not adversarial detection. **This is the single biggest "never contemplated" gap I found** — and it has regulatory tailwind (FTC Act Section 5, EU AI Act Art. 12). It is also the one gap where MemoryHub's existing curator subsystem is the natural architectural home for a fix.

### 7. Multi-agent consistency

**What is needed.** In a multi-agent system, two agents cannot maintain conflicting facts about the same entity without detection. Arxiv 2603.17787 ("Governed Memory: A Production Architecture for Multi-Agent Workflows") frames this as: "Agents can read stale data written by a peer or overwrite each other's episodic records". Multi-agent memory consistency requires read-time conflict handling and update-time visibility.

**MemoryHub status.** **Partial.** Within a tenant, all agents write into the same memory-tree, so there is a shared surface. curator-agent dedup detects write-time similarity. `report_contradiction` allows flagging. But there is no active cross-agent conflict detection that would, say, detect that agent A wrote "Q3 NRR is 112%" while agent B wrote "Q3 NRR is 108%" for the same quarter. **This becomes critical the moment kagenti-integration or llamastack-integration ships**, because those integrations bring multi-agent coordination patterns into scope.

### 8. Trust boundaries for "team memory" and org-scoped knowledge

**What is needed.** When memory is shared across a team (the Cq thread's framing), there must be a trust/review layer between an agent's proposed memory and the shared pool. Cq bakes this in as "local storage by default; optional team sharing with human-in-the-loop review before other agents access". This is an explicit response to the poisoning and hallucination concerns in the thread.

**MemoryHub status.** **Partial by scope.** The scope system (user / project / role / organizational / enterprise) is a static classification, not a promotion workflow. An agent writes into `organizational` scope at its own discretion, subject to RBAC. There is no inline review step between a user scope memory and an organizational scope memory.

This is an interesting design question: should promotion to higher scopes go through curator-agent review or human-in-the-loop approval? The current answer is "no" and nobody on the team has argued otherwise. But the cross-team Cq pattern suggests enterprises will ask.

### 9. BYO embeddings, air-gap, and FIPS

**What is needed.** Enterprises with data-residency, air-gap, or FIPS requirements need:

- BYO embedding model (no "send everything to OpenAI to embed")
- On-prem / air-gap deployable
- FIPS 140-3 validated encryption at rest and in transit
- No outbound dependency on third-party inference endpoints

**MemoryHub status.** **Aligned by architecture.**

- Embedding model is all-MiniLM-L6-v2 served via vLLM on OpenShift AI — on-cluster, no outbound dependency.
- Cross-encoder reranker (ms-marco-MiniLM-L12-v2) is also vLLM-served on cluster, and the focus-path code gracefully falls back to plain pgvector cosine when the reranker URL is unreachable.
- PostgreSQL + pgvector + MinIO are all deployable air-gapped.
- FIPS compliance is inherited from the OpenShift cluster's FIPS mode but has **not been validated end-to-end** per `docs/SYSTEMS.md`.

This is another differentiator that academic benchmarks don't touch and that vendor benchmarks (AMB, Letta) don't measure. Worth calling out.

### 10. Unified data platform vs architectural sprawl

**What is needed.** Oracle's December 2025 launch post is explicit: enterprises do not want a "vector store + graph DB + document store + RDBMS" stack just to run agent memory. They want one system that supports all four data models with consistent governance.

**MemoryHub status.** **Aligned.** PostgreSQL + pgvector handles vectors, relational, and graph (we use it for `create_relationship` / `get_relationships`). MinIO is the only auxiliary store, and it is deferred. This is the same architectural bet Oracle just made. We should expect to see Oracle AI Agent Memory and MemoryHub described as making the same architectural choice, against the Mem0 / Zep / Letta "separate specialized service" model.

---

## Mapping enterprise requirements to MemoryHub

| Requirement | MemoryHub status | Aligned subsystem | Priority gap |
|---|---|---|---|
| Auditability (EU AI Act Art. 12) | Partial (versioning yes, audit log stub) | governance (#67) | **Close #67** |
| Content-level access control | Shipped (#46 Phase 4) | governance + memory-tree | — |
| Provable deletion (GDPR Art. 17) | Partial (delete exists, receipt missing) | governance | Deletion receipt via audit log |
| Staleness / invalidation | Not contemplated | org-ingestion (TBD) | Design-time for org-ingestion |
| Cost controls | Not measured | observability (TBD) | Instrument on AMB run |
| Poisoning resistance | Not contemplated | curator-agent (natural home) | **Biggest gap** |
| Multi-agent consistency | Partial | kagenti / llamastack integrations | Design-time for integration partners |
| Team memory trust boundaries | Static via scopes; no promotion workflow | memory-tree + curator | Open design question |
| BYO embeddings / air-gap / FIPS | Aligned architecturally; FIPS end-to-end unvalidated | storage-layer + embeddings | FIPS validation |
| Unified data platform | Aligned (Postgres-only) | storage-layer | — (strong already) |

---

## What the enterprise literature agrees MemoryHub should emphasize

Points on which every enterprise-facing source agrees and MemoryHub already delivers:

- Single-platform (no fragmentation) — Oracle, Atlan, our Postgres-only approach all agree
- Content-level access control via scope + tenant — Atlan Risk #3, DASF v3.0, our #46 Phase 4
- Versioned memory with `isCurrent` / provenance — lands EU AI Act Art. 12 traceability partway home

Points on which the enterprise literature agrees and MemoryHub has gaps:

- Audit trail that a regulator could consume (#67)
- Poisoning resistance (no design)
- Staleness invalidation (will matter once org-ingestion ships)
- Cost instrumentation (no data)
- Provable deletion (no receipt)

## One warning

The enterprise governance literature is vendor-heavy. Atlan sells a governance platform; Oracle sells a database. Both have an interest in calling memory-layer-only solutions insufficient. The claims still check out against academic sources (PoisonedRAG, Cloud Security Alliance, IAPP, the "Governed Memory" arxiv paper), and the regulatory anchors (GDPR, HIPAA, SOX, EU AI Act) are real. But anyone using this file for an external pitch should be careful not to over-rely on vendor framing.
