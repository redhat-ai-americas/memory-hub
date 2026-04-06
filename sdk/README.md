# memoryhub

Centralized, governed memory for AI agents.

MemoryHub provides a persistent memory layer for AI agents running on OpenShift AI, with scope-based access control, multi-tenant isolation, and an immutable audit trail. It works with any agent framework — LlamaStack, LangChain, Claude Code, Cursor, and more.

**Status:** Alpha (v0.1.0). Core operations are stable; curation and relationship APIs may evolve.

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
| `search(query, *, scope, max_results, ...)` | Semantic similarity search |
| `read(memory_id, *, depth, include_versions)` | Read a memory by ID |
| `write(content, *, scope, weight, parent_id, ...)` | Create a new memory |
| `update(memory_id, *, content, weight, metadata)` | Update an existing memory |

### Lifecycle

| Method | Description |
|--------|-------------|
| `get_history(memory_id, *, max_versions)` | Version history |
| `report_contradiction(memory_id, observed_behavior, *, confidence)` | Flag stale memories |

### Relationships and curation

| Method | Description |
|--------|-------------|
| `get_similar(memory_id, *, threshold)` | Find similar memories |
| `get_relationships(node_id, *, relationship_type, direction)` | Get memory relationships |
| `create_relationship(source_id, target_id, relationship_type)` | Create a relationship |
| `suggest_merge(memory_a_id, memory_b_id, reasoning)` | Suggest merging duplicates |
| `set_curation_rule(name, *, tier, action, config)` | Configure curation rules |

## Authentication

The SDK uses OAuth 2.1 `client_credentials` grant under the hood. Token management is fully automatic — the SDK fetches, caches, and refreshes JWT access tokens transparently. You never need to handle tokens directly.

## Links

- [GitHub](https://github.com/rdwj/memory-hub)
- [Architecture](https://github.com/rdwj/memory-hub/blob/main/docs/ARCHITECTURE.md)
- [License](https://github.com/rdwj/memory-hub/blob/main/LICENSE)
