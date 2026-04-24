# Architecture

MemoryHub is a Kubernetes-native agent memory system for OpenShift AI. It provides centralized, governed memory that consumers reach through four surfaces — agents over MCP, a typed Python SDK, a CLI, and a dashboard UI — all routed through a single MCP server backed by PostgreSQL with pgvector and protected by an OAuth 2.1 authorization server with service-layer RBAC.

This document covers the big picture. Subsystem details live in their own docs (see [SYSTEMS.md](SYSTEMS.md)).

## System Overview

```mermaid
graph TB
    subgraph "Consumer surfaces"
        AGENT[Agents over MCP<br/>Claude Code, kagenti,<br/>LlamaStack, custom]
        SDK[Python SDK<br/>memoryhub on PyPI]
        CLI[memoryhub-cli]
        UI_FE[Dashboard frontend<br/>React + PatternFly 6]
    end

    subgraph "memory-hub-mcp namespace"
        MCP[MCP Server<br/>FastMCP 3<br/>2 tools &#40;compact profile&#41;]
        UI_BE[Dashboard BFF<br/>FastAPI]
        OAP[oauth-proxy<br/>sidecar]
    end

    subgraph "memoryhub-auth namespace"
        AUTH[OAuth 2.1 AS<br/>FastAPI<br/>JWT + JWKS]
    end

    subgraph "Inside MCP server pod"
        AUTHZ[core/authz.py<br/>JWT verify, RBAC,<br/>scope filtering]
        SVC[src/memoryhub_core/services/<br/>memory + graph + curation]
        MOD[src/memoryhub_core/models/<br/>SQLAlchemy]
    end

    subgraph "memoryhub-db namespace"
        PG[(PostgreSQL<br/>pgvector + graph)]
    end

    subgraph "RHOAI vLLM serving"
        EMB[all-MiniLM-L6-v2<br/>384-dim embeddings]
        RR[ms-marco-MiniLM-L12-v2<br/>cross-encoder reranker<br/>optional, falls back to cosine]
    end

    AGENT --> MCP
    SDK --> MCP
    CLI --> SDK
    UI_FE --> OAP --> UI_BE --> MCP

    SDK -. OAuth client_credentials .-> AUTH
    MCP -. JWKS .-> AUTH
    UI_BE -. admin API .-> AUTH

    MCP --> AUTHZ
    AUTHZ --> SVC
    SVC --> MOD
    MOD --> PG

    SVC --> EMB
    SVC --> RR
```

Every memory operation flows through the MCP server. The server applies authorization in `core/authz.py` (JWT-first, session-fallback) before any tool call reaches the service layer. The service layer in `src/memoryhub_core/services/` is the single source of truth for memory CRUD, search, graph relationships, and curation; the MCP tools are thin wrappers that call into it.

The OAuth 2.1 authorization server runs in a separate namespace and never touches PostgreSQL. The MCP server validates incoming JWTs against the auth server's JWKS endpoint; the dashboard BFF brokers admin client management calls. SDK consumers fetch tokens via `client_credentials` and refresh transparently. Token rotation, JWKS caching, and signature validation are all handled by FastMCP 3's built-in `JWTVerifier`.

PostgreSQL with pgvector handles relational data, vector similarity search, and graph relationships in a single database — no separate vector store, no separate graph database. The `all-MiniLM-L6-v2` embedding model and the optional `ms-marco-MiniLM-L12-v2` cross-encoder reranker run on RHOAI's vLLM serving and are reached over the cluster network. The reranker is only invoked on the focus path of `search_memory` and gracefully degrades to plain cosine recall when unreachable, so the system stays usable if the reranker pod is unhealthy.

## Data flow

A memory's lifecycle has several phases. Here is how a typical memory moves through the system, with both the no-focus and the session-focus retrieval paths shown.

```mermaid
sequenceDiagram
    participant Agent
    participant MCP as MCP Server
    participant Authz as core/authz
    participant Svc as services/memory
    participant PG as PostgreSQL
    participant EMB as Embedding model
    participant RR as Cross-encoder<br/>(optional)

    Note over Agent,RR: Memory creation
    Agent->>MCP: write_memory(content, scope=user)
    MCP->>Authz: authorize_write(scope, owner_id)
    Authz->>Authz: verify JWT, build scope filter
    MCP->>Svc: create_memory(...)
    Svc->>EMB: embed(content)
    EMB-->>Svc: 384-dim vector
    Svc->>PG: INSERT memory_node + embedding
    MCP-->>Agent: memory_id + curation summary

    Note over Agent,RR: Search without focus (Layer 1 path)
    Agent->>MCP: search_memory(query)
    MCP->>Authz: authorize_read + build scope filter
    MCP->>Svc: search_memories(query, ...)
    Svc->>EMB: embed(query)
    Svc->>PG: pgvector cosine top-K
    PG-->>Svc: ranked candidates
    Svc->>Svc: weight-based stub vs full,<br/>token-budget packing,<br/>branch nesting
    MCP-->>Agent: results + total_matching + has_more

    Note over Agent,RR: Search with focus (Layer 2 path, #58)
    Agent->>MCP: search_memory(query, focus="OpenShift",<br/>session_focus_weight=0.4)
    MCP->>Svc: search_memories_with_focus(...)
    Svc->>EMB: embed(query) and embed(focus)
    Svc->>PG: pgvector cosine recall (top K=32)
    PG-->>Svc: candidate set
    Svc->>RR: rerank(query, candidate_texts)
    alt reranker reachable
        RR-->>Svc: relevance scores
        Svc->>Svc: RRF blend rerank ranks<br/>with focus cosine ranks (NEW-1)
    else reranker unreachable
        Svc->>Svc: log fallback reason,<br/>use plain cosine ranks
    end
    Svc->>Svc: compute pivot_suggested<br/>(distance from focus > 0.55)
    MCP-->>Agent: results + pivot_suggested<br/>+ focus_fallback_reason
```

> **Note:** The diagram uses legacy tool names (`write_memory`, `search_memory`) which remain as deprecated aliases. The compact profile (default) consolidates these into a single `memory` tool with an `action` parameter. See [agent-integration-guide.md](agent-integration-guide.md) for the current tool surface.

The session-focus path (#58) is the most architecturally interesting addition. It is **stateless** by design — the focus string is passed per call rather than stored on a session — which avoided every coordination question that a stateful focus would have raised. The cost is one re-embed of the focus string per call (~50ms with a warm vLLM), which is negligible relative to the cross-encoder rerank latency. When the user has not set a focus, the entire path short-circuits and the server falls through to the plain Layer 1 cosine retrieval — there is no rerank latency on the no-focus hot path.

The cross-encoder reranker (`ms-marco-MiniLM-L12-v2`) was deployed mid-session during the #58 implementation. Empirical benchmarking on a 200-memory synthetic corpus showed that **NEW-1** (RRF blend over cross-encoder rerank with focus cosine ranks) strictly dominated three alternatives at `session_focus_weight ∈ [0.2, 0.4]`. The cross-encoder alone is roughly neutral on this synthetic corpus — memory-hub's memories are short and topic-coherent, which is the regime where pure cosine works well — but the architecture is correct for noisier production data and the reranker stays optional via `MEMORYHUB_RERANKER_URL`. Full benchmark methodology and results live in [`research/agent-memory-ergonomics/two-vector-retrieval.md`](../research/agent-memory-ergonomics/two-vector-retrieval.md).

## The tree-based memory model

Memories are organized as a tree, not a flat list or a layered stack. Each memory is a node that can have child branches — some required (like scope metadata), some optional (like rationale or provenance). This is explained in detail in [memory-tree.md](memory-tree.md), but here is the structural concept:

```mermaid
graph TD
    ROOT[Memory Root]

    U1[prefers Podman<br/>weight: 0.9<br/>scope: user]
    U1R[works for Red Hat,<br/>that's their runtime<br/>type: rationale]

    U2[uses pytest for testing<br/>weight: 0.7<br/>scope: user]

    O1[scan for secrets<br/>before commits<br/>weight: 1.0<br/>scope: org]
    O1R[detected across 30+ users<br/>type: rationale]
    O1S[source: user memories<br/>u47, u102, u203...<br/>type: provenance]

    P1[FIPS compliance required<br/>weight: 1.0<br/>scope: enterprise]

    ROOT --> U1 & U2 & O1 & P1
    U1 --> U1R
    O1 --> O1R & O1S
```

The weight on each node controls injection behavior. A weight of 1.0 means always inject full content. Lower weights produce stubs. The `mode` and `max_response_tokens` parameters on `search_memory` (Layer 1, #56/#57) layered explicit knobs on top of weight-based stubbing so callers can opt into "give me everything" or "give me an index" mode regardless of weight.

Branches are no longer ranked as siblings of their parent in the search response. The default is to omit them and let the agent drill in via `read_memory` using `has_rationale` / `has_children` flags; pass `include_branches=True` to nest them under the parent (Layer 1, #56).

## Authorization model

Authentication and authorization are handled by two cooperating layers.

**Authentication** is OAuth 2.1 (`memoryhub-auth`). Three grant types are supported:

- `client_credentials` for agents and SDK consumers — the standard machine-to-machine flow.
- `authorization_code + PKCE` for browser-based human users (currently used by the dashboard via the OpenShift OAuth proxy).
- `token_exchange` (RFC 8693) for platform-integrated agents (kagenti, RHOAI) — designed but not yet wired.

JWTs are RSA-2048-signed, short-lived (5-15 min), and refreshed via DB-backed refresh tokens. The auth server publishes a JWKS endpoint that the MCP server's `JWTVerifier` polls. Token claims include `sub`, `client_id`, operational scopes (`memory:read`, `memory:write`, `memory:admin`), access-tier scopes (`user`, `project`, `campaign`, `role`, `organizational`, `enterprise`), and a `tenant_id` for future multi-tenant isolation (#46).

**Authorization** is enforced inside the MCP server in `core/authz.py`:

- `get_claims_from_context()` extracts JWT claims (or falls back to a session shim from `register_session` for the dev path).
- `build_authorized_scopes()` maps the token's access-tier scopes onto a SQL filter that limits visible memories to those the caller is authorized to read.
- `authorize_read()` and `authorize_write()` are called by every tool before any service-layer call. Cross-reference tools (`manage_graph(action="get_similar", ...)`, `manage_graph(action="get_relationships", ...)`) do post-fetch filtering and report an `omitted_count` so callers know when they hit something they couldn't see.
- `search_memory` applies the authorized-scopes filter at the SQL level so RBAC violations are impossible by construction.

The dev-path API key flow (`register_session(api_key="mh-dev-...")`) is a compatibility shim that produces the same claim structure as a real JWT. It is intended to be removed once all consumers move to OAuth.

## Deployment topology

MemoryHub deploys to an existing OpenShift AI cluster as a standalone component. It does not require modifications to OpenShift AI itself.

```mermaid
graph TB
    subgraph "OpenShift cluster"
        subgraph "memory-hub-mcp namespace"
            MCP_POD[memory-hub-mcp pod<br/>FastMCP 3]
            UI_POD[memoryhub-ui pod<br/>BFF + oauth-proxy sidecar]
        end

        subgraph "memoryhub-auth namespace"
            AUTH_POD[auth-server pod]
        end

        subgraph "memoryhub-db namespace"
            PG_POD[(memoryhub-pg-0<br/>PostgreSQL + pgvector)]
        end

        subgraph "RHOAI model serving"
            EMB[all-MiniLM-L6-v2 vLLM]
            RR[ms-marco-MiniLM-L12-v2 vLLM]
        end

        subgraph "openshift-monitoring (planned)"
            PROM[Prometheus]
            GRAF[Grafana]
        end
    end

    MCP_POD --> PG_POD
    MCP_POD --> EMB
    MCP_POD --> RR
    MCP_POD -. JWKS .-> AUTH_POD
    UI_POD --> MCP_POD
    UI_POD -. admin API .-> AUTH_POD
    AUTH_POD --> PG_POD

    PROM -. future .-> MCP_POD & UI_POD & AUTH_POD
```

The MCP server pod and the dashboard pod share the `memory-hub-mcp` namespace so the BFF can reach the MCP server over the cluster network without crossing namespace boundaries. The auth server lives in its own namespace because it has a different release cadence and a smaller blast radius for security incidents. PostgreSQL lives in its own namespace because the OOTB PostgreSQL operator that ships with OpenShift expects it there and because future replica scaling does not need to touch the application namespaces.

All containers use Red Hat UBI9 base images. FIPS compliance is inherited from the cluster's FIPS mode — PostgreSQL delegates crypto to OS-level OpenSSL, the auth server's RSA signing uses the OS crypto provider, and end-to-end FIPS validation is on the roadmap but not yet completed.

The MCP server pods are designed to be horizontally scalable behind a Service. Today the deployment runs a single pod because the workload does not yet justify replicas; the codebase is stateless except for the dev-path session shim, which writes to in-pod memory and would need to move to Valkey before scaling out.

External cluster routes:

- `memory-hub-mcp-memory-hub-mcp.apps.<cluster>` — the MCP server's streamable-HTTP endpoint that agents and the SDK connect to.
- `auth-server-memoryhub-auth.apps.<cluster>` — the OAuth 2.1 token endpoint, JWKS, and admin client management API.
- `memoryhub-ui-memory-hub-mcp.apps.<cluster>` — the dashboard, behind the OpenShift OAuth login wall via the oauth-proxy sidecar.

## What's decided and what's open

**Decided and shipped.** Tree-based memory model. PostgreSQL + pgvector for relational + vector + graph in one database. MCP as the primary agent interface. OAuth 2.1 with `client_credentials` and short-lived JWTs. Service-layer RBAC enforced via `core/authz.py`. Stateless session focus with cross-encoder reranking and graceful cosine fallback. `.memoryhub.yaml` schema with Pydantic v2 in the SDK. CLI with `memoryhub config init` for project-level setup, feature parity with MCP tool surface (#199), structured `--output json` for agent consumption (#200), and `--version` flag (#165). Single-namespace co-location of MCP + UI; separate namespaces for auth and database. Dashboard with six panels behind oauth-proxy. Three-namespace deployment topology. Server-side library renamed to `memoryhub-core` (distribution name) / `memoryhub_core` (import name) so it no longer collides with the published SDK (#55 closed). SDK v0.6.0 on PyPI with stub result parsing fix (#205). Campaign & domain framework MVP — campaign as a new scope between project and organizational with enrollment-based RBAC, crosscutting domain tags on memories with RRF-integrated retrieval boosting (#154). Project auto-enrollment (#188) — `projects` table with `enrollment_policy` (open/invite_only), agents writing to open projects are auto-enrolled on first project-scoped write, `manage_project` tool for project discovery and lifecycle management. MCP tool compaction (#201/#202) — 10 tools consolidated to 2 (`register_session` + `memory` action-dispatch); old tools retained as deprecated aliases during migration. Session enhancements (#189/#190) — `register_session` returns project list with memory counts, quick-start hints, and `expires_at` for session TTL. `search_memory` project_id filtering (#194) — `project_id` parameter now correctly restricts results to the specified project. PostgreSQL backup and restore scripts (#191).

**Decided, not yet implemented.** Kubernetes Operator with CRDs (skeleton only). Valkey-backed session vector store (deferred until #61 or #62 lands). Audit logging stub interface (#67). FIPS end-to-end validation. `token_exchange` grant for platform-integrated agents. Campaign promotion pipeline (Phase 3+) — curator-driven cross-project knowledge promotion with HITL approval queue. Emergent domain ontology — automatic synonym detection and normalization of domain tags.

**Open.** Multi-cluster federation. CRD naming and structure for the operator. Grafana dashboard layouts. The actor_id / driver_id model for distinguishing the agent that wrote a memory from the human it acted for (#66). HIPAA / PHI detection patterns in the curation pipeline (#68).

The architecture is designed to let these open questions be resolved incrementally. The core data flow and subsystem boundaries are stable; the internals of each subsystem are where the remaining design work lives.

## See also

- [`SYSTEMS.md`](SYSTEMS.md) — per-subsystem inventory with status, doc links, and dependency graph
- [`agent-memory-ergonomics/`](agent-memory-ergonomics/) — the design cluster covering search response shape, session focus retrieval, and project configuration (Layers 1-3 shipped 2026-04-07)
- [`mcp-server.md`](mcp-server.md) — current MCP tool surface and parameter reference
- [`memory-tree.md`](memory-tree.md) — the tree memory model in detail
- [`storage-layer.md`](storage-layer.md) — pgvector usage and schema
- [`governance.md`](governance.md) — RBAC, JWT verification, audit (planned)
- [`package-layout.md`](package-layout.md) — the #55 server/SDK naming collision and proposed rename
- [`planning/kagenti-integration/`](../planning/kagenti-integration/) — Kagenti platform integration design
- [`planning/llamastack-integration/`](../planning/llamastack-integration/) — LlamaStack platform integration design
