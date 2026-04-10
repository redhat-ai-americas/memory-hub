# memoryhub

Centralized, governed memory for AI agents.

MemoryHub provides a persistent memory layer for AI agents running on OpenShift AI, with scope-based access control, multi-tenant isolation, and an immutable audit trail. It works with any agent framework — LlamaStack, LangChain, Claude Code, Cursor, and more.

**Status:** Alpha (v0.4.0). Core operations are stable; curation and relationship APIs may evolve.

## Installation

```bash
pip install memoryhub
```

Requires Python 3.10+.

## Quick start

```python
import asyncio
from memoryhub import MemoryHubClient

async def main():
    client = MemoryHubClient(
        url="https://mcp-server.apps.example.com/mcp/",
        auth_url="https://auth-server.apps.example.com",
        client_id="my-agent",
        client_secret="my-secret",
    )

    async with client:
        # Search memories
        results = await client.search("deployment patterns", max_results=5)
        for memory in results.results:
            print(f"[{memory.scope}] {memory.content[:80]}")

        # Write a memory
        written = await client.write(
            "FastAPI is the preferred web framework",
            scope="project",
            weight=0.85,
        )
        print(f"Created: {written.memory.id}")

        # Read it back
        memory = await client.read(written.memory.id)
        print(memory.content)

        # Update it
        updated = await client.update(written.memory.id, weight=0.9)
        print(f"Version: {updated.version}")

        # Campaign-scoped search (requires project enrollment)
        campaign_results = await client.search(
            "shared patterns",
            project_id="my-project",
            domains=["React", "Spring Boot"],
        )

asyncio.run(main())
```

## Environment variables

Instead of passing credentials directly, use `MemoryHubClient.from_env()`:

```bash
export MEMORYHUB_URL="https://mcp-server.apps.example.com/mcp/"
export MEMORYHUB_AUTH_URL="https://auth-server.apps.example.com"
export MEMORYHUB_CLIENT_ID="my-agent"
export MEMORYHUB_CLIENT_SECRET="my-secret"
```

```python
client = MemoryHubClient.from_env()
```

## Project configuration

`MemoryHubClient.from_env()` (and construction without an explicit `project_config` argument) auto-discovers `.memoryhub.yaml` by walking up from the current working directory. If found, the file's `retrieval_defaults` are applied to outbound calls whenever the caller omits the corresponding argument, and `memory_loading.live_subscription` controls whether the client subscribes to push updates on connect.

In practice that means a caller can write a plain search and inherit the project's retrieval policy:

```python
client = MemoryHubClient.from_env()
async with client:
    # .memoryhub.yaml sets retrieval_defaults.max_results: 20
    # so this call transparently uses max_results=20
    results = await client.search("deployment patterns")
```

To opt out of auto-discovery, pass `auto_discover_config=False`:

```python
client = MemoryHubClient.from_env(auto_discover_config=False)
```

Or pass an explicit `ProjectConfig` to the constructor to use a fixed policy regardless of cwd. The recommended way to generate `.memoryhub.yaml` is the `memoryhub-cli` wizard (`memoryhub config init`); see the [repo root README](https://github.com/redhat-ai-americas/memory-hub#project-configuration) for the split between project config (`.memoryhub.yaml`, committed) and connection config (`~/.config/memoryhub/config.json`, per-developer).

## Sync usage

For non-async contexts, use the `_sync` variants:

```python
from memoryhub import MemoryHubClient

client = MemoryHubClient(
    url="https://mcp-server.apps.example.com/mcp/",
    auth_url="https://auth-server.apps.example.com",
    client_id="my-agent",
    client_secret="my-secret",
)

results = client.search_sync("deployment patterns")
```

## API reference

### Core operations

| Method | Description |
|--------|-------------|
| `search(query, *, scope, max_results, project_id, domains, ...)` | Semantic similarity search |
| `read(memory_id, *, include_versions, project_id)` | Read a memory by ID |
| `write(content, *, scope, weight, project_id, domains, ...)` | Create a new memory |
| `update(memory_id, *, content, weight, project_id, domains, ...)` | Update an existing memory |

### Lifecycle

| Method | Description |
|--------|-------------|
| `get_history(memory_id, *, max_versions, project_id)` | Version history |
| `report_contradiction(memory_id, observed_behavior, *, project_id)` | Flag stale memories |

### Relationships and curation

| Method | Description |
|--------|-------------|
| `get_similar(memory_id, *, threshold, project_id)` | Find similar memories |
| `get_relationships(node_id, *, relationship_type, direction, project_id)` | Get memory relationships |
| `create_relationship(source_id, target_id, relationship_type, *, project_id)` | Create a relationship |
| `suggest_merge(memory_a_id, memory_b_id, reasoning, *, project_id)` | Suggest merging duplicates |
| `set_curation_rule(name, *, tier, action, config)` | Configure curation rules |

All methods accepting `project_id` use it for campaign enrollment verification. When a target memory has `scope="campaign"`, the server resolves campaign membership through `project_id`. The `domains` parameter on `search()` boosts domain-matching results (non-matching results still appear); on `write()`/`update()` it tags the memory with crosscutting knowledge domains.

## Authentication

The SDK uses OAuth 2.1 `client_credentials` grant under the hood. Token management is fully automatic — the SDK fetches, caches, and refreshes JWT access tokens transparently. You never need to handle tokens directly.

## Further documentation

The SDK is one surface of the [memory-hub](https://github.com/redhat-ai-americas/memory-hub) monorepo. For deeper context:

- **[Architecture overview](https://github.com/redhat-ai-americas/memory-hub/blob/main/docs/ARCHITECTURE.md)** — System design, deployment topology, data flow
- **[MCP server tool reference](https://github.com/redhat-ai-americas/memory-hub/blob/main/docs/mcp-server.md)** — The 15 tools the SDK wraps, with parameter reference
- **[Memory tree data model](https://github.com/redhat-ai-americas/memory-hub/blob/main/docs/memory-tree.md)** — How scopes, branches, and versioning work
- **[Governance and authorization](https://github.com/redhat-ai-americas/memory-hub/blob/main/docs/governance.md)** — RBAC, scope-based access, audit trail
- **[Agent memory ergonomics design](https://github.com/redhat-ai-americas/memory-hub/blob/main/docs/agent-memory-ergonomics/design.md)** — Full `.memoryhub.yaml` schema, retrieval defaults, session focus, and loading patterns
- **[Package layout](https://github.com/redhat-ai-americas/memory-hub/blob/main/docs/package-layout.md)** — How `memoryhub` (this SDK) relates to `memoryhub-core` (server-side library) and `memoryhub-cli`

## Links

- **[GitHub repository](https://github.com/redhat-ai-americas/memory-hub)**
- **[CLI (`memoryhub-cli`)](https://pypi.org/project/memoryhub-cli/)** — companion CLI client
- **[Issue tracker](https://github.com/redhat-ai-americas/memory-hub/issues)**
- **[License (Apache 2.0)](https://github.com/redhat-ai-americas/memory-hub/blob/main/LICENSE)**
