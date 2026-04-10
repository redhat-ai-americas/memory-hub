# MemoryHub Gap Analysis

Two-way mapping between MemoryHub's subsystems and the benchmark landscape in `benchmark-inventory.md`. This is the file to bring into the discussion — it is where the "honest gap" answer lives.

Status of MemoryHub subsystems cross-referenced against `docs/SYSTEMS.md` (as of 2026-04-08). Shipped = green; roadmap = yellow; never contemplated = red.

---

## Direction A — "We have X, is there a benchmark for it?"

For each MemoryHub subsystem or feature, what benchmark (if any) can we point at to give the team a score?

### A1. memory-tree — tree-structured memories with branches, weights, scopes, versioning

- **Benchmark fit:** weak. No public benchmark tests tree-structured memory as a shape. LoCoMo / LongMemEval / AMB all treat memory as a flat bag of strings with vector retrieval on top.
- **Closest fit:** MemoryAgentBench's FactConsolidation (tests whether the system reconciles updated facts) would exercise our versioning/`isCurrent` path indirectly — but it cannot reward us for the audit-trail we preserve vs a system that overwrites in place.
- **Honest read:** if we ran LongMemEval against MemoryHub the tree structure would be invisible to the scoring. We would be judged only on the quality of our retrieval, not on the provenance or audit properties of the store.

### A2. storage-layer — PostgreSQL + pgvector

- **Benchmark fit:** none directly. Storage layer is an implementation detail all the benchmarks are indifferent to.
- **Indirect:** Mem0 paper's latency numbers (91% p95 reduction vs full-context) are storage-adjacent and let the team set expectations for what AMB's latency column would look like for MemoryHub. We would likely land in the same order of magnitude.

### A3. curator-agent — deterministic inline curation (regex scan, embedding dedup, three-layer rules)

- **Benchmark fit:** **MemoryAgentBench** is the best match. Its "selective forgetting" and "FactConsolidation" competencies test capabilities our curator is designed to provide. Running MemoryHub against MemoryAgentBench would be the first place we could get an academic number on the curator's behaviour.
- **Second fit:** MemSim methodology. MemSim is a *simulator* rather than a static dataset; it generates QA pairs from synthetic user messages under a Bayesian relation network. Borrowing the simulator pattern (not necessarily the Chinese daily-life corpus) would let us generate curator-shaped test data without hand-authoring QA pairs.
- **Gap:** the curator's three-layer rules engine (system / org / user) has no benchmark. Its behaviour as a pluggable policy layer is something we would have to test in-house.

### A4. governance — RBAC, JWT, audit log stub, FIPS compliance

- **Benchmark fit:** **none in the academic literature.** This is not coincidental — governance is an architectural property and benchmarks avoid it.
- **Industry positioning** (not a benchmark, but usable for messaging): Atlan's six-risk framework (memory poisoning, stale context, access control, compliance failures, audit absence, multi-agent conflicts) is the closest thing to an enterprise "rubric". We already cover several of the six risks by construction (RBAC + tenant isolation; audit log is stub not shipped; multi-agent consistency out of scope).
- **Honest read:** we should expect this gap to stay open. If we want to push on governance as a differentiator we should publish our own checklist-style evaluation, not wait for an academic benchmark.

### A5. mcp-server — 15 tools

- **Benchmark fit:** no benchmark evaluates a memory layer by its tool surface. AMB's `agent` mode calls a provider's native `direct_answer()` but doesn't exercise the full tool catalog.
- **Indirect:** Letta Context-Bench's Skills Suite tests whether models can discover and load the right tools from a library — **loosely** analogous to how well an agent picks the right memory tool. But Context-Bench holds the framework constant (Letta), so it cannot tell us whether MemoryHub's tool shape specifically is good.
- **Gap:** there is no benchmark that would tell us "is `set_session_focus` ergonomically useful?" — only our own exercise sessions (the `/exercise-tools` flow).

### A6. memoryhub-auth — OAuth 2.1 authorization server

- **Benchmark fit:** none. Not in scope for any memory benchmark.

### A7. sdk, cli, ui — consumer surfaces

- **Benchmark fit:** none directly. Vendor leaderboards (Letta, AMB) implicitly reward ease of integration by attracting more provider plugins.

### A8. agent-memory-ergonomics — two-vector retrieval, session focus, search shape knobs

- **Benchmark fit:** **this is where the clearest match is.** The team already ran an internal benchmark (`benchmarks/two-vector-retrieval-20260407T184120Z.json`) for the focus-weight tuning. That internal harness measures MRR / precision@10 / recall@10 — the same family of metrics AMB uses on LoCoMo / LongMemEval / PersonaMem.
- **The natural next step is to run MemoryHub against AMB's harness** as a provider plugin. The AMB pipeline (Ingest → Retrieve → Generate → Judge) is a superset of our internal benchmark — it adds LLM-as-judge downstream accuracy scoring, a multi-dataset suite, and an independent generation/judge model (Gemini).
- **Specific datasets that would stress-test what we shipped in #58 (Layer 2):**
  - **LongMemEval** temporal-reasoning split would directly test whether our cross-encoder rerank helps on time-anchored queries
  - **PersonaMem 32K / 128K** would stress-test session focus on implicit preferences — our current two-vector math is designed for exactly this
  - **LoCoMo** multi-hop split would expose whether the single-call pgvector recall is enough or whether we need a graph-aware step
- **Cautionary note:** our internal benchmark showed that NEW-2 (focus-augmented query into the cross-encoder) is dead — cross-topic recall collapsed -37%. We should expect any academic benchmark that mixes topics within a session to punish naive focus-injection. The RRF-blend architecture we shipped should be more robust.

### A9. operator — Kubernetes operator (skeleton)

- **Benchmark fit:** none. Not in scope.

### A10. observability — TBD

- **Benchmark fit:** none. Not in scope.

### A11. org-ingestion — TBD

- **Benchmark fit:** **LifeBench** is the closest match. LifeBench explicitly targets non-declarative memory inferred from fragmented personal signals (chats, calendar, notes, SMS, health records). If org-ingestion lands, LifeBench becomes the place to evaluate it — with the caveat that LifeBench is niche and has a small cohort (10 users).
- **Also relevant:** AMA-Bench's "real-world agentic trajectories" component, which assumes memory is built from agent-environment interaction streams rather than handcrafted writes. This is the right frame if org-ingestion is going to pull from logs, Slack, wikis, etc.

### A12. kagenti-integration, llamastack-integration — design-stage

- **Benchmark fit:** none. These are integration specs, not capabilities.

---

## Direction B — "Benchmarks test Y, do we do it?"

For each capability the benchmarks (and governance literature) measure, where does MemoryHub land: shipped / roadmap / never contemplated?

Legend:

- **Shipped** — live on OpenShift with tests
- **Roadmap** — designed, not built (or open issue)
- **Never contemplated** — no design, no issue, no discussion

### B1. Top-k retrieval accuracy

- **MemoryHub status:** **Shipped.** `search_memory` with pgvector cosine, cross-encoder rerank, RRF blend with focus. Two-vector benchmark run 2026-04-07.
- **Gap:** none. This is the strongest column.

### B2. Multi-hop retrieval / reasoning chains

- **MemoryHub status:** **Partial.** We have `create_relationship` / `get_relationships` and a graph representation in Postgres. We do not currently use the graph *during retrieval* — search is pure vector. Multi-hop answers require the agent to call `search_memory` then `get_relationships` then assemble the answer itself.
- **Gap:** if multi-hop benchmark scores matter (Mem0 reports 7% improvement from graph memory on LoCoMo multi-hop), we would need to either (a) add graph expansion to retrieval, or (b) rely on the agent orchestrating the two-call pattern. Option (b) lines up with Letta's "agents beat specialized memory tools" finding.

### B3. Long-range retrieval under noise

- **MemoryHub status:** **Shipped but untested at scale.** Our two-vector retrieval is agnostic to store size. We have not tested it at 10M tokens equivalent or at 100K memories. The two-vector benchmark used a small synthetic corpus.
- **Gap:** we don't know how we'd score on BEAM's 1M / 10M splits. Memory count (rather than token count in a single context) is the dimension we control.

### B4. Agentic retrieval (agent decides when and how to query)

- **MemoryHub status:** **Shipped via MCP.** Our MCP surface is tool-driven; the agent decides when to call `search_memory` with what query. We do not currently test the *agentic-rag* pattern where the agent makes multiple retrieval calls with different queries before answering.
- **Gap:** we do not exercise this explicitly in test. `/exercise-tools` is close but not systematic. Letta's filesystem result (74% on LoCoMo with a grep-style agentic loop) suggests we should look at whether MemoryHub's tool ergonomics support multi-call retrieval loops as well as filesystem tools do.

### B5. Temporal reasoning over stored facts

- **MemoryHub status:** **Partial.** Every memory has `created_at` / `updated_at` / `expires_at` fields (I saw these in the `search_memory` results). `get_memory_history` returns version history. But `search_memory` does not currently bias retrieval by recency, and there is no "what was the state as of date X" API.
- **Gap:** no bi-temporal model. Zep's +38.4% on LongMemEval temporal reasoning came from explicit bi-temporal graph modeling. MemoryHub could add query-time temporal filtering without restructuring data, but we'd score weak on a LongMemEval temporal sub-split today.

### B6. Knowledge updates / supersession

- **MemoryHub status:** **Shipped.** `update_memory` creates a new version, sets `isCurrent=true` on the new version, marks the old version historical. `get_memory_history` returns the full chain. This is exactly what LongMemEval's "knowledge updates" ability tests.
- **Gap:** we should expect to score well on this sub-task, but we have never run it.

### B7. Staleness detection (upstream source changed)

- **MemoryHub status:** **Never contemplated.** The model assumes memories are written deliberately by agents or users; there is no upstream data source to detect changes from. org-ingestion, if built, would surface this as a design problem.
- **This is Atlan Risk #2 (Stale context).** If org-ingestion goes forward, we will need to design freshness / invalidation signals before launch or we inherit this risk by construction.

### B8. Temporal validity / TTL / explicit expiry

- **MemoryHub status:** **Partial.** The `expires_at` field exists on the memory model. I could not confirm from the search output whether a scheduled job actively removes or hides expired memories, or whether expiry is just advisory.
- **Action to verify before discussion:** grep `expires_at` usage in `src/memoryhub_core` to see if expiry is enforced.

### B9. Writing / ingestion quality (agent picks what to store)

- **MemoryHub status:** **Agent-delegated.** MemoryHub does not decide what to store; the agent calls `write_memory`. The curator-agent then decides whether to merge, dedupe, or keep. "What to store" is a joint property of the agent prompt + MemoryHub's integration rule (`.claude/rules/memoryhub-integration.md`).
- **Gap:** benchmarks that test autonomous write selection (MemoryAgentBench's "test-time learning") would measure this joint behaviour. We can't control the agent half.

### B10. Deduplication / consolidation

- **MemoryHub status:** **Shipped.** curator-agent does embedding-based dedup on write (`get_similar_memories`, `suggest_merge`).
- **Gap:** dedup quality is not benchmarked. MemoryAgentBench FactConsolidation is a fit but has not been run.

### B11. Versioning and history

- **MemoryHub status:** **Shipped.** `get_memory_history`, `isCurrent`, `previous_version_id`, `current_version_id` — all in the search response shape.
- **Gap:** **no benchmark rewards this.** Every PM benchmark scores only on the query-answer accuracy; none gives credit for "MemoryHub can tell you the previous version of this memory and when it changed". This is a structural mismatch — MemoryHub has done work here that the benchmarks will not reward.

### B12. Selective forgetting (agent decides what to drop)

- **MemoryHub status:** **Partial.** `delete_memory` exists as a tool. The curator-agent can delete during consolidation. There is no autonomous forgetting or decay.
- **Gap:** MemoryAgentBench tests this explicitly as a competency. Our score would depend on whether the benchmark considers curator-driven delete equivalent to agent-driven forgetting. The `set_curation_rule` tool is relevant here.

### B13. Curation / quality signals

- **MemoryHub status:** **Shipped (three-layer rules + weights + dedup).**
- **Gap:** no benchmark. Our internal evaluation is the only signal.

### B14. Scope / isolation (per-user, per-project, per-tenant)

- **MemoryHub status:** **Shipped (#46 Phase 4, 2026-04-08).** Tenant isolation landed in the service-layer SQL path. Scopes are: user, project, role, organizational, enterprise. Cross-tenant reads return `MemoryNotFoundError` (indistinguishable from nonexistent).
- **Gap:** **no academic benchmark tests this.** We have done the work. The only way to evaluate it is to write our own adversarial test suite that tries to cross boundaries.
- **This is Atlan Risk #3** and a real differentiator for MemoryHub vs any of the vendor systems reviewed.

### B15. Cross-agent consistency

- **MemoryHub status:** **Not in scope.** One tenant, one memory store. If two agents disagree about the same entity, both writes land and both surface in search. No active conflict detection across independent writes (beyond dedup on similarity).
- **Atlan Risk #6** — structural. This is a "never contemplated" item for MemoryHub unless the agent coordination layer (kagenti-integration? llamastack-integration?) decides to own it.

### B16. Contradiction handling

- **MemoryHub status:** **Shipped.** `report_contradiction` tool. The agent can flag a contradiction for later human review. There is also `check_similarity` on the curator path that can detect write-time overlaps.
- **Gap:** `report_contradiction` is a passive flag, not an active resolver. No benchmark tests contradiction-handling UX directly.

### B17. Provenance / citability

- **MemoryHub status:** **Shipped.** memory-tree has a `provenance` branch type explicitly. `parent_id` links. `get_memory_history` returns an audit chain.
- **Gap:** **no benchmark rewards this** beyond what we already said for versioning. This is another structural mismatch.

### B18. Latency

- **MemoryHub status:** **Measured internally, not exposed.** The two-vector benchmark measured end-to-end retrieval time but did not track ingestion latency or p95/p99.
- **Gap:** if we run against AMB, latency becomes a first-class reported metric. We should expect to need a benchmark harness run to produce the numbers for a public release.

### B19. Cost (tokens, dollars per user/day)

- **MemoryHub status:** **Not measured.** MemoryHub does not currently instrument per-query token cost.
- **Gap:** if we run AMB, we will need to at least track embedding tokens for ingest + query and the Gemini generator/judge cost for the benchmark run. For production, we have no dashboard for "dollars per user per day". This is **Atlan's and Hindsight's shared key argument** — and we can't answer it today.

### B20. Scale under load

- **MemoryHub status:** **Not tested.** We have tens to hundreds of memories in dev; we do not have load-test data at 100K or 1M memories.
- **Gap:** before making any scale claim, we need to run this. Observability subsystem (TBD) would be the right home.

### B21. Configuration / operator burden

- **MemoryHub status:** **Reasonable.** `memoryhub config init` generates `.memoryhub.yaml` and the Claude integration rule file. SDK and CLI are thin wrappers. UI is a single container with oauth-proxy sidecar.
- **Gap:** no benchmark. AMB lists usability as one of its four axes but doesn't score it yet.

### B22. Trust / poisoning resistance

- **MemoryHub status:** **Never contemplated as a test surface.** Authenticated writes via JWT, RBAC-gated by scope — so *unauthorized* writes are blocked. But *authorized-but-malicious* writes (an agent or compromised user writing poisoned memories) are accepted at face value, with only the curator's dedup/regex rules as defence.
- **PoisonedRAG benchmark applicability:** we could in principle run a PoisonedRAG-style adversarial write against MemoryHub and measure whether the poisoned memory surfaces in retrieval. **Nobody has done this.**
- **Regulatory tailwind:** FTC Act Section 5, EU AI Act Article 12.
- **This is the single biggest "never contemplated" gap I would flag for discussion.**

### B23. Deletion provability (GDPR Art. 17 compliance)

- **MemoryHub status:** **Partial.** `delete_memory` marks rows deleted (or removes them — needs verification). Embeddings are stored in the same row, so a row-delete removes the embedding. But **proving deletion** — i.e. producing an audit trail that an operator can show a regulator — is not explicit.
- **Gap:** no benchmark, but compliance-relevant. Audit log stub (#67) is the right place for this, and it hasn't shipped.

### B24. Poisoning / integrity via provenance

- **MemoryHub status:** The memory-tree has `provenance` branches as a concept but I did not verify what's stored there. Cryptographic integrity (the Atlan recommendation) is not present.
- **Gap:** never contemplated. If poisoning resistance becomes a discussion point, provenance branches are the most natural place to start.

### B25. Multi-tenancy with per-request identity

- **MemoryHub status:** **Shipped.** #46 Phase 4 plumbed `tenant_id` through all service-layer read paths. Cross-tenant reads raise not-found.
- **Gap:** **no benchmark rewards this** but it is a strong differentiator from the academic systems (all of which assume one user, one memory). Vendor systems vary — Oracle AI Agent Memory explicitly positions itself on governed multi-tenancy.

---

## "Never contemplated" gaps, ranked by how much they matter

1. **Poisoning resistance.** No design, no issue, no test. PoisonedRAG shows small adversarial writes have outsize impact. Regulatory tailwind. High leverage because MemoryHub already has a curator — it is the right structural home, but the curator is tuned for dedup, not adversarial detection.
2. **Staleness detection from upstream sources.** Architecturally missing. Will become blocking for org-ingestion. Atlan Risk #2.
3. **Cross-agent consistency in multi-agent systems.** Out of scope today but kagenti-integration and llamastack-integration are heading here. Will need a design before the integration partners hit this in production.
4. **Per-memory dollar/token cost instrumentation.** No data. AMB and Letta both treat this as a first-class column. We cannot participate in a "good memory at reasonable cost" conversation without numbers.
5. **Provable deletion for regulated data.** GDPR Art. 17 enforcement is active. No vector DB has solved this, but we should at least be able to tell a compliance team what our story is.
6. **Scale under load (100K, 1M, 10M memories).** Not tested. Our production workload hasn't reached it, but any enterprise pitch will.
7. **Scope-isolation adversarial testing.** The isolation code just shipped (#46 Phase 4); nobody has tried to break it. An internal red-team run would give a stronger signal than any public benchmark could.

---

## What I would recommend looking into (not recommending to do)

These are discussion points for the user, not commitments:

- **Run MemoryHub against AMB.** The harness is open source, the data is open, and the result is directly comparable to Hindsight, Cognee, hybrid-search, bm25. LongMemEval, PersonaMem, and LoCoMo would all exercise shipped #58 code. Estimated cost: one engineer-week to build a provider adapter plus the generation/judge Gemini bill.
- **Run MemoryHub against MemoryAgentBench** specifically for the curator. FactConsolidation and selective-forgetting are the parts of our product the flagship benchmarks don't reward.
- **Adopt MemSim's simulator methodology** for our own internal curation-rules testing. We do not need Chinese daily-life data; we need scope-aware synthetic streams.
- **Author a "MemoryHub Governance Scorecard"** modelled on the Atlan six-risk framework — not a benchmark, but a public rubric that scores shipped vendors against enterprise-actual requirements. MemoryHub scores well on isolation + contradiction + provenance; weak on poisoning and deletion provability. Making this a public artifact positions the roadmap against the right risks.
- **Do not build a new benchmark from scratch.** The landscape is crowded. Every gap described above is better addressed by (a) running against the good existing benchmarks, or (b) publishing rubric-style evaluations against governance frameworks. A MemoryHub-authored "AgentMemoryBench" would look like self-dealing the way AMB does — which the community already calls out.

None of the above is for this session. This file is for the discussion the user wants to have before anything is built.

---

## Postscript (2026-04-08, after discussion)

The discussion this file was written to support happened. The outcome: **none of the "what I would recommend looking into" items above are being acted on.** Specifically, the team decided not to run MemoryHub against AMB, MemoryAgentBench, or any other public benchmark — not because the recommendations were wrong on the research, but because the research itself surfaced the structural mismatch. Every benchmark in the landscape measures retrieval accuracy over a personal corpus (the "library" in our working analogy). MemoryHub's differentiators are all "librarian" properties — private, time-indexed, editorially governed, scope-bounded — that the benchmarks do not and likely will not reward. Chasing benchmark scores would bend the architecture toward being an also-ran on the wrong problem shape.

The evaluation path the team settled on instead:

1. **Agent-level evals with memory ablation**, using whatever agent evaluation harnesses already exist or ship with RHOAI / Kagenti. Run the same agent with MemoryHub on and off; grade the agent on multi-session retention, freshness handling, scope respect, and auditable behaviour. Memory becomes a lever, not a scoreboard.
2. **A governance scorecard we author**, modelled on Atlan's six-risk framework and DASF v3.0. A public rubric, not a leaderboard.
3. **Adversarial red-team runs** on what already shipped — particularly the tenant-isolation code from #46 Phase 4.

The "never contemplated" ranked list above (poisoning resistance, staleness, cross-agent consistency, cost instrumentation, provable deletion, scale under load, isolation adversarial testing) all stand as research findings. The team did not promote any of them into the active roadmap in this session. They are honest gaps to pick up later, not commitments.

The framing in the README (`semantic = library = RAG` vs `episodic + procedural = MemoryHub = librarian`) is the durable vocabulary that came out of the discussion. Read that section of the README before using this file for anything external.
