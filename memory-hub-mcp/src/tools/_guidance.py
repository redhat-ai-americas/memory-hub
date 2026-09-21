"""Shared tool-layer entry for localized procedural guidance (#553).

``search_memory`` and ``manage_graph(action="get_guidance")`` both call
``run_guidance``. The walk and the model call live in
``localized_guidance``; this module only translates service errors into
``ToolError`` and shapes the search response.
"""

import uuid
from collections.abc import Callable
from typing import Any

from fastmcp.exceptions import ToolError
from sqlalchemy.ext.asyncio import AsyncSession

from memoryhub_core.models.schemas import MemoryNodeRead
from memoryhub_core.services.exceptions import (
    GuidanceAccessDeniedError,
    LLMExtractionServiceError,
    LLMExtractionServiceUnavailableError,
    MemoryNotFoundError,
)
from memoryhub_core.services.procedural_guidance import (
    GuidanceResult,
    hop_count,
    localized_guidance,
    neighborhood_payload,
)

_MAX_HOPS = 5


def _parse_node_id(node_id: str) -> uuid.UUID:
    try:
        return uuid.UUID(node_id.strip())
    except (AttributeError, ValueError):
        raise ToolError(f"Invalid node id {node_id!r}. Must be a valid UUID.") from None


def _parse_max_hops(max_hops: int) -> int:
    if isinstance(max_hops, bool) or not isinstance(max_hops, int) or not 0 <= max_hops <= _MAX_HOPS:
        raise ToolError(f"max_hops must be an integer between 0 and {_MAX_HOPS}.")
    return max_hops


async def run_guidance(
    node_id: str,
    session: AsyncSession,
    *,
    tenant_id: str,
    max_hops: int = 2,
    authorize: Callable[[MemoryNodeRead], bool],
) -> GuidanceResult:
    """Resolve one step and return the guidance the model produced.

    ``authorize`` is ``authorize_read`` bound to the caller's claims.
    It runs before the model sees the subgraph.
    """
    parsed = _parse_node_id(node_id)
    hops = _parse_max_hops(max_hops)
    try:
        return await localized_guidance(
            parsed,
            session,
            tenant_id=tenant_id,
            max_hops=hops,
            authorize=authorize,
        )
    except MemoryNotFoundError:
        raise ToolError(f"Memory node {node_id} not found.") from None
    except GuidanceAccessDeniedError as exc:
        raise ToolError(str(exc)) from None
    except LLMExtractionServiceUnavailableError as exc:
        raise ToolError(
            f"Procedural guidance is unavailable: {exc}. Search without current_step_id still works."
        ) from exc
    except LLMExtractionServiceError as exc:
        raise ToolError(f"Procedural guidance failed: {exc}") from exc


def search_guidance_response(
    result: GuidanceResult,
    *,
    graph_depth: int = 0,
    focus: str | None = None,
    domains: list[str] | None = None,
    entities: list[str] | None = None,
    graph_relationship_types: list[str] | None = None,
) -> dict[str, Any]:
    """One ``results`` entry. Not a ranked memory, so it skips ``_format_entry``.

    ``query`` is always listed in ``ignored_parameters``. Other ranking
    inputs are listed only when the caller actually set them.
    """
    entry = {
        "id": str(result.subgraph.current.id),
        "content": result.guidance_text,
        "result_type": "guidance",
        "guidance_text": result.guidance_text,
        "neighborhood": neighborhood_payload(result.subgraph),
        "hop_count": hop_count(result.subgraph),
    }
    ignored = ["query"]
    if graph_depth > 0:
        ignored.append("graph_depth")
    if graph_relationship_types:
        ignored.append("graph_relationship_types")
    if focus is not None and str(focus).strip():
        ignored.append("focus")
    if domains:
        ignored.append("domains")
    if entities:
        ignored.append("entities")
    response: dict[str, Any] = {
        "results": [entry],
        "total_matching": 1,
        "has_more": False,
        "query_ignored": True,
        "ignored_parameters": ignored,
    }
    if result.omitted_count:
        response["omitted_count"] = result.omitted_count
    return response
