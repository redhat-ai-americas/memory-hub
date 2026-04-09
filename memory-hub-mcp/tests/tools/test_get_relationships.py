"""Tests for get_relationships tool."""

import inspect
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastmcp.exceptions import ToolError

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
    """Unauthenticated calls raise ToolError."""
    auth_mod._current_session = None
    with pytest.raises(ToolError):
        await get_relationships(node_id=str(uuid.uuid4()))


@pytest.mark.asyncio
async def test_get_relationships_invalid_uuid():
    """Bad UUID format raises ToolError with a clear message."""
    with pytest.raises(ToolError, match="Invalid node_id format"):
        await get_relationships(node_id="not-a-uuid")


@pytest.mark.asyncio
async def test_get_relationships_invalid_direction():
    """Invalid direction raises ToolError listing valid options."""
    with pytest.raises(ToolError, match="outgoing"):
        await get_relationships(
            node_id=str(uuid.uuid4()),
            direction="sideways",
        )


@pytest.mark.asyncio
async def test_get_relationships_invalid_type():
    """Invalid relationship_type raises ToolError listing valid types."""
    with pytest.raises(ToolError, match="derived_from"):
        await get_relationships(
            node_id=str(uuid.uuid4()),
            relationship_type="bad_type",
        )


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


@pytest.mark.asyncio
async def test_get_relationships_forwards_tenant_id_to_service():
    """Phase 4 (#46): the tool must forward claims.tenant_id into the
    get_relationships_service call so the SQL-level filter runs in the
    caller's tenant."""
    mock_session = AsyncMock()
    mock_gen = AsyncMock()
    fake_claims = {
        "sub": "wjackson",
        "identity_type": "user",
        "tenant_id": "tenant_a",
        "scopes": ["memory:read:user", "memory:write:user"],
    }

    with (
        patch(
            "src.tools.get_relationships.get_claims_from_context",
            return_value=fake_claims,
        ),
        patch(
            "src.tools.get_relationships.get_db_session",
            return_value=(mock_session, mock_gen),
        ),
        patch(
            "src.tools.get_relationships.release_db_session",
            new_callable=AsyncMock,
        ),
        patch(
            "src.tools.get_relationships.get_relationships_service",
            new_callable=AsyncMock,
            return_value=[],
        ) as mock_service,
    ):
        await get_relationships(node_id=str(uuid.uuid4()))

    _, kwargs = mock_service.call_args
    assert kwargs.get("tenant_id") == "tenant_a", (
        f"Expected tenant_id='tenant_a' forwarded into get_relationships_service, "
        f"got kwargs={kwargs}"
    )
