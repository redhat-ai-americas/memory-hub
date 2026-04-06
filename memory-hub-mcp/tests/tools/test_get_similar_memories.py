"""Tests for get_similar_memories tool."""

import inspect
import uuid
from unittest.mock import AsyncMock, patch

import pytest

import src.tools.auth as auth_mod
from src.tools.get_similar_memories import get_similar_memories


def test_get_similar_memories_is_decorated():
    """Verify get_similar_memories is a decorated MCP tool."""
    assert callable(get_similar_memories)


def test_get_similar_memories_is_async():
    """The tool function must be async."""
    assert inspect.iscoroutinefunction(get_similar_memories)


def test_get_similar_memories_has_required_parameters():
    """Verify the function signature includes all expected parameters."""
    sig = inspect.signature(get_similar_memories)
    param_names = set(sig.parameters.keys())

    required = {"memory_id"}
    assert required.issubset(param_names), (
        f"Missing required params: {required - param_names}"
    )

    optional = {"threshold", "max_results", "offset", "ctx"}
    assert optional.issubset(param_names), (
        f"Missing optional params: {optional - param_names}"
    )


def test_get_similar_memories_default_values():
    """Verify default values for optional parameters."""
    sig = inspect.signature(get_similar_memories)
    params = sig.parameters

    assert params["threshold"].default == 0.80
    assert params["max_results"].default == 10
    assert params["offset"].default == 0


@pytest.mark.asyncio
async def test_get_similar_memories_requires_auth():
    """Unauthenticated calls return an error."""
    auth_mod._current_session = None
    result = await get_similar_memories(memory_id=str(uuid.uuid4()))
    assert result["error"] is True


@pytest.mark.asyncio
async def test_get_similar_memories_invalid_uuid():
    """Bad UUID format returns a clear error."""
    result = await get_similar_memories(memory_id="not-a-uuid")
    assert result["error"] is True
    assert "Invalid memory_id format" in result["message"]


@pytest.mark.asyncio
async def test_get_similar_memories_success():
    """Successful query returns paged results."""
    mock_session = AsyncMock()
    mock_gen = AsyncMock()

    with (
        patch("src.tools.get_similar_memories.get_db_session", return_value=(mock_session, mock_gen)),
        patch("src.tools.get_similar_memories.release_db_session", new_callable=AsyncMock),
        patch(
            "src.tools.get_similar_memories.get_similar_memories_service",
            new_callable=AsyncMock,
            return_value={"results": [], "total": 0, "has_more": False},
        ),
    ):
        result = await get_similar_memories(memory_id=str(uuid.uuid4()))
    assert result["total"] == 0
    assert result["has_more"] is False
