# Outcome: Governed Agent Memory

## Problem

No hive mind for agents. Agent memory implementations today are usually either conversation-scoped or single-agent persistent. Conversation-scoped memory is discarded at session end; single-agent stores (typically flat vector collections) persist across sessions but are bound to one agent's context. Neither provides a mechanism for knowledge to flow between agents, projects, or teams. An insight learned by one agent is invisible to another working in the same project, or across an organization. AI factory platforms lack a shared memory infrastructure with a scope hierarchy -- user, project, campaign, role, organizational, enterprise -- where knowledge promoted to a higher scope becomes available to every agent operating at that level.

No enterprise governance for agent memory. Shared memory without governance is untrusted memory. If any agent can write to a shared pool without access control, versioning, or provenance, consuming agents have no basis for treating retrieved knowledge as reliable -- and operators have no way to reconstruct what an agent knew when it made a given decision. Governed shared memory requires scope-based RBAC, immutable version history, provenance tracking on promoted knowledge, and an audit trail over all operations. These properties are what make shared agent memory a platform-level capability rather than an application-level integration.

## Scope

- Tree-structured episodic and procedural memory with branching (rationale, provenance)
- Hierarchical scope model: user -> project -> campaign -> role -> organizational -> enterprise, each with distinct read/write governance
- Multi-tenant isolation with tenant-scoped RBAC
- Semantic search with session-focus retrieval and optional cross-encoder reranking
- Memory versioning with full version history for forensic reconstruction
- Inline curation pipeline: dedup detection, contradiction reporting, merge suggestions, configurable rules engine
- Framework-agnostic access via MCP, typed Python SDK, CLI, and dashboard UI
- OAuth authorization server with JWT-based RBAC
- Kubernetes-native deployment on OpenShift AI (UBI9, FIPS-delegated)

## Acceptance Criteria

- Agents can write, search, read, update, and delete memories without custom plumbing (via MCP or SDK)
- Every memory operation is scoped, authorized, and auditable
- Memory works across frameworks -- any MCP-capable agent gets the full surface; SDK available for direct integration
- Regulated customers can answer "what did the agent know, when, and why?" via version history and audit trail
- Multi-tenant: teams share infrastructure without cross-tenant data leakage
- Curation primitives (dedup, contradiction detection, merge suggestions) keep memory quality high without manual grooming






## What's shipped

- Core memory model, storage (PostgreSQL + pgvector), and all CRUD/search/graph/curation MCP tools
- OAuth 2.1 auth server with `client_credentials`, JWKS, and admin client management
- Service-layer RBAC enforced on every operation via `core/authz.py`
- Two-vector retrieval with stateless session focus, cross-encoder reranking, and graceful cosine fallback
- SDK (PyPI), CLI (`memoryhub-cli`), and dashboard (React + PatternFly 6) with six panels
- Multi-tenant isolation (tenant-scoped queries, curation rules, and audit)
- Campaign scope with enrollment-based RBAC and domain-aware retrieval boosting
- Agent-memory ergonomics: response shaping (mode/token-budget/weight-based stubbing), project config auto-discovery (`.memoryhub.yaml`), rule generation for consuming agents

## Roadmap (designed, not yet implemented)

- Kubernetes Operator with CRDs for lifecycle management and policy configuration
- Immutable audit logging wired through the governance engine (stub interface exists)
- Platform integrations: kagenti (MCP connector -> extension -> native ContextStore), LlamaStack (MCP tool group -> Vector IO provider -> distribution template)
- Session persistence via Valkey for horizontal pod scaling
- Org-ingestion pipeline for scanning external sources into organizational memory
- Observability: Prometheus metrics, Grafana dashboards
- `token_exchange` (RFC 8693) for platform-integrated agents
- FIPS end-to-end validation
- Curator Phase 3: cross-project knowledge promotion with HITL approval queue
- Actor/driver identity model (distinguishing the agent from the human it acts for)

