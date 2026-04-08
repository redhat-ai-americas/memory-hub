# Research: Pivot Detection for Pattern C

**Status:** Options identified 2026-04-07. No empirical data yet. Recommendation is a hybrid but needs validation against real agents.

**Feeds into:** [`../../docs/agent-memory-ergonomics/design.md`](../../docs/agent-memory-ergonomics/design.md) §Loading Patterns (Pattern C), issue #58 (adjacent), open question Q2.

## Question

Pattern C in the design doc is "lazy load after the first user turn, then rebias the working set when the session pivots to a new topic." This pattern needs a concrete trigger for "a pivot just happened." The vague instruction "watch for pivots and search again" produces inconsistent agent behavior — we know this because the current `.claude/rules/memoryhub-integration.md` already has a version of it and the pivot detection is ad-hoc.

What's the right way to detect a pivot, and where should the detection live?

## Three Concrete Triggers (from `design.md`)

The design doc already commits to three specific triggers. A "pivot" is any of:

1. **Subsystem change.** The user changes subsystems — e.g., from discussing "deployment" to discussing "UI architecture."
2. **Unknown concept.** The user references a concept that's not in the agent's current working set and can't be answered from loaded memory.
3. **Explicit switch.** The user explicitly says "let's switch to X" or similar.

These triggers are good enough as rules of thumb, but they need to be operationalized. "The user changes subsystems" is a judgment call; "the user references a concept not in your working set" is measurable but requires state tracking.

## Two Candidate Approaches for Detection

### Approach 1: Server-side detection

The MCP server measures the embedding distance between the incoming query (or a rolling conversation summary) and the session focus vector. If the distance exceeds a threshold, the server surfaces a hint in the `search_memory` response:

```json
{
  "results": [...],
  "total_matching": 12,
  "has_more": false,
  "pivot_suggested": true,
  "pivot_reason": "query vector distance from session focus is 0.67 (threshold 0.55)"
}
```

The agent sees the hint and decides whether to rebias (call `register_session(focus=...)` with a new focus and re-search).

**How it maps to the three triggers:**
- **Subsystem change** — captured directly by embedding distance
- **Unknown concept** — captured indirectly; a query about a concept the session focus doesn't cover has high distance from the focus vector
- **Explicit switch** — **not captured** by embedding distance alone; the user saying "let's switch to UI" produces a short query that may or may not embed far from the session focus

**Pros:**
- Consistent across agents — every agent sees the same pivot signal for the same query
- Cheap — reuses the session focus vector infrastructure from #58, adds one cosine-distance computation per `search_memory` call
- No LLM calls needed
- Easy to tune centrally (one threshold knob)

**Cons:**
- Only captures trigger 1 well; triggers 2 and 3 are harder
- Threshold tuning is empirical and model-dependent
- The agent still has to act on the hint — server-side detection alone doesn't *cause* a rebias

### Approach 2: Agent-side detection (LLM judgment)

The agent self-detects pivots via a rule in `.claude/rules/memoryhub-loading.md` with concrete language. Example (refined from the design doc's current draft):

```markdown
## Pivot detection

After each user turn, check whether a pivot has occurred. A pivot is any of:

1. **Subsystem change** — the user is now asking about a different area of the
   codebase than the previous turn (e.g., they were asking about deployment and
   now they're asking about UI components). Use the working set you loaded at
   session start to decide what "different area" means. If your working set is
   90% memories tagged `deployment` and the user is now asking about
   `authentication`, that's a pivot.

2. **Unknown concept** — the user referenced a concept, file path, function
   name, or subsystem that does not appear in any memory in your working set.
   This is the strongest pivot signal.

3. **Explicit switch** — the user says "let's switch to X," "now let's talk
   about X," "can we look at X instead," or similar. Treat any explicit
   topic-change language as a pivot even if the topic is close to the current one.

If you detect a pivot, call `search_memory(query=<new topic summary>, max_results=15)`
and ADD the results to your working set. Do not replace — the prior context may
still be relevant.
```

**Pros:**
- Captures all three triggers well, including the explicit-switch case that embedding distance misses
- Flexible — the agent can use its judgment for edge cases the rule doesn't cover
- No server changes needed — ships entirely in the rule file template
- Easy to iterate on — just edit the rule language

**Cons:**
- Inconsistent across agents — different LLMs (or different versions of the same LLM) will interpret the rule differently
- Doesn't scale to non-LLM agents (though this might not matter — the primary consumer is Claude Code and kagenti LangGraph agents)
- No central observability — you can't measure "how often did pivots happen this week" from the server
- Depends on the agent being disciplined about checking the rule after each turn

### Approach 3: Hybrid (recommended)

Server provides a hint, agent decides. The server computes embedding distance from the session focus and surfaces `pivot_suggested: true` when the distance exceeds a threshold. The agent rule tells the agent to:

1. Act on any `pivot_suggested: true` from the server
2. Also self-detect using the three concrete triggers
3. Override the server hint if the agent's judgment disagrees (e.g., server suggests pivot on a vague query that the agent knows is still on-topic)

The agent's final decision combines the server signal with its own judgment, which should be more reliable than either alone.

**Pros:**
- Captures all three triggers
- Server-side signal gives agents a low-effort default that works even when the rule is under-followed
- Explicit override path means the hybrid isn't more restrictive than agent-side alone
- Central observability — the server sees "how many pivots suggested" and "how many were acted on"

**Cons:**
- More complex than either alone — two mechanisms to tune and debug
- The override path needs to be worded carefully in the rule file to avoid "agent always ignores the server" and "agent always trusts the server" failure modes

## Recommendation

**Hybrid, with agent-side as the leading indicator and server-side as a safety net.** Reasoning:

1. The three triggers in the design doc are the actual definition of a pivot. Two of them (unknown concept, explicit switch) can't be captured by embedding distance alone. Agent-side detection is therefore **necessary, not optional**.
2. Server-side detection is cheap to add once #58's session focus vector exists, and it catches the "quiet drift" failure mode where the agent forgets to check the rule.
3. The hybrid gives us observability without forcing the agent to be strict about it.

**Implementation order:**
1. Ship the agent-side rule first, as part of #60 (rule file generation). This is cheap and gives us immediate value.
2. Add the server-side hint as a follow-up once #58 lands and the session focus vector is available. Until then, `pivot_suggested` just isn't in the response.
3. Measure both in parallel: count server-side suggestions, count agent-side rebias calls, compare.

## Validation Plan

Before committing to the hybrid, validate both approaches independently.

### Agent-side validation

Take a handful of real Claude Code sessions (sanitized) and walk through each user turn manually, deciding whether a pivot occurred. Then give Claude the session transcript and the proposed rule text and ask "at which turn did a pivot occur?" Measure agreement.

Target: Claude agrees with the manual label on ≥90% of turns across 10+ sessions. If agreement is lower, the rule text needs to be more concrete (possibly with examples).

### Server-side validation

Once #58 has a synthetic benchmark (see [`two-vector-retrieval.md`](two-vector-retrieval.md)), extend it: for each cross-topic query, measure the embedding distance from the session focus vector and compare against the ground-truth label.

Target: at threshold 0.55 (starting guess), server-side detection catches ≥75% of cross-topic queries with ≤20% false positives on same-topic queries. Tune the threshold empirically.

### Hybrid validation

Only meaningful once both component validations pass. At that point, run the agent on the benchmark synthetic queries with the server-side hint available, and measure whether the combined signal catches more pivots than either alone.

## Open Sub-Questions

1. **What's the right threshold for `pivot_suggested`?** Starting guess is cosine distance 0.55 from the session focus vector. Needs empirical tuning.
2. **Should the server track a rolling conversation summary, or just compare to the raw query?** Raw query is simpler but misses cases where the pivot is implicit across multiple turns. Rolling summary is more accurate but requires the agent to send conversation context to the server — which memory-hub doesn't currently do.
3. **Does pivot detection need to be recoverable?** If the agent detects a false pivot and rebiases, it has added memories to its working set. Is there a "drop the rebias and go back" path? Probably not worth it — pulling in extra context is cheap relative to missing context.
4. **How often should the agent check the rule?** Every turn feels right but might be aggressive. Maybe only when the user's turn includes a noun phrase the agent doesn't recognize? This is the "unknown concept" trigger applied more loosely.
5. **Should explicit switches bypass the server hint check?** Probably yes — if the user says "let's switch to auth" the agent should rebias immediately without waiting for a server hint on the next `search_memory`.

## References

- `../../docs/agent-memory-ergonomics/design.md` §Loading Patterns (Pattern C) — the design this research supports
- `../../docs/agent-memory-ergonomics/open-questions.md` Q2 — the question this research tracks
- `two-vector-retrieval.md` — the session focus vector this detection reuses
- `../../.claude/rules/memoryhub-integration.md` — current hand-written loading rule with an ad-hoc version of pivot detection
- Issue #58 — implementation tracking (the rule template, not the session vector itself)
- Issue #60 — where the rule file generation lives
