# MemoryHub Documentation

MemoryHub is a Kubernetes-native agent memory component for OpenShift AI. See the [root README](../README.md) for the project overview and the three ways to use it.

This directory holds shipped architecture and user-facing reference material. In-flight designs, research notes, and demo scripts live in sibling directories — see the bottom of this page.

## Start here

- [`ARCHITECTURE.md`](ARCHITECTURE.md) — System architecture, deployment topology, and the "why" behind the major design choices.
- [`SYSTEMS.md`](SYSTEMS.md) — Per-subsystem inventory with status (shipped, in-flight, roadmap).
- [`package-layout.md`](package-layout.md) — How `memoryhub-core`, `memoryhub`, and the other distribution packages fit together.

## Subsystem designs (shipped architecture)

- [`governance.md`](governance.md) — Memory governance model: scopes, visibility, ownership, tenant isolation.
- [`memory-tree.md`](memory-tree.md) — Tree/branch model, versioning with `isCurrent`, rationale and provenance branches.
- [`storage-layer.md`](storage-layer.md) — PostgreSQL + pgvector schema, row-level security, migration conventions.
- [`curator-agent.md`](curator-agent.md) — Curator agent design for duplicate detection, merge suggestions, and rule-driven curation.
- [`mcp-server.md`](mcp-server.md) — FastMCP 3 server design, tool shapes, streamable-http transport, session handling.
- [`build-deploy-hardening.md`](build-deploy-hardening.md) — Build and deploy invariants shared across all MemoryHub components.

## Agent memory ergonomics

- [`agent-memory-ergonomics/overview.md`](agent-memory-ergonomics/overview.md) — Concept overview: what problem the ergonomics work solves and how the pieces fit.
- [`agent-memory-ergonomics/design.md`](agent-memory-ergonomics/design.md) — Full design cluster: search shape, session focus vector, cross-encoder reranking, loading patterns, real-time push.

## Auth

- [`auth/README.md`](auth/README.md) — OAuth 2.1 auth service and JWT verification. Start here, then follow links to the LibreChat integration and the OpenShift broker work.

## Admin operations

- [`admin/README.md`](admin/README.md) — Administrative controls: agent and user management, content moderation, filter rules.

## Identity model

- [`identity-model/README.md`](identity-model/README.md) — The owner/actor/driver triple, project-scope membership, audit logging, and the agent-generation CLI.

## Related directories

- [`../planning/`](../planning/) — In-flight designs for unimplemented features (operator, observability, org-ingestion, session-persistence) and the kagenti and LlamaStack integration plans. Also houses the agent-memory-ergonomics open-questions tracker.
- [`../research/`](../research/) — Investigations and explorations: FIPS storage evaluation, agent-memory-ergonomics research papers (two-vector retrieval benchmark, pivot detection, FastMCP 3 push notifications), Claude Code JWT limitations.
- [`../demos/`](../demos/) — Conference demo scripts (HIMSS, RSA, IACP, IAEM, World AgriTech) and the RHOAI dashboard demo material.
