# Kagenti Integration Phases

This document defines the phased rollout plan for integrating MemoryHub with Kagenti. Each phase is independently deliverable and builds on the previous. See `overview.md` for context on why this integration exists and how the platforms relate.

---

## Phase 1: MCP Connector

**Goal:** Register MemoryHub as a kagenti connector so any kagenti-deployed agent can discover and use MemoryHub's MCP tools through the platform's standard tool discovery.

Kagenti has a connector system — a REST API (`POST /api/v1/connectors` on the `adk-server`) for registering external MCP servers. Agents declare an `MCPDemand` for a memory server and receive the MemoryHub MCP endpoint as fulfillment. This is how kagenti is designed to extend; no platform patches required.

### Deliverables

- Ensure the MemoryHub MCP server's streamable-http endpoint is reachable from kagenti's network (OpenShift Route or in-cluster Service).
- Document the connector registration process, including the `POST /api/v1/connectors` payload and how agents declare `MCPDemand`.
- Provide an example agent demonstrating the `register_session` → `search_memory` → `write_memory` flow through kagenti's MCP client pattern.
- Test connectivity from kagenti-deployed agent pods to the MemoryHub MCP service (in-cluster Service URL and OpenShift Route).
- Verify connectivity using the `memoryhub` Python SDK (v0.6.0, available on PyPI) for agents that prefer typed access over raw MCP calls.

### Auth Story

API key via `register_session` — same as today's model. This works immediately with no OAuth dependency, which is intentional. Phase 1 is about connectivity, not auth sophistication.

### Client Access Options

Two paths are available in Phase 1. Agents can call MemoryHub tools directly through the MCP session (raw MCP), or use the `memoryhub` Python package, which wraps MCP calls with session management for a typed, ergonomic interface (SDK). The CLI client is planned separately and is not scoped in this integration plan.

### Dependencies

None on the kagenti side. This phase only requires the MemoryHub MCP server to be deployed and network-reachable.

### Success Criteria

A kagenti-deployed LangGraph agent can search and write memories through the connector. The integration survives pod restarts — meaning no session state is lost because MemoryHub, not the agent pod, holds the memory.

### Validation Status (PoC 2026-04-23)

**Gateway registration: BLOCKED.** The MCP Gateway's Istio listeners use dev-oriented hostnames (`mcp.127-0-0-1.sslip.io`, `*.mcp.local`), and Istio rejects HTTPRoutes that don't match. Registering external MCP servers on production OCP clusters requires gateway listener reconfiguration. Filed as kagenti/kagenti#1275.

**Direct MCP connection: PASS.** Agent pods connecting directly to the MemoryHub MCP service (bypassing the gateway) works. This is the recommended path until the gateway hostname issue is resolved.

**Implication:** Phase 1 is deliverable today via direct MCP connections. Gateway-mediated registration is deferred until kagenti/kagenti#1275 is resolved. The connector documentation should cover both paths.

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

The OAuth 2.1 auth service design is already complete; see the auth architecture docs in `../../docs/auth/` for the decisions and wire format. This phase also depends on the kagenti extension system API being stable enough to target.

### Success Criteria

A kagenti agent authenticates via token exchange (no API key involved), accesses MemoryHub through the typed extension interface, and memories are tenant-isolated by namespace. The `MemoryHubExtensionSpec(scope="project")` annotation determines which memories the agent can read and write.

### Validation Status (PoC 2026-04-23)

**Not yet attempted.** Keycloak identity federation and token exchange testing were deferred to a follow-up session. The OAuth 2.1 auth service design is complete and deployed for standalone use; the Keycloak federation path has not been validated.

---

## Phase 3: MemoryStore (ADK Platform Integration)

**Goal:** Implement a `MemoryStore` protocol in the ADK so every kagenti agent gets governed cross-session memory through dependency injection — separate from `ContextStore`, which handles conversation replay.

### How It Works

A new `MemoryStore` protocol is defined in `kagenti_adk.server.store` alongside the existing `ContextStore`. The two are separate abstractions: `ContextStore` handles per-conversation message replay (append-only, context-owner-only); `MemoryStore` handles cross-session governed knowledge (semantic search, full RBAC, version history). `MemoryHubMemoryStore` implements `MemoryStore` by calling MemoryHub's MCP server over HTTP, authenticated with the agent's Keycloak-issued Bearer token.

### Scope

Governed cross-session memory via ADK dependency injection. Agents access `MemoryStoreInstance` through `Depends(get_memory_store_instance)` — the standard ADK pattern. The `MemoryStore` is complementary to `ContextStore`, not a replacement. Agents that need both conversation replay and governed memory use both.

### Deliverables

- `MemoryStore` protocol definition in `kagenti_adk.server.store` with `MemoryStoreInstance` (search, write, read, update, delete).
- `MemoryHubMemoryStore` implementation calling MemoryHub's MCP server over HTTP.
- Integrated into the `kagenti-memoryhub` package from Phase 2 — no separate install required.
- DI wiring: agents access via `Annotated[MemoryStoreInstance, Depends(get_memory_store_instance)]`.
- Documentation and example agent.

### Dependencies

Phase 2 (auth and extension package). The `MemoryStore` abstraction lives alongside `ContextStore` in the ADK — it requires an ADK PR to be accepted. The MemoryHub team contributes and maintains the implementation code; the kagenti team's review obligation is limited to the protocol definition and DI wiring.

### Success Criteria

A kagenti agent using `MemoryHubMemoryStore` can search, write, and recall memories through the DI interface. Memories survive pod restarts. No MemoryHub-specific imports are needed in agent business logic — only the protocol type from `kagenti_adk.server.store`.

### Validation Status (PoC 2026-04-23)

**MemoryStore DI integration: PASS.** Memory written with ID `7fadd4e8-...`, recalled via semantic search, and survived pod restart. All three core operations (write, search, read) validated.

**ADK `Depends` async workaround required.** ADK's `Depends.__call__` does not `await` async dependency callables (kagenti/adk#229). Workaround: synchronous callable returning a lazy-initializing proxy (`_MemoryProxy`). This pattern is implemented on branch `feat/memory-store-protocol` on `rdwj/adk`.

**Implication:** Phase 3 is validated before Phases 1 (gateway) and 2 (identity). The phases are independent, not sequential as originally assumed — an agent can use the MemoryStore DI path today via direct MCP connection with API key auth, without waiting for gateway registration or Keycloak federation.

---

## Phase Summary

| Phase | What | Auth | Kagenti Changes | MemoryHub Work | PoC Status |
|---|---|---|---|---|---|
| 1 | MCP Connector | API key | None | Connector docs, example agent, SDK publish | Direct: PASS; Gateway: BLOCKED (kagenti#1275) |
| 2 | Extension + OAuth | Token exchange | None (uses extension system) | Extension package, OAuth 2.1 service | Not yet attempted |
| 3 | MemoryStore | API key (direct) or inherited | ADK PR (protocol + DI) | MemoryStore implementation | PASS (with Depends workaround) |

Phases 1 and 2 require zero changes to the kagenti platform itself. Phase 3 requires an ADK PR to add the `MemoryStore` protocol and DI wiring — contributed and maintained by the MemoryHub team. The phases are independently deliverable and can be adopted in any order; the PoC validated Phase 3 before Phase 1, demonstrating that the assumed sequential dependency is not a hard constraint.

The CLI client option is planned separately and is not scoped in this integration plan.
