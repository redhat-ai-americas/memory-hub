"""OGX Memory Demo Agent -- persistent memory via MemoryHub.

Uses OGX's Responses API with Gemma 4 for inference and MemoryHub
as an MCP connector for memory operations. Thin FastAPI server
translates between OpenAI chat completions (gateway/UI) and the
Responses API.

Supports both streaming (SSE) and non-streaming responses.
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid

from fipsagents.baseagent import BaseAgent, StepResult, load_config
from fipsagents.baseagent.events import ContentDelta, StreamComplete
from memoryhub import MemoryHubClient

import uvicorn
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

log = logging.getLogger(__name__)

PROJECT_ID = "ogx-memory-demo"


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    model: str = ""
    messages: list[ChatMessage] = Field(default_factory=list)
    stream: bool = False


class OGXMemoryAgent(BaseAgent):
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


def _build_instructions() -> str:
    instructions = _system_prompt
    if _api_key:
        instructions += (
            f"\n\nYour MemoryHub API key is: {_api_key}\n"
            "Call register_session with this key at the start of every "
            "conversation before performing any memory operations.\n"
            f"When writing memories, use scope='project' and "
            f"project_id='{PROJECT_ID}' so memories are scoped to this demo."
        )
    return instructions


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

    instructions = _build_instructions()
    messages = [{"role": m.role, "content": m.content} for m in request.messages]
    cmpl_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"

    if request.stream:
        return StreamingResponse(
            _stream_response(agent, messages, instructions, cmpl_id),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    response = await agent.call_model_responses(
        input=messages,
        instructions=instructions,
    )
    return {
        "id": cmpl_id,
        "object": "chat.completion",
        "created": int(time.time()),
        "model": _config.model.name,
        "choices": [{
            "index": 0,
            "message": {
                "role": "assistant",
                "content": response.content or response.refusal or "",
            },
            "finish_reason": "stop",
        }],
        "usage": {
            "prompt_tokens": getattr(response.usage, "input_tokens", 0) or 0,
            "completion_tokens": getattr(response.usage, "output_tokens", 0) or 0,
            "total_tokens": getattr(response.usage, "total_tokens", 0) or 0,
        },
    }


async def _stream_response(agent, messages, instructions, cmpl_id):
    created = int(time.time())
    model = _config.model.name

    async for event in agent.call_model_responses_stream(
        input=messages,
        instructions=instructions,
    ):
        if isinstance(event, ContentDelta):
            chunk = {
                "id": cmpl_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model,
                "choices": [{
                    "index": 0,
                    "delta": {"content": event.content},
                    "finish_reason": None,
                }],
            }
            yield f"data: {json.dumps(chunk)}\n\n"

        elif isinstance(event, StreamComplete):
            chunk = {
                "id": cmpl_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model,
                "choices": [{
                    "index": 0,
                    "delta": {},
                    "finish_reason": event.finish_reason or "stop",
                }],
            }
            yield f"data: {json.dumps(chunk)}\n\n"
            yield "data: [DONE]\n\n"


@app.get("/v1/memories")
async def list_memories(limit: int = 20):
    mh_url = os.environ.get("MEMORYHUB_URL", "")
    if not _api_key or not mh_url:
        return {"memories": [], "error": "MemoryHub not configured"}
    try:
        async with MemoryHubClient(server_url=mh_url, api_key=_api_key) as client:
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


if __name__ == "__main__":
    config = load_config("agent.yaml")
    uvicorn.run(
        app,
        host=config.server.host,
        port=config.server.port,
    )
