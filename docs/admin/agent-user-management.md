# Agent and User Management

> Status: Skeleton -- needs design work before implementation

## Problem

Admins need to lock and unlock agents and users in response to security incidents, compliance requirements, or operational needs. A compromised API key needs its agent locked immediately. An agent behaving erratically -- writing garbage memories, flooding search, or violating scope boundaries -- needs to be stopped before it causes more damage. A user being offboarded needs all their agents suspended and their access revoked.

These operations must be fast (seconds, not minutes), auditable (who locked whom and why), and reversible (an accidental lock shouldn't require a database intervention to undo).

## Operations

Each operation below is a function in the core admin library at `src/core/admin/operations.py`. Authorization is enforced inside the function against the supplied `Identity`. Audit entries are written by the core. The Transports subsection on each operation lists the wrappers that currently expose it.

### `lock_agent`

Revokes an agent's active session and blocks new session creation. After locking, the agent cannot read or write memories. Any in-flight requests complete normally (we don't kill TCP connections), but subsequent requests are rejected with an authorization error.

The lock is implemented by adding the agent's identity to a lock table. The authorization layer checks this table before permitting any operation. This is separate from JWT validation -- a locked agent's JWT may still be cryptographically valid, but the authorization check rejects it.

```python
def lock_agent(
    identity: Identity,
    agent_id: str,
    reason: str,
    incident_reference: str | None = None,
) -> LockResult
```

**Authorization.** Identity must carry `memory:admin`.

**Audit.** A `lock_agent` entry is written including target agent id, reason, incident reference, and the list of sessions terminated as a side effect.

**Transports.**
- MCP tool: `admin_lock_agent`
- BFF route: `POST /api/admin/agents/{agent_id}/lock`
- Worker entry point: callable from a behavioral-anomaly worker that auto-locks on threshold breach

### `unlock_agent`

Reverses a lock. The agent can create new sessions and resume normal operations. Does not restore any previously active session -- the agent must re-authenticate.

```python
def unlock_agent(
    identity: Identity,
    agent_id: str,
    reason: str,
) -> UnlockResult
```

**Authorization.** Identity must carry `memory:admin`.

**Audit.** An `unlock_agent` entry is written.

**Transports.**
- MCP tool: `admin_unlock_agent`
- BFF route: `POST /api/admin/agents/{agent_id}/unlock`
- Worker entry point: not applicable (always operator-initiated)

### `lock_user`

Suspends all agents for a user. Every agent bound to this user identity is locked (equivalent to calling `lock_agent` for each one), and new session creation is blocked for any agent presenting this user's identity. The user's memories remain intact but are inaccessible until the user is unlocked.

```python
def lock_user(
    identity: Identity,
    user_id: str,
    reason: str,
    incident_reference: str | None = None,
) -> LockResult
```

**Authorization.** Identity must carry `memory:admin`.

**Audit.** A `lock_user` entry is written, plus a `lock_agent` entry per cascaded agent lock.

**Transports.**
- MCP tool: `admin_lock_user`
- BFF route: `POST /api/admin/users/{user_id}/lock`
- Worker entry point: callable from an offboarding worker that consumes HR system events

### `unlock_user`

Reverses a user lock. All the user's agents are unlocked and can create new sessions.

```python
def unlock_user(
    identity: Identity,
    user_id: str,
    reason: str,
) -> UnlockResult
```

**Authorization.** Identity must carry `memory:admin`.

**Audit.** An `unlock_user` entry plus per-agent `unlock_agent` entries.

**Transports.**
- MCP tool: `admin_unlock_user`
- BFF route: `POST /api/admin/users/{user_id}/unlock`
- Worker entry point: not applicable

### `list_sessions`

Returns active sessions with identity, scope, creation time, and last activity timestamp. Provides visibility into who is connected and what they're doing, which is essential context during incident response.

```python
def list_sessions(
    identity: Identity,
    user_id: str | None = None,
    agent_id: str | None = None,
    scope: str | None = None,
    max_results: int = 50,
) -> list[SessionInfo]
```

**Authorization.** Identity must carry `memory:admin`.

**Audit.** A read-style audit entry recording the filter parameters and result count. Result content is not stored.

**Transports.**
- MCP tool: `admin_list_sessions`
- BFF route: `GET /api/admin/sessions`
- Worker entry point: called by the stale-session reaper to enumerate candidates for revocation

### `revoke_session`

Terminates a specific session immediately. The session's identity must re-authenticate to continue. Use this for surgical intervention when locking the entire agent is too broad -- for example, revoking a session created with a leaked API key while allowing the agent to re-authenticate with a rotated key.

```python
def revoke_session(
    identity: Identity,
    session_id: str,
    reason: str,
) -> RevocationResult
```

**Authorization.** Identity must carry `memory:admin`.

**Audit.** A `revoke_session` entry recording the target session id, the affected identity, and the reason.

**Transports.**
- MCP tool: `admin_revoke_session`
- BFF route: `DELETE /api/admin/sessions/{session_id}`
- Worker entry point: called by the stale-session reaper for sessions exceeding idle thresholds

## Worker Integration

`list_sessions` and `revoke_session` have a natural background-worker counterpart: a stale-session reaper that periodically enumerates active sessions, identifies those exceeding idle or maximum-age thresholds, and revokes them. The worker is a thin wrapper that constructs a service identity (granted `memory:admin` for this purpose) and calls the same core functions the MCP and BFF transports call. The audit log records reaper actions with `actor_type=service`, distinguishing them from operator-initiated revocations while keeping the entries in a single uniform stream.

The same pattern applies to behavioral-anomaly workers calling `lock_agent` and offboarding workers calling `lock_user`. None of these require a separate code path -- they all funnel through the core.

## Relationship to Auth Architecture

Lock and unlock operations interact with the JWT lifecycle defined in [governance.md](../governance.md). When an agent is locked:

1. The agent's identity is added to the lock table (checked on every request).
2. Any refresh tokens for the agent are invalidated, preventing JWT renewal.
3. Existing JWTs remain cryptographically valid but are rejected by the authorization check. Since JWTs have short TTLs (5-15 minutes), this means a locked agent's existing tokens expire naturally and cannot be renewed. The lock table check provides immediate enforcement without waiting for expiry.

This two-layer approach (lock table for immediate effect, refresh token invalidation for sustained effect) ensures that locking is both fast and durable.

## Audit

All lock/unlock operations are logged to the `audit_log` table with full detail:

| Field | Content |
|-------|---------|
| `operation` | `lock_agent`, `unlock_agent`, `lock_user`, `unlock_user`, `revoke_session` |
| `actor_id` | The admin who performed the action |
| `memory_id` | null (these operations target identities, not memories) |
| `request_context` | Target identity, reason, incident reference, list of affected sessions |

## Open Questions

- **Should locking cascade?** When a user is locked, the current design locks all their agents explicitly. An alternative is to check the user lock at the agent level -- if the user is locked, all their agents are implicitly locked. The explicit approach is simpler to reason about and audit; the implicit approach handles new agents created between the lock and the check.

- **Grace period for lock operations?** Should an agent receive a "you are being locked" signal before cutoff, giving it a chance to complete in-progress work cleanly? Or is immediate cutoff the right default, with graceful shutdown as an optional parameter? For security incidents, immediate cutoff is clearly correct. For operational reasons (agent misbehaving but not malicious), a grace period might reduce collateral damage.

- **How does this interact with Kubernetes service account agents?** Agents that authenticate via token exchange from a Kubernetes service account token have their identity tied to the K8s service account, not a MemoryHub API key. Locking such an agent requires either locking the MemoryHub identity (which the token exchange maps to) or coordinating with Kubernetes to disable the service account. The former is simpler and doesn't require cross-system coordination.

- **User offboarding workflow**: When a user leaves the organization, what happens to their memories? Options include: delete all memories (clean but loses knowledge), transfer ownership to a designated successor (preserves knowledge but raises attribution questions), or archive memories as read-only under a system identity (preserves knowledge without attribution to an active user). This likely needs a dedicated design rather than being folded into the lock/unlock mechanism.
