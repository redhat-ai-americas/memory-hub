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

import os
import time
import uuid

from fipsagents.baseagent import BaseAgent, StepResult, load_config

import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel, Field


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


@app.on_event("startup")
async def startup():
    global _config, _system_prompt, _api_key
    _config = load_config("agent.yaml")
    agent = OGXMemoryAgent(config=_config)
    await agent.setup()
    _system_prompt = agent.build_system_prompt()
    _api_key = os.environ.get("MEMORYHUB_API_KEY", "")


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


if __name__ == "__main__":
    config = load_config("agent.yaml")
    uvicorn.run(
        app,
        host=config.server.host,
        port=config.server.port,
    )
