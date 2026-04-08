# Research: FastMCP 3 Push Notifications for Swarm Broadcast

**Status:** Investigated 2026-04-07 against the FastMCP 3 source at `/Users/wjackson/Developer/MCP/fastmcp`. Core findings confirmed against code; the two in-cluster verification items were resolved during the #62 implementation session on 2026-04-08 (see [Implementation Notes](#implementation-notes-2026-04-08) at the end of this file). #62 shipped in a different shape than this research originally proposed — memory-hub built its own subscriber pipeline rather than reusing FastMCP's `push_notification` + `notification_subscriber_loop`. Read the implementation notes section before relying on any of the "What memory-hub needs to add" sketches below; they are preserved for historical context but parts of them are wrong.

**Feeds into:** [`../../docs/agent-memory-ergonomics/design.md`](../../docs/agent-memory-ergonomics/design.md) §Real-Time Push (Pattern E), issue #62.

## Question

Can memory-hub implement server-initiated push notifications on top of FastMCP 3 so that when one agent writes a memory, other connected agents receive a notification without polling? And if so, what does the implementation need to add on top of FastMCP's primitives?

The use case is the active-swarm scenario where one agent's write is immediately relevant to other connected agents (the "needle-in-haystack" project shape described in `../../docs/agent-memory-ergonomics/design.md` §Session Focus and Retrieval Biasing). Pull-only patterns have a latency floor — the next-pull interval — which is too slow for active coordination.

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

**This is spec-compliant but adds a round-trip** on every notification — the subscriber gets the URI, then has to call back in. Whether that round-trip is acceptable is tracked as Q6 in `../../docs/agent-memory-ergonomics/open-questions.md`.

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

This is tracked as Q7 in `../../docs/agent-memory-ergonomics/open-questions.md`.

## Spec Compliance vs. Latency

`ResourceUpdatedNotification` carries only the URI, which forces a round-trip: subscriber gets the URI, calls `read_memory` to fetch content. For a small-fanout low-latency deployment this is fine. For a large swarm it adds latency and load.

MCP allows custom notification methods under the pattern `notifications/$vendor/$method`. Memory-hub could define:

```
notifications/memoryhub/memory_written
```

carrying the full memory record inline. Non-spec but valid. Trade-off: spec compliance and small notifications vs. latency and round-trip count.

**Recommendation:** Ship URI-only as the default (`push_payload: uri_only`). Add `push_payload: full_content` as a YAML opt-in that switches to the custom notification method. Let real usage decide the default at scale.

This is tracked as Q6 in `../../docs/agent-memory-ergonomics/open-questions.md`.

## Reliable Queue vs. Pub/Sub

FastMCP's existing mechanism is Valkey LPUSH/BRPOP with retry — reliable, but O(N) per write (we push once per session). Valkey pub/sub is fire-and-forget and scales better via Valkey-side fanout, but disconnected agents miss notifications and have to catch up via a search-on-reconnect.

For memory-hub's use case:
- **Reliable queue** is correct when the notification matters enough that a disconnected agent should catch up. Example: a curator agent that must eventually see every memory write for audit.
- **Pub/sub** is correct when the notification is transient. Example: a "another agent is typing" status that's meaningless after the typist finishes.

Memory-hub's first real use case is memory writes, which mostly fall into the first category. **Default to reliable queue.** The `push_transport` YAML knob lets individual deployments switch to pub/sub if their use case warrants it.

This is tracked as Q8 in `../../docs/agent-memory-ergonomics/open-questions.md`.

## Coupling with Session Focus (Layer 2)

Pattern E reuses the session focus vector from [`two-vector-retrieval.md`](two-vector-retrieval.md) to pre-filter broadcasts. An agent that declared `focus="auth"` should not receive notifications about UI writes.

Concretely: when `write_memory` computes the new memory's embedding, it also computes cosine similarity against each active session's focus vector. If the similarity is below the session's `push_filter_weight` threshold, skip the broadcast to that session.

This means:

1. The session focus vector must be **stored in a place the broadcast code can read** (not just in the retrieval code path). Valkey is the natural choice — same lifecycle as the session registry.
2. The embedding model used for session vectors must match the embedding model used for memory vectors. Document the contract in `../../docs/mcp-server.md`.
3. The push-side filter knob (`push_filter_weight`) and the pull-side bias knob (`session_focus_weight`) are conceptually the same dial but should be **separately configurable**, since users may want strong push filtering with looser pull biasing or vice versa.

**This is a hard prerequisite coupling: #62 cannot ship without #58 having established the session vector mechanism.** Design and review the two issues together.

## In-Cluster Verification Required Before Implementation

Two items must be verified against the running FastMCP 3 deployment before committing to #62:

1. **Subscriber lifecycle hook** (Q7). Can we start a subscriber loop at session-registration time, or do we need upstream work?
2. **Valkey backend** (lower priority). Verify that FastMCP 3's notification queue actually runs against the same Valkey instance memory-hub uses, not a separately-configured one. Shouldn't be an issue — they read from the same connection string — but worth checking the config path.

Both are small spikes. Do them first in the #62 session.

## Implementation Notes 2026-04-08

These notes were added after #62 actually shipped. They correct two wrong assumptions in the original research and document how the implementation diverged from the sketches above.

### Q7 (subscriber lifecycle) resolved cleanly — but Q7 wasn't the real blocker

The Phase 0 spike against FastMCP 3.2.0 found that `ensure_subscriber_running(session_id, session, docket, fastmcp)` at `fastmcp/server/tasks/notifications.py:238-275` is **idempotent** and decoupled from task submission. The function's only existing caller is the task-submission code path in `handlers.py:194-209`, but the function itself doesn't depend on a submitted task. The original research's worry that "FastMCP currently starts notification subscribers when a task is submitted" conflated *the only existing caller* with *the only possible caller*. Memory-hub can call `ensure_subscriber_running` directly from `register_session` for pure-listener agents. Cleanup uses `ctx.session._exit_stack.push_async_callback(...)` calling `stop_subscriber(session_id)`, the same pattern FastMCP uses internally. **No upstream FastMCP work was required.**

### The actual blocker: `_send_mcp_notification` method whitelist

While reading the source carefully during the spike, a separate restriction surfaced that the original research missed. `_send_mcp_notification` (the helper called by `notification_subscriber_loop` to forward messages from the BRPOP loop to `session.send_notification`) hard-codes a method whitelist:

```python
method = notification_dict.get("method", "notifications/tasks/status")
if method != "notifications/tasks/status":
    raise ValueError(f"Unsupported notification method for subscriber: {method}")
```

This means `push_notification` + `notification_subscriber_loop` is single-purpose for task-status events. Any attempt to pipe `notifications/resources/updated` (or memory-hub's custom `notifications/memoryhub/memory_written`) through them raises `ValueError` and the subscriber drops the message. The original research's recommendation to "reuse FastMCP's distributed notification queue directly" was wrong. The queue (LPUSH/BRPOP) is reusable; the subscriber/dispatcher is not.

### What memory-hub actually shipped

A parallel pipeline that clones FastMCP's lifecycle pattern but is method-agnostic:

1. **`memoryhub_core/services/valkey_client.py`** gained `register_active_session`, `deregister_active_session`, `read_active_sessions`, `read_session_focus_vector`, `push_broadcast_message`, and `pop_broadcast_message`. Two new key prefixes: `memoryhub:active_sessions` (set, populated from `register_session`) and `memoryhub:broadcast:<session_id>` (per-session reliable queue, 300s TTL).
2. **`memoryhub_core/services/push_subscriber.py`** ships `memoryhub_subscriber_loop`, `ensure_memoryhub_subscriber_running`, and `stop_memoryhub_subscriber`. The loop reads its own queue, reconstructs a `ServerNotification(ResourceUpdatedNotification(...))`, and forwards via `session.send_notification`. Module-level `_active_subscribers: dict[str, tuple[asyncio.Task, weakref.ref[ServerSession]]]` mirrors FastMCP's own registry shape.
3. **`memoryhub_core/services/push_broadcast.py`** ships `broadcast_to_sessions(notification, memory_embedding, push_filter_weight, exclude_session_id)`. It SMEMBERSes `memoryhub:active_sessions`, reads each session's focus vector from the #61 hash (no re-embedding), cosine-filters, and LPUSHes envelopes onto the per-session broadcast queues. Build helpers `build_uri_only_notification` and `build_full_content_notification` produce the dict shapes that the subscriber loop reconstructs.
4. **`memory-hub-mcp/src/tools/register_session.py`** got a private `_start_push_for_session` helper that runs in both the JWT and API-key auth paths. It SADDs the session_id, calls `ensure_memoryhub_subscriber_running`, and registers an `_exit_stack` cleanup callback that calls `stop_memoryhub_subscriber` + `deregister_active_session` on disconnect. Session-scoped flag prevents duplicate cleanup registration.
5. **`memory-hub-mcp/src/tools/_push_helpers.py`** ships `broadcast_after_write` — the post-commit hook called by `write_memory`, `update_memory`, and `delete_memory`. The fast path returns immediately when the only relevant subscriber is the writer itself, so single-session deployments pay zero embedding cost per write. When other subscribers exist, the helper embeds the new content once and calls `broadcast_to_sessions`.
6. **`sdk/src/memoryhub/client.py`** gained `MemoryHubClient.on_memory_updated(callback)`. It registers callbacks with a `_MemoryHubMessageHandler` (subclass of FastMCP's `MessageHandler`) that overrides `on_resource_updated` and routes `memoryhub://memory/*` URIs to the registered callbacks. Pre-connect callbacks are buffered and replayed at `__aenter__`. The handler is only constructed when `memory_loading.live_subscription` is true in the project config — opt-in by design.

### The full-content receive-side limitation

The custom `notifications/memoryhub/memory_written` method ships server-side via `build_full_content_notification` and the subscriber loop happily forwards it via `session.send_notification`. **However**, the typed Python SDK cannot receive it. The underlying `mcp` library deserializes incoming notifications against `mcp.types.ServerNotification` — a closed Pydantic union with nine pre-defined notification types. Custom `notifications/$vendor/$method` notifications fail deserialization at the JSON-RPC layer before reaching `MessageHandler.dispatch`. They never get to `on_resource_updated` or any other typed hook.

`session.send_notification` works for sending custom methods (it just calls `.model_dump()` on the notification model). What's broken is the *receiving* side of the typed Python SDK. Lifting this requires either:
- An upstream `mcp` library upgrade with an extensible `ServerNotification` union or a fallback path for unknown notification methods, or
- A raw transport-level subscriber in memory-hub that bypasses the typed deserializer and parses notifications directly off the streamable-http stream.

Both are tracked as #62 follow-ups, not blockers. The first real consumer (memory-hub itself, single developer, low fanout) is well-served by URI-only delivery.

### Q8 confirmed in code

The original research recommended reliable queue (LPUSH/BRPOP) over pub/sub as the default, with the caveat that this needed in-cluster verification. Verified against the installed FastMCP 3.2.0: lines 72 and 112 of `notifications.py` use `redis.lpush` and `redis.brpop` respectively, with explicit code comments ("LPUSH/BRPOP for reliable ordered delivery"). Memory-hub's subscriber loop uses the same pattern with the same retry-up-to-3-times semantics (`MAX_DELIVERY_ATTEMPTS = 3`). The `push_transport: pubsub` YAML knob is accepted by the schema but not implemented in v1; it's reserved for future swarm-scale use cases.

## References

- FastMCP 3 source: `/Users/wjackson/Developer/MCP/fastmcp` (reference) and `memory-hub-mcp/.venv/lib/python3.11/site-packages/fastmcp/` (installed 3.2.0; what actually runs)
- MCP spec on notifications: https://spec.modelcontextprotocol.io/specification/basic/notifications/
- `../../docs/agent-memory-ergonomics/design.md` §Real-Time Push (Pattern E) — the design this research supports
- `../../docs/agent-memory-ergonomics/open-questions.md` Q6, Q7, Q8, Q9 — Q6/Q7/Q8 resolved 2026-04-08 with #62; Q9 still open
- Issue #62 — implementation tracking
