"""OGX Memory Demo Agent -- persistent memory via MemoryHub.

Reads: framework memory injection at setup time (reliable)
Writes: override shutdown() to extract and write after each turn
"""

from __future__ import annotations

import asyncio
import json
import logging
import os

from fipsagents.baseagent import BaseAgent, StepResult, load_config
from memoryhub import MemoryHubClient

import httpx

log = logging.getLogger(__name__)

_api_key = os.environ.get("MEMORYHUB_API_KEY", "")
_mh_url = os.environ.get("MEMORYHUB_URL", "")
_model_endpoint = os.environ.get(
    "MODEL_ENDPOINT",
    "http://gemma4.gemma-model.svc.cluster.local/v1",
)
_model_name = os.environ.get("MODEL_NAME", "google/gemma-4-E4B-it")


async def extract_and_write(user_text: str) -> None:
    if len(user_text) < 10 or not _api_key or not _mh_url:
        return
    try:
        async with httpx.AsyncClient(timeout=30) as http:
            resp = await http.post(
                f"{_model_endpoint}/chat/completions",
                json={
                    "model": _model_name,
                    "messages": [
                        {"role": "system", "content": (
                            "Extract any personal preference, decision, or "
                            "fact the user stated about themselves. Return "
                            'ONLY JSON: {"memory": "<one sentence>"} or '
                            '{"memory": null} if nothing worth remembering.'
                        )},
                        {"role": "user", "content": user_text},
                    ],
                    "max_tokens": 100,
                    "temperature": 0,
                },
                headers={"Authorization": "Bearer not-required"},
            )
        text = resp.json()["choices"][0]["message"].get("content", "").strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        parsed = json.loads(text)
        memory_text = parsed.get("memory")
        if not memory_text:
            return
        log.info("Extracted memory: %s", memory_text[:80])
        async with MemoryHubClient(server_url=_mh_url, api_key=_api_key) as client:
            result = await client.write(memory_text, scope="user")
            mid = result.memory.id if result.memory else "curation-blocked"
            log.info("Memory written: %s", mid)
    except Exception as e:
        log.warning("Memory extraction failed: %s", e)


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
        return StepResult.done(result=response.content)

    async def shutdown(self) -> None:
        # Extract and write memory from the user's last message
        user_msgs = [m for m in self.messages if m.get("role") == "user"]
        if user_msgs:
            last = user_msgs[-1].get("content", "")
            asyncio.create_task(extract_and_write(last))
        await super().shutdown()


if __name__ == "__main__":
    from fipsagents.server import OpenAIChatServer

    config = load_config("agent.yaml")
    server = OpenAIChatServer(
        agent_class=OGXMemoryAgent,
        config_path="agent.yaml",
        title=config.agent.name,
        version=config.agent.version,
    )

    @server.app.get("/v1/memories")
    async def list_memories(limit: int = 20):
        if not _api_key or not _mh_url:
            return {"memories": [], "error": "MemoryHub not configured"}
        try:
            async with MemoryHubClient(server_url=_mh_url, api_key=_api_key) as client:
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
