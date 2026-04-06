# LlamaStack Integration Overview

## What Is LlamaStack

LlamaStack (github.com/meta-llama/llama-stack) is Meta's open-source agentic API server for building AI applications. Its defining characteristic is OpenAI API compatibility: it implements `/v1/chat/completions`, `/v1/embeddings`, `/v1/responses`, `/v1/vector_stores`, `/v1/files`, and `/v1/batches`, which means any OpenAI client can point at a LlamaStack server without code changes.

The internal architecture is built around a provider/adapter model. A developer can build an application locally against an Ollama provider and deploy it against vLLM or Fireworks without changing application code — the provider swap is configuration, not a code change. LlamaStack exposes APIs across a broad surface area: Inference, Responses (server-side agentic orchestration), Vector IO, Files, Batches, Models, Safety (shields), Agents (native multi-turn), Tool Runtime, DatasetIO, Scoring, Eval, Telemetry, and Post-Training.

A "distribution" is a pre-built `run.yaml` bundling providers for a target environment — the same concept as a Linux distribution, where the API is stable but the underlying components differ. Named distributions include `starter`, `ollama`, `remote-vllm`, `nvidia`, `fireworks`, `together`, `bedrock`, and `openai`. LlamaStack runs on port 8321 by default.

MCP is a first-class citizen in LlamaStack. MCP servers register as tool groups using the `remote::model-context-protocol` provider, and they are accessible from both the Agents API (`toolgroups: ["mcp::my-server"]`) and the Responses API (inline MCP tool definitions). Client SDKs are available for Python (`llama-stack-client`), TypeScript, Go, Swift, and Kotlin. For embedding in existing applications, LlamaStack also supports a library mode (`LlamaStackAsLibraryClient`) that runs in-process without a server.

## LlamaStack on RHOAI

Red Hat ships LlamaStack as a Technology Preview on Red Hat OpenShift AI (RHOAI) via the `opendatahub-io/llama-stack-k8s-operator`. The operator introduces a `LlamaStackDistribution` CRD (`apiVersion: llamastack.io/v1alpha1`) and reconciles the full application stack: PVC, NetworkPolicy, Deployment, Service, and optionally an OpenShift Route.

The RHOAI-specific distribution is `rh-dev`. Its expected topology is a KServe `InferenceService` running vLLM for model serving, a LlamaStack pod running the `rh-dev` distribution as the orchestration server, and PostgreSQL for metadata and vector storage. Authentication uses OAuth2/OIDC via Keycloak or RHSSO, with an option to validate Kubernetes tokens against the OpenShift API server. The build pipeline enforces FIPS compliance, and containers run as non-root (user 1001).

One known constraint: the operator requires Kubernetes 1.32+, but OpenShift 4.15 runs Kubernetes 1.28. A CRD schema validation workaround is needed for clusters on OCP 4.15.

## Why Integrate

LlamaStack's Vector IO system is a capable general-purpose RAG store. It handles chunked document retrieval well, and its provider model means it can back a vector store with any supported backend. What it is not is a structured memory system. Everything in Vector IO is a chunk of text with flat metadata — there is no concept of versioning, contradiction, provenance, scoping by agent identity, or curation. MemoryHub provides exactly those capabilities.

The gap analysis below maps each capability to the system that provides it.

| Capability | LlamaStack | MemoryHub |
|---|---|---|
| Cross-session persistence | Yes (disk-backed vector stores) | Yes |
| Cross-agent sharing | Yes (any request can reference any vector store by ID) | Yes (RBAC-scoped) |
| Semantic search | Yes (first-class, all vector backends) | Yes |
| Memory versioning | No | Yes (isCurrent flag, version history) |
| Contradiction detection | No | Yes (report_contradiction) |
| Provenance/rationale tracking | No (flat chunk metadata only) | Yes (branch types, parent_id) |
| Memory governance/curation | No | Yes (set_curation_rule, suggest_merge) |
| Hierarchical scoping | No (flat namespace with RBAC) | Yes (user/project/role/organizational/enterprise) |
| Weight-based injection priority | No | Yes |
| Agent memory write during turn | No (must use custom/MCP tool) | Yes (write_memory MCP tool) |
| Keyword/hybrid search | Yes (provider-dependent) | Vector only |
| Built-in chunking on ingest | Yes (file attachment auto-chunks) | No (caller manages) |

LlamaStack's Vector IO and MemoryHub are complementary rather than competing. Vector IO handles document retrieval (RAG); MemoryHub handles structured agent knowledge: preferences, decisions, accumulated context, and rationale. An agent can use both simultaneously — Vector IO for retrieving relevant documents at query time, MemoryHub for persisting and retrieving what the agent has learned across sessions.

## How LlamaStack Compares to Kagenti

Kagenti and LlamaStack are both relevant to MemoryHub's integration surface, but they solve different problems and the comparison below clarifies where each fits.

| Dimension | LlamaStack | Kagenti |
|---|---|---|
| Primary abstraction | Agent development framework and API spec | Infrastructure and deployment platform |
| Framework stance | Provides its own framework with provider adapters | Framework-neutral (wraps any framework) |
| K8s integration | Operator-based deployment, not deeply K8s-native | Native (agents are K8s Deployments with labels) |
| Agent communication | LlamaStack APIs, no A2A | A2A protocol (Google) |
| MCP support | First-class tool runtime provider | First-class via Envoy-based MCP Gateway |
| Memory and state | Vector IO (RAG-focused) | Delegated to the agent (no built-in) |
| Security | OAuth2/OIDC, Kubernetes auth, RBAC | Zero-trust (SPIFFE/SPIRE, mTLS, Keycloak) |
| RHOAI deployment | Tech Preview via opendatahub-io operator | Ansible installer targeting OpenShift |
| Target audience | Agent developers | Platform and ops teams |

These two platforms are complementary. A LlamaStack agent can be containerized and deployed on Kagenti, gaining Kagenti's security and observability infrastructure while retaining LlamaStack's development model. MemoryHub integrates with both through MCP.

## Integration Approach Summary

The integration follows a three-phase approach, ordered from lowest coupling to deepest integration. Phase 1 registers MemoryHub as an MCP server tool group in LlamaStack using the existing `remote::model-context-protocol` provider — no changes to LlamaStack are required. Once registered, agents can access all MemoryHub tools through the standard tool group mechanism. Phase 2 introduces a custom Vector IO provider backed by MemoryHub alongside an OAuth 2.1 token exchange so that per-agent identity flows into MemoryHub's RBAC and memory scoping. Phase 3 implements LlamaStack-native memory primitives for deeper framework integration, making MemoryHub access transparent to agents at the framework level.

See `integration-phases.md` for the phased rollout plan with acceptance criteria, and `architecture.md` for the technical design covering data flow, identity propagation, and API contracts.
