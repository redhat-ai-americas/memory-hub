"""OGX Memory Demo Agent -- persistent memory via MemoryHub.

Direct-to-vLLM with framework memory injection for reads. Writes are
handled in application code: after every turn, a second LLM call
decides if the user stated something worth remembering, and if so,
writes it to MemoryHub via the MCP tool.

This bypasses the unreliable tool-calling behavior of small models.
"""

from __future__ import annotations

import json
import logging
import os

from fipsagents.baseagent import BaseAgent, StepResult, load_config
from memoryhub import MemoryHubClient

log = logging.getLogger(__name__)


class OGXMemoryAgent(BaseAgent):

    async def setup(self) -> None:
        await super().setup()
        raw = os.environ.get("OGX_MODEL_NAME", "")
        if raw and hasattr(self, "llm"):
            original = self.llm._base_kwargs
            def patched(**overrides):
                kwargs = original(**overrides)
                kwargs["model"] = raw
                return kwargs
            self.llm._base_kwargs = patched

    def get_tool_schemas(self):
        schemas = super().get_tool_schemas()
        blocked = {"ask_user", "spawn_agent"}
        return [s for s in schemas if s["function"]["name"] not in blocked]

    async def step(self) -> StepResult:
        response = await self.call_model()
        response = await self.run_tool_calls(response)

        # After the model responds, check if the user said something
        # worth remembering and write it programmatically.
        await self._maybe_write_memory()

        return StepResult.done(result=response.content)

    async def _maybe_write_memory(self) -> None:
        """Use a cheap LLM call to extract memorable facts from the
        user's last message, then write them via the memory tool."""
        user_msgs = [m for m in self.messages if m.get("role") == "user"]
        if not user_msgs:
            return
        last_user = user_msgs[-1].get("content", "")
        if len(last_user) < 10:
            return

        extract_prompt = [
            {"role": "system", "content": (
                "Extract any personal preference, decision, or fact the user "
                "stated about themselves. Return ONLY a JSON object: "
                '{"memory": "<one sentence>"}. '
                "If nothing worth remembering, return "
                '{"memory": null}. '
                "No explanation, just the JSON."
            )},
            {"role": "user", "content": last_user},
        ]

        try:
            result = await self.call_model(
                messages=extract_prompt,
                include_tools=False,
            )
            text = (result.content or "").strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
            parsed = json.loads(text)
            memory_text = parsed.get("memory")
            if not memory_text:
                return

            log.info("Writing memory: %s", memory_text[:80])
            tool_result = await self.tools.execute(
                "memory",
                action="write",
                content=memory_text,
                scope="user",
            )
            log.info("Memory write result: %s", str(tool_result)[:200])
        except Exception as e:
            log.debug("Memory extraction skipped: %s", e)


if __name__ == "__main__":
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
                result = await client.search(
                    query="preferences decisions context user",
                    max_results=limit,
                    mode="full",
                )
            memories = []
            for m in result.results:
                memories.append({
                    "id": m.id,
                    "content": m.content or m.stub or "",
                    "scope": m.scope or "",
                    "weight": m.weight or 0,
                    "created_at": str(m.created_at) if m.created_at else "",
                    "content_type": m.content_type or "",
                })
            return {"memories": memories, "total": result.total_matching}
        except Exception as e:
            log.warning("Failed to list memories: %s", e)
            return {"memories": [], "error": str(e)}

    server.run(host=config.server.host, port=config.server.port)
