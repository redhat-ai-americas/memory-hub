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

Every tool except `manage_curation(action="set_rule", ...)` calls one of these enforcement
functions. `manage_curation(action="set_rule", ...)` pins `owner_id` silently to `claims["sub"]`
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

- **Project-scope membership (implemented, #167).** `authz.py` checks
  `memory.scope_id in project_ids` for reads and `scope_id in project_ids`
  for writes, where `project_ids` is resolved from the `project_memberships`
  table via `get_projects_for_user()`. The `_build_search_filters` function
  filters project-scoped results by `scope_id IN (caller's project
  memberships)`. Feature-flagged via `MEMORYHUB_PROJECT_ISOLATION_ENABLED`
  (default: on).
- **Role matching (implemented, #167).** `authz.py` checks
  `memory.scope_id in role_names` where `role_names` is resolved from the
  `role_assignments` table plus JWT `roles` claims. Role writes remain
  restricted to service identities (curator agent). Feature-flagged via
  `MEMORYHUB_ROLE_ISOLATION_ENABLED` (default: on).
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
    api_key: <ed-triage-nurse-01-api-key>
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

No audit log exists in the codebase. The design in `docs/design/governance.md:407`
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
| `manage_curation(action="report_contradiction", ...)` | `memory.contradiction_reported` |
| `manage_graph(action="create_relationship", ...)` | `memory.relationship_created` |
| `register_session` | `session.registered` |

`search_memory` records the search but not individual results. Result-level
audit (which memories were returned in response to which query) is
deferred — it's expensive and the demo doesn't need it.

### Persistence backend evaluation and implementation

Issue #70 required evaluating persistence backends before implementation. Four candidates were considered:

**LlamaStack telemetry** — Evaluated against the five criteria but taken off the table per backlog refinement 2026-07-28. LlamaStack ships as a Technology Preview on RHOAI and exposes a first-class telemetry provider (`provider_type: inline::meta-reference`), but evaluation revealed gaps:

- **First-class identity fields** (criterion 1): Unknown. LlamaStack telemetry spec doesn't document whether `actor_id`/`driver_id` would be first-class fields or free-form span attributes. If attributes, queryability suffers (string matching vs indexed columns).
- **Tamper-evidence** (criterion 2): Storage-dependent. LlamaStack telemetry delegates to backend storage (S3, block storage). Immutability requires platform-side configuration (S3 object lock, immutable storage class) rather than application-enforced guarantees. Harder to verify and audit.
- **Retention** (criterion 3): Platform-managed. Would require negotiating RHOAI platform team to configure 7-year retention, fund storage costs, and maintain the pipeline. Typical telemetry retention is 30-90 days; 7 years is atypical and expensive.
- **Denied operations** (criterion 4): Likely supported. Telemetry systems capture error traces alongside successful traces. But verification needed — some telemetry backends drop error spans to reduce volume.
- **Query path** (criterion 5): TraceQL/Grafana. Healthcare compliance auditors expect SQL export to CSV, not Grafana dashboards. Would need export tooling to bridge the gap.

Conclusion: LlamaStack telemetry *could* meet requirements with sufficient platform investment (immutable storage, 7-year retention config, export tooling), but MemoryHub can't control that timeline. Deferred for future evaluation once LlamaStack reaches GA and RHOAI's telemetry stack matures.

**OpenTelemetry export** — Evaluated but rejected. Would push audit events as OTLP spans to platform Loki/Tempo backends. Assessment against criteria:

- **First-class identity fields** (criterion 1): ❌ Fields become span attributes (string key-value pairs like `audit.actor_id="user-123"`), not typed schema columns. Queryable but slower than indexed SQL.
- **Tamper-evidence** (criterion 2): ⚠️ Storage-dependent. Loki/Tempo can use immutable S3 backends, but requires platform configuration. Not application-enforced.
- **Retention** (criterion 3): ❌ Loki retention often capped at 30-90 days due to cost. Configuring 7-year retention is expensive and requires platform negotiation.
- **Denied operations** (criterion 4): ✅ Both successful and error spans captured. OpenTelemetry handles errors well.
- **Query path** (criterion 5): ⚠️ PromQL (Loki) or TraceQL (Tempo). Healthcare compliance teams expect SQL exports to CSV, not Grafana dashboards. Would need export tooling.

Rejected because retention limits (criterion 3) and query path mismatch (criterion 5) create compliance risk.

**Platform logs (JSON to stdout)** — Stub implementation already shipping. Rejected for production use. Assessment against criteria:

- **First-class identity fields** (criterion 1): ❌ Fields are string values in JSON blobs (`"actor_id": "user-123"`), not queryable columns. Every query requires full log scan.
- **Tamper-evidence** (criterion 2): ❌ None. Cluster admin or compromised workload can edit log lines to change `actor_id` or delete entries to hide unauthorized operations. Violates core audit trust property.
- **Retention** (criterion 3): ❌ Pod logs rotate in days. Platform log aggregation (if configured) typically retains 30-90 days, not 7 years.
- **Denied operations** (criterion 4): ✅ Both allowed/denied logged identically (same JSON structure).
- **Query path** (criterion 5): ❌ Grep/jq on log files. Doesn't scale beyond thousands of events. No compliance-friendly export.

Critical gap: tamper-evidence (criterion 2). Healthcare auditors cannot trust mutable logs as authoritative record.

**PostgreSQL audit table** — Selected. Meets all five criteria:

1. **First-class identity fields**: `actor_id` and `driver_id` are typed VARCHAR(255) columns with dedicated indexes. Queryable in milliseconds via `WHERE actor_id = '...'`.
2. **Tamper-evidence**: Application-enforced immutability via RLS policies + `REVOKE UPDATE, DELETE FROM PUBLIC`. A compromised MCP server can insert new events (correct audit path) but cannot modify/delete historical records. Optional: add SHA-256 hash chain in `metadata.previous_hash` for cryptographic proof.
3. **Retention**: 7-year retention via monthly partitioning. Drop partitions older than 84 months with a cron job (`DROP TABLE audit_log_2019_08`). Each partition is independent — can be backed up to S3, archived, or dropped without downtime.
4. **Denied operations**: Both `decision='allowed'` and `decision='denied'` use identical schema. No difference in capture, storage, or query path.
5. **Query path**: Native SQL. Healthcare compliance auditors run standard queries, export to CSV, and present findings in regulatory reviews. No Grafana or custom UI required.

Additional wins: (6) No platform dependency (PostgreSQL already deployed as OOTB component), (7) transactional safety (audit events commit/rollback with operations when using caller's session), (8) proven technology (every compliance team understands SQL audit tables).

#### Implementation (2026-08-18/19)

**Dual-path architecture**: Every audit call writes to both PostgreSQL (when session available) and JSON logs (always). PostgreSQL provides queryable compliance trail, logs provide backward compatibility and graceful degradation when DB unavailable.

**Schema**: Migration 028 creates the `audit_log` table with 11 identity/event columns, 5 indexes for query performance, RLS policies enforcing INSERT-only semantics, and a CHECK constraint on `decision IN ('allowed', 'denied')`. The `FORCE ROW LEVEL SECURITY` directive ensures append-only semantics apply even to the table owner, backing the tamper-evidence claim.

**Session timing is critical**: tools must acquire DB session before authorization checks to ensure both allowed and denied events reach PostgreSQL. Tools that authorize first then get session will only write to logs, not database.

**Future work**: Monthly partitioning for automated 7-year retention (drop partitions older than 84 months). Optional: cryptographic hash chain in metadata.previous_hash for tamper detection (RLS provides application-enforced immutability; hash chain provides cryptographic proof).

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
| Other write tools | `update_memory.py`, `delete_memory.py`, `manage_curation.py` (report_contradiction action), etc. | Same pattern: capture driver, persist on the row, record audit event. |
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
