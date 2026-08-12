# MemoryHub Open Issues by Stakeholder Dimension

*Updated 2026-08-12 -- 62 open issues*

This document arranges the open issue backlog by who cares and why, across five stakeholder dimensions: the AI agent consuming MemoryHub, the developer integrating it, marketing/positioning, the customer's cybersecurity team, and the end user whose interactions are remembered.

---

## Agent (the AI that uses MemoryHub)

*"Does my memory actually help me do my job better?"*

These issues directly affect what the agent retrieves, how accurately it recalls, and whether its memory stays clean over time.

### Retrieval accuracy -- what comes back when the agent searches

| Issue | Title | Notes |
|-------|-------|-------|
| #306 | Time-decay recency bias in search scoring | v0.2 milestone |
| #389 | S3 hydration for large-content tail (rank on prefix, hydrate top-k) | |
| #397 | Hard-stop mode (truncate results vs degrade to stubs) | |
| #404 | Effective-k observability -- kill the silent capping funnel | **Bug** -- agent silently gets fewer results than requested |
| #453 | Reimplement disabled_signals for RRF signal toggling | future |
| #454 | Reimplement entity-aware search | future |
| #511 | embedding_max_tokens config mismatches deployed model limit | **Bug** -- config hardcoded to 8192 (GPU model) but CPU variant maxes at 256 tokens; memories exceeding ~1000 chars fail with HTTP 413 |

Bad retrieval means the agent hallucinates or ignores what it should know. #404 is the scariest: the agent silently gets fewer results than it asked for, and nobody knows. #511 blocks writes entirely for longer memories when the CPU embedding model is active.

### Memory hygiene -- keeping the memory store trustworthy over time

```
#350 Curator scaffold ──► #352 Deep-dedup sweep
#351 Labeled dedup pair set ──► #352
#350 ──────────────────────► #353 Staleness sweep + conflict detection
```

| Issue | Title | Dependency |
|-------|-------|------------|
| #350 | Curator scaffold (AgentPlugin, leader election, CronJob) | Blocks #352, #353 |
| #351 | Labeled dedup pair set + deep-dedup judge | Blocks #352 |
| #352 | Deep-dedup sweep -- wire judge into Curator | Depends on #350, #351 |
| #353 | Staleness sweep + cross-scope conflict detection | Depends on #350 |
| #345 | Provenance-driven reflection (Layer 3) | |
| #346 | Domain ontology refinement | |
| #239 | Convergent learning (consolidate duplicates across users) | v0.4, future |
| #512 | Chunk and fact node creation fails: logical_id NOT NULL violation | **Bug** -- three MemoryNode construction sites omit logical_id; zero chunk or fact nodes exist in the database. These features have never worked end-to-end |

Without curation, memory accumulates noise. The agent's recall degrades as the store grows. #352 and #353 are the highest-leverage: dedup and staleness are the two ways memory rots. #512 reveals that chunk/fact node creation is completely non-functional -- a foundational storage bug.

### Agent autonomy and resilience

| Issue | Title | Notes |
|-------|-------|-------|
| #491 | Memory rewind/rollback for wedged agents | needs-design |
| #104 | Persist session state across pod restarts | |
| #87 | Typed SDK push notifications (full-content) | future |
| #431 | Session-close memory capture (SessionEnd hook) | |
| #313 | Turn-level hooks: automatic rebias and extraction | v0.3 |

#491 matters when an agent writes bad memories and spirals -- today there's no undo. #104 matters because a pod restart wipes the agent's session context mid-conversation.

---

## Developer (the person integrating MemoryHub)

*"Can I actually build with this thing without fighting it?"*

### CLI and SDK ergonomics

```
#492 Per-project identity selection
 ├─► #493 delete-agent command
 └─► #497 Surface last_updated_by in responses
```

| Issue | Title | Notes |
|-------|-------|-------|
| #492 | Per-project identity selection | Complements #493, #497 |
| #493 | Add delete-agent command for client removal and recreation | |
| #497 | Surface last_updated_by in memory responses | |
| #458 | create-agent table output omits api_key | **Bug** -- papercut |
| #459 | Add rotate-api-key subcommand | |

#458 is a papercut: you create an agent and can't see the key you just generated. #492 is the bigger deal for anyone running MemoryHub across multiple projects -- today you manually juggle credentials.

### Multi-harness and onboarding

```
#310 Framework-agnostic onboarding (needs-design)
 └─ tracked by ► #312 Multi-harness tracking
```

| Issue | Title | Notes |
|-------|-------|-------|
| #310 | Framework-agnostic agent onboarding | v0.3, needs-design |
| #312 | Multi-harness support (tracking) | v0.3 |
| #313 | Turn-level hooks | v0.3 |
| #489 | OpenClaw integration | v0.3 |
| #509 | OpenCode integration | v0.3 |
| #494 | OpenClaw: Fix scope/project_id placement | **Bug** |
| #495 | OpenClaw: Connection leak in resetSession | **Bug** |
| #496 | OpenClaw: Remove as-never casts, cleanup | **Bug** |
| #82 | LibreChat integration | v0.5 |

Today MemoryHub works well with Claude Code. #310 is the gate for every other harness. The OpenClaw bugs (#494-496) are the lived proof that onboarding a second client surfaces rough edges. #509 adds OpenCode as a third harness target.

### Developer confidence

| Issue | Title | Notes |
|-------|-------|-------|
| #375 | Full local test suite hang | **Bug** -- corrosive; devs stop running tests |
| #383 | Capability-claim sweep of agent-facing documents | Catches docs that promise features that don't exist yet |
| #426 | EvalHub sidecar result-drain retry | |
| #505 | Create test deployment of Hindsight | Competitive analysis -- hands-on comparison |
| #506 | Create test deployment of GBrain | Competitive analysis -- hands-on comparison |
| #511 | embedding_max_tokens config mismatches deployed model limit | **Bug** -- blocks writes for longer memories on CPU |
| #512 | Chunk and fact node creation fails: logical_id NOT NULL | **Bug** -- chunk/fact features completely non-functional |
| #518 | UI deploy script hard-fails without RHOAI installed | **Bug** -- RHOAI is optional but deploy.sh treats it as required |

---

## Marketing (what makes MemoryHub worth choosing)

*"What can we say in a demo, a pitch, or a paper?"*

### Provable claims (benchmarks)

```
#330 LongMemEval_S full-haystack ──► #331 answer-quality with LLM judge
```

| Issue | Title | Notes |
|-------|-------|-------|
| #330 | Run LongMemEval_S full-haystack variant | Blocks #331 |
| #331 | LongMemEval answer-quality evaluation with LLM judge | Depends on #330 |
| #370 | Ablation Matrix B (focus/domain/graph) | |
| #273 | Graph-traversal vs flat vector search comparison | v0.2 -- answers "why not just pgvector?" |
| #272 | Measure entity extraction throughput | v0.2 |
| #400 | Evaluate AutoRAG for pipeline optimization | |
| #337 | Platform-level benchmark design | Depends on #334 |
| #334 | Adversarial write / poisoning resistance | Feeds #337 |
| #507 | Demo: quantitative benefits of agent memory sharing | needs-design -- a demo scenario showing clear quantitative gains from cross-user memory sharing |

Marketing can't claim "better recall" without #330/#331. #273 is the "why not just use pgvector?" question every prospect asks. #337 is the benchmark that positions MemoryHub as a platform, not just a vector store. #507 provides the tangible demo for the memory-sharing value proposition.

### Differentiation features

| Issue | Title | Notes |
|-------|-------|-------|
| #345 | Provenance-driven reflection (dreaming Layer 3) | "Nobody else does this" |
| #289 | Statistician Agent (population-level patterns) | v0.4 |
| #290 | Five-stage promotion pipeline | v0.4 |
| #270 | Semantic search over conversation threads | future -- demo crowd-pleaser |
| #516 | PTC-aligned provenance and taint metadata | compliance -- Trust Bricks PTC standard for provenance envelopes |
| #517 | GAL-aligned memory trust lifecycle (promotion/demotion) | compliance -- Trust Bricks GAL standard for authority lifecycle |

Dreaming (#345), population statistics (#289), and governed promotion (#290) are the curation story that separates MemoryHub from "just another RAG database." #516 and #517 add formal compliance standards (Trust Bricks PTC/GAL) that strengthen the governance narrative for regulated industries.

### Competitive landscape

| Issue | Title | Notes |
|-------|-------|-------|
| #505 | Create test deployment of Hindsight | Hands-on comparison with competing agent memory service |
| #506 | Create test deployment of GBrain | Hands-on comparison with competing agent memory service |

Understanding what competitors offer strengthens positioning and identifies gaps worth closing.

### Integration breadth

| Issue | Title | Notes |
|-------|-------|-------|
| #82 | LibreChat integration | v0.5 |
| #489 | OpenClaw integration | v0.3 |
| #509 | OpenCode integration | v0.3 |
| #310 | Framework-agnostic onboarding | v0.3 |

"Works with X" is a marketing checkbox. Each integration widens the addressable market.

### Design documents

| Issue | Title | Notes |
|-------|-------|-------|
| #508 | "Building the case for agent memory" design document | subsystem: memory-tree, target: planning/ folder |

---

## Customer's Cybersecurity Team (the people who approve or block adoption)

*"Can we let this into our environment?"*

### Audit and accountability

```
#70 Persist audit log ──► #71 Intersection authorization
```

| Issue | Title | Notes |
|-------|-------|-------|
| #70 | Persist audit log to durable store | v0.4 -- table stakes for regulated customers |
| #71 | Intersection authorization (actor + driver permissions) | future, references #70 |
| #497 | Surface last_updated_by in responses | Complements #492 |
| #492 | Per-project identity selection | Makes identity legible |
| #514 | Validate project membership before owner_id bypass in list/search | **Bug** -- PR #513 removed the owner_id safety net; callers can now see other members' memories in projects they don't belong to |

#70 is table stakes for any regulated customer. Today audit events exist in-memory but don't survive restarts. Without it, "who did what when" is unanswerable after a pod recycle. #514 is an authorization bug with immediate security implications -- project membership is not enforced on list/search.

### Data protection and privacy

| Issue | Title | Notes |
|-------|-------|-------|
| #72 | driver_id redaction on read for sensitive contexts | future |
| #68 | HIPAA/PHI detection in curation pipeline | v0.4 -- hard gate for healthcare |
| #40 | Versioning and edit tracking for curation rules | v0.4 |
| #516 | PTC-aligned provenance and taint metadata | Trust Bricks PTC standard for memory provenance envelopes |
| #517 | GAL-aligned memory trust lifecycle (promotion/demotion) | Trust Bricks GAL standard for authority lifecycle |

#68 is a hard gate for healthcare customers. #72 addresses "the agent remembers who asked, but the next reader shouldn't see that." #516 and #517 formalize provenance and trust lifecycle using Trust Bricks standards -- relevant for any customer with data classification requirements.

### Adversarial resistance

| Issue | Title | Notes |
|-------|-------|-------|
| #334 | Adversarial write / poisoning resistance | Feeds #337 |
| #337 | Platform-level benchmark design | Depends on #334 |

"What happens if someone writes malicious memories to manipulate agent behavior?" is the question every security review asks.

### Infrastructure safety

| Issue | Title | Notes |
|-------|-------|-------|
| #395 | MinIO content doesn't survive uninstall --skip-db | **Bug** -- data loss risk |
| #241 | Evaluate pluggable storage backend | future -- "we use Ceph, not MinIO" |

#395 is a data-loss bug: you reinstall the app layer thinking the data is preserved, but object storage content is gone.

---

## End User (non-developer whose interactions are remembered)

*"Does the agent actually remember me? Is my data safe?"*

The end user never touches MemoryHub directly, but they feel every retrieval and curation issue.

### Better agent behavior (indirect)

| Issue | Title | What the user experiences |
|-------|-------|--------------------------|
| #306 | Time-decay recency bias | Agent remembers recent context better |
| #352 | Deep-dedup sweep | Agent doesn't repeat itself |
| #353 | Staleness sweep | Agent forgets outdated facts |
| #345 | Provenance-driven reflection | Agent synthesizes, not just recalls |
| #389 | S3 hydration | Agent retrieves full content, not stubs |
| #404 | Effective-k fix | Agent gets all the results it asked for |

### Safety and control

| Issue | Title | What the user gains |
|-------|-------|---------------------|
| #491 | Memory rewind/rollback | "The agent learned something wrong about me, undo it" |
| #68 | HIPAA/PHI detection | Health data doesn't leak into agent memory |
| #72 | driver_id redaction | Who asked isn't visible to everyone |
| #334 | Adversarial resistance | Someone can't poison what the agent knows about me |

#491 is the user-facing version of "right to be forgotten." Today if an agent writes a bad memory, cleaning it up is manual DB surgery.

---

## Cross-cutting dependency map

Issues at the intersection of multiple stakeholders are the highest-leverage items:

| Issue | Agent | Dev | Mktg | Security | End User |
|-------|-------|-----|------|----------|----------|
| **#492** Identity selection | | primary | | enables #497, #71 | |
| **#70** Durable audit log | | | | primary | indirect |
| **#350 -> #352** Dedup pipeline | primary | | differentiator | | feels it |
| **#310** Framework onboarding | | primary | integration story | | |
| **#330 -> #331** LongMemEval | validates | | primary | | |
| **#491** Memory rollback | primary | | | | primary |
| **#68** HIPAA/PHI detection | | | healthcare gate | primary | protected |
| **#334** Adversarial resistance | | | proof point | primary | protected |
| **#404** Effective-k bug | primary | | | | feels it |
| **#514** AuthZ project membership | | primary | | primary | |
| **#511/#512** Storage bugs | primary | primary | | | |
| **#516/#517** Trust Bricks compliance | | | differentiator | primary | |

---

## Summary

| Stakeholder | Issue count | Biggest gap |
|-------------|-------------|-------------|
| Agent | ~22 | Retrieval quality + curation pipeline |
| Developer | ~18 | Multi-harness onboarding (#310) |
| Marketing | ~16 | No provable benchmark numbers yet (#330 -> #331) |
| Security | ~13 | No durable audit log (#70); authorization bug (#514) |
| End User | ~8 | No rollback/undo capability (#491) |

Counts overlap because many issues serve multiple stakeholders. The "biggest gap" column is the single most painful absence for each audience today.

### By milestone

| Milestone | Count | Issues |
|-----------|-------|--------|
| v0.2 - Retrieval Quality | 3 | #272, #273, #306 |
| v0.3 - Multi-Harness & Onboarding | 5 | #310, #312, #313, #489, #509 |
| v0.4 - Curation & Governance | 6 | #40, #68, #70, #239, #289, #290 |
| v0.5 - Platform Integrations | 1 | #82 |
| Unassigned | 47 | |

### By type

| Type | Count |
|------|-------|
| Bugs | 11 (#375, #395, #404, #458, #494, #495, #496, #511, #512, #514, #518) |
| Features | 24 |
| Design | 5 (#104, #270, #337, #383, #508) |
| Enhancement | 9 |
| Tracking | 1 (#312) |
| Investigation | 1 (#400) |
| Flagged future/deferred | 7 (#71, #72, #87, #241, #270, #453, #454) |
