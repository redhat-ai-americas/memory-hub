# Research: FastMCP 3 Push Notifications for Swarm Broadcast

**Status:** Investigated 2026-04-07 against the FastMCP 3 source at `/Users/wjackson/Developer/MCP/fastmcp`. Core findings are confirmed against code. Two items still require in-cluster verification before #62 implementation can begin.

**Feeds into:** [`../design.md`](../design.md) §Real-Time Push (Pattern E), issue #62.

## Question

Can memory-hub implement server-initiated push notifications on top of FastMCP 3 so that when one agent writes a memory, other connected agents receive a notification without polling? And if so, what does the implementation need to add on top of FastMCP's primitives?

The use case is the active-swarm scenario where one agent's write is immediately relevant to other connected agents (the "needle-in-haystack" project shape described in `../design.md` §Session Focus and Retrieval Biasing). Pull-only patterns have a latency floor — the next-pull interval — which is too slow for active coordination.

## Findings

### 1. Streamable-HTTP transport supports bidirectional message flow

memory-hub already uses FastMCP 3's streamable-http transport. This transport supports server-initiated messages (not just request-response), so **no transport change is needed**. Server-push works over the existing MCP endpoint at `https://memory-hub-mcp-.../mcp/`.

This was the first thing to verify. If streamable-http had been request-response only, Pattern E would have required a transport switch (probably to WebSocket) which would be a significant re-architecture. It isn't.

### 2. The relevant MCP primitive is `ResourceUpdatedNotification`

MCP's `notifications/resources/updated` notification is the spec-native way to signal that a resource has changed. In FastMCP 3, this is sent from within a tool via:

```python
from mcp.types import ResourceUpdatedNotification

await ctx.send_notification(
    ResourceUpdatedNotification(
        params={"uri": f"memoryhub://memory/{memory_id}"}
    )
)
```

Per the MCP spec, the notification carries only the resource URI. Clients are expected to refetch via `resources/read` (or memory-hub's `read_memory` tool) to get the actual content.

**This is spec-compliant but adds a round-trip** on every notification — the subscriber gets the URI, then has to call back in. Whether that round-trip is acceptable is tracked as Q6 in `../open-questions.md`.

### 3. `ctx.send_notification` only reaches the calling session by default

This is the subtle point. `ctx.send_notification` is per-session: it sends the notification down the streamable-http channel of the session that invoked the tool. For memory-hub's use case — broadcasting to *other* connected agents — we need to reach every session *except* (or including) the caller.

FastMCP 3 has infrastructure for this already, in a subsystem that currently powers task-status notifications.

### 4. FastMCP's distributed notification queue

At `fastmcp/server/tasks/notifications.py`, FastMCP 3 exposes:

```python
async def push_notification(
    session_id: str,
    notification: Notification,
    docket: str,
) -> None:
    ...
```

This function LPUSHes the notification onto a per-session queue (`docket:<session_id>` in the backing cache). A subscriber loop running in each session's task group BRPOPs from its queue and delivers the notification to the client.

This subsystem was built for task status updates (e.g., "your submitted task finished") but the primitive is general-purpose — any server code that can enumerate session IDs can broadcast to them.

**memory-hub can reuse this directly.** The broadcast helper becomes a thin wrapper:

```python
async def broadcast_to_sessions(
    notification: Notification,
    session_ids: Iterable[str],
    docket: str = "memoryhub",
) -> None:
    for sid in session_ids:
        await push_notification(sid, notification, docket)
```

Fanout cost is O(N) per write, which is fine up to ~100 agents. Beyond that, see Q9.

### 5. The queue uses Valkey, not Redis

FastMCP 3's notification queue is backed by Valkey (the memory-hub cluster already runs Valkey as its standard distributed cache). Valkey is API-compatible with Redis at the protocol level, so FastMCP's Redis client code works unchanged — **no client library change is needed** on memory-hub's side.

This matters because it means Pattern E doesn't introduce a new infrastructure dependency. The Valkey instance memory-hub already runs for rate-limiting and session state is the same instance FastMCP uses for notification queueing.

## What Memory-Hub Needs to Add

Four pieces on top of FastMCP's primitives:

### a. Agent session registry

A Valkey set (e.g., `memoryhub:active_sessions`) populated when an agent calls `register_session` and torn down via session-close hooks. Without this, there's no way to enumerate "all connected agents" for broadcast.

Implementation sketch:

```python
# in register_session tool
await valkey.sadd("memoryhub:active_sessions", session_id)

# in a session-close hook (FastMCP exposes this)
await valkey.srem("memoryhub:active_sessions", session_id)
```

**Open item:** FastMCP 3's session-close hook surface needs verification. If there's no clean hook, the registry entries will leak on ungraceful disconnect and need a TTL-based cleanup.

### b. Broadcast helper

Wraps `push_notification` over the session registry. See the sketch in finding 4 above. This is a 10-line function.

### c. Hooks in mutating tools

`write_memory`, `update_memory`, and `delete_memory` need post-persistence broadcast calls. These are the only tools where memory state changes, so they are the only tools that need to notify subscribers. Read tools don't broadcast.

Sketch for `write_memory` (after the existing DB commit):

```python
notification = ResourceUpdatedNotification(
    params={"uri": f"memoryhub://memory/{memory.id}"}
)
active_sessions = await valkey.smembers("memoryhub:active_sessions")
# Optionally filter by session focus vector -- see Layer 2 coupling below
await broadcast_to_sessions(notification, active_sessions)
```

### d. Subscriber lifecycle for pure-listener agents — **needs verification**

This is the most important open item. FastMCP 3 currently starts notification subscribers when a task is submitted. Agents that don't submit tasks but want to listen for broadcasts need a subscriber loop started at session-registration time.

**This may not exist in FastMCP 3 today.** If it doesn't, memory-hub has two choices:

1. **Upstream fix.** File an issue against FastMCP 3 requesting a session-registration subscriber hook, and block #62 on that landing. Slower but cleaner.
2. **Downstream workaround.** memory-hub's `register_session` tool manually kicks off a subscriber loop using FastMCP's lower-level primitives. Faster but creates a maintenance burden.

**Action before #62 implementation:** A small spike against the FastMCP 3 source to find the task-submission code path, trace where the subscriber loop starts, and determine whether it can be hoisted to session-registration without upstream changes. The specific files to read:

- `fastmcp/server/tasks/tasks.py` — task submission entry points
- `fastmcp/server/tasks/notifications.py` — push_notification implementation
- `fastmcp/server/session.py` or equivalent — session lifecycle hooks

This is tracked as Q7 in `../open-questions.md`.

## Spec Compliance vs. Latency

`ResourceUpdatedNotification` carries only the URI, which forces a round-trip: subscriber gets the URI, calls `read_memory` to fetch content. For a small-fanout low-latency deployment this is fine. For a large swarm it adds latency and load.

MCP allows custom notification methods under the pattern `notifications/$vendor/$method`. Memory-hub could define:

```
notifications/memoryhub/memory_written
```

carrying the full memory record inline. Non-spec but valid. Trade-off: spec compliance and small notifications vs. latency and round-trip count.

**Recommendation:** Ship URI-only as the default (`push_payload: uri_only`). Add `push_payload: full_content` as a YAML opt-in that switches to the custom notification method. Let real usage decide the default at scale.

This is tracked as Q6 in `../open-questions.md`.

## Reliable Queue vs. Pub/Sub

FastMCP's existing mechanism is Valkey LPUSH/BRPOP with retry — reliable, but O(N) per write (we push once per session). Valkey pub/sub is fire-and-forget and scales better via Valkey-side fanout, but disconnected agents miss notifications and have to catch up via a search-on-reconnect.

For memory-hub's use case:
- **Reliable queue** is correct when the notification matters enough that a disconnected agent should catch up. Example: a curator agent that must eventually see every memory write for audit.
- **Pub/sub** is correct when the notification is transient. Example: a "another agent is typing" status that's meaningless after the typist finishes.

Memory-hub's first real use case is memory writes, which mostly fall into the first category. **Default to reliable queue.** The `push_transport` YAML knob lets individual deployments switch to pub/sub if their use case warrants it.

This is tracked as Q8 in `../open-questions.md`.

## Coupling with Session Focus (Layer 2)

Pattern E reuses the session focus vector from [`two-vector-retrieval.md`](two-vector-retrieval.md) to pre-filter broadcasts. An agent that declared `focus="auth"` should not receive notifications about UI writes.

Concretely: when `write_memory` computes the new memory's embedding, it also computes cosine similarity against each active session's focus vector. If the similarity is below the session's `push_filter_weight` threshold, skip the broadcast to that session.

This means:

1. The session focus vector must be **stored in a place the broadcast code can read** (not just in the retrieval code path). Valkey is the natural choice — same lifecycle as the session registry.
2. The embedding model used for session vectors must match the embedding model used for memory vectors. Document the contract in `../../mcp-server.md`.
3. The push-side filter knob (`push_filter_weight`) and the pull-side bias knob (`session_focus_weight`) are conceptually the same dial but should be **separately configurable**, since users may want strong push filtering with looser pull biasing or vice versa.

**This is a hard prerequisite coupling: #62 cannot ship without #58 having established the session vector mechanism.** Design and review the two issues together.

## In-Cluster Verification Required Before Implementation

Two items must be verified against the running FastMCP 3 deployment before committing to #62:

1. **Subscriber lifecycle hook** (Q7). Can we start a subscriber loop at session-registration time, or do we need upstream work?
2. **Valkey backend** (lower priority). Verify that FastMCP 3's notification queue actually runs against the same Valkey instance memory-hub uses, not a separately-configured one. Shouldn't be an issue — they read from the same connection string — but worth checking the config path.

Both are small spikes. Do them first in the #62 session.

## References

- FastMCP 3 source: `/Users/wjackson/Developer/MCP/fastmcp`
- MCP spec on notifications: https://spec.modelcontextprotocol.io/specification/basic/notifications/
- `../design.md` §Real-Time Push (Pattern E) — the design this research supports
- `../open-questions.md` Q6, Q7, Q8, Q9 — unresolved items this research surfaced
- Issue #62 — implementation tracking
