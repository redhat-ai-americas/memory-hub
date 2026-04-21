# Curation Pipeline

Curation in MemoryHub is not a separate service. It's a pipeline embedded in the MCP tools themselves, evaluated at write time. The pipeline is entirely deterministic -- regex and embedding checks, no LLM calls. The key insight: instead of sampling an LLM to judge ambiguous cases, `write_memory` returns a similarity count as part of its response. The calling agent -- which already has an LLM -- decides what to do. This avoids the MCP sampling HITL approval problem entirely and keeps write latency low.

The single-agent consistency argument from the original design still applies for above-user-level writes (promotion). But the day-to-day curation work -- dedup, secrets scanning, quality gating -- is distributed across the agents themselves, within their RBAC scope. Every agent that uses MemoryHub contributes to curation as a side effect of normal operation.

## Write-Time Curation Pipeline

The pipeline runs inside `write_memory` before the memory is persisted. Every tier is deterministic and fast.

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
| 0.80 - 0.95 | Flag in metadata, allow write |
| < 0.80 | Allow write (distinct memory) |

Thresholds are configurable via curation rules. Users with intentionally similar memories (e.g., dataset-specific notes) can raise the dedup threshold.

Note the key difference from earlier designs: the 0.80-0.95 range does NOT escalate to an LLM. The memory is written with a curation flag, and the similar_count is returned to the agent.

### No inline sampling

Earlier designs included Tier 3 (LLM sampling via `ctx.sample()`) and Tier 4 (human elicitation) in the write pipeline. These were removed because:

1. **MCP spec requires HITL for sampling.** The spec says clients SHOULD always have a human in the loop with the ability to deny sampling requests. For invisible plumbing like write-time dedup checks, popping an approval dialog on every ambiguous write is terrible UX.

2. **The calling agent already has an LLM.** By returning similarity information in the `write_memory` response, we let the agent's existing reasoning handle the judgment call as part of its normal flow. No extra infrastructure, no HITL friction, no recursive loop risk.

3. **Deterministic pipelines are predictable.** Regex and embedding checks produce the same result every time. LLM judgment varies by model, temperature, and context. For a write path, predictability matters.

Sampling remains available for explicit agent-initiated tools like `review_my_memories`, where the HITL approval is expected because the user asked for it. See [Sampling for Explicit Review](#sampling-for-explicit-review).

## Similarity Feedback on Write

The core curation mechanism: `write_memory` returns similarity information alongside the created memory, so the calling agent can make informed decisions.

### Response shape

When a memory is written successfully, the response includes:

```json
{
    "memory": { ... },          // the created MemoryNodeRead
    "curation": {
        "similar_count": 3,     // number of existing memories above the flag threshold
        "nearest_id": "uuid",   // ID of the most similar memory (if any)
        "nearest_score": 0.87,  // cosine similarity of the nearest match
        "flags": ["possible_duplicate"],  // any curation flags applied
        "blocked": false        // whether the write was blocked (secrets, exact dup)
    }
}
```

When a write is blocked (secrets scan, exact duplicate), the response includes:

```json
{
    "memory": null,
    "curation": {
        "blocked": true,
        "reason": "secrets_scan",
        "detail": "Content matches API key pattern (AKIA...)",
        "similar_count": 0
    }
}
```

### How agents use this

The tool description for `write_memory` includes guidance like:

> If `curation.similar_count` is greater than 0, consider reviewing existing similar memories before creating more. Use `search_memory` to find them, or call `manage_graph(action="get_similar", memory_id=...)` to see what's similar. If the existing memory says the same thing, consider calling `update_memory` on it instead of creating a duplicate.

This nudges the agent toward good memory hygiene without blocking writes. The agent's LLM makes the judgment call -- "is this actually a duplicate or a legitimately different memory?" -- using its full conversation context, which is richer than anything we could provide in a sampling prompt.

### `manage_graph(action="get_similar", ...)` tool

A read-only action that returns paged similar memories for a given memory ID:

```
manage_graph(action="get_similar", memory_id=..., threshold=0.80, max_results=10, offset=0)
```

Returns a list of similar memories with their similarity scores. This is how the agent drills into `similar_count > 0` without getting context-bombed -- it controls the page size. The tool uses the stored embedding from the source memory, so no re-embedding is needed.

## Curation Rules Engine

Rules define what gets checked and what happens. They're stored in a database table so they're versionable, evolvable, and manageable at multiple organizational levels.

### Rule Schema

```sql
CREATE TABLE curator_rules (
    id              UUID PRIMARY KEY,
    name            TEXT NOT NULL,       -- unique within (layer, owner_id)
    description     TEXT,
    trigger         TEXT NOT NULL,       -- on_write, on_read, periodic, on_contradiction_count
    tier            TEXT NOT NULL,       -- regex, embedding
    config          JSONB NOT NULL,      -- tier-specific configuration
    -- config keys by tier:
    --   regex:     pattern (regex string)
    --   embedding: threshold (float), similarity_range ([low, high])
    action          TEXT NOT NULL,       -- block, quarantine, flag, reject_with_pointer,
                                         -- merge, decay_weight
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

Note: the `tier` enum no longer includes `llm` or `human`. Inline curation is deterministic only. LLM-powered curation happens through explicit agent tools, not through the rules engine.

### Three Rule Layers

Rules are scoped to three layers, evaluated bottom-up (most specific wins, with exceptions):

| Layer | Who manages | Overridable | Example |
|---|---|---|---|
| System | Platform admin / MemoryHub defaults | Some marked `override=true` | Secrets scanning, PII detection, hard dedup threshold (>0.95) |
| Organizational | Org admin | Yes, unless system rule has `override=true` | "Quarantine memories mentioning customer names" |
| User | The user (or their agent) | Yes, unless higher layer has `override=true` | "Raise my dedup threshold to 0.98 -- my dataset memories are intentionally similar" |

The `override` flag is the key mechanism. System-layer rules for secrets scanning are marked `override=true`, which means no user or org rule can weaken them. But the dedup threshold? Users can adjust that -- the system default is a recommendation, not a mandate.

User-layer rules evolve with the user's working style. An agent that notices frequent false-positive duplicate warnings can call `manage_curation(action="set_rule", ...)` to adjust the user's threshold. Over time, each user's curation rules become tuned to their memory patterns.

### Rule Evaluation Logic

For a given (trigger, scope, owner_id):

1. Load user rules for this owner_id
2. Load org rules for this owner_id's organization
3. Load system rules
4. Merge: user rules override org rules override system rules, matched by name. Exception: if a higher-layer rule has `override=true`, it cannot be overridden by a lower layer.
5. Filter to matching trigger and scope_filter
6. Evaluate in tier order (regex, embedding)
7. Within a tier, evaluate by priority (lower number = higher priority)
8. Stop at the first rule that produces a definitive action (block, reject). Continue for rules that produce advisory actions (flag, decay_weight).

### Default Rule Set

System-layer rules that ship with MemoryHub:

| Name | Tier | Trigger | Action | Override | Notes |
|---|---|---|---|---|---|
| `secrets_scan` | regex | on_write | quarantine | yes | AWS keys, GitHub tokens, generic API keys, private key headers, bearer tokens |
| `pii_scan` | regex | on_write | flag | yes | SSNs, email addresses, phone numbers |
| `exact_duplicate` | embedding | on_write | reject_with_pointer | no | Cosine similarity > 0.95 within same (owner_id, scope) |
| `near_duplicate` | embedding | on_write | flag | no | Similarity 0.80 - 0.95, flags in metadata and returns similar_count |
| `staleness_trigger` | regex | on_contradiction_count | flag | no | When contradiction count reaches threshold (default 5), flag for review |

Note that `secrets_scan` and `pii_scan` are marked `override=true`. Users cannot disable secrets scanning. They can add their own regex rules that whitelist specific patterns (e.g., "AKIA in an example block is fine"), but the base scan always runs.

## Agent Self-Curation

Every agent that uses MemoryHub contributes to curation from its RBAC-limited perspective. Agents are sensors for above-scope issues and self-curators within their own scope.

### How agents curate naturally

The similarity feedback on `write_memory` is the primary curation signal. When an agent writes a memory and gets `similar_count: 3` back, its LLM can reason about what to do:

- Read the similar memories via `manage_graph(action="get_similar", ...)`
- Decide: "these are genuinely different" (do nothing) or "I should update the existing one instead" (call `update_memory`)
- Or: "these should be merged" (call `manage_graph(action="create_relationship", ...)` with `conflicts_with` type and merge metadata)

This works because the calling agent has full conversation context -- it knows *why* it's writing this memory and can judge similarity better than any isolated curation check could.

### Existing tools that contribute

- `manage_curation(action="report_contradiction", ...)` -- accumulates staleness signals when an agent observes behavior contradicting a stored memory. These contradiction counts feed into the `staleness_trigger` rule.

### New tools

**`manage_graph(action="get_similar", memory_id=..., threshold=0.80, max_results=10, offset=0)`** -- Returns paged similar memories for a given memory ID with similarity scores. Read-only. This is how agents drill into similarity counts without context bloat.

**Merge suggestion** -- Create a `conflicts_with` relationship via `manage_graph(action="create_relationship", ...)` with merge metadata. The agent noticed two memories that should be one. Constrained to the agent's RBAC scope -- an agent can only suggest merges for memories it can read. Flags both memories for review.

**`manage_curation(action="set_rule", name=..., config=...)`** -- Lets agents (within user scope) create or update user-layer curation rules. Example: the agent notices the user keeps getting false-positive duplicate warnings and adjusts the threshold. This tool can only create rules at the `user` layer for the authenticated owner_id. Cannot override system rules marked with `override=true`.

### Sampling for Explicit Review

**`review_my_memories(scope=None, max_results=20)`** -- Triggers a sampling-powered self-audit. The tool fetches the agent's memories, uses `ctx.sample()` to have the LLM review them, and returns suggestions: merge candidates, stale memories, conflicts. The agent can then act on the suggestions by calling `manage_graph(action="create_relationship", ...)` for merges, `update_memory`, or `manage_curation(action="report_contradiction", ...)`.

Unlike write-time curation, sampling here is appropriate because:
- The user explicitly initiated it (or their agent did as a deliberate action)
- The HITL approval dialog makes sense -- "MemoryHub wants to review your memories" is a reasonable prompt when you asked for a review
- It's not on the hot path -- it runs when the agent has idle time, not blocking a write

The sampling handler for `review_my_memories` uses the Llama 4 Scout fallback for clients that don't support sampling:

```python
sampling_handler=OpenAISamplingHandler(
    api_key=os.getenv("LLAMA_4_SCOUT_API_KEY"),
    base_url=os.getenv("LLAMA_4_SCOUT_BASE_URL"),
    default_model=os.getenv("LLAMA_4_SCOUT_MODEL_ID"),
)
sampling_handler_behavior="fallback"
```

With `"fallback"` behavior: Claude Code clients use their own LLM (zero marginal cost); simpler clients use Llama.

## Background Curator (Future)

The inline pipeline handles write-time curation. A background curator agent handles periodic tasks that require cross-user visibility:

- **Promotion analysis** -- scan for patterns across users, propose org memories
- **Cross-scope conflict detection** -- org memory contradicted by many user agents
- **Deep dedup sweeps** -- the 0.70-0.80 similarity range across large memory sets
- **Staleness processing** -- act on accumulated contradiction signals

This is deferred to a later phase. It requires multi-user data (we have one user currently), a long-lived agent process with elevated RBAC, and cost management for periodic LLM calls at scale. The single-agent consistency argument applies here: one curator agent checking for duplicates and conflicts across organizational scope means no two processes can independently create conflicting organizational memories.

The graph relationships built in [memory-tree.md](memory-tree.md) (`derived_from`, `supersedes`, `conflicts_with`) are the substrate for promotion provenance tracking. When a user memory gets promoted to organizational scope, the provenance chain links back to the source memories, enabling reversal if the promotion turns out to be wrong.

The background curator uses `sampling_handler_behavior="always"` with the Llama 4 Scout handler, since it's server-side infrastructure with no client HITL involved.

## Design Questions (Resolved)

These were open in the original design. Here's where we landed:

**Should curation use LLM sampling at write time?** No. The MCP spec requires HITL for sampling, which is unacceptable friction on write operations. Instead, `write_memory` returns similarity counts and the calling agent's existing LLM handles the judgment. Sampling is reserved for explicit review tools.

**Threshold for promotion?** Deferred -- needs multi-user data. When implemented, configurable via curation rule with trigger `periodic`.

**Promotion reversals?** Mark promoted memory as not-current, restore original user memories from provenance chain (graph relationships). The `supersedes` and `derived_from` edges make this a graph traversal, not a guessing game.

**Schema for human review queue?** Database-backed queue (flagged memories in metadata) for async review. Elicitation available for `review_my_memories` if needed. External ticketing integration deferred.

**Bottleneck prevention?** Inline curation is fully deterministic: regex in microseconds, one pgvector query in milliseconds. No LLM calls on the write path means write latency is bounded and predictable.

**Leader election?** Deferred to operator phase. Not needed for inline curation. Only matters when the background curator is introduced.

**Recursive loop risk?** Eliminated by design. The write pipeline has no sampling, so there's nothing to recurse. The `review_my_memories` tool uses sampling but doesn't write -- it returns suggestions for the agent to act on.

## Design Questions (Open)

- How should `manage_curation(action="set_rule", ...)` validate that user rules don't create security gaps? Users need guardrails on what they can adjust. Thresholds are safe to change; disabling secrets scanning is not. The `override` flag on system rules prevents weakening, but we need clear error messages when a user tries to override a protected rule.

- Should `review_my_memories` be proactive (runs automatically after N writes) or only on-demand? On-demand is simpler to start. Proactive could be a curation rule with trigger `periodic` and a write-count threshold.

- How do we define "similarity" in the tool description guidance? The 0.80 threshold is based on all-MiniLM-L6-v2 embeddings, which cluster differently than larger models. The threshold should be calibrated against real memory data. Starting conservative (0.80) and adjusting based on false-positive rates is the right approach.

- Should `manage_graph(action="get_similar", ...)` also return memories that have been flagged as similar to the given memory (reverse lookup via curation metadata), or only do a fresh embedding search? Fresh search is simpler; reverse lookup is faster for previously-flagged pairs.

## Implementation Phases

### Phase 2a: Inline Pipeline + Rules Engine

- Curation rules table (migration, ORM model, Pydantic schemas)
- Rule evaluation engine with layer merging
- Tier 1 regex scanning in `write_memory`
- Tier 2 embedding similarity in `write_memory` with similar_count response
- Default system rules: `secrets_scan`, `pii_scan`, `exact_duplicate`, `near_duplicate`, `staleness_trigger`
- `manage_graph(action="get_similar", ...)` (part of `manage_graph` MCP tool)
- merge suggestion via `manage_graph(action="create_relationship", ...)` with `conflicts_with` type
- `manage_curation(action="set_rule", ...)` (part of `manage_curation` MCP tool)
- Update `write_memory` response format with curation feedback
- Tests for rule evaluation, regex patterns, embedding thresholds, response format

### Phase 2b: Explicit Review Tools

- Wire up Llama 4 Scout as fallback sampling handler in MCP server config
- `review_my_memories` tool with sampling
- Tests with mocked sampling

### Phase 3: Background Curator

- Long-lived curator agent process with `sampling_handler_behavior="always"`
- Promotion analysis across users
- Cross-user dedup and conflict detection
- Staleness processing for accumulated contradiction signals

### Phase 4: Human-in-the-Loop

- Elicitation integration for `review_my_memories`
- Review queue UI/API
- Notification system for flagged memories
