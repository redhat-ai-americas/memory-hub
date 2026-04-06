# Filter Rule Management

> Status: Skeleton -- needs design work before implementation

## Problem

Admins need to create, edit, and delete curation and filter rules at the system and organizational layers. The [curation pipeline](../curator-agent.md) defines a three-layer rule model (system, organizational, user) where higher layers can override lower ones. Users manage their own rules via `set_curation_rule`. Admins manage the rules that users cannot: system defaults that enforce security baselines, and organizational rules that reflect company policy.

This is the admin view of the same `curator_rules` table and evaluation logic defined in [curator-agent.md](../curator-agent.md). The difference is scope, not mechanism.

## Operations

Each operation below is a function in the core admin library at `src/core/admin/operations.py`. Authorization is enforced inside the function against the supplied `Identity`. Audit entries are written by the core. The Transports subsection on each operation lists the wrappers that currently expose it.

### `set_rule`

Creates or updates a curation rule at the system or organizational layer. This is a superset of the user-facing `set_curation_rule` (which is limited to user-layer rules). Upsert semantics: if a rule with the same `(layer, owner_id, name)` already exists, it is updated; otherwise a new rule is created.

Admin-created rules can set the `override` flag, which prevents lower layers from weakening the rule. A system rule with `override=True` for secrets scanning means no organizational rule and no user rule can reduce the sensitivity of that scan.

```python
def set_rule(
    identity: Identity,
    name: str,
    layer: str,
    tier: str,
    trigger: str,
    config: dict,
    action: str,
    priority: int,
    scope_filter: str | None = None,
    override: bool = False,
    description: str | None = None,
    enabled: bool = True,
) -> Rule
```

`layer` is `system` or `organizational` (user-layer rules are managed via `set_curation_rule`). `tier` is `regex` or `embedding`. `trigger` is `on_write`, `on_read`, `periodic`, or `on_contradiction_count`. `action` is one of `block`, `quarantine`, `flag`, `reject_with_pointer`, `merge`, `decay_weight`.

**Authorization.** Identity must carry `memory:admin`. Setting `override=True` at the `system` layer additionally requires `memory:admin:system_override`.

**Audit.** A `set_rule` entry is written including the full rule body and whether the call was an insert or update. For updates, `state_before` contains the prior rule definition.

**Transports.**
- MCP tool: `admin_set_rule`
- BFF route: `POST /api/admin/rules` (create) and `PUT /api/admin/rules/{rule_id}` (update)
- Worker entry point: not applicable (rule authoring is operator-driven)

### `list_rules`

Returns the effective rule set for a given context, showing how the three layers resolve. For each rule, the response includes which layer it comes from, whether it's overridden by a higher layer, and whether it's overriding lower layers. This gives admins visibility into what is actually enforced, not just what rules exist.

```python
def list_rules(
    identity: Identity,
    layer: str | None = None,
    owner_id: str | None = None,
    scope_filter: str | None = None,
    show_resolution: bool = False,
) -> list[ResolvedRule]
```

**Authorization.** Identity must carry `memory:admin`.

**Audit.** A read-style entry recording the filter parameters and result count.

**Transports.**
- MCP tool: `admin_list_rules`
- BFF route: `GET /api/admin/rules`
- Worker entry point: called by the periodic rule evaluation worker to load the active rule set

### `override_rule`

Sets or clears the `override` flag on an existing rule. Targeted operation for when an admin needs to lock down a rule that was previously overridable, or relax a rule that was previously locked. Cleaner than calling `set_rule` with the full rule definition just to change one flag.

```python
def override_rule(
    identity: Identity,
    rule_id: UUID,
    override: bool,
    reason: str,
) -> Rule
```

**Authorization.** Identity must carry `memory:admin`. Setting `override=True` on a `system`-layer rule additionally requires `memory:admin:system_override`.

**Audit.** An `override_rule` entry recording prior and new states plus the reason.

**Transports.**
- MCP tool: `admin_override_rule`
- BFF route: `PATCH /api/admin/rules/{rule_id}/override`
- Worker entry point: not applicable

### `delete_rule`

Removes a rule from the `curator_rules` table. This is a hard delete -- the rule row is removed. The audit log records the full rule definition before removal so the action is reversible by re-creating the rule.

Deleting a system rule with `override=True` immediately allows lower layers to fill the gap. If secrets scanning is enforced by a system rule and an admin deletes it, organizational and user rules become the only defense. The function should warn when deleting override rules, but ultimately the admin has the authority to make this call.

```python
def delete_rule(
    identity: Identity,
    rule_id: UUID,
    reason: str,
) -> DeletionResult
```

**Authorization.** Identity must carry `memory:admin`.

**Audit.** A `delete_rule` entry with `state_before` containing the full rule body.

**Transports.**
- MCP tool: `admin_delete_rule`
- BFF route: `DELETE /api/admin/rules/{rule_id}`
- Worker entry point: not applicable

## User-Layer Rules: Read-Only for Admins

Admins can view user-layer rules via `list_rules` (with `owner_id` set) but cannot create or edit them through these operations. This is intentional: user-layer rules are part of a user's personal memory configuration, and the user (or their agent) is the authoritative source. If an admin needs to intervene on a problematic user rule, the supported paths are:

1. **Override at a higher layer**: create a system or organizational rule with `override=True` that supersedes the user rule's effect.
2. **Delete the user rule via `delete_rule`**: this is supported across all layers including user-layer, but does not let the admin replace it with their own version.
3. **Lock the user temporarily**: see [agent-user-management.md](agent-user-management.md) — drastic, but appropriate when a user rule is causing immediate harm.

The asymmetry exists because admins editing user-layer rules silently would undermine the user's trust in their own configuration. Override is loud (the user can see the system rule); silent edits are not.

## Relationship to Curation Pipeline

These operations work against the same `curator_rules` table defined in [curator-agent.md](../curator-agent.md). The rule schema, evaluation logic, and layer merging behavior are all defined there. Admin operations add no new evaluation semantics -- they just provide CRUD access to layers that regular users cannot reach.

The rule evaluation order remains the same regardless of whether a rule was created by an admin tool or shipped as a default:

1. Load user rules for the target owner
2. Load organizational rules
3. Load system rules
4. Merge bottom-up (user overrides org overrides system), respecting the `override` flag
5. Filter by trigger and scope
6. Evaluate by tier, then by priority within tier

## Worker Integration

Rules with the `periodic` trigger need a background worker to evaluate them on a schedule -- they are not driven by an inbound write or read. The periodic rule evaluation worker is the natural background counterpart to the admin-managed rules in this document. It loads the active rule set via `list_rules` (called with a service identity granted `memory:admin`), iterates the periodic rules, and applies their actions through other core operations: `quarantine_memory` for `quarantine` actions, `hard_delete_memory` for `block`-style cleanups, and so on.

Because the worker calls the same core authorization and audit code that the MCP and BFF transports call, periodic rule enforcement is indistinguishable from operator-initiated enforcement in the audit log except by `actor_type=service`. There is no parallel "worker rules engine" to keep in sync with the operator-facing engine; there is one engine, with multiple callers.

## Scenarios

**Responding to a new threat pattern.** A new credential format starts appearing in memories (e.g., a SaaS vendor changes their API key format). The admin creates a system-layer regex rule to quarantine memories matching the new pattern. Because it's a system rule with `override=true`, it takes effect immediately across all users and organizations, and no user can weaken it.

**Adjusting organizational policy.** An organization decides that memories mentioning customer names should be flagged for review. The admin creates an organizational-layer regex rule with action `flag`. Users in that organization see their memories flagged but not blocked -- they can still write, but the flag triggers a review workflow. Individual users cannot override this rule if it's marked with `override=true`, but they can add their own stricter rules (e.g., blocking instead of just flagging).

**Emergency override.** A user has adjusted their dedup threshold to 0.99, effectively disabling duplicate detection. The admin discovers this is causing memory sprawl that affects system performance. The admin creates a system-layer embedding rule with `override=true` that enforces a maximum dedup threshold of 0.95. The user's 0.99 threshold is now overridden.

## Open Questions

- **Rule versioning**: Should rule changes be versioned like memories are (with `isCurrent`, `previous_version_id`, version history)? This would allow rolling back rule changes and auditing the evolution of the rule set over time. The tradeoff is additional schema complexity for a table that changes infrequently.

- **Rule testing / dry run**: Should admins be able to "dry run" a rule against existing memories before enabling it? This would show which memories would be affected (flagged, quarantined, blocked) without actually taking action. Useful for estimating impact before deploying a new regex pattern. Could be implemented as a separate core operation (`test_rule`) or as a flag on `set_rule`. Either way it lives in the core and is exposed by every transport.

- **Notification**: Should users be notified when an admin rule affects their writes? If a new system rule starts quarantining a user's memories, the user sees "write blocked" errors without understanding why. A notification mechanism (even a simple "your write was affected by system rule X" in the error response) would improve the experience. The curation feedback in `write_memory` responses is the natural place for this -- the `blocked` response could include the rule name and layer.

- **Rule conflict detection**: When an admin creates a rule that overlaps with an existing rule at the same layer (same trigger, same tier, overlapping scope), should the system warn about potential conflicts? Two regex rules at the system layer with overlapping patterns could produce confusing behavior depending on priority ordering.
