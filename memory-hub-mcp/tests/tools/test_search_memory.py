"""Tests for search_memory tool."""

import inspect

import pytest
from unittest.mock import AsyncMock

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
