# memoryhub

Centralized, governed memory for AI agents.

MemoryHub provides a persistent memory layer for AI agents running on OpenShift AI, with scope-based access control, multi-tenant isolation, and an immutable audit trail. It works with any agent framework — LlamaStack, LangChain, Claude Code, Cursor, and more.

**Status:** Pre-alpha. The SDK is under active development.

## Quick start

```python
from memoryhub import MemoryHubClient

client = MemoryHubClient(
    url="https://memoryhub.apps.example.com",
    api_key="your-api-key",
)

# Search memories
results = await client.search("deployment patterns")

# Write a memory
await client.write("FastAPI is the preferred web framework", scope="project")
```

## Links

- [GitHub](https://github.com/rdwj/memory-hub)
- [Architecture](https://github.com/rdwj/memory-hub/blob/main/docs/ARCHITECTURE.md)
