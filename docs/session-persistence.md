# Session Persistence Across MCP Server Restarts

How a MemoryHub MCP server pod restart affects connected agents -- and what we can do to make restarts non-disruptive for the broader fleet.

**Status: skeleton.** Captures the problem statement, the surface area, and the rough fork. The detailed design lands when the umbrella issue this doc references picks up the work.

## The problem

When the `memory-hub-mcp` pod restarts (deploy, autoscale, OOM kill, node drain), every connected agent loses its in-flight MCP session. The next request from a client carrying the old session id gets `"Session not found"` from the FastMCP streamable-http transport. Affected agents must re-issue `initialize` and call `register_session` again before any tool will work.

For the agents we own (Claude Code harness, the demo fleet, the ones we launch ourselves), this is annoying but recoverable -- the operator restarts the conversation or the client harness reconnects. For the agents we **don't** own -- third-party LibreChat instances, kagenti swarms, customer-deployed agents using the SDK, anything embedding `mcp::memoryhub` via LlamaStack -- we don't get to ask them to reconnect. They're connected, they go quiet, and the only signal they have is "the MCP server stopped responding."

This is a real production blocker for the enterprise scenario:

> "We have N hundred agents connected and doing work. We need to ship an mcp-server update. Right now we'd have to restart all the agents."

We need restarts to be non-disruptive for clients -- or, at minimum, to be transparently recoverable on the client side without manual operator intervention.

## What gets lost on restart

The pod's in-memory state spans several layers, each with different ownership and different recovery strategy:

1. **FastMCP streamable-http transport-level session id.** Owned by FastMCP 3 upstream (`fastmcp.server.http.streamable`). Session id is allocated on `initialize`, tracked in an in-memory dict keyed by session id, and looked up on every subsequent JSON-RPC request. We do not own session id allocation or storage. Pod restart wipes this dict; the next request from a client with the old session id gets `Session not found` at the transport layer, **before** any of our code runs.

2. **MemoryHub application-level session map (`register_session`).** Owned by us at `memoryhub_core/auth/session_store.py` (single in-process dict keyed by session id; populated on `register_session`, consumed by `get_claims_from_context()` as the session-fallback path when JWT extraction fails). Pod restart wipes this dict; the next tool call from a previously-registered client falls through to the JWT path or fails authorization if no JWT is present.

3. **Pattern E push subscriber loops (#62).** The `memoryhub:active_sessions` set in Valkey survives restarts -- that part is already persistent. The actual subscriber loop (the Python coroutine that tails `memoryhub:broadcast:<session_id>` and dispatches notifications) runs in the pod process and dies with it. After restart, the new pod has zero subscribers running until each client re-issues `register_session` to spin a new subscriber.

4. **JWT verification context.** The JWT itself is fine -- it's a token, not state. JWKS caching and `JWTVerifier` configuration both rebuild from env vars at startup. Nothing to persist here.

The four layers don't all need the same fix. Layer 4 is fine. Layers 2 and 3 we own and can persist to Valkey. Layer 1 is upstream FastMCP and is the hardest piece.

## Forks the design will need to resolve

### Fork A -- Application-level session persistence (Layers 2 + 3)

Move the `register_session` map from in-process to Valkey. Every `register_session` call writes a hash like `memoryhub:app_sessions:<session_id>` carrying user_id, scopes, tenant_id, expiry. `get_claims_from_context()` reads from Valkey instead of the in-process dict on the session-fallback path. Push subscriber loops re-spawn lazily on first request after restart by reading the active-sessions set.

Cost: ~1 round-trip per tool call against Valkey (already on the path for #61 / #62). The active-sessions set is already in Valkey (#62) so the push side is a small lift. Subscriber lifecycle becomes self-healing.

Open questions:
- Eviction strategy for stale `app_sessions` entries (TTL? explicit on disconnect? heartbeat?).
- What happens when JWT and Valkey disagree (JWT says scope X, Valkey says scope Y -- which wins, and how does that interact with the upgrade path for #86's per-conversation session id).
- Subscriber re-spawn ordering: the new pod can't proactively subscribe to every active session at startup (could be hundreds); it has to lazily spawn on the first request from each. What's the per-session warm-up cost?

### Fork B -- Transport-level session id persistence (Layer 1)

This requires either:

**B1.** **Stateless mode for streamable-http.** FastMCP 3 may already support a stateless session model where every request carries enough identity to reconstruct the session on the server side without server-allocated session ids. Needs upstream investigation. If supported, we move to it and Layer 1 disappears.

**B2.** **Persist FastMCP transport state to Valkey.** The session id dict and any per-session transport state (subscriber registrations, mounted resources) get serialized to Valkey. Requires either upstream FastMCP changes or a fork. High blast radius -- transport-layer code is shared across every FastMCP server in the wild.

**B3.** **Make register_session a no-op when JWT is present.** The cleanest variant of Fork A taken to its conclusion: every JWT-authenticated request carries identity per-request, so the application has no reason to maintain session state at all. Push subscriber lifecycle still needs handling, but we can drive it from the JWT sub claim (or whatever #86 lands on for session id) instead of from a `register_session` round-trip. This eliminates Layer 2 entirely. Layer 1 still has the upstream FastMCP problem, but if we're stateless on the application side, a transport-layer reconnect is invisible to the user as long as the client retries with the same JWT. The transport-layer session id becomes a per-connection HTTP detail rather than a logical user-session identifier.

**B4.** **Document client retry contract.** The narrowest option: don't fix the server, fix the client expectation. Document that any client connecting to MemoryHub MUST handle `Session not found` by re-initializing and re-issuing the original request, with a single retry. Update the SDK to do this transparently. Affected clients we don't control (LibreChat, kagenti, customer-deployed) are responsible for following the contract. Cheapest in code; most fragile in practice because we're trusting third parties to read our contract doc.

### Fork C -- The hybrid most likely to ship

The realistic path is probably a combination:

- **Fork A's Valkey persistence for application state** (we own this, it's straightforward, it composes with #61/#62 infrastructure)
- **Fork B3 (no-op register_session under JWT)** to eliminate the Layer 2 problem entirely
- **Fork B4 (client retry contract) in the SDK** to handle the residual Layer 1 problem transparently for clients using our SDK
- An open question on **upstream FastMCP** for whether B1 or B2 is feasible -- this is the long pole and we should not block on it

The umbrella issue should resolve which combination ships first and which gets deferred.

## Composition with related work

- **#86** (per-conversation session id, currently noted as a swarm-blocker) interacts directly with this. The persistence strategy needs to survive the session id model change. Coordinate with #86's implementation -- ideally land them together or land #86 first.
- **#61 / #62** Valkey infrastructure (`memoryhub:sessions:<session_id>`, `memoryhub:active_sessions`) is the substrate this work builds on. The new `memoryhub:app_sessions:<session_id>` key prefix from Fork A should fit alongside.
- **#34** (OAuth 2.1 token exchange) and **#74-#81** (OpenShift OAuth broker) widen the JWT story -- the more JWT-driven everything is, the smaller Layer 2 gets.
- **#82** (LibreChat as second MCP client) is one of the third-party clients this is meant to protect. Worth coordinating the client retry contract with whatever LibreChat needs.
- **`docs/agent-memory-ergonomics/design.md`** is concept-closed; this is genuinely a new concept, not an extension.

## Out of scope for this doc

- Multi-pod / horizontal-scale MCP server (separate concern; affects how Valkey state is sharded, but not what we persist)
- Stateful session migration during rolling deploys (related but distinct -- this doc is about pod restart, not zero-downtime deploys)
- Operator-side rolling deploy strategy (the operator can adopt whatever this doc lands on)

## Related

- Retro `2026-04-08_agent-memory-ergonomics-concept-close/RETRO.md` -- the experience of losing the MCP session mid-conversation when deploying mcp-server during the #88 work was the trigger for this issue.
- `docs/agent-memory-ergonomics/design.md` -- precedent for "stateless where possible" composition (Layer 2 of the agent-memory-ergonomics concept made focus stateless per-call exactly to avoid this class of problem).
- Issue #86 -- session_id model upgrade that this work must compose with.
