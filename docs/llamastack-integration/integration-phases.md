# LlamaStack Integration Phases

This document defines the phased rollout plan for integrating MemoryHub with LlamaStack. Each phase is independently deliverable and builds on the previous. See the kagenti integration docs for context on the shared auth service, which this integration reuses in Phase 2.

---

## Phase 1: MCP Tool Group

**Goal:** Register MemoryHub as an MCP server tool group in LlamaStack so any LlamaStack agent can use MemoryHub's memory tools through the standard tool runtime.

LlamaStack has a first-class MCP tool runtime provider (`remote::model-context-protocol`). MCP servers are registered as tool groups and become available to agents. The MCP utility layer auto-detects transport (tries streamable_http first, falls back to SSE) and caches sessions per endpoint. Registration can happen via the client SDK or inline in the Responses API.

### Deliverables

- Ensure the MemoryHub MCP server endpoint is reachable from LlamaStack pods (OpenShift Route or in-cluster Service).
- Document the `run.yaml` configuration for adding memoryhub-mcp as a `tool_runtime` provider (server-side, persistent).
- Document the Responses API inline MCP tool definition path (per-request, no server config needed).
- Provide an example agent using the `Agent` helper class with inline MCP tools for multi-turn sessions.
- Provide an example using the Responses API with inline MCP tool definition.
- Test tool discovery (LlamaStack calls `list_tools` on the MCP server at startup from run.yaml config) and invocation end-to-end.
- Verify and publish the `memoryhub` Python SDK (v0.1.0 exists) to PyPI for agents that want typed access without going through LlamaStack's tool runtime.

### Registration Paths

**Via run.yaml** (server-side, persistent — survives restarts):

Tool groups are auto-registered at LlamaStack server startup from the `run.yaml` configuration. `client.toolgroups.register()` does not exist in the SDK. Add the memoryhub-mcp provider to the server's `run.yaml`:

```yaml
tool_runtime:
  - provider_id: memoryhub-mcp
    provider_type: remote::model-context-protocol
    # MCPProviderConfig has no config fields; the MCP server URL is configured
    # via environment variables or the provider's dynamic configuration.
```

The tool group is then auto-discovered at startup. Agents reference it as `mcp::memoryhub-mcp`.

**Via Responses API** (inline, per-request):

```python
client.responses.create(
    model="llama-3.3-70b",
    input="What do you know about my deployment preferences?",
    tools=[
        {
            "type": "mcp",
            "server_label": "memoryhub",
            "server_url": "http://memoryhub-mcp.memoryhub.svc.cluster.local:8080/mcp/",
            "require_approval": "never",
        }
    ],
)
```

### Auth Story

API key via `register_session` — the first MCP tool the agent calls. This works immediately with no OAuth dependency, which is intentional. Phase 1 is about connectivity, not auth sophistication. LlamaStack passes headers to MCP servers server-side, so a Bearer token can be forwarded via `mcp_headers` if MemoryHub's auth is configured to accept it without an explicit `register_session` call.

### Client Access Options

Two paths are available in Phase 1. Agents can call MemoryHub tools directly through LlamaStack's tool runtime (raw MCP), or use the `memoryhub` Python package, which provides typed, ergonomic access by bypassing LlamaStack's tool runtime entirely. The CLI client is planned separately and is not scoped in this integration plan.

### Dependencies

None on the LlamaStack side. This phase only requires the MemoryHub MCP server to be deployed and network-reachable.

### Success Criteria

A LlamaStack agent — using both the `Agent` helper class and the Responses API paths — can search and write memories through MemoryHub MCP tools, with tool discovery working correctly (auto-discovered from run.yaml on startup, or inline per-request via the Responses API).

---

## Phase 2: Custom Vector IO Provider + OAuth 2.1

**Goal:** Ship a MemoryHub-backed Vector IO provider for LlamaStack and transition auth to token exchange.

These two deliverables ship together deliberately. The Vector IO provider needs proper auth — a typed integration shipping with API keys would be a step backward.

### Vector IO Provider

LlamaStack agents use the `file_search` and `knowledge_search` built-in tools for RAG, which route through the Vector IO API. A MemoryHub Vector IO provider makes MemoryHub memories searchable through these built-in tools without agents needing to call MCP tools explicitly. This is complementary to Phase 1 — MCP gives full access to MemoryHub's rich API (write, update, contradict, curate), while Vector IO provides read-path integration with LlamaStack's native RAG pipeline.

The provider is registered in `run.yaml` like any other vector IO provider:

```yaml
vector_io:
  - provider_id: memoryhub
    provider_type: remote::memoryhub
    config:
      url: "http://memoryhub-mcp.memoryhub.svc.cluster.local:8080/mcp/"
      scope: "user"
      weight_threshold: 0.5
```

Once registered, `file_search` and `knowledge_search` automatically query MemoryHub when the agent's vector stores are backed by the `memoryhub` provider. Writes go through MCP tools; the Vector IO interface is read-only by design.

### OAuth 2.1 Service

The auth service ships as a standalone component, shared with the kagenti integration. The same service handles both integrations:

- `client_credentials` grant for LlamaStack server-to-MemoryHub auth
- `token_exchange` grant (RFC 8693) for Kubernetes service account token → MemoryHub JWT
- Short-lived JWTs with scopes crossing two dimensions: operations (`memory:read`, `memory:write`, `memory:admin`) and tiers (`memory:read:user`, `memory:write:user`, `memory:write:organizational`, etc.)
- `register_session` becomes a compatibility shim for non-JWT clients
- Tenant ID carried in JWT claims, isolated by namespace annotation `memoryhub.redhat.com/tenant-id`

LlamaStack supports multiple auth providers: `oauth2_token` (JWKS/introspection), `kubernetes` (K8s API server validation), `github_token`, and custom (external HTTP). On RHOAI, the `oauth2_token` provider with Keycloak/RHSSO is the standard path. The token exchange flow: LlamaStack's service account token is exchanged at the MemoryHub `/token` endpoint using `grant_type=urn:ietf:params:oauth:grant-type:token-exchange`. The response is a MemoryHub-scoped JWT carrying `tenant_id`, `sub`, `identity_type`, and the appropriate memory scopes. If bidirectional auth is needed, LlamaStack's `OAuth2TokenAuthProvider` can validate MemoryHub-issued JWTs via JWKS.

### Dependencies

The OAuth 2.1 auth service design is complete (shared with kagenti integration). This phase also requires the LlamaStack VectorIO provider API to be stable enough to target.

### Success Criteria

A LlamaStack agent uses `file_search` to query MemoryHub memories through the Vector IO provider, authenticating via token exchange with no API key involved. The MCP tool group from Phase 1 continues to work alongside for write operations and rich memory management.

---

## Phase 3: Distribution Template + Native Primitives

**Goal:** Ship a MemoryHub-aware LlamaStack distribution template and explore deeper framework integration.

### Distribution Template

A `memoryhub` distribution template (`run.yaml`) pre-configures a LlamaStack server with full MemoryHub integration out of the box:

- `remote::memoryhub` as a `vector_io` provider
- `remote::model-context-protocol` with the MemoryHub MCP endpoint as a `tool_runtime` provider
- OAuth 2.1 auth configuration for MemoryHub

The template ships in the MemoryHub project, not upstream in `llama-stack`. This avoids creating an upstream dependency and lets the template evolve with MemoryHub's release cycle independently of LlamaStack's.

### Native Primitives (Exploratory)

Three areas are worth investigating before committing to implementation:

Whether a custom `ToolRuntime` provider (beyond raw MCP) would meaningfully improve ergonomics for agents that use MemoryHub heavily — the main question is whether MCP's tool-call interface is sufficient or whether LlamaStack-native typed bindings would reduce boilerplate for agent authors.

Whether LlamaStack's Conversations API could benefit from MemoryHub-backed persistence. This is analogous to the kagenti `ContextStore` integration — if LlamaStack exposes a similar abstraction for conversation history, a MemoryHub implementation could give agents durable context across pod restarts with no code changes required.

Whether contributing a MemoryHub provider upstream to `llama-stack` makes sense long-term. This requires an upstream relationship and agreement on the interface contract, and is only worth pursuing once the provider API has demonstrated stability across multiple LlamaStack versions.

None of these are committed deliverables for Phase 3. The distribution template is the concrete deliverable; the native primitives work is gated on investigation results.

### Dependencies

Phases 1 and 2. Upstream LlamaStack distribution template format stability.

### Success Criteria

A developer can start a LlamaStack server using the MemoryHub distribution template and have full memory capabilities — search, write, governance — available without manual configuration of individual providers.

---

## Phase Summary

| Phase | What | Auth | LlamaStack Changes | MemoryHub Work |
|---|---|---|---|---|
| 1 | MCP Tool Group | API key | None (uses existing MCP provider) | run.yaml config docs, example agents (Agent class + Responses API), SDK publish |
| 2 | Vector IO Provider + OAuth | Token exchange | None (custom provider) | Provider package, OAuth 2.1 service (shared) |
| 3 | Distribution Template | Inherited from Phase 2 | None (template, not upstream change) | Distribution template, native primitive exploration |

All three phases require zero changes to the LlamaStack codebase. The integration builds on LlamaStack's published extension points: the MCP tool runtime provider, the Vector IO provider API, and the distribution template system.

The CLI client option is planned separately and is not scoped in this integration plan.
