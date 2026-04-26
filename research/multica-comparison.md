# Multica: Competitive and Architectural Comparison with MemoryHub

**Date**: 2026-04-21
**Status**: Research analysis
**Context**: Multica (github.com/multica-ai/multica) is an open-source managed agents platform with emergent memory through task orchestration. This analysis informs an upcoming blog post and arXiv survey paper.

---

## 1. Executive Summary

Multica is a task orchestration platform that treats AI coding agents as team members on a shared kanban board. It is not a memory system. Its "memory" is emergent from six relational surfaces: workspace context, issues, task queue snapshots, skills, comments, and activity logs. Memory is assembled by the server at dispatch time and pushed to agents as a frozen JSONB snapshot — agents never query memory at runtime. This push-based, snapshot-at-dispatch model is the architectural opposite of MemoryHub's pull-based, query-at-need model. Multica validates the need for cross-agent context sharing (they have an open issue explicitly requesting it), but its current architecture cannot provide it. It is a potential consumer of MemoryHub's capabilities, not a competitor.

## 2. Architecture

Multica has three tiers:

**Server** — Go backend (Chi router, sqlc, gorilla/websocket) with PostgreSQL 17 + pgvector. Handles auth (JWT/HS256), task lifecycle, real-time WebSocket event broadcasting, and multi-tenant workspace isolation. 28+ database tables, 60+ WebSocket event types, 54+ SQL migrations.

**Client** — Next.js 16 web app and Electron desktop app in a pnpm + Turborepo monorepo. Shared packages for business logic (`packages/core`), UI (`packages/ui`, shadcn-based), and views. TanStack Query for server state, Zustand for client state.

**Daemon** — Local Go binary that auto-detects installed AI CLIs on `$PATH`, registers them as "runtimes" with the server, polls for task assignments every 3 seconds, and executes tasks in isolated per-task working directories. Heartbeats every 15 seconds. Up to 20 concurrent tasks. Supports 10 agent providers: Claude Code, OpenAI Codex, Cursor Agent, Gemini CLI, OpenClaw, OpenCode, Hermes, Pi, Kimi, Copilot.

## 3. Memory Model

Multica has no dedicated memory subsystem. Its memory is emergent from six relational tables and a dispatch-time snapshot pattern.

### The six memory surfaces

1. **`workspace.context`** — A single `TEXT` column. Manually-edited static prompt context inherited by all agents in the workspace. Injected at task dispatch time.

2. **`issue`** — The primary unit of task context. Title, description, acceptance criteria (JSONB), status, priority, assignee. Issues are the "what" that agents work on.

3. **`agent_task_queue.context`** — A `JSONB` column storing a point-in-time snapshot of everything the daemon needs. The critical design choice: the server assembles a complete context snapshot at dispatch time. The database stays cold during inference.

4. **`skill` + `skill_file` + `agent_skill`** — Structured, reusable knowledge documents. Skills have a name, description, content, and files. Workspace-scoped, attached to agents via many-to-many junction. Written to disk in provider-specific directories (`.claude/skills/`, `.github/skills/`) before the agent starts.

5. **`comment`** — Threaded issue comments serve as "working memory." Agents post progress updates, questions, and results as comments. This is how agent output gets persisted and visible.

6. **`activity_log`** — Append-only audit trail of workspace state transitions.

### Memory types by taxonomy

| Type | Coverage | Mechanism |
|---|---|---|
| Episodic | Partial | Comment threads, task messages. No cross-issue recall. |
| Semantic | Partial | Skills system (curated knowledge documents). |
| Procedural | Partial | Skills encoding step-by-step procedures, session resumption. |
| Working | Yes | Task context snapshot + in-progress comments. |

### What is absent

- No vector search for memory retrieval. pgvector is a dependency but unused for memory operations — skills are retrieved via explicit SQL joins.
- No cross-issue memory. Each task starts fresh.
- No memory graph, versioning, decay, prioritization, or agent-writable persistent memory store.
- Open issue [#838](https://github.com/multica-ai/multica/issues/838) explicitly states: "Currently agents have no persistent memory across issues. Each task starts fresh — agents repeatedly re-explore the same project structure, and technical decisions made in one issue are invisible to agents on subsequent issues."

### Session resumption

The one exception to "no persistent memory": Multica tracks `session_id` and `work_dir` on the task queue table. When the same agent gets a new task on the same issue, the daemon resumes the prior Claude Code session via `--resume <session_id>`. This is provider-specific (Claude Code only) rather than a general memory mechanism.

## 4. Agent Coordination

Agents coordinate through the issue board as a shared work surface, not through direct communication.

**Task lifecycle**: Issues assigned on a kanban board. Server enqueues tasks, daemon claims and executes, reports results. Lifecycle: enqueue → claim → start → complete/fail.

**Communication**: Agents post results as issue comments via `multica issue comment add`. Terminal output is explicitly not delivered to users. Agents can also create issues, mention others, and react to comments.

**Autopilot**: Scheduled or webhook-triggered workflows that auto-create issues and assign them to agents. Supports cron schedules. Two modes: `create_issue` (creates issue + task) or `run_only` (task only).

**What is absent**: No direct agent-to-agent communication. No shared memory blackboard. No negotiation protocol. No capability advertising between agents. Coordination is entirely mediated by human workflow patterns (issues, comments, assignments).

## 5. Where They Validate Our Approach

**The need is real.** Issue #838 is a direct validation of MemoryHub's thesis. The Multica team has built a production agent orchestration platform and discovered, through operational experience, that the absence of cross-issue persistent memory is a significant gap. Their issue description reads like a requirements document for MemoryHub.

**Multi-agent coordination requires shared state.** Multica's architecture demonstrates that kanban-mediated coordination (assign, execute, comment) is necessary but insufficient. Agents that cannot access what other agents have learned re-derive knowledge, make inconsistent decisions, and duplicate exploration. The Multica team is discovering this at scale.

**Skills as curated memory.** The skill system — human-curated, structured knowledge documents shared across agents at workspace scope — validates MemoryHub's scope hierarchy. Multica's skills are analogous to MemoryHub's organizational-scope memories: team-level knowledge that any agent in the workspace should have access to. The difference is that Multica's skills are static and human-written; MemoryHub's memories are dynamic and agent-writable.

**Provider-agnostic agent abstraction.** Multica's `Backend` interface abstracts 10 CLI agents behind a single `Execute()` method. This validates the design principle that memory should be decoupled from any specific agent provider — exactly the argument for MCP as the memory access protocol rather than provider-specific APIs.

## 6. Where We Diverge

**Push vs. pull.** The fundamental architectural split. Multica assembles context at dispatch time and freezes it into a JSONB snapshot. MemoryHub provides on-demand search at query time. Push is simpler and avoids runtime DB queries, but the snapshot goes stale during long tasks and agents cannot discover relevant context they were not explicitly given. Pull is more complex but allows agents to seek what they need when they need it. This is the same dispatch-time-snapshot vs. runtime-query tension that appears in the Cloudflare comparison, though Multica and Cloudflare implement it very differently.

**Orchestration platform vs. memory service.** Multica is a complete task management product: kanban boards, agent lifecycle, multi-provider support, desktop/web UI, real-time progress tracking. MemoryHub is infrastructure: a governed memory service that any orchestration platform can consume. These are different layers of the stack, not competing products.

**Human-mediated vs. agent-autonomous.** In Multica, memory is human-curated: humans write workspace context, humans define skills, humans assign issues. Agents produce comments but do not write persistent memories. In MemoryHub, agents autonomously write, update, search, and curate memories within governed boundaries. The agent is a first-class memory participant, not just a consumer of human-prepared context.

**No governance.** Multica has workspace-level multi-tenancy but no RBAC on memory access, no scope hierarchy, no curation pipeline, no contradiction detection, no audit trail on memory operations, and no retention policies. Memory governance is not yet part of their problem space.

## 7. What They Do Well That We Don't

**Agent-as-teammate UX.** Agents appear alongside humans on the kanban board, in assignee dropdowns, in comment threads. They have profiles, post status updates, and report blockers. This treatment — agents as peers, not tools — is a deliberate UX choice that shapes how teams interact with AI. MemoryHub has no user-facing coordination UI; it is backend infrastructure.

**Multi-provider orchestration.** Ten agent providers behind a single interface, with provider-specific skill injection, session management, and working directory isolation. MemoryHub is provider-agnostic at the protocol level (MCP), but we have not built the orchestration layer that dispatches tasks to heterogeneous agents.

**Session resumption via native mechanisms.** Rather than building a general conversation persistence layer, Multica stores the Claude Code session ID and passes `--resume` on subsequent tasks. This is lean and effective, leveraging the underlying agent's own session management rather than reimplementing it. MemoryHub's conversation persistence subsystem (#168) takes the more ambitious route of protocol-level thread management — which is more general but also more complex.

**Autopilot / scheduled workflows.** Cron-triggered or webhook-triggered task creation and assignment. MemoryHub has no scheduling capability; we are a memory service, not a workflow engine.

**Skills as importable, shareable knowledge.** Skills can be imported from external registries (ClawHub, Skills.sh), creating a marketplace-like ecosystem for agent capabilities. MemoryHub has no equivalent to "install a pre-built memory pack from a registry."

## 8. What We Do That They Can't

**Cross-agent memory sharing.** MemoryHub's data model is designed for it: scope-based visibility, RBAC-filtered search, project enrollment, cross-agent read with `omitted_count` transparency. Multica's per-issue isolation means Agent C cannot search what Agents A and B have learned. This is the gap their issue #838 identifies.

**Semantic search.** MemoryHub uses pgvector embeddings (all-MiniLM-L6-v2, 384-dim), optional cross-encoder reranking (ms-marco-MiniLM-L12-v2), and RRF blending. Multica retrieves skills via SQL joins — no semantic similarity matching. The difference is significant when the memory corpus grows beyond what explicit joins can navigate.

**Agent-writable persistent memory.** MemoryHub agents autonomously write, update, version, and curate memories. Multica agents produce comments (working memory) but cannot create persistent, searchable knowledge that survives issue closure.

**Governance.** Six scope tiers, three-layer curation rules, inline secrets/PII detection, embedding-based dedup, contradiction detection and resolution. Multica has workspace-level tenancy and nothing else.

**Version history and memory graph.** `update_memory` preserves the full version chain. Four relationship types create a graph over the memory tree. Multica's comment-based working memory is append-only with no versioning or relationship tracking.

**Budget-aware retrieval.** Three response modes, `max_response_tokens` soft cap with degradation to stubs, weight-based content control, `pivot_suggested` signal. Multica's dispatch snapshot has no budget negotiation — whatever fits in the JSONB blob is what the agent gets.

**Cache-optimized memory assembly.** Epoch-based stable ordering (#175) maximizes KV cache hit rates when memories are injected into prompts. Multica's snapshot assembly has no caching consideration.

## 9. Implications for Our Publications

### Blog Post ("When Agent Memory Becomes a Platform Concern")

Multica is a strong illustration of the **gap between the harness tier and the platform tier**. They have built a sophisticated orchestration platform that coordinates multiple agents across providers — and hit exactly the wall the blog describes. Issue #838 is the blog's thesis stated as a feature request: when agents operate as a team, per-task memory isolation breaks down and you need a shared, governed memory service.

Multica is not a platform-memory play in the way Cloudflare is (no lock-in concern, open source, no proprietary memory format). It is instead an example of the **demand side**: a real orchestration platform discovering that cross-agent memory is the missing infrastructure layer. This makes it a natural complement to the Cloudflare example. Cloudflare demonstrates how platform vendors try to own memory; Multica demonstrates why orchestration platforms need memory they don't yet have.

**Recommendation**: Mention Multica in the "gap" section as a concrete example of a multi-agent orchestration platform that has reached the memory wall. Something like: "Multica, an open-source platform managing coding agents across ten providers, explicitly tracks this as an open issue: 'Agents have no persistent memory across issues. Each task starts fresh.' The orchestration layer is mature. The memory layer does not yet exist." Keep it to 1-2 sentences; the blog argues about the pattern, not any single project.

### arXiv Paper (Agent Memory Survey)

**Taxonomy (Section 3).** Multica's skill system is a data point for the "curated semantic memory" category. Skills are structured, human-authored knowledge documents with metadata, files, and workspace-scoped sharing. They sit between "system prompts" (too unstructured) and "knowledge bases" (too static) in the taxonomy. The import/marketplace model (ClawHub, Skills.sh) adds a distribution dimension that the current taxonomy does not address.

**Architectural placement (Section 7 draft).** Multica represents the "orchestration-mediated memory" position — memory assembled and injected by the orchestration layer rather than owned by the agent harness or an external service. This is a third position between harness-native (Cloudflare) and external service (MemoryHub) that the draft should acknowledge. The dispatch-time snapshot pattern is pragmatic and well-suited to short-lived coding tasks, but it breaks down when tasks are long-running or when agents need to query memory mid-execution.

**Multi-agent coordination (if addressed).** Multica's coordination model — kanban board, issue assignment, comment-based reporting — is the simplest viable multi-agent coordination pattern. It demonstrates that even this simple model surfaces the need for shared memory. Worth citing as evidence that the cross-agent memory problem is not hypothetical.

**Session resumption.** The provider-specific `--resume` pattern is a pragmatic alternative to protocol-level conversation persistence. Worth a footnote in any discussion of conversation continuity as an example of leveraging native provider mechanisms rather than building a persistence layer.

**Recommendation**: Cite Multica in Section 7 as the orchestration-mediated position (dispatch snapshot) alongside harness-native (Cloudflare) and external service (MemoryHub). Reference issue #838 as evidence of the cross-agent memory gap in multi-agent orchestration platforms. Mention skills as a curated-knowledge pattern in Section 3. One paragraph total.

## 10. Integration Opportunity

Multica is not a competitor — it is a potential integration target. The fit is natural:

- **Multica** handles task orchestration, agent lifecycle, multi-provider dispatch, and human-agent collaboration.
- **MemoryHub** handles persistent, governed, cross-agent memory with semantic search, versioning, and scope isolation.

The integration path would be: MemoryHub as an MCP server that Multica's agents query via their existing tool-use mechanisms. When a Multica agent starts a task, it searches MemoryHub for relevant cross-issue context. When it completes work, it writes key learnings to MemoryHub. The skill system could reference MemoryHub memories as dynamic, auto-updating knowledge that evolves with the project rather than requiring human curation.

This is the same "memory follows the protocol, not the platform" argument from the Cloudflare comparison, but with a more natural integration story: Multica is open source, runs self-hosted, and already supports MCP-capable agents (Claude Code). Issue #838 proposes building a simple key-value memory store; MemoryHub could serve as the sophisticated memory backend that addresses the requirements they have identified.

## 11. Maturity Assessment

| Metric | Value |
|---|---|
| Stars | ~18,600 (growing rapidly) |
| Contributors | 30+ |
| Commits | ~2,526 |
| Releases | 30 (v0.1.29 through v0.2.13) |
| Age | ~3 months (created Jan 13, 2026) |
| Release cadence | 2-3 per day |
| Migrations | 54 SQL migrations |
| License | Modified Apache 2.0 (commercial SaaS restriction) |
| Documentation | README (EN/CN), Fumadocs site, CLAUDE.md, AGENTS.md |

This is a fast-growing, early-stage project with strong momentum. The rapid release cadence, high star count, and active contributor base suggest significant community interest. The codebase is production-quality Go + TypeScript. The memory capabilities are nascent — the team is explicitly aware of the gap.

## 12. Strategic Assessment

Multica validates MemoryHub's thesis from the demand side. They have built a mature multi-agent orchestration platform and discovered, through operational experience, that cross-issue persistent memory is the missing layer. Their issue #838 is essentially a requirements document for what MemoryHub provides. The strategic relationship is complementary, not competitive: Multica handles orchestration, MemoryHub handles memory. If Multica builds their own simple key-value memory store (as #838 proposes), it will cover the minimum viable case but will lack semantic search, governance, versioning, contradiction detection, and the other capabilities that distinguish a memory service from a context cache. The opportunity is for MemoryHub to be the memory backend that Multica's agents connect to — governed, persistent, and shared across issues, agents, and providers.
