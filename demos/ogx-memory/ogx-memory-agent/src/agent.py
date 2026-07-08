"""OGX Memory Demo Agent -- persistent memory via MemoryHub.

Uses the standard BaseAgent path with client-side MCP tool routing.
OGX serves as the inference backend (OpenAI-compatible chat completions),
and MemoryHub is connected as a client-side MCP server. The model calls
MemoryHub tools directly via vLLM's built-in tool calling support.

OGX's Responses API (platform mode) has a tool name formatting bug with
the 20B model that causes tool calls to fail. Chat completions + vLLM's
--tool-call-parser openai works reliably. See fips-agents/agent-template#231.

A /v1/memories endpoint is added for the UI's memory viewer pane.
"""

from __future__ import annotations

import logging
import os

from fipsagents.baseagent import BaseAgent, StepResult, load_config
from memoryhub import MemoryHubClient

log = logging.getLogger(__name__)

PROJECT_ID = "ogx-memory-demo"


class OGXMemoryAgent(BaseAgent):
    """Agent with MemoryHub via client-side MCP.

    Overrides setup to patch the LLM client's model name. The fipsagents
    framework strips 'vllm/' from model names, but OGX registers models
    with that prefix. This patches the model name back to include it.
    """

    async def setup(self) -> None:
        await super().setup()
        raw_name = os.environ.get("OGX_MODEL_NAME", "")
        if raw_name and hasattr(self, "llm"):
            original = self.llm._base_kwargs

            def patched_base_kwargs(**overrides):
                kwargs = original(**overrides)
                kwargs["model"] = raw_name
                return kwargs

            self.llm._base_kwargs = patched_base_kwargs

    def get_tool_schemas(self):
        """Filter out stock tools that confuse the 20B model."""
        schemas = super().get_tool_schemas()
        blocked = {"ask_user", "spawn_agent"}
        return [s for s in schemas if s["function"]["name"] not in blocked]

    async def step(self) -> StepResult:
        response = await self.call_model()
        response = await self.run_tool_calls(response)
        return StepResult.done(result=response.content)


if __name__ == "__main__":
    from fastapi import FastAPI
    from fipsagents.server import OpenAIChatServer

    config = load_config("agent.yaml")
    server = OpenAIChatServer(
        agent_class=OGXMemoryAgent,
        config_path="agent.yaml",
        title=config.agent.name,
        version=config.agent.version,
    )

    api_key = os.environ.get("MEMORYHUB_API_KEY", "")
    mh_url = os.environ.get("MEMORYHUB_URL", "")

    @server.app.get("/v1/memories")
    async def list_memories(limit: int = 20):
        if not api_key or not mh_url:
            return {"memories": [], "error": "MemoryHub not configured"}
        try:
            async with MemoryHubClient(server_url=mh_url, api_key=api_key) as client:
                result = await client.list(max_results=limit, current_only=True)
            memories = []
            for m in result.get("memories", []):
                memories.append({
                    "id": m.get("id", ""),
                    "content": m.get("content", m.get("stub", "")),
                    "scope": m.get("scope", ""),
                    "weight": m.get("weight", 0),
                    "created_at": m.get("created_at", ""),
                    "content_type": m.get("content_type", ""),
                })
            memories.reverse()
            return {"memories": memories, "total": result.get("total", len(memories))}
        except Exception as e:
            log.warning("Failed to list memories: %s", e)
            return {"memories": [], "error": str(e)}

    server.run(host=config.server.host, port=config.server.port)
