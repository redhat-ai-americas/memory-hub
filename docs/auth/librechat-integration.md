# LibreChat Integration

## Why this exists

MemoryHub's strategic claim is that *any* agent can use it. Today the only
agent platform we've actually proven this with is Claude Code (via MCP +
the `register_session` shim and, more recently, JWT auth). One client is
not a generalization. This document captures the work to validate that
claim by integrating MemoryHub with a structurally different second client:
**LibreChat**.

LibreChat is a good second-client choice because:

- It's a multi-model chat UI, not a coding assistant — different shape of
  workload, different UX, different conversation patterns.
- It already supports MCP servers natively, with full OAuth 2.0 on
  streamable-http transport, per-user token storage, and auto-discovery.
  Confirmed in `packages/api/src/mcp/oauth/` of the LibreChat codebase.
- It's deployed in our environment already — no new infrastructure to
  stand up.
- It's open-source, so the integration steps and any quirks we hit can be
  contributed back if useful.

The forcing function is just the demo claim. Showing two
architecturally-different agent platforms hitting the same MemoryHub MCP
server, with real per-user identity, makes the multi-client claim
self-evident in a way that no slide deck does.

## What LibreChat brings to the table

LibreChat's MCP support, as of the version currently deployed, supports:

- **Streamable-http transport** (and SSE, but SSE is deprecated upstream).
- **OAuth 2.0 auto-discovery** — if the MCP server returns 401 with proper
  RFC 8414 OAuth metadata, LibreChat discovers `authorization_endpoint`
  and `token_endpoint` automatically.
- **Pre-configured OAuth** — alternatively, set the endpoints, `client_id`,
  `client_secret`, and scopes explicitly in `librechat.yaml` to skip
  discovery.
- **Dynamic client registration (RFC 7591)** — works without a pre-issued
  `client_id`/`client_secret`. LibreChat registers itself.
- **PKCE (S256)** — with a `skip_code_challenge_check` escape hatch for
  AWS Cognito, which we don't need.
- **Token refresh + automatic reconnection** via the
  `OAuthReconnectionManager`.
- **Per-user encrypted token storage.** Each LibreChat user authenticates
  separately to the MCP server. This is the load-bearing feature for
  multi-tenancy: one MemoryHub deployment serves N LibreChat users with
  N distinct identities.
- **Custom headers on OAuth requests** via `oauth_headers` (for corporate
  proxies — not needed in our cluster).
- **Default callback** at `/api/mcp/{serverName}/oauth/callback`.

What LibreChat does **not** do: validate or inspect the JWT itself. That
remains the MCP server's job. LibreChat treats the access token as an
opaque bearer string and forwards it on every request.

## Required configuration

The `librechat.yaml` block to add the MemoryHub MCP server, once the
broker is in place:

```yaml
mcpServers:
  memoryhub:
    type: streamable-http
    url: https://memory-hub-mcp-memory-hub-mcp.apps.cluster-n7pd5.n7pd5.sandbox5167.opentlc.com/mcp/
    requiresOAuth: true        # optional; auto-detected on 401
    oauth:
      authorization_url: https://auth-server-memoryhub-auth.apps.cluster-n7pd5.n7pd5.sandbox5167.opentlc.com/authorize
      token_url:         https://auth-server-memoryhub-auth.apps.cluster-n7pd5.n7pd5.sandbox5167.opentlc.com/token
      client_id:     ${MEMORYHUB_LIBRECHAT_CLIENT_ID}
      client_secret: ${MEMORYHUB_LIBRECHAT_CLIENT_SECRET}
      scope: "memory:read:user memory:write:user"
      token_exchange_method: default_post
    chatMenu: true
    startup: false             # don't auto-start; users authenticate via UI
```

The `client_id`/`client_secret` come from a confidential client registered
in the broker's `oauth_clients` table. Alternatively, dynamic client
registration could be used to skip the manual registration step entirely
— but this requires `memoryhub-auth` to expose an RFC 7591 endpoint, which
is not currently planned and would be its own design discussion.

The `redirect_uri` LibreChat uses for the callback is
`https://librechat.example.com/api/mcp/memoryhub/oauth/callback` (with
`memoryhub` matching the server name in the YAML). This URI must be
registered in `oauth_clients.redirect_uris` exactly — see
[`openshift-broker.md#get-authorize`](openshift-broker.md#get-authorize)
for the validation rules.

The actual LibreChat hostname goes here in place of `librechat.example.com`
when the issue lands; it's environment-dependent.

## Required system prompt

LibreChat agents — unlike Claude Code — don't have an existing convention
for how to use MemoryHub. The system prompt has to teach the agent the
basic protocol: search at the start of any task, write when learning
something durable, use the right scope.

Sketch of the prompt content (refine during implementation):

```
You have access to MemoryHub, a persistent memory tool that survives
across conversations. Use it actively, not as an afterthought.

At the start of any task:
- Call `search_memory` with a query relevant to what the user is asking.
- Use the returned memories to inform your work. If the user has stated
  a preference before, follow it without re-asking.

When you learn something that should outlive this conversation:
- Call `write_memory`. Choose the scope carefully:
  - `user` for personal preferences and decisions specific to this user
  - `project` for context about the project the user is working on
- Be specific. "User prefers FastAPI over Flask" is useful. "User talked
  about Python" is not.
- Don't write trivia, ephemeral state, or things you can re-derive from
  context.

When updating an existing memory, use `update_memory` (not `write_memory`)
to preserve version history.

When you notice the user contradicting a stored memory, call
`report_contradiction` with both memory IDs.

When the topic shifts mid-conversation, search memory again. Memories are
retrieved on demand, not loaded once.
```

This is shorter than the Claude Code rules in
`.claude/rules/memoryhub-integration.md` deliberately. LibreChat agents
are not coding assistants and don't need the file-system / commit /
deployment-aware guidance. The full coding-agent prompt can be a follow-up
if we want LibreChat to be a coding assistant too — that's a separate
question.

The system prompt lives in LibreChat's agent configuration, not in
MemoryHub. Where exactly it gets injected (per-agent? global? per-model?)
depends on LibreChat's agent system and is something to confirm during
integration, not something MemoryHub controls.

## Verification — what proves it works

The integration is "done" when an end-to-end demo can show:

1. A LibreChat user logs in (any user — htpasswd, GitHub, whatever the
   cluster is configured for).
2. They open a conversation that uses the MemoryHub-enabled agent.
3. On first use of the agent, LibreChat triggers the OAuth flow. The user
   sees the OpenShift consent screen, approves it, and is bounced back
   into LibreChat with a working session.
4. The agent calls `search_memory` and gets back any memories that user
   has accumulated (likely empty on first run).
5. The user tells the agent something they want remembered. The agent
   calls `write_memory`. The memory is persisted.
6. In a *second* LibreChat conversation (or after a refresh), the agent
   calls `search_memory` again and finds the memory from the first
   conversation.
7. A *different* LibreChat user, in their own session, calls
   `search_memory` and does **not** see the first user's memories. This
   is the per-user isolation proof.
8. The same Claude Code session, using its own JWT, also doesn't see the
   LibreChat users' memories — they're distinct identities.

If all eight steps work, the multi-client claim is demonstrated. Any one
of them failing is the bug to fix before declaring done.

## Pre-requisites

Hard dependencies — none of this work can start until these land:

- **[#74](https://github.com/rdwj/memory-hub/issues/74)** and all its
  children. The broker has to exist for LibreChat's OAuth flow to work
  at all. Without `authorization_code + PKCE` in `memoryhub-auth`,
  LibreChat's auto-discovery sees no `authorization_endpoint` and gives
  up. There is no workaround at the LibreChat side.

Soft dependencies — not blockers but worth resolving in parallel:

- **A registered LibreChat client in the broker.** This is one row in
  `oauth_clients`: a `client_id` like `librechat`, a generated
  `client_secret`, the LibreChat callback URL in `redirect_uris`, scopes
  `memory:read:user memory:write:user`, `public=false` (LibreChat is a
  confidential client, it has secret storage).
- **The system prompt** above, polished and tested against a couple of
  real agent runs to make sure the agent actually uses memory the way we
  want it to.

## Open questions

These do not block filing the issue. They are decisions to make during
implementation.

1. **Manual `oauth_clients` row vs RFC 7591 dynamic registration.** Manual
   is one SQL insert and we move on. Dynamic registration is a real
   `memoryhub-auth` feature that future MCP clients would also benefit
   from, but it's its own design discussion. For LibreChat alone, manual
   is fine. Recommendation: **manual for the demo, file dynamic
   registration as a separate follow-up if and when a third client wants
   it.**

2. **Where the system prompt lives in LibreChat.** Per-agent? Global
   instructions field? A shared template? This is a LibreChat
   configuration question, not a MemoryHub design question. Resolve by
   reading their docs or asking in their issues.

3. **What model the LibreChat-MemoryHub agent uses.** Doesn't affect the
   integration mechanically, but a smart model uses memory tools more
   gracefully than a dumb one. Probably whatever is the default in
   LibreChat at the time, unless there's a specific reason to pin.

4. **Demo scenario.** What does the user actually *do* in the demo
   conversation that shows memory paying off? "Tell the agent your
   preferred language, log out, log in, ask the agent what it remembers"
   is the minimum. A more compelling scenario probably uses domain
   context — e.g., the user's role or current project — that the agent
   can productively use later. Worth designing alongside the technical
   integration, not after.

5. **Whether to write a similar doc for additional clients** (Continue,
   Cursor, Goose, Cline, Claude Desktop, etc) once LibreChat is proven.
   Each would be its own doc-and-issue pair following this template.
   Don't speculate now; do them when they're real.

## Out of scope

- **The broker itself.** Designed in
  [`openshift-broker.md`](openshift-broker.md), tracked in #74. Not
  re-documented here.
- **Per-user identity model details.** The identity primitives (`sub`,
  `tenant_id`, scopes) are documented in
  [`docs/identity-model/`](../identity-model/). This doc just consumes
  them.
- **System prompt for LibreChat as a coding assistant.** The sketch above
  is for a general chat agent. Coding-assistant guidance (file paths,
  commits, deployments) belongs in a follow-up if and when we want
  LibreChat to fill that role.
- **LibreChat configuration management.** How `librechat.yaml` is
  versioned, who has permission to edit it, how secrets are injected —
  all LibreChat-side operational concerns, not MemoryHub design.
- **Claude Desktop, Continue, or any other MCP client.** Each gets its
  own doc + issue when we get to them.

## Status

Design draft. Hard-blocked on the broker tracker (#74) — none of this
work can begin until the broker exists.

- Tracking issue: [#82](https://github.com/rdwj/memory-hub/issues/82)
- See also: [README.md](README.md#tracking-issues)
