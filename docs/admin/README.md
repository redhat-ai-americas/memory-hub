# Admin Capabilities

MemoryHub's admin model follows a single design principle: **every admin operation is a function in a core Python library, and authorization and audit happen inside that function**. The function is the canonical surface. Transports -- MCP tools, FastAPI BFF routes, background workers, a future break-glass CLI -- are thin wrappers that authenticate their caller, build an `Identity` object, and invoke the core function. Because every transport calls the same code, every transport produces identical authorization checks and identical audit log entries.

This is governance-first, transport-agnostic. Admin actions get the same guarantees regardless of how they were invoked: identity-based authorization, scope checks, and immutable audit logging via the existing [governance](../governance.md) infrastructure. The core does not know or care which transport called it.

## Why Multiple Transports

Three concrete reasons admin work cannot live exclusively behind MCP:

1. **Resilience.** Admin must keep working when the MCP server is down. The existing dashboard already talks directly to PostgreSQL through a FastAPI BFF (`memoryhub-ui/backend/`), and that is the right shape for it -- the BFF should not depend on the MCP server being reachable to load a panel or quarantine a memory.
2. **Background processes.** TTL pruning, orphan cleanup, audit log archival, periodic rule evaluation, and stale-session reaping all need authorization and audit but are not agent operations. They need a non-MCP entry point that still funnels through the same governance.
3. **No protocol lock-in.** If MCP evolves or is replaced, the operations themselves do not get rewritten. Only the transport wrapper changes.

## Where the Core Library Lives

The core library lives at `memory-hub-mcp/src/core/admin/` today. This is deliberate: starting it inside the MCP server repo avoids premature extraction. The intent is to extract it as a standalone `memory-hub-core/` package once a second consumer (the BFF) actually exists and the import boundary has been validated by real use.

Rough layout:

```
src/core/admin/
  operations.py        # core functions: hard_delete(identity, ...), quarantine(...), etc.
  authorization.py     # identity-based authz; no JWT-specific code
  audit.py             # writes audit entries; called from operations

src/mcp_tools/admin.py          # thin wrapper: extract identity from JWT, call core
memoryhub-ui/backend/admin.py   # thin wrapper: extract identity from session, call core
src/workers/pruner.py           # thin wrapper: build service identity, call core
```

The core takes an `Identity` object (who is acting) plus operation parameters. Authorization and audit happen inside the core function. Transports never write audit entries directly and never bypass authorization.

## The Admin Agent

An "admin agent" is one specific kind of caller: an agent identity carrying the `memory:admin` scope, invoking admin operations via the MCP transport. It authenticates through the same OAuth 2.1 flow as any other agent (`client_credentials`), the auth service issues a JWT with the admin scope, and the MCP wrapper extracts the identity and calls the core. Admin agents are typically service identities (`identity_type: "service"`).

The admin agent is not the only admin caller. The dashboard's BFF wrapper builds an `Identity` from the operator's OpenShift session and calls the same core functions. A pruning worker builds a `service` identity and calls the same core functions. All three paths produce identical audit log entries differing only in the actor identity recorded.

## Admin Domains

Admin capabilities are organized into three domains, each with its own design document:

**[Content Moderation](content-moderation.md)** covers the incident-response workflow for sensitive data in memories: searching across all owners and scopes, quarantining suspect content, and executing hard deletes when content must be physically removed. The most demanding scenario here is classified data spill response, where soft-delete is insufficient and the audit trail itself must be sanitized.

**[Agent and User Management](agent-user-management.md)** covers locking and unlocking agents and users in response to security incidents, compliance actions, or operational needs. This includes session management -- viewing active sessions, revoking specific sessions, and blocking new session creation for compromised or misbehaving identities.

**[Filter Rule Management](filter-rules.md)** covers admin-level management of curation and filter rules at the system and organizational layers. This is the admin complement to the user-facing `manage_curation(action="set_rule", ...)` tool action -- where users manage their own rules, admins manage the rules that apply across the organization and the system defaults that users cannot override.

## Relationship to Existing Infrastructure

Admin operations build on infrastructure already defined in the project's design documents rather than introducing new mechanisms:

- RBAC enforcement and the `memory:admin` scope are defined in [governance.md](../governance.md). The core authorization module consumes these but does not redefine them.
- The immutable audit trail schema (`audit_log` table) is defined in [governance.md](../governance.md) and [storage-layer.md](../storage-layer.md). The core audit module is the only writer for admin operations.
- The curation rules engine and layer model are defined in [curator-agent.md](../curator-agent.md).
- MCP tool patterns and error handling conventions are defined in [mcp-server.md](../mcp-server.md). These apply to the MCP transport wrapper, not to the core.
- The dashboard BFF that talks directly to PostgreSQL lives at `memoryhub-ui/backend/`. It will gain admin routes that import the core library directly rather than calling MCP.
