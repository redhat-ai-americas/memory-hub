# Authorization Model

## Current state — what works and what doesn't

The RBAC framework lives in `memory-hub-mcp/src/core/authz.py` (180 lines)
and the SQL filter builder in
`src/memoryhub/services/memory.py:336-372`. It exposes three decision
functions plus a helper:

- `get_claims_from_context()` — resolves the calling identity from FastMCP
  access tokens, raw `Authorization: Bearer` headers, or the
  `register_session` fallback. Returns a normalized
  `{sub, identity_type, tenant_id, scopes}` dict.
- `authorize_read(claims, memory) -> bool`
- `authorize_write(claims, scope, owner_id) -> bool`
- `build_authorized_scopes(claims) -> dict` — pushes the read decision into
  SQL as a per-tier `WHERE` predicate for `search_memory`.

Every tool except `set_curation_rule` calls one of these enforcement
functions. `set_curation_rule` pins `owner_id` silently to `claims["sub"]`
and is effectively user-scope-only by construction.

The framework correctly enforces:

- **User-scope isolation.** A memory owned by user A cannot be read or
  written by user B unless B has the blanket `memory:read` / `memory:write`
  scopes. Verified by `memory-hub-mcp/tests/test_authz.py`.
- **Cross-user identity resolution.** Each request resolves its own caller
  via JWT claims, fixing the prior bug where the module-level session global
  could leak between concurrent SDK clients (commit `0c8308a`,
  `test_authz.py:115-132`).
- **Identity-type gates for organizational and role scope.** Writes to those
  scopes require `claims["identity_type"] == "service"`.
- **Enterprise-scope writes blocked.** Always denied at the API; the design
  intent is HITL approval through a separate workflow.

The framework does **not** enforce:

- **Project-scope membership.** This is the gap that blocks the demo.
  `authz.py:135` and `:156` literally `return True` for project-scope reads
  and writes, with `# project membership check TBD` comments. The SQL filter
  at `authz.py:173-177` emits no `owner_id` predicate for non-user tiers, so
  project-scope `search_memory` calls return every project-scope memory in
  the database regardless of caller. Tests at `test_authz.py:23,57`
  explicitly assert the permissive behavior as the correct outcome.
- **Role matching.** `authz.py:138` notes `# role matching TBD`. Role scope
  is not in scope for the demo.
- **Anything resembling an audit log.** No `audit` module exists in the
  codebase.

## Project membership enforcement (critical path)

The hive-mind narrative is the demo. Project-scope writes are how agents
broadcast findings to the rest of the fleet. If those writes are unenforced,
the demo's central trust claim collapses. This work has to land before the
demo.

### Data model

A new table `project_memberships`:

```sql
CREATE TABLE project_memberships (
  user_id    VARCHAR(255) NOT NULL,
  project_id VARCHAR(255) NOT NULL,
  role       VARCHAR(64)  NOT NULL DEFAULT 'member',
  added_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
  added_by   VARCHAR(255),
  PRIMARY KEY (user_id, project_id)
);
CREATE INDEX ix_project_memberships_project ON project_memberships (project_id);
```

Membership is deliberately a flat `(user, project)` join, not a hierarchical
RBAC. Roles within a project are reserved (`member`, `admin`) but not
enforced by the demo. Population happens at agent provisioning time via the
generation CLI (see [cli-requirements.md](cli-requirements.md)).

The users ConfigMap (`memory-hub-mcp/deploy/users-configmap.yaml`) gains a
new optional field per user entry:

```yaml
users:
  - user_id: ed-triage-nurse-01
    name: ED Triage Nurse 01
    api_key: mh-svc-ed-triage-nurse-01-2026
    identity_type: service
    scopes: ["user", "project"]
    project_memberships:
      - ed-discharge-workflow
      - medication-reconciliation
```

The session loader in `memory-hub-mcp/src/tools/auth.py` reads
`project_memberships` and stuffs them into the resolved session record. The
generation CLI is the source of truth for what's in the ConfigMap.

For the demo path the membership data lives in the ConfigMap. For Phase 2
JWT identities, membership would come from a JWT claim (e.g., a `groups`
claim mapped through Keycloak), and the same enforcement code would consume
it.

### Enforcement points

`authorize_read` and `authorize_write` for project scope check that
`project_id` (the memory's `owner_id`, since project-scope memories are
owned by the project) is in the caller's set of project memberships:

```python
# pseudo-code; real implementation lives in authz.py
def authorize_read(claims, memory):
    if memory.scope == "project":
        return memory.owner_id in claims["project_memberships"]
    ...

def authorize_write(claims, scope, owner_id):
    if scope == "project":
        return owner_id in claims["project_memberships"]
    ...
```

`build_authorized_scopes` emits a SQL predicate for project scope that
constrains `owner_id IN (...)` to the caller's memberships. This means
`search_memory` at project scope is correctly bounded at the database
level, not just at the application layer.

The `claims` dict gains a `project_memberships` field populated by both the
session-fallback path and the JWT path. JWT path reads it from a `groups`
claim or equivalent.

### Tests

The two parametrized cases at `test_authz.py:23,57` that currently assert
the permissive behavior have to be updated. The change is the entire point
of the work — we want non-members to be denied. New tests:

- Member of `proj-1` can read and write `proj-1` memories.
- Non-member of `proj-1` cannot read or write `proj-1` memories.
- `search_memory` at project scope returns only memories from projects the
  caller is a member of.
- A user who is a member of multiple projects sees the union of those
  projects' memories.
- A user who is a member of zero projects gets an empty result set for
  project-scope searches.

## The intersection authorization model (production target)

The data model captures both `actor_id` and `driver_id` so an authorization
decision can in principle require *both* the actor and the driver to be
permitted. This is the OAuth On-Behalf-Of pattern, RFC 8693 token exchange
semantics, and the FHIR Provenance assumption all in one. It is the right
model for production.

For the demo, we run in **audit-only mode**: the `driver_id` is captured on
every write but only the *actor's* permissions are checked. The data model
supports the intersection model from day one, but the enforcement layer
consults only `actor_id`. This keeps the demo's surface area small without
locking out the production path.

The migration from audit-only to intersection enforcement is well-defined:

1. Add a `permissions_for(principal)` resolver that, given an actor or
   driver identity, returns the set of scopes and project memberships that
   identity is allowed.
2. At every enforcement point, compute `actor_perms ∩ driver_perms` and
   evaluate the operation against the intersection.
3. Add a feature flag (`MEMORYHUB_INTERSECTION_AUTHZ`) so the switch is
   reversible during initial rollout.
4. Migrate tests to assert intersection semantics.

The intersection model is filed as a separate future-work issue. The audit
log is its prerequisite — without `actor_id` and `driver_id` recorded on
every operation, intersection enforcement cannot be retroactively verified.

### Why not enforce intersection at the demo

Two reasons. First, modeling driver permissions requires either a
permissions table for drivers or a JWT path that carries them, and neither
exists. The demo's drivers are us (Wes via the CLI harness, Claude driving
agents) and synthesized clinician identities — none of which have real
permission grants. Second, the demo's narrative is "MemoryHub captures who
did what on whose behalf and enforces project membership," not "MemoryHub
enforces complex delegated authorization." Intersection enforcement is one
layer too far for the story we're trying to tell, and we'd have to invent
fake driver permissions to demo it. Better to capture the model and ship it
post-demo.

## Audit logging — stub now, persistence later

No audit log exists in the codebase. The design in `docs/governance.md:407`
is solid but unimplemented. We need *something* for the demo because the
demo's audit story is one of its three core narratives.

### Stub interface

A new module `memory-hub-mcp/src/core/audit.py` exposes a single function:

```python
def record_event(
    event_type: str,
    actor_id: str,
    driver_id: str,
    scope: str,
    owner_id: str,
    memory_id: str | None,
    decision: str,
    metadata: dict | None = None,
) -> None:
    """Record an audit event. Demo-stage implementation: structured log line."""
```

The stub implementation writes a single JSON-structured log line via the
existing logger. No database, no persistence, no state. This satisfies
three things:

- Every tool that mutates or reads memory has the call site in place from
  day one. When persistence lands, it's a drop-in replacement.
- The demo can grep structured logs to show "every operation was recorded."
- The shape of the recorded event includes both `actor_id` and `driver_id`,
  proving the data model carries through.

### Call sites

Every tool calls `audit.record_event` immediately after its
`authorize_*` decision, regardless of decision outcome. Both successful and
denied operations get recorded — denied operations are exactly the ones
auditors care about most.

| Tool | Event type |
|---|---|
| `write_memory` | `memory.write` |
| `read_memory` | `memory.read` |
| `search_memory` | `memory.search` |
| `update_memory` | `memory.update` |
| `delete_memory` | `memory.delete` |
| `report_contradiction` | `memory.contradiction_reported` |
| `create_relationship` | `memory.relationship_created` |
| `register_session` | `session.registered` |

`search_memory` records the search but not individual results. Result-level
audit (which memories were returned in response to which query) is
deferred — it's expensive and the demo doesn't need it.

### Persistence (future work) — prefer LlamaStack telemetry over rolling our own

The original plan was a custom audit log: partitioned `audit_log` table,
append-only enforcement via PostgreSQL Row-Level Security, dedicated
`audit_writer` role, retention policies (the design at
`docs/governance.md:407`). Before building any of that, evaluate
**LlamaStack telemetry** as the persistence backend.

LlamaStack ships as a Technology Preview on Red Hat OpenShift AI and
exposes a first-class `telemetry` provider in its run config — the
`llamastack-integration/architecture.md` example at line 291 already lists
`provider_type: inline::meta-reference` for telemetry. The platform we're
deploying on already has tracing and logging infrastructure built in. The
existing llamastack-integration architecture even flags the gap:
"MCP-level metrics and access logs are available only through MemoryHub's
own Prometheus instrumentation, not through a unified platform view"
(`../../planning/llamastack-integration/architecture.md:322`). Pushing audit events
through LlamaStack telemetry closes that gap *and* avoids duplicating
infrastructure.

Why this matters: a custom `audit_log` table is real engineering — schema,
RLS policies, a privileged writer role, retention, query API,
performance work. LlamaStack telemetry gives us trace correlation, log
aggregation, retention, and a query surface that integrates with the rest
of the RHOAI observability stack. If it covers MemoryHub's audit
requirements, we should use it. If it has gaps (e.g., immutability
guarantees, structured field schemas, retention policies tied to
healthcare compliance), we identify the gaps specifically and decide
whether to fill them in LlamaStack-land or fall back to a custom store.

The stub interface in `memory-hub-mcp/src/core/audit.py` is deliberately
backend-agnostic: `record_event(...)` takes structured fields and returns
nothing. The eventual implementation can route to LlamaStack telemetry,
OpenTelemetry, a database, or all of the above without changing call
sites.

**Evaluation criteria when picking up the persistence work:**

- Does LlamaStack telemetry preserve `actor_id` and `driver_id` as
  first-class fields, or only as free-form attributes? First-class is
  preferred for queryability.
- Can audit events be made tamper-evident or append-only? This may
  require RHOAI-side configuration (immutable storage backend) rather
  than application code.
- What's the retention story? Healthcare compliance frequently requires
  6-7 year retention; verify this is achievable through the LlamaStack
  telemetry pipeline before committing to it.
- How are denied operations recorded? The MCP tool returns an error and
  the audit call still has to happen — verify LlamaStack telemetry can
  capture both successful and denied operations with equal fidelity.
- What does the query path look like for "show me everything actor X did
  during conversation Y"? If it's a Grafana/Loki query, that's fine for
  a demo. If it's a custom UI, that's a separate piece of work.

If the evaluation finds LlamaStack telemetry sufficient, the persistence
issue is closed by writing a thin adapter from `audit.record_event` to
the LlamaStack telemetry SDK plus configuration of the telemetry provider
in MemoryHub's deployment. If it's insufficient, the original `audit_log`
table design remains the fallback — but only the parts that LlamaStack
can't cover, not a wholesale custom build.

The stub interface doesn't change shape regardless of which backend
wins.

## How the new fields flow through the existing enforcement layer

The intersection model's hooks identified during research:

| Surface | File:line | What changes for the demo |
|---|---|---|
| Claim resolver | `memory-hub-mcp/src/core/authz.py:59-117` | Returns `claims` with new `project_memberships` field. `actor_id` derived from `claims["sub"]`. |
| `authorize_read` | `memory-hub-mcp/src/core/authz.py:120-138` | Real project membership check at line 135. Signature unchanged. |
| `authorize_write` | `memory-hub-mcp/src/core/authz.py:141-157` | Real project membership check at line 156. Signature unchanged. |
| `build_authorized_scopes` | `memory-hub-mcp/src/core/authz.py:160-179` | Emits `owner_id IN (...)` predicate for project tier. |
| SQL filter builder | `src/memoryhub/services/memory.py:336-372` | Consumes the project-scope membership list in the filter. |
| Session loader | `memory-hub-mcp/src/tools/auth.py:27-74` | Loads `project_memberships` from each user record. |
| `write_memory` body | `memory-hub-mcp/src/tools/write_memory.py:108-121` | Captures `driver_id` parameter, persists `actor_id`/`driver_id` on the new memory, calls `audit.record_event`. |
| Other write tools | `update_memory.py`, `delete_memory.py`, `report_contradiction.py`, etc. | Same pattern: capture driver, persist on the row, record audit event. |
| Read tools | `read_memory.py`, `search_memory.py`, etc. | Return `actor_id`/`driver_id` in payload. Record audit event. |

For the demo, the *signatures* of `authorize_read` and `authorize_write`
remain unchanged. The intersection model would require expanding them to
take an actor/driver pair, which is a future change.

## Security notes

- `actor_id` is **not** caller-provided. It is always derived from the
  authenticated identity. A caller cannot claim to be a different actor than
  it actually is. This is the core integrity property of the audit log.
- `driver_id` **is** caller-provided. A malicious actor could lie about the
  driver. This is acceptable in the audit-only model — the actor is still
  recorded truthfully, so any falsified driver claim is attributable to the
  lying actor. In intersection mode this becomes a real threat and would
  need to be addressed by requiring the driver's identity to be backed by a
  cryptographic claim (delegation token, signed assertion, etc.).
- `driver_id` is not redacted on read in the demo. This means an agent can
  see who initiated any memory it has access to. Filed as future work.
- Audit log records both `actor_id` and `driver_id` for every operation,
  including denied ones. This is required for the demo's "trace everything
  agent #07 did during the discharge workflow" narrative.

## Open questions

- *Should the project membership check be case-sensitive?* Yes by default —
  treat `project_id` as an opaque identifier.
- *Should an agent be able to write to a project it has no membership in if
  it has the blanket `memory:write` scope?* No. Blanket scope grants the
  *operation type* across all tiers but does not bypass project membership.
  This needs to be clearly tested.
- *Should `register_session` validate that all declared
  `project_memberships` exist as known projects somewhere?* For the demo,
  no — there's no project registry yet. Membership is whatever the
  ConfigMap says it is.
