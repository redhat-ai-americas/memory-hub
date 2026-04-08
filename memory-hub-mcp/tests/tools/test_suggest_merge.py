"""Tests for suggest_merge tool."""

import inspect
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import src.tools.auth as auth_mod
from src.tools.suggest_merge import suggest_merge


def test_suggest_merge_is_decorated():
    """Verify suggest_merge is a decorated MCP tool."""
    assert callable(suggest_merge)


def test_suggest_merge_is_async():
    """The tool function must be async."""
    assert inspect.iscoroutinefunction(suggest_merge)


def test_suggest_merge_has_required_parameters():
    """Verify the function signature includes all expected parameters."""
    sig = inspect.signature(suggest_merge)
    param_names = set(sig.parameters.keys())

    required = {"memory_a_id", "memory_b_id", "reasoning"}
    assert required.issubset(param_names), (
        f"Missing required params: {required - param_names}"
    )

    optional = {"ctx"}
    assert optional.issubset(param_names), (
        f"Missing optional params: {optional - param_names}"
    )


@pytest.mark.asyncio
async def test_suggest_merge_requires_auth():
    """Unauthenticated calls return an error."""
    auth_mod._current_session = None
    result = await suggest_merge(
        memory_a_id=str(uuid.uuid4()),
        memory_b_id=str(uuid.uuid4()),
        reasoning="duplicates",
    )
    assert result["error"] is True


@pytest.mark.asyncio
async def test_suggest_merge_invalid_uuid():
    """Bad UUID format returns a clear error."""
    result = await suggest_merge(
        memory_a_id="bad-uuid",
        memory_b_id=str(uuid.uuid4()),
        reasoning="duplicates",
    )
    assert result["error"] is True
    assert "Invalid memory_a_id format" in result["message"]


@pytest.mark.asyncio
async def test_suggest_merge_self_reference():
    """Same source and target returns an error."""
    same_id = str(uuid.uuid4())
    result = await suggest_merge(
        memory_a_id=same_id,
        memory_b_id=same_id,
        reasoning="duplicates",
    )
    assert result["error"] is True
    assert "must be different" in result["message"]


@pytest.mark.asyncio
async def test_suggest_merge_empty_reasoning():
    """Empty reasoning returns an error."""
    result = await suggest_merge(
        memory_a_id=str(uuid.uuid4()),
        memory_b_id=str(uuid.uuid4()),
        reasoning="   ",
    )
    assert result["error"] is True
    assert "reasoning cannot be empty" in result["message"]


@pytest.mark.asyncio
async def test_suggest_merge_success():
    """Successful merge suggestion returns relationship and confirmation."""
    mock_result = MagicMock()
    mock_result.model_dump.return_value = {
        "id": str(uuid.uuid4()),
        "relationship_type": "conflicts_with",
        "metadata": {"merge_suggested": True},
    }

    mock_session = AsyncMock()
    mock_gen = AsyncMock()

    mock_memory = SimpleNamespace(scope="user", owner_id="test-user", tenant_id="default")

    with (
        patch("src.tools.suggest_merge.get_db_session", return_value=(mock_session, mock_gen)),
        patch("src.tools.suggest_merge.release_db_session", new_callable=AsyncMock),
        patch("src.tools.suggest_merge._read_memory", new_callable=AsyncMock, return_value=mock_memory),
        patch("src.tools.suggest_merge.create_relationship_service", new_callable=AsyncMock, return_value=mock_result),
    ):
        result = await suggest_merge(
            memory_a_id=str(uuid.uuid4()),
            memory_b_id=str(uuid.uuid4()),
            reasoning="Both describe Podman preference",
        )
    assert "relationship" in result
    assert "message" in result
    assert "Merge suggestion recorded" in result["message"]
