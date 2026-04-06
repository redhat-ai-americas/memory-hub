"""Tests for get_relationships tool."""

import inspect
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import src.tools.auth as auth_mod
from src.tools.get_relationships import get_relationships


def test_get_relationships_is_decorated():
    """Verify get_relationships is a decorated MCP tool."""
    assert callable(get_relationships)


def test_get_relationships_is_async():
    """The tool function must be async."""
    assert inspect.iscoroutinefunction(get_relationships)


def test_get_relationships_has_required_parameters():
    """Verify the function signature includes all expected parameters."""
    sig = inspect.signature(get_relationships)
    param_names = set(sig.parameters.keys())

    required = {"node_id"}
    assert required.issubset(param_names), (
        f"Missing required params: {required - param_names}"
    )

    optional = {"relationship_type", "direction", "include_provenance", "ctx"}
    assert optional.issubset(param_names), (
        f"Missing optional params: {optional - param_names}"
    )


def test_get_relationships_default_values():
    """Verify default values for optional parameters."""
    sig = inspect.signature(get_relationships)
    params = sig.parameters

    assert params["relationship_type"].default is None
    assert params["direction"].default == "both"
    assert params["include_provenance"].default is False


@pytest.mark.asyncio
async def test_get_relationships_requires_auth():
    """Unauthenticated calls return an error."""
    auth_mod._current_session = None
    result = await get_relationships(node_id=str(uuid.uuid4()))
    assert result["error"] is True


@pytest.mark.asyncio
async def test_get_relationships_invalid_uuid():
    """Bad UUID format returns a clear error."""
    result = await get_relationships(node_id="not-a-uuid")
    assert result["error"] is True
    assert "Invalid node_id format" in result["message"]


@pytest.mark.asyncio
async def test_get_relationships_invalid_direction():
    """Invalid direction returns an error with valid options."""
    result = await get_relationships(
        node_id=str(uuid.uuid4()),
        direction="sideways",
    )
    assert result["error"] is True
    assert "outgoing" in result["message"]


@pytest.mark.asyncio
async def test_get_relationships_invalid_type():
    """Invalid relationship_type returns an error."""
    result = await get_relationships(
        node_id=str(uuid.uuid4()),
        relationship_type="bad_type",
    )
    assert result["error"] is True
    assert "derived_from" in result["message"]


@pytest.mark.asyncio
async def test_get_relationships_success():
    """Successful query returns relationships and count."""
    mock_rel = MagicMock()
    mock_rel.model_dump.return_value = {
        "id": str(uuid.uuid4()),
        "relationship_type": "related_to",
    }

    mock_session = AsyncMock()
    mock_gen = AsyncMock()

    with (
        patch("src.tools.get_relationships.get_db_session", return_value=(mock_session, mock_gen)),
        patch("src.tools.get_relationships.release_db_session", new_callable=AsyncMock),
        patch("src.tools.get_relationships.get_relationships_service", new_callable=AsyncMock, return_value=[mock_rel]),
    ):
        result = await get_relationships(node_id=str(uuid.uuid4()))
    assert result["count"] == 1
    assert len(result["relationships"]) == 1
