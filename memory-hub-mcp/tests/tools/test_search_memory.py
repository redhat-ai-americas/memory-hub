"""Tests for search_memory tool."""

import inspect
from unittest.mock import AsyncMock, patch

import pytest

import src.tools.auth as auth_mod
from src.tools.search_memory import search_memory


def test_search_memory_is_importable():
    """Verify the tool module imports and the decorated function exists."""
    assert search_memory is not None
    assert callable(search_memory)


def test_search_memory_has_required_parameters():
    """Verify query is required and optional params have defaults."""
    sig = inspect.signature(search_memory)
    params = sig.parameters

    assert "query" in params
    assert "scope" in params
    assert "owner_id" in params
    assert "max_results" in params
    assert "weight_threshold" in params
    assert "current_only" in params
    assert "ctx" in params

    # query has no default -- it is required
    assert params["query"].default is inspect.Parameter.empty
    # optional params have defaults
    assert params["scope"].default is None
    assert params["max_results"].default == 10
    assert params["weight_threshold"].default == 0.0
    assert params["current_only"].default is True


@pytest.mark.asyncio
async def test_search_memory_rejects_empty_query():
    """Calling with an empty query should raise ToolError."""
    from fastmcp.exceptions import ToolError

    ctx = AsyncMock()
    with pytest.raises(ToolError, match="Query cannot be empty"):
        await search_memory(query="   ", ctx=ctx)


@pytest.mark.asyncio
async def test_search_memory_rejects_invalid_scope():
    """Calling with an invalid scope should raise ToolError."""
    from fastmcp.exceptions import ToolError

    ctx = AsyncMock()
    with pytest.raises(ToolError, match="Invalid scope filter"):
        await search_memory(query="test query", scope="invalid_scope", ctx=ctx)


def _fake_search_result(stub: str, weight: float):
    """Build a (MemoryNodeStub, score) tuple for use as a fake search result."""
    import uuid as _uuid

    from memoryhub.models.schemas import MemoryNodeStub, MemoryScope

    return (
        MemoryNodeStub(
            id=_uuid.uuid4(),
            stub=stub,
            scope=MemoryScope.USER,
            weight=weight,
            branch_type=None,
            has_children=False,
            has_rationale=False,
        ),
        0.9,
    )


@pytest.mark.asyncio
async def test_search_memory_has_more_when_paginated():
    """Regression for #53: total_matching > page size must surface as has_more.

    Issues a search with max_results=2 against 5 fake matches and asserts
    has_more=true and total_matching=5.
    """
    mock_session = AsyncMock()
    mock_gen = AsyncMock()
    fake_embedding_service = AsyncMock()
    page_results = [
        _fake_search_result("first match", 0.5),
        _fake_search_result("second match", 0.4),
    ]

    auth_mod._current_session = {
        "user_id": "wjackson",
        "scopes": ["user"],
        "identity_type": "user",
    }
    try:
        with (
            patch("src.tools.search_memory.get_db_session", return_value=(mock_session, mock_gen)),
            patch("src.tools.search_memory.release_db_session", new_callable=AsyncMock),
            patch("src.tools.search_memory.get_embedding_service", return_value=fake_embedding_service),
            patch(
                "src.tools.search_memory.search_memories",
                new_callable=AsyncMock,
                return_value=page_results,
            ),
            patch(
                "src.tools.search_memory.count_search_matches",
                new_callable=AsyncMock,
                return_value=5,
            ),
        ):
            result = await search_memory(query="memory", max_results=2)
    finally:
        auth_mod._current_session = None

    assert result["total_matching"] == 5
    assert result["has_more"] is True
    assert len(result["results"]) == 2
    assert "total_accessible" not in result


@pytest.mark.asyncio
async def test_search_memory_has_more_false_when_page_holds_all():
    """When the page contains every match, has_more must be false."""
    mock_session = AsyncMock()
    mock_gen = AsyncMock()
    fake_embedding_service = AsyncMock()
    page_results = [_fake_search_result("only match", 0.5)]

    auth_mod._current_session = {
        "user_id": "wjackson",
        "scopes": ["user"],
        "identity_type": "user",
    }
    try:
        with (
            patch("src.tools.search_memory.get_db_session", return_value=(mock_session, mock_gen)),
            patch("src.tools.search_memory.release_db_session", new_callable=AsyncMock),
            patch("src.tools.search_memory.get_embedding_service", return_value=fake_embedding_service),
            patch(
                "src.tools.search_memory.search_memories",
                new_callable=AsyncMock,
                return_value=page_results,
            ),
            patch(
                "src.tools.search_memory.count_search_matches",
                new_callable=AsyncMock,
                return_value=1,
            ),
        ):
            result = await search_memory(query="memory", max_results=10)
    finally:
        auth_mod._current_session = None

    assert result["total_matching"] == 1
    assert result["has_more"] is False
    assert len(result["results"]) == 1


@pytest.mark.asyncio
async def test_search_memory_empty_returns_zero_total():
    """Empty results must still emit total_matching and has_more=False."""
    mock_session = AsyncMock()
    mock_gen = AsyncMock()
    fake_embedding_service = AsyncMock()

    auth_mod._current_session = {
        "user_id": "wjackson",
        "scopes": ["user"],
        "identity_type": "user",
    }
    try:
        with (
            patch("src.tools.search_memory.get_db_session", return_value=(mock_session, mock_gen)),
            patch("src.tools.search_memory.release_db_session", new_callable=AsyncMock),
            patch("src.tools.search_memory.get_embedding_service", return_value=fake_embedding_service),
            patch(
                "src.tools.search_memory.search_memories",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "src.tools.search_memory.count_search_matches",
                new_callable=AsyncMock,
                return_value=0,
            ),
        ):
            result = await search_memory(query="nothing")
    finally:
        auth_mod._current_session = None

    assert result["results"] == []
    assert result["total_matching"] == 0
    assert result["has_more"] is False
