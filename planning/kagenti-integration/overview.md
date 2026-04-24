# Kagenti Integration Overview

## What Is Kagenti

Kagenti ([github.com/kagenti/kagenti](https://github.com/kagenti/kagenti)) is a Kubernetes-native agent deployment platform incubated at Red Hat (planned as part of OpenShift AI). Its central design principle is framework neutrality: Kagenti wraps existing agent frameworks — LangGraph, CrewAI, AG2, and others — without replacing them, providing infrastructure for deploying and operating agents at scale on OpenShift rather than dictating how agents are built. See the upstream repository for the current list of supported frameworks and the active version.

Agents in Kagenti are standard Kubernetes Deployments annotated with `kagenti.io/type: agent`. This means existing Kubernetes tooling — `kubectl`, Kiali, OpenShift monitoring — works on agents without modification. Kagenti adds two protocols on top of this foundation: A2A (Google's Agent-to-Agent protocol) for structured agent-to-agent communication, and MCP for tool access via a dedicated Envoy-based MCP Gateway.

The platform ships with a production-oriented security stack. SPIFFE/SPIRE provides workload identity and mTLS between services. Keycloak handles OAuth2/OIDC for user-facing authentication. Shipwright enables in-cluster container builds so agents can be deployed directly from source. The installer is Ansible-based and targets OpenShift (tested on OCP 4.20.11). Key namespaces after installation are `kagenti-system`, `keycloak`, `spire-system`, and workload namespaces per tenant.

## Why Integrate

Kagenti provides strong deployment infrastructure but its memory model is minimal by design. Conversation history is managed through a `ContextStore` abstraction with two implementations: `InMemoryContextStore`, which is the default and is lost on pod restart, and `PlatformContextStore`, which is durable but still append-only. A `VectorStore` API exists for semantic search, but it is scoped per-agent rather than shared across the platform. There is no cross-session memory, no cross-agent memory sharing, no contradiction detection, no provenance tracking, and no governance layer.

MemoryHub fills this gap completely. The table below shows the capability delta.

| Capability | Kagenti Today | MemoryHub |
|---|---|---|
| Conversation history | Per-context, append-only | Yes, with versioning |
| Cross-session memory | No | Yes |
| Cross-agent memory sharing | No | Yes (RBAC-scoped) |
| Semantic search | Per-agent VectorStore only | Platform-wide |
| Memory governance and curation | No | Yes (weights, rules, scopes) |
| Provenance and rationale | No | Yes (branch types) |
| Contradiction detection | No | Yes |
| Memory scopes | Just `context_id` | user / project / role / organizational / enterprise |

## How Kagenti Compares to LlamaStack

Kagenti is often mentioned alongside LlamaStack, but they solve different problems and are complementary rather than competing. The comparison below clarifies where each fits.

| Dimension | Kagenti | LlamaStack |
|---|---|---|
| Primary abstraction | Infrastructure and deployment platform | Agent development framework and API spec |
| Framework stance | Framework-neutral | Provides its own framework with provider adapters |
| Kubernetes integration | Native (agents are K8s Deployments) | None built-in |
| Agent communication | A2A protocol | LlamaStack APIs, no A2A |
| MCP support | First-class; agents connect to MCP servers via connector registration | MCP as a tool provider |
| Memory and state | Delegated to the agent | Built-in memory providers (vector, key-value) |
| Security | Zero-trust (SPIFFE/SPIRE, mTLS, Keycloak) | OAuth2/OIDC, Kubernetes auth, RBAC |
| Identity | SPIFFE/SPIRE workload identity, OAuth2 token exchange | Kubernetes ServiceAccount, OAuth2 tokens |
| Target audience | Platform and ops teams deploying agents | Developers building agents |

These two platforms are complementary. A LlamaStack agent can be containerized and deployed on Kagenti, gaining Kagenti's security and observability infrastructure while retaining LlamaStack's development model. MemoryHub integrates with both.

## Integration Approach Summary

The integration follows a three-phase approach, ordered from lowest coupling to deepest integration. Phase 1 registers MemoryHub as an MCP connector via Kagenti's connector API (`POST /api/v1/connectors` on the adk-server), requiring zero changes to Kagenti itself — agents call MemoryHub tools using standard MCP client patterns against the MemoryHub service URL. Phase 2 introduces a `MemoryHubExtensionServer` Python package that wires OAuth 2.1 token exchange between Keycloak and MemoryHub's authorization layer, enabling per-agent identity to flow into memory scoping and RBAC enforcement. Phase 3 implements a `MemoryHubContextStore` that replaces or wraps Kagenti's native `ContextStore`, making conversation persistence to MemoryHub transparent to agents without requiring any changes to agent code.

See `integration-phases.md` for the phased rollout plan with acceptance criteria, and `architecture.md` for the technical design covering data flow, identity propagation, and API contracts.
