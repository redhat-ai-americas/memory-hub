"""Personal-edition register_session tool with on-connect dreaming."""

from __future__ import annotations

import asyncio
import logging
from typing import Annotated, Any

from fastmcp import Context
from pydantic import Field

logger = logging.getLogger(__name__)

_DREAMING_TIMEOUT = 30.0
_MAX_DRAIN_DEFAULT = 3


async def register_session(
    ctx: Context,
    api_key: Annotated[
        str | None,
        Field(description="Ignored in personal edition. No API key needed."),
    ] = None,
    default_driver_id: Annotated[
        str | None,
        Field(description="Identity of the upstream human or system."),
    ] = None,
) -> dict[str, Any]:
    """Register this session with MemoryHub.

    In the personal edition, sessions are auto-registered. No API key is
    needed. This tool exists for compatibility with agents that expect
    the cluster edition's registration flow.

    On-connect dreaming: if there are threads with unextracted messages,
    this tool will automatically extract facts from them using MCP
    sampling (up to 3 threads by default).
    """
    from memoryhub_local.identity import get_owner_id

    user_id = get_owner_id()

    response: dict[str, Any] = {
        "session_id": "local",
        "user_id": user_id,
        "name": user_id,
        "scopes": ["user", "project"],
        "project_memberships": [],
        "default_driver_id": default_driver_id,
        "projects": [],
        "quick_start": [
            "memory(action='write', content='...') to save a memory",
            "memory(action='search', query='...') to find memories",
            "memory(action='read', memory_id='...') to retrieve by ID",
        ],
        "message": f"Personal edition ready. User: {user_id}",
    }

    # On-connect dreaming: drain pending extraction via sampling
    try:
        dreaming_result = await _drain_pending(ctx)
        if dreaming_result:
            response["dreaming"] = dreaming_result
    except Exception as exc:
        logger.warning("On-connect dreaming failed: %s", exc)
        response["dreaming"] = {"error": str(exc)}

    return response


async def _drain_pending(ctx: Context) -> dict[str, Any] | None:
    """Check for pending threads and extract via sampling."""
    from memoryhub_local.services.extraction import (
        EXTRACTION_SYSTEM_PROMPT,
        ExtractionResult,
        extract_from_thread,
        get_pending_threads,
    )
    from memoryhub_local.tools._state import get_state

    state = get_state()

    async with state.session_factory() as session:
        pending = await get_pending_threads(session)

    if not pending:
        return None

    async def _sampling_llm(messages_text: str) -> list[dict]:
        result = await asyncio.wait_for(
            ctx.sample(
                messages=EXTRACTION_SYSTEM_PROMPT + "\n\n" + messages_text,
                result_type=ExtractionResult,
                temperature=0.0,
                max_tokens=4000,
            ),
            timeout=_DREAMING_TIMEOUT,
        )
        if not result.result:
            return []
        return [item.model_dump() for item in result.result.extractions]

    results = []
    for thread_info in pending[:_MAX_DRAIN_DEFAULT]:
        try:
            async with state.session_factory() as session:
                r = await extract_from_thread(
                    session,
                    thread_info["id"],
                    llm_fn=_sampling_llm,
                    embedding_service=state.embedding_service,
                    recall_backend=state.recall_backend,
                )
                results.append({
                    "thread_id": thread_info["id"],
                    "extracted_count": r.get("extracted_count", 0),
                })
        except Exception as exc:
            logger.warning("Dreaming failed for thread %s: %s", thread_info["id"], exc)
            results.append({
                "thread_id": thread_info["id"],
                "error": str(exc),
            })

    total_extracted = sum(r.get("extracted_count", 0) for r in results)
    return {
        "pending_threads": len(pending),
        "threads_drained": len(results),
        "total_extracted": total_extracted,
        "results": results,
    }
