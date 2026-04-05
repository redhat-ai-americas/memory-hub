"""Tests for create_relationship tool."""

import inspect
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.tools.create_relationship import create_relationship


def test_create_relationship_is_decorated():
    """Verify create_relationship is a decorated MCP tool."""
    assert callable(create_relationship)


def test_create_relationship_is_async():
    """The tool function must be async."""
    assert inspect.iscoroutinefunction(create_relationship)


def test_create_relationship_has_required_parameters():
    """Verify the function signature includes all expected parameters."""
    sig = inspect.signature(create_relationship)
    param_names = set(sig.parameters.keys())

    required = {"source_id", "target_id", "relationship_type"}
    assert required.issubset(param_names), (
        f"Missing required params: {required - param_names}"
    )

    optional = {"metadata", "ctx"}
    assert optional.issubset(param_names), (
        f"Missing optional params: {optional - param_names}"
    )


def test_create_relationship_default_values():
    """Verify default values for optional parameters."""
    sig = inspect.signature(create_relationship)
    params = sig.parameters

    assert params["metadata"].default is None


@pytest.mark.asyncio
async def test_create_relationship_requires_auth():
    """Unauthenticated calls return an error."""
    with patch("src.tools.create_relationship.require_auth", side_effect=RuntimeError("Not authenticated")):
        result = await create_relationship(
            source_id=str(uuid.uuid4()),
            target_id=str(uuid.uuid4()),
            relationship_type="related_to",
        )
    assert result["error"] is True
    assert "Not authenticated" in result["message"]


@pytest.mark.asyncio
async def test_create_relationship_invalid_type():
    """Invalid relationship_type returns an error with valid options."""
    with patch("src.tools.create_relationship.require_auth", return_value={"user_id": "test"}):
        result = await create_relationship(
            source_id=str(uuid.uuid4()),
            target_id=str(uuid.uuid4()),
            relationship_type="bad_type",
        )
    assert result["error"] is True
    assert "derived_from" in result["message"]


@pytest.mark.asyncio
async def test_create_relationship_invalid_uuid():
    """Bad UUID format returns a clear error."""
    with patch("src.tools.create_relationship.require_auth", return_value={"user_id": "test"}):
        result = await create_relationship(
            source_id="not-a-uuid",
            target_id=str(uuid.uuid4()),
            relationship_type="related_to",
        )
    assert result["error"] is True
    assert "Invalid source_id format" in result["message"]


@pytest.mark.asyncio
async def test_create_relationship_self_reference():
    """Same source and target returns an error."""
    same_id = str(uuid.uuid4())
    with patch("src.tools.create_relationship.require_auth", return_value={"user_id": "test"}):
        result = await create_relationship(
            source_id=same_id,
            target_id=same_id,
            relationship_type="related_to",
        )
    assert result["error"] is True
    assert "self-referential" in result["message"]


@pytest.mark.asyncio
async def test_create_relationship_success():
    """Successful creation returns the relationship data."""
    mock_result = MagicMock()
    mock_result.model_dump.return_value = {
        "id": str(uuid.uuid4()),
        "source_id": str(uuid.uuid4()),
        "target_id": str(uuid.uuid4()),
        "relationship_type": "related_to",
    }

    mock_session = AsyncMock()
    mock_gen = AsyncMock()

    with (
        patch("src.tools.create_relationship.require_auth", return_value={"user_id": "test"}),
        patch("src.tools.create_relationship.get_db_session", return_value=(mock_session, mock_gen)),
        patch("src.tools.create_relationship.release_db_session", new_callable=AsyncMock),
        patch("src.tools.create_relationship.create_relationship_service", new_callable=AsyncMock, return_value=mock_result),
    ):
        result = await create_relationship(
            source_id=str(uuid.uuid4()),
            target_id=str(uuid.uuid4()),
            relationship_type="related_to",
        )
    assert "error" not in result
    assert result["relationship_type"] == "related_to"
