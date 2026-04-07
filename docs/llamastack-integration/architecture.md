# LlamaStack Integration Architecture

This document covers the technical design for MemoryHub's integration with LlamaStack: network topology, MCP tool group registration, agent consumption patterns, the Phase 2 Vector IO provider, authentication flows, the Phase 3 distribution template, and multi-tenancy semantics.

For motivation and phased roadmap, see `overview.md` and `integration-phases.md`.

---

## Network Topology

MemoryHub and LlamaStack run in separate namespace groups within the same OpenShift cluster. LlamaStack is deployed via the `opendatahub-io/llama-stack-k8s-operator`, which manages a `LlamaStackDistribution` CR and reconciles the full stack.

```
llama-stack-ns     LlamaStack pod (rh-dev distribution, :8321)
                   KServe InferenceService (vLLM model serving)
                   PostgreSQL (metadata, conversations, vector stores)

memory-hub-mcp     MCP Server pod, Dashboard UI pod (BFF + oauth-proxy sidecar)
memoryhub-auth     OAuth 2.1 authorization server
memoryhub-db       PostgreSQL with pgvector
```

MemoryHub's namespace group is unchanged by this integration. The LlamaStack namespaces communicate with MemoryHub over the cluster's internal network, with no shared namespace between them.

### Phase 1 Connection Path

LlamaStack's MCP utility layer connects directly to MCP server endpoints. There is no gateway intermediary as in the Kagenti integration — no Envoy broker, no tool prefix namespacing, no centralized MCP routing. Each LlamaStack instance manages its own MCP connections.

```
LlamaStack Pod          MemoryHub MCP Server
(llama-stack-ns, :8321)  →  (memory-hub-mcp, :8080, /mcp/)
```

The MCP utility layer auto-detects transport protocol: it tries `streamable_http` first and falls back to SSE. MemoryHub's FastMCP server uses streamable-HTTP (SSE is deprecated), so the negotiation succeeds on the first attempt. Sessions are cached per `(endpoint, headers_hash)` with a 1-hour TTL, so the first request to a tool group incurs a `list_tools()` call; subsequent requests within the session use the cached tool list.

For external clients, MemoryHub is reachable via its OpenShift Route. LlamaStack server-to-server communication should use the in-cluster Service URL to avoid the extra hop through the OpenShift router:

```
http://memoryhub-mcp.memoryhub.svc.cluster.local:8080/mcp/
```

---

## MCP Tool Group Registration

MemoryHub registers as an MCP tool group using LlamaStack's `remote::model-context-protocol` provider. Two registration approaches are available.

### Server-Side Configuration (Persistent)

Tool groups are auto-registered from the `run.yaml` configuration at LlamaStack server startup. There is no client API call to register a tool group — the `client.toolgroups.register()` method does not exist in the SDK. The correct approach for production deployments is to add MemoryHub as a `tool_runtime` provider in the LlamaStack server's `run.yaml`:

```yaml
# In run.yaml
tool_runtime:
  - provider_id: memoryhub-mcp
    provider_type: remote::model-context-protocol
```

The MCP server URL is configured via environment variables or the provider's dynamic configuration — `MCPProviderConfig` has no config fields and `mcp_endpoint` is not a valid field under `tool_runtime[].config`. The tool group `mcp::memoryhub-mcp` is then auto-discovered at server startup via `list_tools()`.

After the server starts with this configuration, agents can reference the tool group in their requests. LlamaStack connects to the MCP endpoint lazily on first tool access and caches the tool list for the duration of the session.

To pass authentication headers to the MCP server, use the `mcp_headers` request header on the LlamaStack request — this is a server-side mechanism, not a client registration parameter.

### Inline Registration

The Responses API supports per-request MCP tool definitions. No persistent registration is required, and the tool group configuration lives entirely in the request. This is appropriate for ad-hoc access, testing, or cases where different requests need different MemoryHub configurations.

```python
response = client.responses.create(
    model="llama-3.3-70b",
    input="Search my memories for deployment preferences",
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

Inline registrations are per-request and carry no persistent state. The `require_approval: "never"` setting means LlamaStack will invoke MemoryHub tools without prompting the user for confirmation, which is appropriate for autonomous agents.

---

## Agent Consumption Patterns

LlamaStack provides two paths for agent consumption: the `Agent` helper class for multi-turn, session-based interactions, and the Responses API for stateless, OpenAI-compatible interactions. Both support MCP tool groups.

### Via Agent Helper Class

The `Agent` helper class manages multi-turn conversations with session state. It is the current API for multi-turn agentic workflows — the low-level `client.agents.create()`, `client.agents.session.create()`, and `client.agents.turn.create()` methods are replaced by this higher-level abstraction.

```python
from llama_stack_client import Agent

agent = Agent(
    client,
    model="llama-3.3-70b",
    instructions=(
        "You are a helpful assistant with access to persistent memory. "
        "Search memory at the start of each conversation for relevant context. "
        "Write important preferences and decisions to memory."
    ),
    tools=[
        {
            "type": "mcp",
            "server_label": "memoryhub",
            "server_url": "http://memoryhub-mcp.memoryhub.svc.cluster.local:8080/mcp/",
            "require_approval": "never",
        }
    ],
)

session_id = agent.create_session("deployment-planning")

response = agent.create_turn(
    messages=[{"role": "user", "content": "What are my deployment preferences?"}],
    session_id=session_id,
)
# Agent calls search_memory via MCP, LlamaStack routes to MemoryHub
```

The system instructions are critical. LlamaStack agents have no built-in "at the start of each turn, search memory" behavior — memory reads and writes only happen when the model explicitly decides to call the tool. The instructions above prompt the model to treat memory access as part of its standard workflow. Without prompting, the model may use its in-context knowledge and skip memory tools entirely.

### Via Responses API

The Responses API is stateless and OpenAI-compatible. Each request is independent; there is no session or agent object to manage. MCP tools are defined inline per request.

```python
response = client.responses.create(
    model="llama-3.3-70b",
    input="Remember that I prefer blue-green deployments over rolling updates.",
    tools=[
        {
            "type": "mcp",
            "server_label": "memoryhub",
            "server_url": "http://memoryhub-mcp.memoryhub.svc.cluster.local:8080/mcp/",
            "require_approval": "never",
        }
    ],
)
# Agent calls write_memory via MCP, persists the preference to MemoryHub
```

The Responses API is the right choice for single-shot automations, scripts, or applications already built around the OpenAI Responses API. Agents API is better suited for interactive or multi-step workflows where session continuity matters.

---

## Vector IO Provider Architecture (Phase 2)

Phase 2 introduces a `remote::memoryhub` Vector IO provider that bridges LlamaStack's RAG pipeline to MemoryHub's search capabilities. Once registered, LlamaStack's built-in `file_search` and `knowledge_search` tools can query MemoryHub memories without the agent needing to call MCP tools explicitly.

```
LlamaStack Request Pipeline
  → Agent/Responses API
  → file_search / knowledge_search tool
  → VectorIORouter
  → VectorStoresRoutingTable (resolves vector_store_id → provider)
  → MemoryHubVectorIOProvider (remote::memoryhub)
  → MemoryHub MCP Server (search_memory)
```

The provider implements LlamaStack's `VectorIO` protocol:

```python
class MemoryHubVectorIOProvider:
    """Maps LlamaStack vector store operations to MemoryHub search."""

    async def openai_search_vector_store(self, vector_store_id, request):
        # Translates to a search_memory call on the MemoryHub MCP server.
        # vector_store_id encodes the MemoryHub scope and owner (see mapping below).
        # request.query becomes the search query.
        # Returns results formatted as VectorStoreSearchResponsePage.
        ...

    async def openai_create_vector_store(self, params):
        # Creates a logical mapping between a LlamaStack vector store ID
        # and a MemoryHub scope/owner. No physical store is created in
        # MemoryHub — memories are the storage unit, not vector stores.
        ...
```

The provider is intentionally read-only from Vector IO's perspective. Creating and updating memories happens through the MCP tool group (Phase 1). This asymmetry is deliberate: LlamaStack's Vector IO API was designed for document ingestion and search, and mapping `write_memory`, `update_memory`, or `report_contradiction` onto vector store file attachment would produce a poor abstraction. The MCP path is the correct interface for writes.

The Vector IO provider authenticates to MemoryHub using the token exchange flow from Phase 2. The provider holds a MemoryHub JWT obtained via the LlamaStack pod's ServiceAccount token and refreshes it on 401. This is provider-level auth, not per-request — the provider authenticates as the LlamaStack service identity, and per-user scoping is derived from the vector store ID mapping (which encodes the MemoryHub scope and owner).

### Vector Store ID Mapping

Vector store IDs encode the MemoryHub scope and owner using a structured prefix convention:

| Vector Store ID | MemoryHub Search |
|---|---|
| `memoryhub:user:<owner_id>` | `search_memory(scope="user", owner_id=<owner_id>)` |
| `memoryhub:project:<project_id>` | `search_memory(scope="project", owner_id=<project_id>)` |
| `memoryhub:org` | `search_memory(scope="organizational")` |

This allows agents to address different scopes within a single MemoryHub deployment using LlamaStack's standard vector store ID mechanism, without any change to the client-side `file_search` API.

---

## Authentication Flow

### Phase 1 — API Key

In Phase 1, the agent calls `register_session` as the first MCP tool invocation. MemoryHub's auth service resolves identity from a static API key. LlamaStack passes authentication headers to MCP servers — the `mcp_headers` mechanism is available server-side and can be configured to forward a Bearer token on every request, making the explicit `register_session` call optional. Either path achieves API key auth with no per-agent identity. All agents sharing the same key are indistinguishable to MemoryHub's governance layer.

### Phase 2 — Token Exchange (RFC 8693)

Phase 2 replaces API keys with JWT token exchange. LlamaStack pods carry Kubernetes ServiceAccount tokens, which are exchanged at the MemoryHub auth service for short-lived, scoped JWTs.

```
LlamaStack Pod           MemoryHub              MemoryHub
(w/ SA token)             Auth Service           MCP Server
     |                        |                      |
     | POST /token            |                      |
     | grant_type=            |                      |
     |   token_exchange       |                      |
     | subject_token=         |                      |
     |   <SA JWT>             |                      |
     |----------------------->|                      |
     |                        |                      |
     | 200 OK                 |                      |
     | { access_token: ...,   |                      |
     |   token_type: Bearer,  |                      |
     |   expires_in: 900 }    |                      |
     |<-----------------------|                      |
     |                        |                      |
     | MCP request                                   |
     | Authorization: Bearer <JWT>                   |
     |---------------------------------------------->|
     |                        |                      |
     | MCP response                                  |
     |<----------------------------------------------|
```

The issued JWT carries claims used for access control and memory scoping:

| Claim | Source | Example |
|---|---|---|
| `sub` | LlamaStack ServiceAccount | `system:serviceaccount:llama-stack-ns:llamastack` |
| `tenant_id` | Namespace annotation `memoryhub.redhat.com/tenant-id` | `acme` |
| `identity_type` | Derived from ServiceAccount convention | `service` |
| `scopes` | Mapped from ServiceAccount role | `["memory:read", "memory:write:user"]` |

The claim structure is consistent with the Kagenti integration. The same MemoryHub auth service handles both, using the same token exchange endpoint and JWT schema.

On RHOAI, if bidirectional auth is needed (for example, MemoryHub calling back to LlamaStack for embedding), LlamaStack's `oauth2_token` auth provider can validate MemoryHub-issued JWTs. The MemoryHub auth service's JWKS endpoint is configured in LlamaStack's `AuthenticationConfig` to enable this.

---

## Distribution Template (Phase 3)

The `memoryhub` distribution template is a `run.yaml` that pre-wires both integration paths — the MCP tool group for full memory management and the Vector IO provider for the read-path RAG pipeline. A developer starting a LlamaStack server with this template has complete MemoryHub integration without manual provider configuration.

```yaml
version: 2
distro_name: memoryhub
providers:
  inference:
    - provider_id: vllm0
      provider_type: remote::vllm
      config:
        url: "${env.VLLM_URL}"
        api_token: "${env.VLLM_API_TOKEN}"
        tls_verify: "${env.VLLM_TLS_VERIFY:=true}"
  vector_io:
    - provider_id: memoryhub
      provider_type: remote::memoryhub
      config:
        url: "${env.MEMORYHUB_MCP_URL:=http://memoryhub-mcp.memoryhub.svc.cluster.local:8080/mcp/}"
        scope: "${env.MEMORYHUB_SCOPE:=user}"
        weight_threshold: "${env.MEMORYHUB_WEIGHT_THRESHOLD:=0.5}"
    - provider_id: pgvector
      provider_type: remote::pgvector
      config:
        host: "${env.PGVECTOR_HOST}"
  tool_runtime:
    - provider_id: memoryhub-mcp
      provider_type: remote::model-context-protocol
      # MCPProviderConfig has no config fields; the MCP server URL is configured
      # via environment variables or the provider's dynamic configuration.
  safety:
    - provider_id: llama-guard
      provider_type: inline::llama-guard
  agents:
    - provider_id: meta-reference
      provider_type: inline::meta-reference
  telemetry:
    - provider_id: meta-reference
      provider_type: inline::meta-reference
```

Both providers are present simultaneously. The `memoryhub` Vector IO provider handles the read path — `file_search` and `knowledge_search` route through it for agent memory retrieval. The `memoryhub-mcp` tool runtime provider gives agents access to the full MCP API: `write_memory`, `update_memory`, `report_contradiction`, `set_curation_rule`, and the rest. The `pgvector` provider is retained alongside for traditional document RAG that does not need MemoryHub's governance features.

The template ships in the MemoryHub project, not in the upstream `llama-stack` repository. This avoids an upstream dependency and lets the template evolve with MemoryHub's release cycle.

---

## Multi-Tenancy

LlamaStack's multi-tenancy is coarse-grained: all users share a server instance, with RBAC filtering on resources. MemoryHub's tenant isolation is finer-grained and enforced at the JWT level — the `tenant_id` claim in the exchanged token, derived from the namespace annotation `memoryhub.redhat.com/tenant-id`, determines which tenant's memory space the request operates within.

In RHOAI deployments with one LlamaStack instance per team, each instance's ServiceAccount maps to a distinct `tenant_id` through token exchange. Memories are isolated at the MemoryHub level even if multiple LlamaStack instances share the same MemoryHub deployment. Cross-tenant memory access is not supported and is not a roadmap item — it is a deliberate isolation boundary.

For single-LlamaStack deployments serving multiple users, MemoryHub's user-scope memories provide per-user isolation. The user identity flows from LlamaStack's authentication middleware through to MCP tool calls via the Authorization header; no application-level routing is required.

MemoryHub's scoping model (`user`, `project`, `role`, `organizational`, `enterprise`) operates within the tenant boundary established by the JWT. Organizational-scope memories in tenant `acme` are shared among all agents in that tenant but are invisible to agents in a different tenant.

---

## Shared Infrastructure

Both LlamaStack (`remote::pgvector`) and MemoryHub use PostgreSQL with pgvector. In an RHOAI deployment they can share a cluster or use separate instances. LlamaStack uses its own table prefix (`vector_stores:pgvector:v3::`) and MemoryHub uses its own schema, so table collisions are not a concern. The practical tradeoff is operational: a shared cluster costs less to run but complicates RBAC at the database level and creates a shared failure domain. Separate PostgreSQL instances are recommended for production; shared is acceptable for development and test.

---

## Design Constraints and Tradeoffs

**No gateway intermediary.** Unlike Kagenti, which routes all MCP traffic through an Envoy-based MCP Gateway, LlamaStack connects directly to MCP servers. There is no tool prefix namespacing, no gateway-level observability of MCP calls, and no centralized MCP routing. Each LlamaStack instance manages its own connections. This is simpler to deploy but means that MCP-level metrics and access logs are available only through MemoryHub's own Prometheus instrumentation, not through a unified platform view.

**Vector IO provider is intentionally read-only.** The asymmetry between Vector IO (read) and MCP (read/write) is a deliberate design choice. LlamaStack's Vector IO API was built for document ingestion and retrieval. Trying to map MemoryHub's write semantics — including versioning, contradiction detection, and weight management — onto vector store file attachment would produce a confusing and leaky abstraction. Agents that need to write memories use MCP tools.

**Tool discovery latency on first access.** LlamaStack discovers MCP tools lazily on first use. The initial request to a MemoryHub tool group incurs a `list_tools()` round trip. Subsequent calls within the session's 1-hour TTL use the cached tool list. For latency-sensitive applications, a no-op `search_memory` call at startup pre-warms the cache before any user-facing request.

**Agents must be prompted to use memory.** Neither the Agents API nor the Responses API has a lifecycle hook for "persist what was learned after each turn." Memory writes happen only when the model explicitly decides to call `write_memory`. This means the system instructions must be written to prompt that behavior — there is no equivalent to the `auto_search` feature in the planned Kagenti `MemoryHubExtensionServer`. LlamaStack does not expose an extension lifecycle system, so automatic memory behavior requires prompt engineering rather than framework-level configuration.

**Phase 1 API keys are shared, not per-agent.** All agents using the same API key are indistinguishable to MemoryHub's governance and audit layers. This is acceptable during development. Phase 2's token exchange resolves the limitation by binding identity to the Kubernetes ServiceAccount, enabling per-agent RBAC, per-agent audit trails, and properly scoped memory access.
