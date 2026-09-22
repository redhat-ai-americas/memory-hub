"""Guidance rendering and mocked Stage-3 generation (#553).

The model is never called. Tests assert what the prompt is given: every
neighbor that is in the subgraph, no neighbor that is not, and no invented
pitfalls or preconditions for a step that recorded none.
"""

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import yaml

from memoryhub_core.models.schemas import (
    ContentType,
    MemoryNodeCreate,
    MemoryScope,
    RelationshipCreate,
    RelationshipRead,
    RelationshipType,
    StorageType,
)
from memoryhub_core.services.exceptions import (
    GuidanceAccessDeniedError,
    LLMExtractionServiceError,
    LLMExtractionServiceUnavailableError,
)
from memoryhub_core.services.graph import PROCEDURAL_RELATIONSHIP_TYPES, create_relationship
from memoryhub_core.services.memory import create_memory as _svc_create_memory
from memoryhub_core.services.procedural_guidance import (
    LocalizedSubgraph,
    _GuidanceGenerator,
    build_localized_subgraph,
    compact_neighborhood_payload,
    generate_guidance,
    hop_count,
    localized_guidance,
    neighborhood_payload,
    render_subgraph_context,
    restrict_subgraph,
)

_TENANT = "tenant_a"
_PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "procedural_guidance.yaml"


def _memory_node(content, **overrides):
    from memoryhub_core.models.schemas import MemoryNodeRead

    now = datetime.now(UTC)
    data = {
        "id": uuid.uuid4(),
        "parent_id": None,
        "content": content,
        "stub": content[:80],
        "storage_type": StorageType.INLINE,
        "content_ref": None,
        "weight": 0.7,
        "scope": MemoryScope.USER,
        "branch_type": "procedure_step",
        "owner_id": "user-123",
        "tenant_id": _TENANT,
        "is_current": True,
        "version": 1,
        "previous_version_id": None,
        "created_at": now,
        "updated_at": now,
        "content_type": ContentType.PROCEDURAL,
    }
    data.update(overrides)
    return MemoryNodeRead(**data)


def _edge(source_id, target_id, rel_type, metadata=None) -> RelationshipRead:
    return RelationshipRead(
        id=uuid.uuid4(),
        source_id=source_id,
        target_id=target_id,
        relationship_type=rel_type,
        metadata=metadata,
        created_at=datetime.now(UTC),
        created_by="agent-test",
        tenant_id=_TENANT,
    )


def _hop(relationship, *, direction, role, from_id, to_id):
    return {
        "relationship": relationship,
        "direction": direction,
        "role": role,
        "from_id": from_id,
        "to_id": to_id,
    }


def _subgraph(current, neighbors, max_hops=2) -> LocalizedSubgraph:
    return LocalizedSubgraph(
        current=current,
        neighbors=neighbors,
        max_hops=max_hops,
        relationship_types=list(PROCEDURAL_RELATIONSHIP_TYPES),
    )


def _sections(rendered: str) -> list[str]:
    sections: list[list[str]] = []
    current: list[str] = []
    for line in rendered.splitlines():
        if line.startswith("CURRENT STEP") or line.startswith("NEIGHBOR "):
            if current:
                sections.append(current)
            current = [line]
        else:
            current.append(line)
    if current:
        sections.append(current)
    return ["\n".join(lines) for lines in sections]


def _http_response(content, *, status=200, finish_reason="stop", payload=None):
    if payload is None:
        payload = {"choices": [{"message": {"content": content}, "finish_reason": finish_reason}]}
    return httpx.Response(
        status,
        content=json.dumps(payload).encode(),
        request=httpx.Request("POST", "http://llm.test/v1/chat/completions"),
    )


async def _generate(subgraph, side_effect, env=None):
    settings = {
        "MEMORYHUB_LLM_EXTRACTION_URL": "http://llm.test",
        "MEMORYHUB_LLM_EXTRACTION_MODEL": "guidance-model",
    }
    if env:
        settings.update(env)
    mock_post = AsyncMock(side_effect=side_effect)
    with (
        patch.dict("os.environ", settings),
        patch("httpx.AsyncClient.post", mock_post),
        patch(
            "memoryhub_core.services.procedural_guidance._backoff_sleep",
            new_callable=AsyncMock,
        ) as mock_sleep,
    ):
        generator = _GuidanceGenerator()
        try:
            text = await generate_guidance(subgraph, generator=generator)
        finally:
            await generator.aclose()
    return text, mock_post, mock_sleep


def _sample_subgraph():
    current = _memory_node(
        "Run the pre-deploy smoke test suite",
        metadata={
            "procedure": {
                "action": "Run the pre-deploy smoke test suite",
                "pitfalls": ["flaky test_cache_warmup fails sometimes"],
                "preconditions": ["staging environment is healthy"],
            }
        },
    )
    successor = _memory_node(
        "Promote the image to staging",
        metadata={"procedure": {"action": "Promote the image to staging", "pitfalls": [], "preconditions": []}},
    )
    edge = _edge(
        current.id,
        successor.id,
        RelationshipType.precedes,
        metadata={"condition": "smoke tests passed", "pitfalls": []},
    )
    neighbor = {
        "node": successor,
        "distance": 1,
        "path": [
            _hop(
                edge,
                direction="outgoing",
                role="successor",
                from_id=current.id,
                to_id=successor.id,
            )
        ],
    }
    return _subgraph(current, [neighbor]), successor


# -- prompt file --


def test_prompt_file_constrains_invention():
    data = yaml.safe_load(_PROMPT_PATH.read_text())
    prompt = data["system_prompt"]
    assert "Do not introduce steps" in prompt
    assert "Do not fill gaps" in prompt
    assert "prerequisite is never a next step" in prompt
    assert "Distinguish the current step" in prompt
    assert "concise" in prompt.lower()
    assert data["parameters"] == [{"temperature": 0.0}, {"max_tokens": 800}]


# -- rendering --


def test_render_includes_recorded_facts_and_omits_empty_fields():
    subgraph, successor = _sample_subgraph()
    rendered = render_subgraph_context(subgraph)
    sections = _sections(rendered)

    assert sections[0].startswith("CURRENT STEP")
    assert "flaky test_cache_warmup fails sometimes" in sections[0]
    assert "staging environment is healthy" in sections[0]
    assert "Run the pre-deploy smoke test suite" in sections[0]

    neighbor = sections[1]
    assert neighbor.startswith("NEIGHBOR distance=1")
    assert str(successor.id) in neighbor
    assert "Promote the image to staging" in neighbor
    assert "pitfalls" not in neighbor.lower()
    assert "preconditions" not in neighbor.lower()
    assert "smoke tests passed" in neighbor
    assert f"role of {successor.id} relative to {subgraph.current.id}: successor" in neighbor
    assert "BETA_SHOULD_NOT_APPEAR" not in rendered


def test_render_keeps_two_hop_chain_literal():
    current = _memory_node("current step")
    mid = _memory_node("middle step", metadata={"procedure": {"action": "Middle action"}})
    needed = _memory_node("needed step", metadata={"procedure": {"action": "Needed action"}})
    first = _edge(current.id, mid.id, RelationshipType.precedes)
    second = _edge(mid.id, needed.id, RelationshipType.requires)
    neighbor = {
        "node": needed,
        "distance": 2,
        "path": [
            _hop(first, direction="outgoing", role="successor", from_id=current.id, to_id=mid.id),
            _hop(second, direction="outgoing", role="prerequisite", from_id=mid.id, to_id=needed.id),
        ],
    }
    rendered = render_subgraph_context(_subgraph(current, [neighbor]))
    section = _sections(rendered)[1]
    assert "via precedes (outgoing)" in section
    assert "via requires (outgoing)" in section
    assert f"role of {mid.id} relative to {current.id}: successor" in section
    assert f"role of {needed.id} relative to {mid.id}: prerequisite" in section
    assert "Needed action" in section
    assert "Middle action" not in section


def test_render_does_not_list_the_current_node_as_a_neighbor():
    current = _memory_node("only the current step")
    rendered = render_subgraph_context(_subgraph(current, []))
    assert rendered.startswith("CURRENT STEP")
    assert "NEIGHBOR " not in rendered
    assert str(current.id) in rendered


def test_neighborhood_payload_includes_current_and_dedups_edges():
    current = _memory_node("current step")
    mid = _memory_node("middle step")
    needed = _memory_node("needed step")
    first = _edge(current.id, mid.id, RelationshipType.precedes)
    second = _edge(mid.id, needed.id, RelationshipType.requires)
    first_hop = _hop(first, direction="outgoing", role="successor", from_id=current.id, to_id=mid.id)
    second_hop = _hop(second, direction="outgoing", role="prerequisite", from_id=mid.id, to_id=needed.id)
    subgraph = _subgraph(
        current,
        [
            {"node": mid, "distance": 1, "path": [first_hop]},
            {"node": needed, "distance": 2, "path": [first_hop, second_hop]},
        ],
    )
    payload = neighborhood_payload(subgraph)
    assert payload["nodes"][0]["id"] == str(current.id)
    assert [node["id"] for node in payload["nodes"]] == [str(current.id), str(mid.id), str(needed.id)]
    assert len(payload["edges"]) == 2
    assert payload["edges"][0]["role"] == "successor"
    assert payload["edges"][0]["from_id"] == str(current.id)
    assert hop_count(subgraph) == 2


def test_compact_payload_keeps_structure_and_drops_bulk():
    """The search-path projection: enough to render the graph, nothing to inject.

    The full payload dumps every MemoryNodeRead field, which for a 2-hop
    neighborhood is orders of magnitude larger than the prose it
    accompanies. That is the full-graph injection localized retrieval
    exists to avoid, so search sends this instead (#553, Decision 5).
    """
    current = _memory_node("current step")
    mid = _memory_node("middle step")
    first = _edge(current.id, mid.id, RelationshipType.precedes)
    hop = _hop(first, direction="outgoing", role="successor", from_id=current.id, to_id=mid.id)
    subgraph = _subgraph(current, [{"node": mid, "distance": 1, "path": [hop]}])

    compact = compact_neighborhood_payload(subgraph)

    assert compact["detail"] == "compact"
    assert [node["id"] for node in compact["nodes"]] == [str(current.id), str(mid.id)]
    # Structure survives: a client can still name a step and draw the edge.
    assert compact["nodes"][1]["stub"] == mid.stub
    assert compact["edges"][0]["role"] == "successor"
    assert compact["edges"][0]["direction"] == "outgoing"
    assert compact["edges"][0]["relationship_type"] == "precedes"
    # Bulk does not.
    for node in compact["nodes"]:
        assert "content" not in node
        assert "metadata" not in node
        assert "created_at" not in node
    for edge in compact["edges"]:
        assert "metadata_" not in edge
        assert "metadata" not in edge


def test_compact_payload_is_much_smaller_than_the_full_one():
    """The size difference is the whole reason the projection exists."""
    import json

    current = _memory_node("current step with a realistic amount of recorded detail")
    neighbors = []
    for index in range(5):
        node = _memory_node(f"neighbor step {index} with its own recorded detail")
        edge = _edge(current.id, node.id, RelationshipType.precedes)
        hop = _hop(edge, direction="outgoing", role="successor", from_id=current.id, to_id=node.id)
        neighbors.append({"node": node, "distance": 1, "path": [hop]})
    subgraph = _subgraph(current, neighbors)

    full_size = len(json.dumps(neighborhood_payload(subgraph)))
    compact_size = len(json.dumps(compact_neighborhood_payload(subgraph)))

    assert compact_size * 3 < full_size, (
        f"compact payload {compact_size}B should be far smaller than full {full_size}B"
    )


# -- subgraph loading --


async def _create_node(session, embedding_service, **overrides):
    defaults = {
        "content": "procedural step",
        "scope": MemoryScope.USER,
        "weight": 0.9,
        "owner_id": "user-123",
        "content_type": ContentType.PROCEDURAL,
    }
    defaults.update(overrides)
    node, _ = await _svc_create_memory(
        MemoryNodeCreate(**defaults),
        session,
        embedding_service,
        tenant_id=_TENANT,
        skip_curation=True,
    )
    return node


def _rel(source_id, target_id, rel_type, metadata=None):
    return RelationshipCreate(
        source_id=source_id,
        target_id=target_id,
        relationship_type=rel_type,
        created_by="agent-test",
        metadata=metadata,
    )


@pytest.mark.asyncio
async def test_build_localized_subgraph_defaults_to_procedural_edges(async_session, embedding_service):
    current = await _create_node(
        async_session,
        embedding_service,
        content="Run the smoke tests",
        metadata={
            "procedure": {
                "action": "Run the smoke tests",
                "pitfalls": ["flaky test_cache_warmup"],
            }
        },
    )
    nxt = await _create_node(
        async_session,
        embedding_service,
        content="Promote the image",
        metadata={"procedure": {"action": "Promote the image"}},
    )
    aside = await _create_node(async_session, embedding_service, content="unrelated note about cheese")
    far = await _create_node(async_session, embedding_service, content="verify health")
    await create_relationship(
        _rel(current.id, nxt.id, RelationshipType.precedes, metadata={"condition": "smoke tests passed"}),
        async_session,
    )
    await create_relationship(_rel(current.id, aside.id, RelationshipType.related_to), async_session)
    await create_relationship(_rel(nxt.id, far.id, RelationshipType.precedes), async_session)

    subgraph = await build_localized_subgraph(current.id, async_session, tenant_id=_TENANT)
    neighbor_ids = {item["node"].id for item in subgraph.neighbors}
    assert subgraph.current.id == current.id
    assert current.id not in neighbor_ids
    assert neighbor_ids == {nxt.id, far.id}
    assert aside.id not in neighbor_ids
    assert subgraph.relationship_types == list(PROCEDURAL_RELATIONSHIP_TYPES)
    assert hop_count(subgraph) == 2

    rendered = render_subgraph_context(subgraph)
    assert "flaky test_cache_warmup" in rendered
    assert "smoke tests passed" in rendered
    assert "Promote the image" in rendered
    assert "unrelated note about cheese" not in rendered

    shallow = await build_localized_subgraph(current.id, async_session, tenant_id=_TENANT, max_hops=1)
    assert {item["node"].id for item in shallow.neighbors} == {nxt.id}
    assert hop_count(shallow) == 1


# -- mocked generation --


@pytest.mark.asyncio
async def test_generate_guidance_sends_rendered_subgraph_and_stage3_settings():
    subgraph, successor = _sample_subgraph()
    rendered = render_subgraph_context(subgraph)

    async def post(url, json):
        assert url == "http://llm.test/v1/chat/completions"
        assert json["model"] == "guidance-model"
        assert json["temperature"] == 0.0
        assert json["max_tokens"] == 800
        assert "response_format" not in json
        assert json["messages"][0]["content"] == yaml.safe_load(_PROMPT_PATH.read_text())["system_prompt"]
        assert json["messages"][1]["content"] == rendered
        assert "unrelated note about cheese" not in json["messages"][1]["content"]
        assert str(successor.id) in json["messages"][1]["content"]
        return _http_response("Run the smoke tests, then promote.")

    text, mock_post, _sleep = await _generate(subgraph, post)
    assert text == "Run the smoke tests, then promote."
    assert mock_post.await_count == 1


@pytest.mark.asyncio
async def test_generate_guidance_retries_empty_then_succeeds():
    subgraph, _successor = _sample_subgraph()
    responses = [_http_response("  "), _http_response("Stay on the smoke tests.")]

    text, mock_post, mock_sleep = await _generate(subgraph, responses)
    assert text == "Stay on the smoke tests."
    assert mock_post.await_count == 2
    mock_sleep.assert_awaited_once_with(1)
    retry_body = mock_post.await_args_list[1].kwargs["json"]
    assert retry_body["messages"][1]["content"] == render_subgraph_context(subgraph)
    assert "Response was empty" in retry_body["messages"][3]["content"]


@pytest.mark.asyncio
async def test_generate_guidance_retries_truncated_response():
    subgraph, _successor = _sample_subgraph()
    responses = [
        _http_response("Run the smoke", finish_reason="length"),
        _http_response("Run the smoke tests."),
    ]
    text, mock_post, _sleep = await _generate(subgraph, responses)
    assert text == "Run the smoke tests."
    assert mock_post.await_count == 2
    correction = mock_post.await_args_list[1].kwargs["json"]["messages"][3]["content"]
    assert "truncated" in correction


@pytest.mark.asyncio
async def test_generate_guidance_retries_service_error_then_succeeds():
    subgraph, _successor = _sample_subgraph()
    responses = [_http_response("busy", status=503), _http_response("Run the smoke tests.")]
    text, mock_post, mock_sleep = await _generate(subgraph, responses)
    assert text == "Run the smoke tests."
    assert mock_post.await_count == 2
    mock_sleep.assert_awaited_once_with(2.0)


@pytest.mark.asyncio
async def test_generate_guidance_does_not_retry_client_error():
    subgraph, _successor = _sample_subgraph()
    with pytest.raises(LLMExtractionServiceError, match="status 400"):
        await _generate(subgraph, [_http_response("bad", status=400)])


@pytest.mark.asyncio
async def test_generate_guidance_exhausts_empty_retries():
    subgraph, _successor = _sample_subgraph()
    with pytest.raises(LLMExtractionServiceError, match="empty"):
        await _generate(subgraph, [_http_response(""), _http_response(""), _http_response("")])


@pytest.mark.asyncio
async def test_generate_guidance_connect_error_is_unavailable():
    subgraph, _successor = _sample_subgraph()
    with pytest.raises(LLMExtractionServiceUnavailableError):
        await _generate(subgraph, httpx.ConnectError("connection refused"))


@pytest.mark.asyncio
async def test_generate_guidance_unexpected_payload_is_a_service_error():
    subgraph, _successor = _sample_subgraph()
    with pytest.raises(LLMExtractionServiceError, match="Unexpected response structure"):
        await _generate(subgraph, [_http_response("", payload={"choices": []})])


@pytest.mark.asyncio
async def test_generate_guidance_without_url_raises_and_does_not_call():
    subgraph, _successor = _sample_subgraph()
    mock_post = AsyncMock()
    with (
        patch.dict("os.environ", {"MEMORYHUB_LLM_EXTRACTION_URL": ""}),
        patch("httpx.AsyncClient.post", mock_post),
    ):
        generator = _GuidanceGenerator()
        try:
            with pytest.raises(LLMExtractionServiceUnavailableError, match="not configured"):
                await generate_guidance(subgraph, generator=generator)
        finally:
            await generator.aclose()
    mock_post.assert_not_awaited()


class _FakeGenerator:
    def __init__(self) -> None:
        self.seen = None

    async def generate(self, subgraph):
        self.seen = subgraph
        return "Run the smoke tests, then promote the image."

    async def aclose(self) -> None:
        return None


def test_restrict_subgraph_drops_unreadable_intermediate_and_what_it_reaches():
    current = _memory_node("current")
    mid = _memory_node("secret intermediate")
    far = _memory_node("reached through the secret")
    direct = _memory_node("visible successor")
    mid_edge = _edge(current.id, mid.id, RelationshipType.precedes)
    far_edge = _edge(mid.id, far.id, RelationshipType.precedes)
    direct_edge = _edge(current.id, direct.id, RelationshipType.precedes)
    subgraph = _subgraph(
        current,
        [
            {
                "node": mid,
                "path": [_hop(mid_edge, direction="outgoing", role="successor", from_id=current.id, to_id=mid.id)],
                "distance": 1,
            },
            {
                "node": far,
                "path": [
                    _hop(mid_edge, direction="outgoing", role="successor", from_id=current.id, to_id=mid.id),
                    _hop(far_edge, direction="outgoing", role="successor", from_id=mid.id, to_id=far.id),
                ],
                "distance": 2,
            },
            {
                "node": direct,
                "path": [
                    _hop(direct_edge, direction="outgoing", role="successor", from_id=current.id, to_id=direct.id)
                ],
                "distance": 1,
            },
        ],
    )

    visible = restrict_subgraph(subgraph, {direct.id})
    assert visible.current.id == current.id
    assert [item["node"].id for item in visible.neighbors] == [direct.id]
    rendered = render_subgraph_context(visible)
    assert "secret intermediate" not in rendered
    assert "reached through the secret" not in rendered
    assert "visible successor" in rendered


@pytest.mark.asyncio
async def test_localized_guidance_omits_unreadable_neighbor_before_generation(async_session, embedding_service):
    current = await _create_node(async_session, embedding_service, content="Run the smoke tests")
    hidden = await _create_node(async_session, embedding_service, content="secret prerequisite")
    visible = await _create_node(async_session, embedding_service, content="Promote the image")
    await create_relationship(
        _rel(hidden.id, current.id, RelationshipType.requires),
        async_session,
    )
    await create_relationship(
        _rel(current.id, visible.id, RelationshipType.precedes),
        async_session,
    )
    fake = _FakeGenerator()

    result = await localized_guidance(
        current.id,
        async_session,
        tenant_id=_TENANT,
        authorize=lambda node: node.id != hidden.id,
        generator=fake,
    )

    assert result.guidance_text.startswith("Run the smoke tests")
    assert result.omitted_count == 1
    assert fake.seen is result.subgraph
    assert {item["node"].id for item in result.subgraph.neighbors} == {visible.id}
    rendered = render_subgraph_context(result.subgraph)
    assert "secret prerequisite" not in rendered
    payload = result.to_payload()
    assert payload["node_id"] == str(current.id)
    assert payload["hop_count"] == 1
    assert payload["omitted_count"] == 1
    assert payload["neighborhood"]["nodes"][0]["id"] == str(current.id)


@pytest.mark.asyncio
async def test_localized_guidance_denies_unreadable_current_without_calling_the_model(
    async_session,
    embedding_service,
):
    current = await _create_node(async_session, embedding_service, content="Run the smoke tests")
    fake = _FakeGenerator()
    with pytest.raises(GuidanceAccessDeniedError, match="Not authorized"):
        await localized_guidance(
            current.id,
            async_session,
            tenant_id=_TENANT,
            authorize=lambda _node: False,
            generator=fake,
        )
    assert fake.seen is None
