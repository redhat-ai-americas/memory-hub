# Curation Pipeline

Curation in MemoryHub is not a separate service. It's a pipeline embedded in the MCP tools themselves, evaluated at write time. The pipeline runs rules in cost order (cheapest first) and escalates only when needed. For tasks requiring judgment, it uses MCP sampling to ask the calling agent's LLM -- or a configured fallback LLM. For genuinely ambiguous cases, elicitation can ask the human.

The single-agent consistency argument from the original design still applies for above-user-level writes (promotion). But the day-to-day curation work -- dedup, secrets scanning, quality gating -- is distributed across the agents themselves, within their RBAC scope. Every agent that uses MemoryHub contributes to curation as a side effect of normal operation.

## Three-Layer Curation Pipeline

The pipeline runs inside `write_memory` (and potentially other write tools) before the memory is persisted. Each tier is more expensive than the last, and earlier tiers gate whether later tiers run at all.

### Tier 0: Schema validation

Pydantic validation. Already exists. Free, always runs.

### Tier 1: Regex scanning

Deterministic pattern matching. Microseconds.

- **Secrets detection**: API keys (AKIA..., sk-..., ghp_..., etc.), passwords, tokens, private key headers (-----BEGIN)
- **PII detection**: SSNs, email patterns, phone numbers

Action on match: block or quarantine, depending on the rule.

This is the cheapest gate. It catches obvious problems before anything touches the database. The patterns are configurable via curation rules, and users can whitelist specific findings.

### Tier 2: Embedding similarity

pgvector cosine similarity query against existing memories in the same (owner_id, scope, is_current=true). Milliseconds.

| Similarity | Action |
|---|---|
| > 0.95 | Reject with pointer to existing memory (near-duplicate) |
| 0.80 - 0.95 | Escalate to Tier 3 (possible duplicate, needs judgment) |
| < 0.80 | Pass -- write normally (distinct memory) |

Thresholds are configurable via curation rules. Users with intentionally similar memories (e.g., dataset-specific notes) can raise the dedup threshold.

### Tier 3: Sampling

Uses `ctx.sample()` from FastMCP to ask the calling agent's LLM for a judgment call. Seconds.

The sampling request provides context: "Memory X (similarity 0.88) already exists. Is this new memory genuinely different, an update, or a duplicate?" It uses structured output (`result_type=CurationDecision`) to force the LLM into returning one of: `allow`, `reject`, `merge`, `flag`.

Constraints on the sampling call:
- Only read-only tools are exposed (e.g., `search_memory`, `read_memory`). Never write tools.
- `max_tokens=300` to keep responses short and costs low.
- Single round only. No multi-turn curation conversations.

If the client doesn't support sampling, the server falls back to a configured LLM (see [Sampling Handler Configuration](#sampling-handler-configuration)).

### Tier 4: Elicitation

Uses FastMCP elicitation to present the human with a choice: "Here are two similar memories. Keep both, merge, or update?" Blocks until answered.

Only triggered when Tier 3 returns "uncertain" or a rule mandates human approval. Deferred for later implementation -- the interface is designed here but not built until Phase 4.

## Circuit Breaker

If `write_memory` calls `ctx.sample()`, and the sampling LLM calls `write_memory` again, that loops infinitely. This must never happen. Four layers of protection:

1. **Tool restriction**: The sampling call only exposes read-only tools. The LLM physically cannot trigger a write, so recursive loops are impossible at the API level.

2. **Structured output**: `result_type=CurationDecision` forces the LLM to return a decision enum, not free-form text that might be misinterpreted as an action.

3. **`skip_curation` parameter**: Write tools accept an internal `skip_curation` flag. When curation sampling decides to merge or update, the downstream writes pass `skip_curation=True` to bypass the pipeline. Defense in depth -- this layer only matters if tool restriction somehow fails.

4. **Single round**: One sampling call per write operation, enforced in code. If one round doesn't resolve the question, escalate to Tier 4 (elicitation) or flag for background review. No retry loops.

## Curation Rules Engine

Rules define what gets checked and what happens. They're stored in a database table so they're versionable, evolvable, and manageable at multiple organizational levels.

### Rule Schema

```sql
CREATE TABLE curator_rules (
    id              UUID PRIMARY KEY,
    name            TEXT NOT NULL,       -- unique within (layer, owner_id)
    description     TEXT,
    trigger         TEXT NOT NULL,       -- on_write, on_read, periodic, on_contradiction_count
    tier            TEXT NOT NULL,       -- regex, embedding, llm, human
    config          JSONB NOT NULL,      -- tier-specific configuration
    -- config keys by tier:
    --   regex:     pattern (regex string)
    --   embedding: threshold (float), similarity_range ([low, high])
    --   llm:       prompt_template (string), similarity_range ([low, high])
    --   human:     message (string)
    action          TEXT NOT NULL,       -- block, quarantine, flag, reject_with_pointer,
                                         -- ask_agent, ask_human, merge, decay_weight
    scope_filter    TEXT,                -- which memory scopes this applies to (null = all)
    layer           TEXT NOT NULL,       -- system, organizational, user
    owner_id        TEXT,                -- null for system/org, set for user-level rules
    override        BOOLEAN DEFAULT FALSE, -- if true, lower layers cannot weaken this rule
    enabled         BOOLEAN DEFAULT TRUE,
    priority        INTEGER NOT NULL,    -- evaluation order within a tier (lower = higher priority)
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE (layer, owner_id, name)
);
```

### Three Rule Layers

Rules are scoped to three layers, evaluated bottom-up (most specific wins, with exceptions):

| Layer | Who manages | Overridable | Example |
|---|---|---|---|
| System | Platform admin / MemoryHub defaults | Some marked `override=true` | Secrets scanning, PII detection, hard dedup threshold (>0.95) |
| Organizational | Org admin | Yes, unless system rule has `override=true` | "Quarantine memories mentioning customer names" |
| User | The user (or their agent) | Yes, unless higher layer has `override=true` | "Raise my dedup threshold to 0.98 -- my dataset memories are intentionally similar" |

The `override` flag is the key mechanism. System-layer rules for secrets scanning are marked `override=true`, which means no user or org rule can weaken them. But the dedup threshold? Users can adjust that -- the system default is a recommendation, not a mandate.

### Rule Evaluation Logic

For a given (trigger, scope, owner_id):

1. Load user rules for this owner_id
2. Load org rules for this owner_id's organization
3. Load system rules
4. Merge: user rules override org rules override system rules, matched by name. Exception: if a higher-layer rule has `override=true`, it cannot be overridden by a lower layer.
5. Filter to matching trigger and scope_filter
6. Evaluate in tier order (regex, embedding, llm, human)
7. Within a tier, evaluate by priority (lower number = higher priority)
8. Stop at the first rule that produces a definitive action (block, reject, allow). Continue for rules that produce advisory actions (flag, decay_weight).

Note on tier advancement: the `ask_agent` action is how a Tier 2 rule escalates to Tier 3 sampling. When the rule engine encounters `ask_agent`, it invokes `ctx.sample()` with the rule's `prompt_template` and the candidate memory context. The sampling result maps back to a concrete action (allow, reject, merge, flag) via the `CurationDecision` structured output. Similarly, `ask_human` triggers Tier 4 elicitation. These actions are the bridges between tiers -- they don't short-circuit the pipeline, they advance it.

### Default Rule Set

System-layer rules that ship with MemoryHub:

| Name | Tier | Trigger | Action | Override | Notes |
|---|---|---|---|---|---|
| `secrets_scan` | regex | on_write | quarantine | yes | AWS keys, GitHub tokens, generic API keys, private key headers, bearer tokens |
| `pii_scan` | regex | on_write | flag | yes | SSNs, email addresses, phone numbers |
| `exact_duplicate` | embedding | on_write | reject_with_pointer | no | Cosine similarity > 0.95 within same (owner_id, scope) |
| `near_duplicate` | embedding | on_write | ask_agent | no | Similarity 0.80 - 0.95, escalates to Tier 3 sampling |
| `staleness_trigger` | regex | on_contradiction_count | flag | no | When contradiction count reaches threshold (default 5), flag for review |

Note that `secrets_scan` and `pii_scan` are marked `override=true`. Users cannot disable secrets scanning. They can add their own regex rules that whitelist specific patterns (e.g., "AKIA in an example block is fine"), but the base scan always runs.

## Agent Self-Curation

Every agent that uses MemoryHub contributes to curation from its RBAC-limited perspective. Agents are sensors for above-scope issues and self-curators within their own scope.

### Existing tools that contribute

- `report_contradiction` -- accumulates staleness signals when an agent observes behavior contradicting a stored memory. These contradiction counts feed into the `staleness_trigger` rule.

### New tools

**`suggest_merge(memory_a_id, memory_b_id, reasoning)`** -- Queues a merge suggestion for evaluation. The agent noticed two memories that should be one. Constrained to the agent's RBAC scope -- an agent can only suggest merges for memories it can read.

**`review_my_memories(scope=None, max_results=20)`** -- Triggers a sampling-powered self-audit. The tool fetches the agent's memories, uses `ctx.sample()` to have the LLM review them, and returns suggestions: merge candidates, stale memories, conflicts. The agent can then act on the suggestions by calling `suggest_merge`, `update_memory`, or `report_contradiction`.

**`set_curation_rule(name, config)`** -- Lets agents (within user scope) create or update user-layer curation rules. Example: the agent notices the user keeps getting false-positive duplicate warnings and adjusts the threshold. This tool can only create rules at the `user` layer for the authenticated owner_id.

## Sampling Handler Configuration

The MCP server configures a fallback sampling handler for clients that don't support sampling natively:

```python
from fastmcp import FastMCP
from fastmcp.client.sampling.handlers.openai import OpenAISamplingHandler

mcp = FastMCP(
    "MemoryHub",
    sampling_handler=OpenAISamplingHandler(
        api_key=os.getenv("LLAMA_4_SCOUT_API_KEY"),
        base_url=os.getenv("LLAMA_4_SCOUT_BASE_URL"),
        default_model=os.getenv("LLAMA_4_SCOUT_MODEL_ID"),
    ),
    sampling_handler_behavior="fallback",
)
```

With `"fallback"` behavior:
- If the client supports sampling (e.g., Claude Code) -- the client's LLM handles it. Already paid for, zero marginal cost.
- If a simpler client connects -- Llama 4 Scout handles it via the OpenAI-compatible API on vLLM/LiteLLM.

The cheapest LLM path is always taken. In practice, most MemoryHub users are Claude Code users, so Tier 3 sampling rarely costs anything extra.

## Background Curator (Future)

The inline pipeline handles write-time curation. A background curator agent handles periodic tasks that require cross-user visibility:

- **Promotion analysis** -- scan for patterns across users, propose org memories
- **Cross-scope conflict detection** -- org memory contradicted by many user agents
- **Deep dedup sweeps** -- the 0.70-0.80 similarity range across large memory sets
- **Staleness processing** -- act on accumulated contradiction signals

This is deferred to a later phase. It requires multi-user data (we have one user currently), a long-lived agent process with elevated RBAC, and cost management for periodic LLM calls at scale. The single-agent consistency argument applies here: one curator agent checking for duplicates and conflicts across organizational scope means no two processes can independently create conflicting organizational memories.

The graph relationships built in [memory-tree.md](memory-tree.md) (`derived_from`, `supersedes`, `conflicts_with`) are the substrate for promotion provenance tracking. When a user memory gets promoted to organizational scope, the provenance chain links back to the source memories, enabling reversal if the promotion turns out to be wrong.

## Design Questions (Resolved)

These were open in the original design. Here's where we landed:

**Threshold for promotion?** Deferred -- needs multi-user data. When implemented, configurable via curation rule with trigger `periodic`.

**Promotion reversals?** Mark promoted memory as not-current, restore original user memories from provenance chain (graph relationships). The `supersedes` and `derived_from` edges make this a graph traversal, not a guessing game.

**Should curator use an LLM?** Yes, via sampling. Cheapest path: calling agent's LLM. Fallback: cluster Llama 4 Scout. Only used when heuristics are ambiguous (Tier 3). The cost structure is: Tier 1 and 2 are essentially free; Tier 3 costs one LLM call per ambiguous write; Tier 4 costs human attention.

**Schema for human review queue?** Elicitation for real-time decisions. Database-backed queue (flagged memories in metadata) for async review. External ticketing integration deferred.

**Bottleneck prevention?** Inline curation runs per-write with efficient early exits. Regex catches most issues in microseconds. Embedding similarity is a single pgvector query. Sampling only fires for the 0.80-0.95 similarity band, which is a small fraction of writes. Background sweeps use incremental scanning (only memories since last run).

**Leader election?** Deferred to operator phase. Not needed for inline curation. Only matters when the background curator is introduced.

## Design Questions (Open)

- How should `set_curation_rule` validate that user rules don't create security gaps? Users need guardrails on what they can adjust. Thresholds are safe to change; disabling secrets scanning is not. The `override` flag on system rules prevents weakening, but we need clear error messages when a user tries to override a protected rule.

- What's the right UX when Tier 3 sampling returns "merge"? Does the tool auto-merge (update existing memory + create `supersedes` relationship), or present the merge plan and ask for confirmation? Auto-merge is faster; confirmation is safer. Likely answer: auto-merge within user scope, confirmation for org scope.

- Should `review_my_memories` be proactive (runs automatically after N writes) or only on-demand? On-demand is simpler to start. Proactive could be a curation rule with trigger `periodic` and a write-count threshold.

- How do we handle the case where the sampling handler is unreachable? Fail open (allow the write, flag for later review) or fail closed (reject the write)? Fail open is better for user experience; fail closed is better for data quality. Likely answer: fail open with a flag, since Tier 2 already caught the high-confidence duplicates.

## Implementation Phases

### Phase 2a: Inline Pipeline + Rules Engine

- Curation rules table and evaluation engine
- Tier 1 regex scanning in `write_memory`
- Tier 2 embedding similarity checking in `write_memory`
- Default system rules: `secrets_scan`, `pii_scan`, `exact_duplicate`, `near_duplicate`, `staleness_trigger`
- Agent contribution tools (`suggest_merge`, `set_curation_rule`)
- Tests for rule evaluation, regex patterns, embedding thresholds

### Phase 2b: Sampling Integration

- Wire up Llama 4 Scout as fallback sampling handler
- Tier 3 sampling for ambiguous dedup cases
- Circuit breaker implementation (tool restriction, structured output, skip_curation, single round)
- `CurationDecision` structured output type
- `review_my_memories` tool
- Tests including sampling mock tests (mocking the sampling call, not the business logic)

### Phase 3: Background Curator

- Long-lived curator agent process
- Promotion analysis across users
- Cross-user dedup and conflict detection
- Staleness processing for accumulated contradiction signals

### Phase 4: Human-in-the-Loop

- Elicitation integration for Tier 4
- Review queue UI/API
- Notification system for flagged memories
