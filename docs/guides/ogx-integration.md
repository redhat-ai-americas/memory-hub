# Integrating MemoryHub with OGX (LlamaStack)

This guide covers how to give an OGX-based agent persistent, governed memory
via MemoryHub's MCP server. The agent discovers and calls MemoryHub tools
through OGX's native MCP connector -- no memory-handling code in your
application.

## Prerequisites

- OGX 0.7+ deployed (with `tool_runtime` and `responses` APIs enabled)
- MemoryHub MCP server deployed and reachable from the OGX pod
- A MemoryHub API key (`mh-dev-...`)

## 1. Register the MCP connector

Add MemoryHub to the `connectors:` list in your OGX `config.yaml`:

```yaml
connectors:
  - connector_id: memoryhub
    provider_id: model-context-protocol
    url: http://memory-hub-mcp.memory-hub-mcp.svc.cluster.local:8080/mcp
```

Ensure `tool_runtime` includes the MCP provider:

```yaml
providers:
  tool_runtime:
    - provider_id: model-context-protocol
      provider_type: remote::model-context-protocol
```

Restart the OGX pod to pick up the change. Verify with:

```bash
curl -s $OGX_URL/v1beta/connectors | python3 -m json.tool
curl -s $OGX_URL/v1beta/connectors/memoryhub/tools | python3 -m json.tool
```

You should see `register_session` and `memory` tools with full schemas.

## 2. Add memory instructions to the system prompt

Generate framework-agnostic instructions:

```bash
memoryhub config init --format system-prompt --non-interactive
```

This produces behavioral guidance telling the agent when to read and write
memories (session start flow, pivot detection, hygiene rules). Paste this
into your agent's system prompt, or use `--format raw` for the instructions
without the header.

Add an authentication instruction at the top of the system prompt:

```
At the start of every conversation, call register_session with the API key
provided in your configuration. This authenticates you with MemoryHub and
enables all memory operations.
```

## 3. Pass MCP tools in API calls

When calling OGX's Responses API, include the MCP tools reference:

```json
{
  "model": "vllm/RedHatAI/gpt-oss-20b",
  "input": "User message here",
  "instructions": "Your system prompt with MemoryHub instructions...",
  "tools": [
    {
      "type": "mcp",
      "server_label": "memoryhub",
      "server_url": "http://memory-hub-mcp.memory-hub-mcp.svc.cluster.local:8080/mcp"
    }
  ]
}
```

OGX discovers the tools from the MCP server, injects their schemas into the
model's context, and routes tool calls back to MemoryHub automatically.

## 4. Working example

Register a session and write a memory in one turn:

```bash
OGX_URL="http://ogx-ogx.apps.cluster-n7pd5.n7pd5.sandbox5167.opentlc.com"
MH_URL="http://memory-hub-mcp.memory-hub-mcp.svc.cluster.local:8080/mcp"
API_KEY="mh-dev-..."

curl -s -X POST "$OGX_URL/v1/responses" \
  -H "Content-Type: application/json" \
  -d "{
    \"model\": \"vllm/RedHatAI/gpt-oss-20b\",
    \"input\": \"Register with api_key '$API_KEY', then remember that I prefer Podman over Docker.\",
    \"tools\": [{\"type\": \"mcp\", \"server_label\": \"memoryhub\", \"server_url\": \"$MH_URL\"}]
  }"
```

The response will show:
1. `mcp_list_tools` -- OGX discovered the available tools
2. `mcp_call` to `register_session` -- authenticated the session
3. `mcp_call` to `memory(action="write", ...)` -- stored the preference
4. A `message` confirming the write

## 5. Authentication patterns

**API key in system prompt (simplest):** Include the key directly in the
instructions. Suitable for demos and single-user agents.

**API key via environment variable:** Have the agent read `MEMORYHUB_API_KEY`
from its environment. The system prompt instructs it to use this value when
calling `register_session`.

**OAuth 2.1 (production):** Use `client_credentials` grant via the
MemoryHub auth server. The agent fetches a JWT and includes it in MCP calls.
See [`planning/llamastack-integration/architecture.md`](https://github.com/redhat-ai-americas/memory-hub-scratchpad/blob/main/planning/llamastack-integration/architecture.md) for the token exchange
flow.

## 6. What the agent sees

After `register_session`, the agent gets back:
- User identity and accessible scopes
- Project memberships with memory counts
- Session TTL (auto-extends on activity)
- Quick-start hints

The `memory` tool supports 20+ actions (search, write, update, delete,
relate, promote, checkpoint, etc.). The agent calls whichever actions are
relevant based on the conversation. MemoryHub's curation pipeline
automatically handles dedup, PII blocking, and entity extraction.

## See also

- [`demos/ogx-memory/`](https://github.com/redhat-ai-americas/memory-hub-scratchpad/tree/main/demos/ogx-memory) -- complete demo with scaffolded agent, gateway, and UI
- [`planning/llamastack-integration/`](https://github.com/redhat-ai-americas/memory-hub-scratchpad/tree/main/planning/llamastack-integration) -- full integration design (phases 1-3)
- `docs/design/mcp-server.md` -- MCP tool surface and parameter reference
