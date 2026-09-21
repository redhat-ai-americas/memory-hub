"""Localized procedural subgraphs and natural-language guidance (#553).

Traversal stays in ``graph.py``. This module loads a bounded neighborhood,
renders it as text, and asks the Stage-3 LLM (``llm_extraction_*``) for
prose guidance. Generation is synchronous and uncached.

``generate_guidance`` takes an already-built subgraph so the walk can be
tested without a model. The model sees only ``render_subgraph_context``
output plus the system prompt.
"""

import asyncio
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import yaml
from sqlalchemy.ext.asyncio import AsyncSession

from memoryhub_core.config import AppSettings
from memoryhub_core.models.schemas import MemoryNodeRead, RelationshipRead
from memoryhub_core.services.exceptions import (
    GuidanceAccessDeniedError,
    LLMExtractionServiceError,
    LLMExtractionServiceUnavailableError,
)
from memoryhub_core.services.graph import (
    _MAX_HOPS_CAP,
    PROCEDURAL_RELATIONSHIP_TYPES,
    _fetch_current_node,
    find_related,
)
from memoryhub_core.services.memory import node_to_read

logger = logging.getLogger(__name__)

# Same budgets as _LLMExtractor. Format retries cover empty or truncated
# prose; service retries cover connection and overload failures.
_MAX_FORMAT_RETRIES = 3
_MAX_SERVICE_RETRIES = 2

_NODE_SCALARS = ("action", "tool_ref", "guidance")
_NODE_LISTS = ("preconditions", "postconditions", "pitfalls")
_EDGE_SCALARS = ("condition", "guidance")
_EDGE_LISTS = ("pitfalls",)


@dataclass(frozen=True)
class LocalizedSubgraph:
    """Current step plus the neighbors ``find_related`` returned.

    The current node is the subject of the guidance. It is not a neighbor
    and does not appear in ``neighbors``.
    """

    current: MemoryNodeRead
    neighbors: list[dict[str, Any]]
    max_hops: int
    relationship_types: list[str]


@dataclass(frozen=True)
class GuidanceResult:
    """Prose plus the subgraph the model actually saw.

    ``omitted_count`` is neighbors dropped because the caller cannot read
    them (or because the path to them crosses such a neighbor). It is 0
    when no read check was applied.
    """

    subgraph: LocalizedSubgraph
    guidance_text: str
    omitted_count: int = 0

    def to_payload(self) -> dict[str, Any]:
        """The ``manage_graph`` / ``get_guidance`` response body."""
        payload = {
            "node_id": str(self.subgraph.current.id),
            "guidance_text": self.guidance_text,
            "neighborhood": neighborhood_payload(self.subgraph),
            "hop_count": hop_count(self.subgraph),
        }
        if self.omitted_count:
            payload["omitted_count"] = self.omitted_count
        return payload


def hop_count(subgraph: LocalizedSubgraph) -> int:
    """Largest distance actually returned, or 0 when the step is isolated."""
    if not subgraph.neighbors:
        return 0
    return max(int(item["distance"]) for item in subgraph.neighbors)


def neighborhood_payload(subgraph: LocalizedSubgraph) -> dict[str, Any]:
    """JSON-ready ``{nodes, edges}`` for the current node and its neighborhood.

    ``nodes[0]`` is the current step. Later nodes follow ``find_related``
    order. Edges carry the hop's direction and role from the first time
    that edge was traversed (the shortest path).
    """
    nodes = [subgraph.current.model_dump(mode="json")]
    seen_nodes = {str(subgraph.current.id)}
    edges: list[dict[str, Any]] = []
    seen_edges: set[str] = set()

    for neighbor in subgraph.neighbors:
        node = neighbor["node"]
        dumped = node.model_dump(mode="json")
        node_id = str(dumped["id"])
        if node_id not in seen_nodes:
            seen_nodes.add(node_id)
            nodes.append(dumped)
        for hop in neighbor["path"]:
            relationship = hop["relationship"]
            edge = relationship.model_dump(mode="json")
            edge_id = str(edge["id"])
            if edge_id in seen_edges:
                continue
            seen_edges.add(edge_id)
            edge["direction"] = hop["direction"]
            edge["role"] = hop["role"]
            edge["from_id"] = str(hop["from_id"])
            edge["to_id"] = str(hop["to_id"])
            edges.append(edge)

    return {"nodes": nodes, "edges": edges}


async def build_localized_subgraph(
    node_id: uuid.UUID,
    session: AsyncSession,
    *,
    tenant_id: str,
    max_hops: int = 2,
    relationship_types: list[str] | None = None,
) -> LocalizedSubgraph:
    """Load ``node_id`` and its procedural neighborhood.

    ``node_id`` is the current step. This does not guess an entry step;
    call ``resolve_procedure_entry`` first when the caller only has a
    procedure root. Relationship types default to the three procedural
    ones so a ``related_to`` edge cannot enter an execution prompt.
    ``find_related`` itself stays unfiltered unless a caller asks.
    """
    applied = min(max(max_hops, 0), _MAX_HOPS_CAP)
    types = list(PROCEDURAL_RELATIONSHIP_TYPES if relationship_types is None else relationship_types)
    current = await _fetch_current_node(node_id, session, tenant_id=tenant_id)
    neighbors = await find_related(
        node_id,
        session,
        tenant_id=tenant_id,
        max_hops=applied,
        relationship_types=types,
    )
    return LocalizedSubgraph(
        current=node_to_read(current, has_children=False, has_rationale=False),
        neighbors=neighbors,
        max_hops=applied,
        relationship_types=types,
    )


def render_subgraph_context(subgraph: LocalizedSubgraph) -> str:
    """Render the subgraph as the user message. Omits empty recorded fields.

    A missing pitfalls or preconditions list produces no line at all, so
    the model is not handed a blank to fill in.
    """
    lines = ["CURRENT STEP", *_node_lines(subgraph.current)]
    for neighbor in subgraph.neighbors:
        lines.append("")
        lines.append(f"NEIGHBOR distance={neighbor['distance']}")
        lines.extend(_node_lines(neighbor["node"]))
        lines.append("path:")
        for index, hop in enumerate(neighbor["path"], start=1):
            lines.append(_hop_line(index, hop))
            lines.extend(_edge_fact_lines(hop["relationship"]))
    return "\n".join(lines).rstrip() + "\n"


def _procedure_fields(node: MemoryNodeRead) -> dict[str, Any]:
    metadata = node.metadata if isinstance(node.metadata, dict) else {}
    procedure = metadata.get("procedure")
    return procedure if isinstance(procedure, dict) else {}


def _node_lines(node: MemoryNodeRead) -> list[str]:
    lines = [f"id: {node.id}", f"content: {node.content}"]
    if node.content_truncated:
        lines.append("content_truncated: true")
    procedure = _procedure_fields(node)
    for label in _NODE_SCALARS:
        lines.extend(_scalar_line(label, procedure.get(label)))
    for label in _NODE_LISTS:
        lines.extend(_list_lines(label, procedure.get(label)))
    return lines


def _hop_line(index: int, hop: dict[str, Any]) -> str:
    relationship = hop["relationship"]
    rel_type = str(relationship.relationship_type)
    return (
        f"- hop {index}: from {hop['from_id']} to {hop['to_id']} "
        f"via {rel_type} ({hop['direction']}); "
        f"role of {hop['to_id']} relative to {hop['from_id']}: {hop['role']}"
    )


def _edge_fact_lines(relationship: RelationshipRead) -> list[str]:
    metadata = relationship.metadata if isinstance(relationship.metadata, dict) else {}
    lines: list[str] = []
    for label in _EDGE_SCALARS:
        for line in _scalar_line(label, metadata.get(label)):
            lines.append(f"  {line}")
    for label in _EDGE_LISTS:
        for line in _list_lines(label, metadata.get(label)):
            lines.append(f"  {line}")
    return lines


def _scalar_line(label: str, value: Any) -> list[str]:
    if not isinstance(value, str) or not value.strip():
        return []
    return [f"{label}: {value.strip()}"]


def _list_lines(label: str, value: Any) -> list[str]:
    items: list[str] = []
    if isinstance(value, str) and value.strip():
        items = [value.strip()]
    elif isinstance(value, list):
        items = [str(item).strip() for item in value if str(item).strip()]
    if not items:
        return []
    return [f"{label}:", *[f"- {item}" for item in items]]


class _GuidanceGenerator:
    """Stage-3 chat completion client for prose guidance.

    Mirrors ``_LLMExtractor``: httpx, YAML system prompt, format retry,
    and service-error backoff. There is no JSON schema to validate.
    """

    def __init__(self) -> None:
        settings = AppSettings()
        self.url = settings.llm_extraction_url.strip().rstrip("/")
        self.model = settings.llm_extraction_model
        self._client = httpx.AsyncClient(
            timeout=settings.llm_extraction_timeout,
            verify=False,  # cluster-internal TLS, same as Stage-3 extraction
        )
        prompt_path = Path(__file__).resolve().parents[3] / "prompts" / "procedural_guidance.yaml"
        with open(prompt_path) as handle:
            data = yaml.safe_load(handle)
        self._system_prompt = data["system_prompt"]
        self._temperature, self._max_tokens = _prompt_parameters(data)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def generate(self, subgraph: LocalizedSubgraph) -> str:
        if not self.url:
            raise LLMExtractionServiceUnavailableError("LLM extraction URL is not configured")

        user_content = render_subgraph_context(subgraph)
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self._system_prompt},
            {"role": "user", "content": user_content},
        ]
        last_error: Exception | None = None

        for attempt in range(_MAX_FORMAT_RETRIES):
            content, finish_reason = await self._call_llm(messages)
            if _usable_guidance(content, finish_reason):
                return content.strip()

            reason = "Response was empty" if not content.strip() else "Response was truncated (finish_reason=length)"
            logger.warning(
                "Procedural guidance format error (attempt %d/%d): %s",
                attempt + 1,
                _MAX_FORMAT_RETRIES,
                reason,
            )
            messages = _inject_correction(messages, content, reason)
            last_error = LLMExtractionServiceError(reason)
            if attempt < _MAX_FORMAT_RETRIES - 1:
                await _backoff_sleep(2**attempt)

        raise last_error or LLMExtractionServiceError("Guidance generation failed after all retries")

    async def _call_llm(self, messages: list[dict[str, Any]]) -> tuple[str, str | None]:
        last_error: Exception | None = None

        for attempt in range(_MAX_SERVICE_RETRIES):
            try:
                response = await self._client.post(
                    f"{self.url}/v1/chat/completions",
                    json={
                        "model": self.model,
                        "messages": messages,
                        "temperature": self._temperature,
                        "max_tokens": self._max_tokens,
                    },
                )
                response.raise_for_status()
            except httpx.ConnectError as exc:
                last_error = LLMExtractionServiceUnavailableError("Could not connect to LLM extraction service")
                last_error.__cause__ = exc
            except httpx.TimeoutException as exc:
                last_error = LLMExtractionServiceUnavailableError("LLM extraction request timed out")
                last_error.__cause__ = exc
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                if status in (429, 502, 503, 504):
                    last_error = LLMExtractionServiceUnavailableError(f"LLM service returned {status}")
                    last_error.__cause__ = exc
                else:
                    raise LLMExtractionServiceError(f"LLM extraction failed with status {status}") from exc
            else:
                try:
                    choice = response.json()["choices"][0]
                    message = choice["message"]
                    content = message.get("content") or ""
                    finish_reason = choice.get("finish_reason")
                except (KeyError, IndexError, TypeError, ValueError) as exc:
                    raise LLMExtractionServiceError(f"Unexpected response structure: {exc}") from exc
                if not isinstance(content, str):
                    content = str(content)
                return content, finish_reason

            if attempt < _MAX_SERVICE_RETRIES - 1:
                delay = (2**attempt) * 2.0
                logger.warning(
                    "LLM service error (attempt %d/%d): %s — retrying in %.0fs",
                    attempt + 1,
                    _MAX_SERVICE_RETRIES,
                    last_error,
                    delay,
                )
                await _backoff_sleep(delay)

        raise last_error or LLMExtractionServiceUnavailableError("LLM service unavailable after all retries")


def _prompt_parameters(data: dict[str, Any]) -> tuple[float, int]:
    temperature = 0.0
    max_tokens = 800
    for item in data.get("parameters") or []:
        if not isinstance(item, dict):
            continue
        if "temperature" in item:
            temperature = float(item["temperature"])
        if "max_tokens" in item:
            max_tokens = int(item["max_tokens"])
    return temperature, max_tokens


def _usable_guidance(content: str, finish_reason: str | None) -> bool:
    if finish_reason == "length":
        return False
    return bool(content.strip())


def _inject_correction(messages: list[dict[str, Any]], bad_response: str, reason: str) -> list[dict[str, Any]]:
    return [
        *messages,
        {"role": "assistant", "content": bad_response},
        {
            "role": "user",
            "content": (
                f"That response cannot be used as guidance: {reason}. "
                "Return concise plain text. Use only the subgraph in the original "
                "user message. Do not add steps, transitions, conditions, tools, or "
                "prerequisites that are not in that subgraph. If a field was omitted, "
                "do not invent a value for it. Keep each hop's role exactly as labeled."
            ),
        },
    ]


async def _backoff_sleep(delay: float) -> None:
    await asyncio.sleep(delay)


async def generate_guidance(
    localized_subgraph: LocalizedSubgraph,
    *,
    generator: _GuidanceGenerator | None = None,
) -> str:
    """Generate prose guidance for an already-localized subgraph."""
    if generator is not None:
        return await generator.generate(localized_subgraph)

    owned = _GuidanceGenerator()
    try:
        return await owned.generate(localized_subgraph)
    finally:
        await owned.aclose()


def restrict_subgraph(
    subgraph: LocalizedSubgraph,
    readable_ids: set[uuid.UUID],
) -> LocalizedSubgraph:
    """Drop neighbors the caller cannot read, and anything reached through them.

    The current node is left in place. A hop-2 neighbor stays only when
    every ``to_id`` on its path is still readable, so an unreadable
    intermediate cannot leak into the prompt as a path step.
    """
    allowed = {uuid.UUID(str(node_id)) for node_id in readable_ids}
    blocked = {item["node"].id for item in subgraph.neighbors if item["node"].id not in allowed}
    kept: list[dict[str, Any]] = []
    for item in subgraph.neighbors:
        if item["node"].id in blocked:
            continue
        if {hop["to_id"] for hop in item["path"]} & blocked:
            continue
        kept.append(item)
    return LocalizedSubgraph(
        current=subgraph.current,
        neighbors=kept,
        max_hops=subgraph.max_hops,
        relationship_types=list(subgraph.relationship_types),
    )


async def localized_guidance(
    node_id: uuid.UUID,
    session: AsyncSession,
    *,
    tenant_id: str,
    max_hops: int = 2,
    relationship_types: list[str] | None = None,
    authorize: Callable[[MemoryNodeRead], bool] | None = None,
    generator: _GuidanceGenerator | None = None,
) -> GuidanceResult:
    """Build a neighborhood, drop unreadable neighbors, and generate prose.

    Both retrieval surfaces call this. ``authorize`` is the tool-layer
    read check. When it rejects the current step this raises
    ``GuidanceAccessDeniedError`` and does not call the model. When it
    is omitted, every tenant-visible neighbor is kept — service tests
    use that. The model sees only the subgraph returned in
    ``GuidanceResult.subgraph``.
    """
    subgraph = await build_localized_subgraph(
        node_id,
        session,
        tenant_id=tenant_id,
        max_hops=max_hops,
        relationship_types=relationship_types,
    )
    omitted = 0
    if authorize is not None:
        if not authorize(subgraph.current):
            raise GuidanceAccessDeniedError(subgraph.current.id)
        before = len(subgraph.neighbors)
        readable = {item["node"].id for item in subgraph.neighbors if authorize(item["node"])}
        subgraph = restrict_subgraph(subgraph, readable)
        omitted = before - len(subgraph.neighbors)
    text = await generate_guidance(subgraph, generator=generator)
    return GuidanceResult(subgraph=subgraph, guidance_text=text, omitted_count=omitted)
