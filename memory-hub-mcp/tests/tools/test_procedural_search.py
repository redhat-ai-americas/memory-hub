"""search_memory current_step_id and manage_graph get_guidance (#553).

The model is not called. These tests check the tool envelope: a set
current_step_id skips embedding, marks the query ignored, and returns one
guidance result; an absent current_step_id still takes the ranked path.
"""

import uuid
from contextlib import ExitStack
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from fastmcp.exceptions import ToolError
from src.tools.manage_graph import manage_graph
from src.tools.search_memory import search_memory

from memoryhub_core.models.schemas import ContentType, MemoryNodeRead, MemoryScope, StorageType
from memoryhub_core.services.exceptions import (
    LLMExtractionServiceUnavailableError,
    MemoryNotFoundError,
)
from memoryhub_core.services.procedural_guidance import GuidanceResult, LocalizedSubgraph

_CLAIMS = {
    "sub": "wjackson",
    "identity_type": "user",
    "tenant_id": "tenant_a",
    "scopes": ["memory:read:user", "memory:write:user"],
    "project_memberships": ["proj-1"],
}


def _node(content: str, *, owner_id: str = "wjackson", tenant_id: str = "tenant_a") -> MemoryNodeRead:
    now = datetime.now(UTC)
    return MemoryNodeRead(
        id=uuid.uuid4(),
        parent_id=None,
        content=content,
        stub=content,
        storage_type=StorageType.INLINE,
        content_ref=None,
        weight=0.7,
        scope=MemoryScope.USER,
        branch_type="procedure_step",
        owner_id=owner_id,
        tenant_id=tenant_id,
        is_current=True,
        version=1,
        previous_version_id=None,
        created_at=now,
        updated_at=now,
        content_type=ContentType.PROCEDURAL,
    )


def _result(text: str = "Check the lockfile, then install.") -> GuidanceResult:
    current = _node("Install dependencies")
    return GuidanceResult(
        subgraph=LocalizedSubgraph(
            current=current,
            neighbors=[],
            max_hops=2,
            relationship_types=["precedes", "requires", "alternative_to"],
        ),
        guidance_text=text,
        omitted_count=0,
    )


def _search_stack(fake_guidance):
    stack = ExitStack()
    stack.enter_context(patch("src.tools.search_memory.get_claims_from_context", return_value=_CLAIMS))
    stack.enter_context(patch("src.tools.search_memory.get_db_session", return_value=(AsyncMock(), AsyncMock())))
    stack.enter_context(patch("src.tools.search_memory.release_db_session", new_callable=AsyncMock))
    stack.enter_context(patch("src.tools.search_memory.get_embedding_service", side_effect=AssertionError("embedding")))
    stack.enter_context(patch("src.tools.search_memory.search_memories", new_callable=AsyncMock))
    stack.enter_context(patch("src.tools._guidance.localized_guidance", fake_guidance))
    return stack


@pytest.mark.asyncio
async def test_search_with_current_step_returns_guidance_and_skips_ranking():
    seen = {}

    async def fake_guidance(node_id, session, **kwargs):
        seen["tenant_id"] = kwargs["tenant_id"]
        seen["max_hops"] = kwargs["max_hops"]
        seen["authorize"] = kwargs["authorize"]
        seen["node_id"] = node_id
        return _result()

    step_id = str(uuid.uuid4())
    with _search_stack(fake_guidance):
        result = await search_memory(
            query="how do I deploy",
            current_step_id=step_id,
            graph_depth=2,
            focus="openshift",
        )

    assert seen["tenant_id"] == "tenant_a"
    assert seen["max_hops"] == 2
    assert seen["node_id"] == uuid.UUID(step_id)
    assert result["query_ignored"] is True
    assert result["ignored_parameters"] == ["query", "graph_depth", "focus"]
    assert result["total_matching"] == 1
    assert result["has_more"] is False
    assert "relevance_score" not in result["results"][0]
    entry = result["results"][0]
    assert entry["result_type"] == "guidance"
    assert entry["content"] == "Check the lockfile, then install."
    assert entry["guidance_text"] == entry["content"]
    assert entry["hop_count"] == 0
    assert entry["neighborhood"]["nodes"][0]["content"] == "Install dependencies"
    assert entry["id"] == entry["neighborhood"]["nodes"][0]["id"]

    own = _node("mine", owner_id="wjackson", tenant_id="tenant_a")
    other = _node("theirs", owner_id="someone-else", tenant_id="tenant_a")
    foreign = _node("foreign", owner_id="wjackson", tenant_id="tenant_b")
    assert seen["authorize"](own) is True
    assert seen["authorize"](other) is False
    assert seen["authorize"](foreign) is False


@pytest.mark.asyncio
async def test_search_without_current_step_still_ranks():
    fake_guidance = AsyncMock(side_effect=AssertionError("guidance"))
    fake_search = AsyncMock(return_value=[])
    with (
        patch("src.tools.search_memory.get_claims_from_context", return_value=_CLAIMS),
        patch("src.tools.search_memory.get_db_session", return_value=(AsyncMock(), AsyncMock())),
        patch("src.tools.search_memory.release_db_session", new_callable=AsyncMock),
        patch("src.tools.search_memory.get_embedding_service", return_value=AsyncMock()),
        patch("src.tools.search_memory.search_memories", fake_search),
        patch("src.tools.search_memory.count_search_matches", new_callable=AsyncMock, return_value=0),
        patch("src.tools.search_memory.detect_patterns", new_callable=AsyncMock, return_value=[]),
        patch("src.tools._guidance.localized_guidance", fake_guidance),
    ):
        result = await search_memory(query="deploy procedures", content_type="procedural")

    fake_search.assert_awaited()
    fake_guidance.assert_not_awaited()
    assert "query_ignored" not in result
    assert result["results"] == []


@pytest.mark.asyncio
async def test_search_current_step_still_rejects_an_empty_query():
    with pytest.raises(ToolError, match="Query cannot be empty"):
        await search_memory(query="  ", current_step_id=str(uuid.uuid4()))


@pytest.mark.asyncio
async def test_search_current_step_rejects_a_bad_id_without_embedding():
    with (
        patch("src.tools.search_memory.get_claims_from_context", return_value=_CLAIMS),
        patch("src.tools.search_memory.get_db_session", return_value=(AsyncMock(), AsyncMock())),
        patch("src.tools.search_memory.release_db_session", new_callable=AsyncMock),
        patch("src.tools.search_memory.get_embedding_service", side_effect=AssertionError("embedding")),
        pytest.raises(ToolError, match="valid UUID"),
    ):
        await search_memory(query="deploy", current_step_id="not-a-uuid")


@pytest.mark.asyncio
async def test_search_current_step_missing_node_is_a_tool_error():
    async def missing(*args, **kwargs):
        raise MemoryNotFoundError(uuid.uuid4())

    with _search_stack(missing), pytest.raises(ToolError, match="not found"):
        await search_memory(query="deploy", current_step_id=str(uuid.uuid4()))


@pytest.mark.asyncio
async def test_search_current_step_llm_unavailable_does_not_rank():
    async def down(*args, **kwargs):
        raise LLMExtractionServiceUnavailableError("LLM extraction URL is not configured")

    with _search_stack(down), pytest.raises(ToolError, match="unavailable"):
        await search_memory(query="deploy", current_step_id=str(uuid.uuid4()))


@pytest.mark.asyncio
async def test_get_guidance_returns_the_service_payload():
    async def fake_guidance(node_id, session, **kwargs):
        assert kwargs["tenant_id"] == "tenant_a"
        assert kwargs["max_hops"] == 1
        return _result("Promote after the canary holds.")

    step_id = str(uuid.uuid4())
    with (
        patch("src.tools.manage_graph.get_claims_from_context", return_value=_CLAIMS),
        patch("src.tools.manage_graph.get_db_session", return_value=(AsyncMock(), AsyncMock())),
        patch("src.tools.manage_graph.release_db_session", new_callable=AsyncMock),
        patch("src.tools.manage_graph.get_projects_for_user", new_callable=AsyncMock, return_value=set()),
        patch("src.tools.manage_graph.get_roles_for_user", new_callable=AsyncMock, return_value=set()),
        patch("src.tools._guidance.localized_guidance", fake_guidance),
    ):
        result = await manage_graph(action="get_guidance", node_id=step_id, max_hops=1)

    assert result["guidance_text"] == "Promote after the canary holds."
    assert result["hop_count"] == 0
    assert "nodes" in result["neighborhood"]
    assert "edges" in result["neighborhood"]
    assert result["node_id"]
