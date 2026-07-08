"""OGX Memory Demo Agent -- persistent memory via MemoryHub.

Uses platform mode: OGX handles MCP tool routing (MemoryHub) and the
inference loop server-side. A thin FastAPI server translates between
OpenAI chat completions format (for the gateway/UI) and OGX's Responses
API (for tool-augmented inference).

The fips-agents OpenAIChatServer doesn't support platform mode yet (its
streaming path bypasses step() and calls chat completions directly).
This workaround will be contributed upstream.
"""

from __future__ import annotations

import logging
import os
import time
import uuid

from fipsagents.baseagent import BaseAgent, StepResult, load_config
from memoryhub import MemoryHubClient

import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel, Field

log = logging.getLogger(__name__)


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    model: str = "vllm/RedHatAI/gpt-oss-20b"
    messages: list[ChatMessage] = Field(default_factory=list)


class OGXMemoryAgent(BaseAgent):
    """Agent with OGX platform mode and MemoryHub memory."""

    async def step(self) -> StepResult:
        user_input = self.messages[-1]["content"] if self.messages else ""
        response = await self.call_model_responses(input=user_input)
        return StepResult.done(result=response.content)


app = FastAPI(title="ogx-memory-agent")
_config = None
_system_prompt: str = ""
_api_key: str = ""
_mh_client: MemoryHubClient | None = None


@app.on_event("startup")
async def startup():
    global _config, _system_prompt, _api_key, _mh_client
    _config = load_config("agent.yaml")
    agent = OGXMemoryAgent(config=_config)
    await agent.setup()
    _system_prompt = agent.build_system_prompt()
    _api_key = os.environ.get("MEMORYHUB_API_KEY", "")
    mh_url = os.environ.get("MEMORYHUB_URL", "")
    if _api_key and mh_url:
        _mh_client = MemoryHubClient(server_url=mh_url, api_key=_api_key)
        log.info("MemoryHub client initialized for /v1/memories endpoint")


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


@app.get("/v1/agent-info")
async def agent_info():
    return {
        "name": _config.agent.name,
        "version": _config.agent.version,
        "description": _config.agent.description,
    }


@app.post("/v1/chat/completions")
async def chat_completions(request: ChatRequest):
    agent = OGXMemoryAgent(config=_config)
    await agent.setup()

    instructions = _system_prompt
    if _api_key:
        instructions += (
            f"\n\nYour MemoryHub API key is: {_api_key}\n"
            "Call register_session with this key at the start of every "
            "conversation before performing any memory operations."
        )

    user_messages = []
    for msg in request.messages:
        if msg.role == "user":
            user_messages.append(msg.content)

    input_text = user_messages[-1] if user_messages else ""

    response = await agent.call_model_responses(
        input=input_text,
        instructions=instructions,
    )

    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": request.model,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": response.content or response.refusal or "",
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": getattr(response.usage, "input_tokens", 0) or 0,
            "completion_tokens": getattr(response.usage, "output_tokens", 0) or 0,
            "total_tokens": getattr(response.usage, "total_tokens", 0) or 0,
        },
    }


@app.get("/v1/memories")
async def list_memories(limit: int = 20):
    mh_url = os.environ.get("MEMORYHUB_URL", "")
    if not _api_key or not mh_url:
        return {"memories": [], "error": "MemoryHub not configured"}
    try:
        async with MemoryHubClient(server_url=mh_url, api_key=_api_key) as client:
            result = await client.search(
                query="",
                max_results=limit,
                mode="index",
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


if __name__ == "__main__":
    config = load_config("agent.yaml")
    uvicorn.run(
        app,
        host=config.server.host,
        port=config.server.port,
    )
