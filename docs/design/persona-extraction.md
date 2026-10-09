# Persona Extraction — Standing Profile from Behavioral Memory

**Issue**: WRIG-1483
**Date**: October 2026
**Status**: Spike complete, awaiting measurement

---

## Summary

Persona extraction compiles a standing user profile from behavioral facts the dreaming pipeline has accumulated over time, storing it as a single versioned synopsis node that agents inject before search at session start. The goal is personalisation: agents should know who the user is without re-discovering that context from search on every session.

---

## Relationship to knowledge-compilation.md

Knowledge compilation (docs/design/knowledge-compilation.md) produces multi-user, scope-shared knowledge articles — the governed equivalent of a team wiki. Persona extraction produces a single-user identity model — a per-person behavioral profile that travels with every session.

The two are complementary:

- Knowledge compilation answers "what does this team/project know?"
- Persona extraction answers "who is this person and how do they work?"

Both use the same node model (versioned `MemoryNode`, provenance edges, RBAC via tenant isolation), but serve different consumers. Persona is explicitly out of scope for the knowledge compilation pipeline because the output is personal and non-shareable. It is better understood as a specialization of the "Personal KB" pattern described in knowledge-compilation.md §User-Scope, scoped to behavioral synthesis rather than topic-keyed article generation.

---

## Problem

Dreaming extracts behavioral facts from every conversation:

```
"Prefers async communication over synchronous meetings"
"Works in deep-focus blocks, avoids context switching"
"Switched to Rust for systems code (September)"
"Ships incrementally — strong aversion to big-bang PRs"
```

These facts exist in the memory tree and are retrievable by search. But they compete with task-relevant results for the context budget, surface inconsistently depending on query phrasing, and require the agent to synthesize a mental model of the user from scratch each session. A user with 40 behavioral facts loses most of them to context budget pressure.

The hypothesis: a pre-synthesized ~400-token profile beats N individual facts competing for context budget, because the LLM has already resolved contradictions, normalized tense, and ranked what matters. The profile is stable across sessions and injected unconditionally, not search-scored.

---

## Architecture

### Data flow

```
Conversation threads
     │
     ▼  dreaming pipeline
Behavioral facts         scope=user, source=dreaming,
                         content_type=behavioral, is_current=True
     │
     ▼  persona compiler (on demand)
Synopsis node            scope=user, source=persona_compiler,
                         content_type=behavioral, weight=1.0,
                         versioned, embedded, provenance edges
     │
     ▼  SessionStart hook / agent tool call
Agent context            injected before search, when synopsis exists
```

### Node model

Synopses and pins are ordinary `MemoryNode` rows. No schema change is required — `scope`, `source`, `status`, `deleted_at`, versioning fields, and parent/child relationships already exist on main.

**Synopsis node**

| Field | Value |
|---|---|
| `scope` | `user` |
| `source` | `persona_compiler` |
| `content_type` | `behavioral` |
| `weight` | `1.0` |
| `is_current` | `True` on active synopsis, `False` on retired |
| `logical_id` | Stable across all versions of this user's synopsis |
| `version` | Increments on each recompile |
| `previous_version_id` | Points to retired synopsis |
| `metadata_["stale"]` | `True` when dreaming has written new facts since last compile |
| `metadata_["source_fact_count"]` | Fact count at compile time |

**Pin node** (user-declared overrides)

| Field | Value |
|---|---|
| `source` | `user` |
| `branch_type` | `persona_pin` (reserved for persona; not shared with dreaming's `fact` children) |
| `parent_id` | Current synopsis node ID |
| `weight` | `0.9` |

Pins survive recompile: the compiler reads them from the retiring synopsis and re-parents them to the new one.

**Provenance edges**

`MemoryRelationship(relationship_type="derived_from")` rows from synopsis → each source behavioral fact. Gives a queryable lineage: which facts contributed to a given profile version.

### Version chain

```
synopsis v1  (logical_id=L)
    │ previous_version_id
synopsis v2  (logical_id=L, previous_version_id=v1.id)
    │ previous_version_id
synopsis v3  (logical_id=L, previous_version_id=v2.id)   ← is_current=True
```

Retired versions remain queryable. `logical_id` is stable across the chain.

---

## Staleness

When the dreaming pipeline commits a behavioral fact it calls `mark_synopsis_stale`, setting `metadata_["stale"]=True` on the current synopsis. The call is non-fatal — if no synopsis exists, or if the call fails, dreaming proceeds normally.

`get_persona()` exposes `is_stale` and `stale_hint` in its response so agents can surface a recompile prompt. The stale profile is still returned — a slightly outdated profile is better than no context.

Recompile is on-demand only (CLI `memoryhub persona compile` or MCP `compile_persona()`). Scheduled recompilation is not implemented yet; see Open Questions.

---

## Injection model

Injection is **opt-in, not unconditional**.

`register_session` returns `persona_synopsis_id: str | None`. Agents check this value:

- If `null` → no profile compiled yet, proceed without it.
- If non-null → call `get_persona()` before `search_memory`. The synopsis is already identified; `get_persona()` fetches content and staleness status.

This means sessions without a compiled profile pay no cost, and the instruction in the system prompt is conditional ("if `persona_synopsis_id` is non-null, call `get_persona()` before search") rather than imperative for every session.

The SessionStart CLI hook (`load-persona.sh`) follows the same pattern: it resolves `user_id`, exits silently if none is found or no synopsis exists, and only emits the `<memoryhub-persona>` context block when a synopsis is present.

Persona tools are registered in the `compact` and `full` profiles. They are not included in `minimal` (small-model profile where tool count is the hard constraint).

---

## Pin identity

User-declared pins use `branch_type="persona_pin"`. This value is reserved for persona and is not written by any other pipeline. This avoids the collision with dreaming's extracted fact children, which use `branch_type="fact"` and `source="dreaming"`. The three-field query `(source="user", branch_type="persona_pin", is_current=True)` is unambiguous.

Pins without a synopsis anchor (`parent_id=None`) are not currently supported. The `list_pins` action in `edit_persona` always resolves the current synopsis before querying, so the returned list is always scoped to the active synopsis.

---

## Authorization

Persona compilation follows existing user-scope authorization:

- Only the authenticated user (or an admin acting on their behalf) may compile or read their own synopsis.
- The `tenant_id` filter on all queries ensures cross-tenant isolation is inherited from the node model.
- The synopsis node is `scope=user`, so it participates in RBAC the same way any user-scoped memory does.

No new authorization rules are required for the spike. If per-project synopses are added later, project-scope RBAC applies to project-scoped synopsis nodes via `scope_id`.

---

## Cost

One LLM call per recompile (same endpoint as dreaming extraction). Input: up to 100 behavioral facts + user-declared pins. Output: ≤512 tokens. Temperature 0.3 for stability. Two retries with exponential backoff on transport failure.

The profile is cached as a node; agents reading it via `get_persona()` or `read_memory(persona_synopsis_id)` pay only a DB read, not an LLM call.

---

## Open questions

**Scheduled recompilation.** Currently recompile is on-demand. A background job that recompiles when `is_stale=True` and the user has been active recently would keep the profile current without agent intervention. Design TBD.

**Per-project synopsis.** The schema supports it via `scope_id`. Not wired in the CLI or MCP surface yet. Worth adding if users work across projects with significantly different behavioral patterns.

**Measurement.** The underlying hypothesis (pre-synthesized profile beats N individual facts) is untested. A controlled comparison — sessions with persona injection versus sessions without, evaluated on a task set where user context is load-bearing — is the next step before treating this as a production feature. The spike is close to being able to run this experiment.

**Contradiction handling.** The compiler prompt instructs the LLM to prefer the more recent timestamp when two facts conflict. There is no user-facing review flow for contradictions surfaced during compilation. The existing `report_contradiction` mechanism covers memory-level contradictions; persona-level conflicts are currently resolved silently by the LLM.

**Synopsis search exclusion.** Synopsis nodes have `source=persona_compiler` and `content_type=behavioral`. They are not excluded from the general search index by a hard filter. Operators should verify that search results do not surface synopses alongside regular memories in contexts where that would be confusing. Adding `source != "persona_compiler"` to the default search filter is a safe conservative option.
