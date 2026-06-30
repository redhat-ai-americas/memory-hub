# memoryhub-agents

Shared framework for MemoryHub curation agents (Trace Reviewer, Curator, Fact Checker, Statistician).

All four agents follow the same lifecycle: authenticate via MCP, dequeue work from Valkey, process it, report results. This package provides the shared infrastructure so individual agents only implement their domain-specific logic.

## Installation

```bash
pip install -e ".[dev]"
```

## Writing an Agent

Subclass `AgentPlugin` and implement `process()`:

```python
import asyncio

from memoryhub_agents.config import AgentConfig
from memoryhub_agents.lifecycle import AgentPlugin, AgentRunner
from memoryhub_agents.mcp_client import MCPSession


class TraceReviewerPlugin(AgentPlugin):
    """Extracts missed memories from completed conversation threads."""

    async def on_start(self, config, mcp):
        # One-time setup after authentication
        self.min_confidence = 0.7

    async def process(self, item: dict, mcp: MCPSession) -> dict:
        thread_id = item["thread_id"]

        # Use the MCP session to read the conversation thread
        thread = await mcp.call_tool("get_thread", thread_id=thread_id)

        # ... analyze messages, extract candidate memories ...

        # Write extracted memories back
        for candidate in candidates:
            await mcp.call_tool(
                "write",
                content=candidate["content"],
                scope="project",
            )

        return {"status": "ok", "extracted": len(candidates)}

    async def on_stop(self):
        pass


if __name__ == "__main__":
    config = AgentConfig()
    plugin = TraceReviewerPlugin()
    runner = AgentRunner(config, plugin)
    asyncio.run(runner.run())
```

## Configuration

All configuration is via environment variables:

| Variable | Default | Description |
|---|---|---|
| `AGENT_TYPE` | `unknown` | Agent type (tracer, curator, factchecker, statistician) |
| `AGENT_ID` | `""` | Unique instance identifier (typically pod name) |
| `MH_MCP_URL` | `""` | MemoryHub MCP server URL |
| `MH_API_KEY` | `""` | API key for MCP authentication |
| `VALKEY_URL` | `redis://memoryhub-valkey:6379` | Valkey connection URL |
| `LLM_ENDPOINT` | `""` | LLM inference endpoint |
| `LLM_MODEL` | `""` | Model name for inference |
| `DAILY_TOKEN_BUDGET` | `100000` | Daily token budget cap |
| `POLL_INTERVAL_SECONDS` | `5.0` | Queue poll interval |
| `MAX_RETRIES` | `5` | Max retries for MCP tool calls |
| `TENANT_ID` | `default` | Tenant identifier for queue/lock keys |

## Components

- **`config.py`** -- `AgentConfig` dataclass reads all settings from environment variables.
- **`queue.py`** -- `AgentQueue` wraps Valkey LIST operations for FIFO work item processing.
- **`leader.py`** -- `LeaderElection` implements distributed locks for singleton agents.
- **`mcp_client.py`** -- `MCPSession` wraps the MemoryHub SDK with exponential backoff retry.
- **`lifecycle.py`** -- `AgentRunner` orchestrates the authenticate-dequeue-process loop.

## Leader Election

Singleton agents (Curator, Statistician) should use `LeaderElection` to ensure only one instance processes work at a time:

```python
from memoryhub_agents.leader import LeaderElection
import redis.asyncio as redis

client = redis.from_url("redis://memoryhub-valkey:6379")
election = LeaderElection(client, config.lock_key)

if await election.try_acquire(config.agent_id):
    # We are the leader -- process work
    while running:
        await election.heartbeat()
        # ... dequeue and process ...
    await election.release()
```

## Testing

```bash
pip install -e ".[dev]"
pytest tests/ -v
```

Tests run without Valkey or MCP server -- everything is mocked.

## Design Reference

See `planning/autonomous-curation-agents.md` for the full design, particularly:
- Section 9: Deployment topology
- Section 13: Shared framework decision
