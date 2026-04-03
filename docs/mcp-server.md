# MCP Server Interface

The MCP server is the sole external interface to MemoryHub. Every agent interaction -- reading, writing, searching, versioning -- goes through MCP tools. There is no REST API, no direct database access, no alternative path. This simplifies security (one interface to secure) and governance (one interface to audit).

**Status: skeleton.** The tool surface is sketched below, but detailed design will use the fips-agents `/plan-tools` workflow. Implementation follows the `/create-tools` -> `/exercise-tools` -> `/deploy-mcp` path.

## Transport and Deployment

The MCP server uses streamable-http transport (SSE is deprecated). It's built with FastAPI and FastMCP v2, deployed as horizontally scalable pods behind a Kubernetes Service. Multiple replicas handle concurrent agent connections; the pods are stateless (all state lives in PostgreSQL and MinIO).

Authentication uses OpenShift's OAuth/OIDC. Agents authenticate with a token that identifies both the user and the agent. The MCP server passes this identity to the governance engine for access control decisions.

## Planned Tool Surface

These are the tools we expect the MCP server to expose. The exact signatures, parameter names, and response schemas will be refined during `/plan-tools`. This is the conceptual surface area.

### read_memory

Retrieve a specific memory by ID. Returns the full content of the node plus metadata (scope, weight, version, timestamps). If the node has branches, returns branch stubs indicating available depth (e.g., "rationale available," "provenance available"). The agent can then decide whether to expand branches with subsequent calls.

### write_memory

Create or update a memory. Parameters include content, scope, optional parent ID (for creating branches), optional weight override, and optional metadata. The governance engine checks authorization (can this agent write to this scope?), scans content for secrets/PII, and logs the operation. For above-user-level scopes, the write gets routed to the curator agent's queue rather than committed directly.

### search_memory

Semantic search across memories the agent has access to. Takes a query string (gets embedded and compared via pgvector) and optional filters (scope, date range, node type). Returns ranked results as a mix of full content and stubs based on each node's weight. This is the primary way agents discover relevant memories -- they don't need to know memory IDs upfront.

### get_branches

Expand a memory node's branches. Given a memory ID, returns the child nodes (rationale, provenance, description, etc.) with their content. This is how an agent "crawls deeper" after seeing a stub in search results.

### list_versions

Return the version history of a specific memory. Shows the chain of changes: who changed it, when, what the previous content was, and which version is current. Supports the forensics use case and helps agents understand how a memory evolved.

### report_contradiction

Signal to MemoryHub that observed behavior contradicts a stored memory. The agent passes the memory ID and a description of the contradiction. The curator agent accumulates these signals for staleness detection. This is how the system learns that a memory might be outdated without requiring explicit user action.

### get_context

A higher-level tool that returns a curated set of memories relevant to the current conversation context. Takes the conversation summary or task description and returns the optimal memory injection -- full content for high-priority matches, stubs for the rest, plus a brief orientation explaining what's available. This tool encapsulates the search + weight + stub logic so the agent doesn't have to manage it.

This tool is the most speculative on the list. It might be better to let agents compose search_memory + read_memory themselves rather than providing a high-level abstraction. To be determined during `/plan-tools`.

## Authentication and Authorization

Every MCP connection carries an identity token from OpenShift OAuth. The token identifies:
- The user the agent is acting on behalf of
- The agent's own identity (useful for audit trails)
- The user's roles (for role-scope memory access)
- The user's project context (for project-scope memory access)

The MCP server validates the token on connection and passes the identity to the governance engine for per-operation authorization. Token refresh follows standard OAuth flows. If a token expires mid-session, the MCP server returns an auth error and the agent reconnects with a fresh token.

Authorization is not implemented in the MCP server itself -- it delegates entirely to the governance engine. The MCP server is a thin transport layer that handles protocol concerns (MCP framing, streamable-http, connection management) and passes everything else through.

## Error Handling

MCP tools should return clear, actionable errors. When a write is denied by governance, the error should explain why ("write to organizational scope requires curator approval"). When a search returns no results, the response should distinguish between "no memories match" and "you don't have access to any memories in that scope."

Errors are not hidden or sanitized. An agent that encounters an error should be able to understand what went wrong and whether it can retry, try a different approach, or surface the issue to the user.

## Design Questions

- Should `get_context` exist as a single high-level tool, or should agents compose lower-level tools? The tradeoff is simplicity (one call) vs. flexibility (agent decides search strategy).
- How should the MCP server handle concurrent writes from multiple agents to the same user's memories? The governance engine serializes writes, but the agent's MCP experience should be smooth -- does it get a "write queued" response with a callback, or does it block until the write completes?
- Should there be an `import_memory` tool for bulk ingestion (e.g., importing from Claude Code's local memory files)? Or is that a separate administrative tool outside the MCP interface?
- What's the right granularity for `search_memory` results? Returning 50 stubs is useless; returning 3 full memories might miss relevant context. Should the tool accept a `max_results` parameter, a `max_tokens` budget, or both?
- How do we handle MCP connections from agents that don't have OpenShift identity? External agents (e.g., a Claude Code instance running locally) would need a different auth path. API keys? Service accounts?
- Rate limiting: should the MCP server enforce per-agent rate limits to prevent a runaway agent from overwhelming the system?
