# Identity Data Model

## The triple: owner, actor, driver

Every memory operation in MemoryHub involves three identities. They have
distinct jobs and they should not be conflated.

| Field | What it answers | Example |
|---|---|---|
| `owner_id` | Who does this memory *belong to*? Determines scope membership and visibility. | An agent's `user_id` for user-scope writes; a `project_id` for project-scope writes. |
| `actor_id` | Which authenticated principal *performed* the operation? | The agent that called `write_memory` — always its own `user_id`. |
| `driver_id` | On *whose behalf* was the action taken? | The user (or upstream agent) that the actor is acting for. Equals `actor_id` for fully autonomous operation. |

`owner_id` exists today. `actor_id` and `driver_id` are new and will be added
to the `MemoryNode` schema and the tool API.

### Why three fields and not two

Two identities — owner and actor — would let us answer "who performed this
action" but not "who is responsible for it." In healthcare, those are
different questions with different audit consequences. The medication
reconciliation agent might write a memory at the request of Dr. Smith. The
*actor* is the agent. The *responsible party* is Dr. Smith. The agent is the
mechanism; the doctor is the principal.

This split also lets us distinguish autonomous operation (`driver_id ==
actor_id`) from delegated operation (`driver_id != actor_id`) at query time
without joining to an audit log. A search like "show me everything that was
written on behalf of Dr. Smith across the entire fleet" becomes a single
indexed lookup.

### Defaults

- `actor_id` defaults to the authenticated caller's `user_id` and cannot be
  overridden by the caller. It is *what we know about who called us*, not a
  claim the caller makes about itself.
- `driver_id` defaults to `actor_id` (fully autonomous mode) when no driver is
  specified. The caller may declare a `driver_id` either at session
  registration time (sets a session default) or per-request (overrides the
  session default).
- `owner_id` defaults as it does today: caller's `user_id` for user-scope,
  required `project_id` for project-scope, etc.

## Schema additions to `MemoryNode`

Two new columns on `memory_nodes`:

```sql
ALTER TABLE memory_nodes ADD COLUMN actor_id  VARCHAR(255);
ALTER TABLE memory_nodes ADD COLUMN driver_id VARCHAR(255);
CREATE INDEX ix_memory_nodes_actor_id  ON memory_nodes (actor_id);
CREATE INDEX ix_memory_nodes_driver_id ON memory_nodes (driver_id);
```

Nullability: nullable in the migration so existing rows are valid; populated
on every new write going forward. Backfill of existing rows: `actor_id =
owner_id`, `driver_id = owner_id` (these are the only sane defaults for rows
that predate the concept).

A composite index on `(driver_id, scope, is_current)` is worth considering
once we know the dominant query pattern in the demo — defer until we have
real workload data.

`MemoryNodeCreate` and `MemoryNodeRead` Pydantic schemas in
`src/memoryhub/models/schemas.py` gain matching optional fields. The SDK
client (`sdk/src/memoryhub/models.py`) and the UI BFF inherit through the
schema regeneration.

## Tool API changes

### `register_session`

Gains an optional `default_driver_id` parameter:

```python
register_session(api_key="mh-svc-cardio-triage-01-2026",
                 default_driver_id="claude-code-cli-test-run-14")
```

If omitted, defaults to the agent's own `user_id` (autonomous mode). The
session default is held in the existing `_current_session` dict in
`memory-hub-mcp/src/tools/auth.py:20`.

### `write_memory`, `update_memory`, `delete_memory`, `report_contradiction`

Each gains an optional `driver_id` parameter that, if provided, overrides the
session default for *this call only*. If both the parameter and session
default are absent, defaults to `actor_id`.

`actor_id` is **not** a parameter — it is always derived from the
authenticated identity (`claims["sub"]`) and cannot be claimed by the caller.

### `search_memory`, `read_memory`, `get_relationships`, `get_memory_history`

Read paths gain `driver_id` as an optional *filter*. Memories returned to the
caller include both `actor_id` and `driver_id` so the calling agent can
inspect the provenance of what it found.

For the demo, `driver_id` is visible to any reader who can see the memory.
Redaction-on-read is filed as future work.

## Mapping to industry standards

We chose `actor_id` because it has clear precedent. We chose `driver_id`
because the alternatives are fragmented enough that picking a project-specific
term is more honest than pretending to follow a single standard. Both are
documented here against the standards they relate to.

### RFC 8693 (OAuth 2.0 Token Exchange)

RFC 8693 defines the canonical machine-readable model for delegated authority
in JWTs.

| RFC 8693 concept | MemoryHub equivalent |
|---|---|
| `subject_token` — the principal whose authority is being delegated | `driver_id` |
| `actor_token` — the party that will act using the delegated authority | `actor_id` |
| `act` claim — embedded in issued tokens to assert the current actor | `actor_id` (when populated from a JWT path) |
| `sub` claim — the subject of the issued token, typically the delegator | `driver_id` (when populated from a JWT path) |
| `may_act` claim — declares which actors are permitted to act for a subject | A future authorization concern; not modeled yet |

When MemoryHub eventually accepts JWTs from a token exchange flow, the
mapping will be: `claims["sub"]` → `driver_id`, `claims["act"]["sub"]` →
`actor_id`. Until then, the API-key path sets `actor_id` from the resolved
session user and `driver_id` from the explicit parameter (or defaults to
`actor_id`).

### HL7 FHIR Provenance

FHIR's `Provenance` resource is the healthcare-domain analog and is the
standard EMRs and HIE systems use to record who did what to a clinical
record.

| FHIR field | MemoryHub equivalent |
|---|---|
| `Provenance.agent.who` — the agent that participated in the event (mandatory) | `actor_id` |
| `Provenance.agent.onBehalfOf` — the principal the agent was acting for (optional) | `driver_id` |

FHIR's convention is that `agent.who` is required and `agent.onBehalfOf` is
optional, defaulting to "the agent acted on its own authority." MemoryHub
follows the same convention: `actor_id` is always populated, `driver_id`
defaults to `actor_id` when not declared.

### Other ecosystems considered

Microsoft Entra "Agent OBO," Google Cloud IAM service-account impersonation,
AWS STS AssumeRole, SPIFFE delegated identity, and Kubernetes user
impersonation were all surveyed. None offers a single dominant field name for
"on whose behalf." Microsoft and the broader OAuth ecosystem use "actor" for
the acting party (matching our choice). For the on-behalf-of side, terms are
fragmented: "subject," "principal," "target," "impersonated user,"
"delegator." We picked `driver_id` for clarity and intuitiveness. The mapping
to the standards above is the contract that makes the choice defensible.

## Naming reference for documentation and code review

Use these terms consistently:

- **Actor** — the entity that *performed* an operation. Always an
  authenticated MemoryHub identity. In code: `actor_id`. In FHIR mapping:
  `Provenance.agent.who`. In RFC 8693 mapping: the `act` claim subject.
- **Driver** — the entity *on whose behalf* an operation was performed. May
  be a human user, another agent, or the same identity as the actor (for
  autonomous operation). In code: `driver_id`. In FHIR mapping:
  `Provenance.agent.onBehalfOf`. In RFC 8693 mapping: the `subject_token`
  principal.
- **Owner** — the entity that a memory *belongs to*. Determines scope
  visibility. In code: `owner_id`. Unchanged from existing semantics.
- **Principal** — generic term for any of the three. Avoid in code; use the
  specific term.
- **Caller** — informal term for the entity making a tool call. Resolves to
  the actor at the point of authentication. Use only in narrative docs, not
  in code.

## Open questions

- *Should the `actor_id` column be `NOT NULL` after backfill, or stay
  nullable?* Leaning toward nullable in the migration, application-enforced
  on writes, with a future migration to add the constraint after the demo.
- *Should an additional composite index `(driver_id, scope, is_current)` be
  created up front?* Defer until we see the demo's dominant query pattern.
- *Should `report_contradiction` capture a separate `reporter_id` distinct
  from `actor_id`?* Probably not — the actor at the time of the report is
  the reporter. Conflating them keeps the model smaller.
