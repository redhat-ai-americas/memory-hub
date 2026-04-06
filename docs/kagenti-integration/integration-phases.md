# Kagenti Integration Phases

This document defines the phased rollout plan for integrating MemoryHub with Kagenti. Each phase is independently deliverable and builds on the previous. See `overview.md` for context on why this integration exists and how the platforms relate.

---

## Phase 1: MCP Connector

**Goal:** Register MemoryHub as a kagenti connector so any kagenti-deployed agent can discover and use MemoryHub's MCP tools through the platform's standard tool discovery.

Kagenti has a connector system — a REST API (`POST /connectors` on the `adk-server`) for registering external MCP servers. Agents declare an `MCPDemand` for a memory server and receive the MemoryHub MCP endpoint as fulfillment. This is how kagenti is designed to extend; no platform patches required.

### Deliverables

- Ensure the MemoryHub MCP server's streamable-http endpoint is reachable from kagenti's network (OpenShift Route or in-cluster Service).
- Document the connector registration process, including the `POST /connectors` payload and how agents declare `MCPDemand`.
- Provide an example agent demonstrating the `register_session` → `search_memory` → `write_memory` flow through kagenti's MCP client pattern.
- Test connectivity through kagenti's MCP Gateway (the Envoy-based aggregation layer that fronts all MCP traffic).
- Verify and publish the `memoryhub` Python SDK (v0.1.0 exists) to PyPI for agents that prefer typed access over raw MCP calls.

### Auth Story

API key via `register_session` — same as today's model. This works immediately with no OAuth dependency, which is intentional. Phase 1 is about connectivity, not auth sophistication.

### Client Access Options

Two paths are available in Phase 1. Agents can call MemoryHub tools directly through the MCP session (raw MCP), or use the `memoryhub` Python package, which wraps MCP calls with session management for a typed, ergonomic interface (SDK). The CLI client is planned separately and is not scoped in this integration plan.

### Dependencies

None on the kagenti side. This phase only requires the MemoryHub MCP server to be deployed and network-reachable.

### Success Criteria

A kagenti-deployed LangGraph agent can search and write memories through the connector. The integration survives pod restarts — meaning no session state is lost because MemoryHub, not the agent pod, holds the memory.

---

## Phase 2: Custom Extension + OAuth 2.1

**Goal:** Ship a first-class kagenti extension package and transition auth from API keys to token exchange.

These two deliverables ship together deliberately. The extension package needs proper auth — shipping it with API keys would be a step backward for a typed integration. Token exchange lets kagenti agents authenticate with their existing SPIFFE identity, eliminating key management entirely.

### Extension Package

The `kagenti-memoryhub` Python package provides three classes following kagenti's `BaseExtensionSpec` / `BaseExtensionServer` / `BaseExtensionClient` pattern:

- `MemoryHubExtensionSpec` — declares the extension's wire format and URI
- `MemoryHubExtensionServer` — server-side runtime that manages the MCP client lifecycle
- `MemoryHubExtensionClient` — client-side interface that attaches memory context to A2A messages

Agents declare memory access via typed annotation:

```python
async def my_agent(
    memory: Annotated[MemoryHubExtensionServer, MemoryHubExtensionSpec(scope="project")],
):
    results = await memory.search("deployment patterns")
```

### OAuth 2.1 Service

The auth service ships as a standalone component, separate from the MCP server:

- `client_credentials` grant for agents and SDKs
- `token_exchange` grant (RFC 8693) for Kubernetes service account token → MemoryHub JWT
- Short-lived JWTs (5–15 minutes) with scopes crossing two dimensions: operations (`memory:read`, `memory:write`, `memory:admin`) and tiers (`memory:read:user`, `memory:write:user`, `memory:write:organizational`, etc.)
- `register_session` becomes a compatibility shim for non-JWT clients rather than the primary auth path
- Namespace annotation `memoryhub.redhat.com/tenant-id` for multi-tenant isolation
- Tenant ID carried in JWT claims

### Auth Alignment with Kagenti

Kagenti uses SPIFFE/SPIRE for workload identity and Keycloak for OAuth2. The token exchange flow: a kagenti agent's SPIFFE-derived service account token is exchanged at the MemoryHub `/token` endpoint using `grant_type=urn:ietf:params:oauth:grant-type:token-exchange`. The response is a MemoryHub-scoped JWT carrying `tenant_id`, `sub`, `identity_type`, and the appropriate memory scopes. This aligns with how kagenti already thinks about identity — agents do not manage credentials, they exchange their workload identity for scoped access.

### Dependencies

The OAuth 2.1 auth service design is already complete; see the auth architecture docs in `docs/` for the decisions and wire format. This phase also depends on the kagenti extension system API being stable enough to target.

### Success Criteria

A kagenti agent authenticates via token exchange (no API key involved), accesses MemoryHub through the typed extension interface, and memories are tenant-isolated by namespace. The `MemoryHubExtensionSpec(scope="project")` annotation determines which memories the agent can read and write.

---

## Phase 3: MemoryHubContextStore

**Goal:** Implement kagenti's `ContextStore` ABC so every kagenti agent gets durable conversation history across pod restarts with zero code changes.

### How It Works

Kagenti's `ContextStore` abstraction defines three operations: `load_history()`, `store()`, and `delete_history_from_id()`. The default `InMemoryContextStore` uses a TTL-based cache that is lost on restart. `MemoryHubContextStore` persists conversation messages to MemoryHub's storage layer and replays them on `load_history()`.

### Scope

Conversation persistence only. This is deliberately narrow — the `ContextStore` interface is append-only with no search or branching. Agents that want semantic search, cross-session memory, or governance still use the MCP tools or extension directly. The `ContextStore` is an adoption wedge, not a replacement for the richer MCP interface.

### Deliverables

- `MemoryHubContextStore` class implementing kagenti's `ContextStoreInstance` interface (`load_history`, `store`, `delete_history_from_id`).
- Integrated into the `kagenti-memoryhub` package from Phase 2 — no separate install required.
- Configuration: agents opt in by setting `context_store=MemoryHubContextStore()` in `create_app()`.
- Documentation showing how to switch from `InMemoryContextStore`.

### Dependencies

Phase 2 (auth and extension package). The `context_id` that kagenti uses to key conversation history needs to map cleanly to MemoryHub's scoping model — this mapping needs to be confirmed against kagenti's `ContextStore` lifecycle documentation before implementation.

### Success Criteria

A kagenti agent using `MemoryHubContextStore` survives pod restarts with full conversation history intact. No changes to agent business logic are required — the context store is wired at the `create_app()` level.

---

## Phase Summary

| Phase | What | Auth | Kagenti Changes | MemoryHub Work |
|---|---|---|---|---|
| 1 | MCP Connector | API key | None | Connector docs, example agent, SDK publish |
| 2 | Extension + OAuth | Token exchange | None (uses extension system) | Extension package, OAuth 2.1 service |
| 3 | ContextStore | Inherited from Phase 2 | None (uses ContextStore ABC) | ContextStore implementation |

All three phases require zero changes to the kagenti platform itself. The integration builds entirely on kagenti's published extension points: the connector registration API, the extension system, and the `ContextStore` ABC.

The CLI client option is planned separately and is not scoped in this integration plan.
