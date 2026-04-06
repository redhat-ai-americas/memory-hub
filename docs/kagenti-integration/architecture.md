# Kagenti Integration Architecture

This document covers the technical design for MemoryHub's integration with Kagenti: how the two systems are connected at the network level, how identity flows between them, and how each integration phase's components are structured.

For the motivation and phased roadmap, see `overview.md` and `integration-phases.md`.

---

## Network Topology

MemoryHub and Kagenti run in separate namespace groups within the same OpenShift cluster. Kagenti occupies several namespaces installed by its Ansible-based installer:

```
kagenti-system     Platform components: Ingress Gateway, Shipwright, Kiali, UI
gateway-system     MCP Gateway: Envoy-based broker, router, controller
mcp-system         MCP broker, router, controller (backend of gateway-system)
keycloak           Keycloak IAM
spire-system       SPIRE server and agents
<workload-ns>      Agent and tool pods (per-tenant namespaces)
```

MemoryHub occupies its own namespace group, unchanged by this integration:

```
memoryhub          MCP Server pods, Curator, Ingestion pipeline, Operator
memoryhub-db       PostgreSQL primary + replica
memoryhub-storage  MinIO
```

The two namespace groups communicate over the cluster's internal network. There is no shared namespace; the boundary between them is explicit and crossed only via defined API contracts.

### Phase 1 Connection Path

In Phase 1, agent pods reach MemoryHub tools through Kagenti's MCP Gateway. The gateway acts as a broker — it holds registrations for downstream MCP servers and routes tool calls to them.

```
Agent Pod             MCP Gateway                MemoryHub MCP Server
(workload-ns)  ---->  (gateway-system, :443)  ---> (memoryhub, :8080, /mcp/)
```

The agent calls the gateway using its standard MCP client. The gateway resolves the tool prefix, identifies the downstream server, and forwards the call. MemoryHub's MCP server never exposes itself directly to agent pods in this path.

An alternative direct path exists using the MemoryHub OpenShift Route, bypassing the gateway. This is simpler to configure but loses gateway-level observability and routing features. It is appropriate during early development or when an agent needs low-latency access without going through the gateway.

```
Agent Pod             OpenShift Route (TLS edge)    MemoryHub MCP Server
(workload-ns)  ---->  memoryhub-mcp.<cluster-domain> ---> (memoryhub, :8080)
```

The route terminates TLS at the OpenShift router; traffic to the MCP Server is plain HTTP inside the cluster. This matches the existing MemoryHub deployment model.

---

## MCP Connector Registration

Registering MemoryHub as a connector makes its tools available through the gateway to all agents that have access to the connector. There are two registration methods.

### REST Connector Registration

Kagenti's connector API accepts a POST to `/connectors` on the gateway controller:

```json
POST /connectors
{
  "name": "memoryhub",
  "url": "https://memoryhub-mcp.memoryhub.svc.cluster.local:8080/mcp/",
  "transport": "streamable_http",
  "description": "Centralized governed memory for agents"
}
```

The `streamable_http` transport matches MemoryHub's current deployment, which uses FastMCP with streamable-HTTP (SSE is deprecated and not used).

### MCPServerRegistration CRD

Kagenti's MCP Gateway also supports a Kubernetes-native registration approach via a custom resource. This is the preferred path for production because it integrates with GitOps workflows and survives gateway restarts without re-registration:

```yaml
apiVersion: mcp.kagenti.com/v1alpha1
kind: MCPServerRegistration
metadata:
  name: memoryhub
  namespace: memoryhub
spec:
  toolPrefix: memory_
  targetRef:
    group: gateway.networking.k8s.io
    kind: HTTPRoute
    name: memoryhub-mcp-route
    namespace: memoryhub
```

The `toolPrefix` field namespaces MemoryHub's tools through the gateway. An agent accessing tools through the gateway sees `memory_write_memory`, `memory_search_memory`, `memory_read_memory`, and so on. Agents that connect directly to MemoryHub's route or internal service see the original tool names without the prefix. This distinction matters for agent code that targets a specific connection path.

MemoryHub resources should carry labels and annotations that identify them to Kagenti's tooling:

```yaml
labels:
  kagenti.io/type: tool
  memoryhub.redhat.com/role: mcp-server
annotations:
  memoryhub.redhat.com/tenant-id: "tenant-acme"
```

---

## Agent MCP Consumption Pattern

From an agent's perspective, MemoryHub tools are consumed through Kagenti's `MCPServiceExtension`. The agent receives an MCP client at runtime through dependency injection and uses it to call tools by name.

```python
from kagenti_adk.a2a.extensions.services.mcp import (
    MCPServiceExtensionServer,
    MCPServiceExtensionSpec,
)

@server.agent()
async def my_agent(
    message: Message,
    context: RunContext,
    mcp: Annotated[MCPServiceExtensionServer, MCPServiceExtensionSpec.single_demand()],
):
    async with mcp.create_client() as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # Register session — Phase 1 uses API key auth
            await session.call_tool("register_session", {"api_key": "mh-dev-agent1-2026"})

            # Load relevant context before processing the request
            results = await session.call_tool("search_memory", {
                "query": "user deployment preferences",
                "max_results": 5
            })

            # ... agent logic using memory context ...

            # Persist what was learned during this session
            await session.call_tool("write_memory", {
                "content": "User prefers blue-green deployments over rolling updates",
                "scope": "user",
                "weight": 0.8
            })
```

When connecting through the gateway, tool names carry the `memory_` prefix. The call to `register_session` becomes `memory_register_session`, and so on. Agents connecting directly skip the prefix. To avoid hardcoding this distinction, agents should accept the tool prefix as a configuration value injected at deployment time.

---

## Extension Architecture (Phase 2)

Phase 2 introduces `MemoryHubExtensionServer` as a typed Python wrapper over the raw MCP client. It follows Kagenti's standard three-part extension pattern — Spec, Server, Client — which provides a clean API to agent authors and integrates with Kagenti's dependency injection system.

```
MemoryHubExtensionSpec (BaseExtensionSpec)
  ├── URI: "memoryhub:memory"
  ├── scope: str             default "user"
  ├── auto_search: bool      default True — pre-load memories on session start
  └── search_query: str      optional initial query for auto_search

MemoryHubExtensionServer (BaseExtensionServer)
  ├── search(query, max_results, scope) -> list[Memory]
  ├── write(content, scope, weight, metadata) -> Memory
  ├── read(memory_id, depth) -> Memory
  ├── update(memory_id, content, weight) -> Memory
  ├── report_contradiction(memory_id, observed_behavior) -> None
  └── lifespan() — MCP client connection setup and teardown

MemoryHubExtensionClient (BaseExtensionClient)
  └── Attaches memory context metadata to outgoing A2A messages
```

The extension server wraps all MCP calls behind a typed interface with domain-appropriate method names, removing the need for agent code to know MCP tool names or argument shapes. The `lifespan()` method manages the underlying MCP client session — it opens the connection during extension startup and closes it cleanly on shutdown.

When `auto_search` is enabled, the extension pre-loads memories relevant to the current task during initialization. This mirrors the recommended pattern from MemoryHub's session setup instructions: register, then search for context before acting. The `search_query` field in the spec lets agents declare their initial context query declaratively, without imperative setup code.

The `MemoryHubExtensionClient` is the outbound-facing counterpart. When an agent sends an A2A message to another agent, the client can attach memory context identifiers as message metadata. The receiving agent's extension can resolve this metadata to load relevant shared memories, enabling lightweight context propagation across agent-to-agent calls without duplicating memory content.

---

## ContextStore Architecture (Phase 3)

Kagenti's `ContextStore` interface defines three operations:

```python
class ContextStoreInstance(ABC):
    async def load_history(self) -> AsyncIterator[Message | Artifact]:
        ...
    async def store(self, item: Message | Artifact) -> None:
        ...
    async def delete_history_from_id(self, uuid: UUID) -> None:
        ...
```

`MemoryHubContextStore` implements this interface on top of MemoryHub's memory tree. Each conversation context maps to a root memory node with `branch_type="conversation_history"`. Individual messages and artifacts are stored as child nodes under this root.

The mapping is as follows:

- `store()` creates a child node under the context root. Messages are stored with `scope="user"` and `weight=0.3`. The low weight prevents conversation turns from appearing prominently in semantic search results — the context store is for durability, not knowledge extraction.
- `load_history()` reads the context root with sufficient depth to expand all child nodes, then streams them back in creation order.
- `delete_history_from_id()` deletes the context root node and all descendants. The implementation details of subtree deletion will need to be confirmed during Phase 3 — MemoryHub's tree structure supports hierarchical relationships, but whether deletion cascades automatically or requires client-side iteration is an implementation detail to resolve.

The context root node carries metadata that makes it identifiable outside the context store interface:

```json
{
  "agent_id": "deployment-agent-v1",
  "framework": "langgraph",
  "created_at": "2026-04-05T12:00:00Z",
  "context_id": "<uuid>"
}
```

This design is intentionally narrow. The `ContextStore` interface does not expose MemoryHub's richer features — scoped memories, weights, contradiction detection, provenance branches. Agents that need those capabilities use the `MemoryHubExtensionServer` or call MCP tools directly. The context store provides durability for conversation history without requiring any changes to agent code.

---

## Authentication Flow

### Phase 1 — API Key

The agent calls `register_session` with a static API key as the first MCP tool invocation. MemoryHub's auth service resolves identity from a ConfigMap keyed by API key. This is the simplest possible mechanism and requires no Kagenti-specific configuration.

### Phase 2 — Token Exchange (RFC 8693)

Phase 2 replaces API keys with JWT token exchange. Agent pods in Kagenti carry SPIFFE/SPIRE workload identity as Kubernetes ServiceAccount tokens. MemoryHub's auth service accepts these tokens and exchanges them for short-lived JWTs via the OAuth 2.0 token exchange grant.

```
Agent Pod              MemoryHub               MemoryHub
(w/ SPIFFE)            Auth Service            MCP Server
     |                      |                      |
     | POST /token           |                      |
     | grant_type=           |                      |
     |   urn:ietf:params:    |                      |
     |   oauth:grant-type:   |                      |
     |   token-exchange      |                      |
     | subject_token=        |                      |
     |   <SA JWT>            |                      |
     |---------------------->|                      |
     |                       |                      |
     | 200 OK                |                      |
     | { access_token: ...,  |                      |
     |   token_type: Bearer, |                      |
     |   expires_in: 900 }   |                      |
     |<----------------------|                      |
     |                       |                      |
     | MCP request                                  |
     | Authorization: Bearer <JWT>                  |
     |--------------------------------------------->|
     |                       |                      |
     | MCP response                                 |
     |<---------------------------------------------|
```

The issued JWT carries claims that MemoryHub uses for access control:

| Claim | Source | Example |
|---|---|---|
| `sub` | Agent's SPIFFE ID | `spiffe://cluster.local/ns/acme-agents/sa/deploy-agent` |
| `tenant_id` | Namespace annotation `memoryhub.redhat.com/tenant-id` | `acme` |
| `identity_type` | Derived from ServiceAccount name convention | `service` |
| `scopes` | Keycloak role mapping | `["memory:read", "memory:write:user"]` |

The memoryhub Python SDK is designed to handle token lifecycle transparently. On a 401 response from the MCP server, the SDK will re-exchange the current ServiceAccount token for a fresh JWT and retry the request. Agent code is not involved in token refresh. (Note: token exchange support is a Phase 2 deliverable; the current SDK uses API key auth.)

---

## Multi-Tenancy

Kagenti workload namespaces map to MemoryHub tenants via the `memoryhub.redhat.com/tenant-id` annotation on the namespace. A single MemoryHub deployment serves multiple Kagenti tenants without any per-tenant configuration — the tenant boundary is enforced in the JWT, not in application code.

The practical consequences of this model:

- Agents in different tenant namespaces have entirely isolated memory stores. An agent in the `acme-agents` namespace cannot read memories belonging to the `globex-agents` namespace even if it presents a valid JWT, because the JWT's `tenant_id` will not match.
- MemoryHub scopes (`user`, `project`, `role`, `organizational`, `enterprise`) operate within a tenant. Organizational-scope memories in tenant `acme` are shared among all agents in that tenant but invisible to agents in `globex`.
- Cross-tenant memory access is not supported and cannot be granted through scopes or RBAC rules. This is a deliberate constraint, not a roadmap gap.

For shared platform-level knowledge that should be visible to all tenants, a curator agent with `identity_type=service` and `memory:write:enterprise` scope can write enterprise-scope memories. Enterprise-scope memories are readable by any tenant but writable only by service identities.

To promote patterns observed across user-scope memories to organizational knowledge, a curator agent running within the tenant can read user-scope observations and, after validation, write them at `organizational` scope with appropriate weight. This promotion process is governed by curation rules set via `set_curation_rule` and subject to audit logging.

---

## Design Constraints and Tradeoffs

**Tool prefix coupling.** The `memory_` prefix introduced by `MCPServerRegistration` means agent code must be written for a specific connection path (gateway vs. direct) or accept the prefix as configuration. There is no automatic prefix negotiation in Phase 1. This is an acceptable tradeoff given the simplicity of configuring a prefix at deployment time.

**Phase 1 API keys are per-deployment, not per-agent.** All agents using the same API key are indistinguishable to MemoryHub's governance layer. Phase 2's token exchange resolves this by binding identity to the Kubernetes ServiceAccount, enabling per-agent RBAC and audit trails.

**ContextStore weight tuning.** The `weight=0.3` choice for conversation history nodes is a starting value. If semantic search results become polluted by conversation turns, the weight should be lowered further or a dedicated `branch_type` exclusion should be added to the search index filter.

**Direct path observability gap.** Agents that connect directly to the MemoryHub OpenShift Route bypass the MCP Gateway's routing layer, losing gateway-level metrics and access logs. Direct-path connections are still observable through MemoryHub's own Prometheus metrics and Grafana dashboards, but the unified gateway-level view of all tool calls is not available for those agents.
