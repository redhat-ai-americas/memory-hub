# Identity Model

This folder captures MemoryHub's identity model: how callers are identified, how
their actions are attributed, and how authorization decisions are made.

## Why this exists

The forcing function is a planned 50-agent healthcare demo. Each agent is a
small loop running as a container on the cluster. Each must have its own
identity, write to its own private memory, post findings to a shared project
memory ("hive mind"), and have every action traceable to both the *agent that
performed it* and the *principal on whose behalf it was performed*.

The demo surfaced three things that were either missing or under-modeled in
MemoryHub today:

1. **No notion of "on whose behalf"** — `owner_id` records who a memory belongs
   to, but there is no first-class field for "this autonomous agent acted on
   Dr. Smith's request" vs "this agent acted on its own initiative." For an
   audit-heavy domain like healthcare, that distinction is load-bearing.
2. **Project-scope authorization is unenforced** — `authorize_read` and
   `authorize_write` for project scope return `True` unconditionally
   (`memory-hub-mcp/src/core/authz.py:135,156`). The hive-mind story requires
   real enforcement, not a rubber stamp.
3. **No audit log exists** — not even a stub. The design in `docs/governance.md`
   is solid but unimplemented.

The identity model design captured here is the foundation that the demo work,
the project-membership work, and the eventual audit log all build on.

## Documents in this folder

- **[data-model.md](data-model.md)** — The `owner_id` / `actor_id` /
  `driver_id` triple. Schema additions to `MemoryNode`. Mapping to RFC 8693
  and HL7 FHIR Provenance. Field semantics and defaults.
- **[authorization.md](authorization.md)** — Current RBAC state (with verified
  gaps), the project-membership enforcement work, the intersection
  authorization model as the production target, audit-only-for-the-demo as
  the interim, and the audit-log stub interface.
- **[cli-requirements.md](cli-requirements.md)** — What the agent generation
  CLI needs to produce so the demo harness can spin up the fleet, give each
  agent its identity, and drive agents while propagating `driver_id`.
- **[demo-plan.md](demo-plan.md)** — Healthcare scenario sketch, PHI/HIPAA
  detection patterns required, contradiction-detection demo flow, and the
  audit-stub strategy in demo terms.

## Scope and non-goals

In scope: identity attribution, project-scope enforcement, audit hooks,
demo-harness driver injection, the data model that lets all of those work.

Out of scope for the demo (tracked as future work, see linked issues):

- Phase 2 OAuth 2.0 token exchange / SPIFFE-based identity (`../../planning/kagenti-integration/`)
- Tenant isolation (the demo runs in a single tenant)
- Full audit log persistence (stub interface only; persistence is future work)
- Intersection authorization enforcement (data model supports it; demo runs
  in audit-only mode)
- `driver_id` redaction on read (filed as future work)

## Status

All docs in this folder are draft and authored together with their
corresponding GitHub issues. Each issue's `## Design reference` section points
back here. Updates to the design happen in this folder first, then propagate
to the issue body if scope changes.
