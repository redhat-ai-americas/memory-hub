"""Tests for get_relationships tool."""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.tools.get_relationships import get_relationships

NODE_ID = "aaaaaaaa-0000-0000-0000-000000000001"
SOURCE_ID = "bbbbbbbb-0000-0000-0000-000000000002"
TARGET_ID = "cccccccc-0000-0000-0000-000000000003"
REL_ID = "dddddddd-0000-0000-0000-000000000004"

_FAKE_USER = {"user_id": "test-user", "scopes": ["user"]}


def _make_relationship_read(source_id: str = SOURCE_ID, target_id: str = TARGET_ID):
    """Build a minimal RelationshipRead for mock returns."""
    from memoryhub.models.schemas import RelationshipRead, RelationshipType

    return RelationshipRead(
        id=uuid.UUID(REL_ID),
        source_id=uuid.UUID(source_id),
        target_id=uuid.UUID(target_id),
        relationship_type=RelationshipType.derived_from,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        created_by="test-user",
    )


def _make_node_stub(node_id: str = NODE_ID):
    """Build a minimal MemoryNodeStub for provenance mock returns."""
    from memoryhub.models.schemas import MemoryNodeStub, MemoryScope

    return MemoryNodeStub(
        id=uuid.UUID(node_id),
        stub="A test memory stub",
        scope=MemoryScope.USER,
        weight=0.8,
    )


@pytest.mark.asyncio
async def test_get_relationships_requires_auth():
    """Unauthenticated call should return an error dict."""
    with patch("src.tools.get_relationships.require_auth", side_effect=RuntimeError("No session registered.")):
        result = await get_relationships(node_id=NODE_ID)

    assert result["error"] is True
    assert "No session registered" in result["message"]


@pytest.mark.asyncio
async def test_get_relationships_invalid_uuid():
    """A malformed node_id should return an error before hitting the service."""
    with patch("src.tools.get_relationships.require_auth", return_value=_FAKE_USER):
        result = await get_relationships(node_id="not-a-uuid")

    assert result["error"] is True
    assert "node_id" in result["message"]
    assert "not-a-uuid" in result["message"]


@pytest.mark.asyncio
async def test_get_relationships_invalid_direction():
    """An unrecognised direction value should return an error listing valid options."""
    with patch("src.tools.get_relationships.require_auth", return_value=_FAKE_USER):
        result = await get_relationships(node_id=NODE_ID, direction="sideways")

    assert result["error"] is True
    assert "sideways" in result["message"]
    for valid in ("outgoing", "incoming", "both"):
        assert valid in result["message"], f"Expected valid direction {valid!r} in error message"


@pytest.mark.asyncio
async def test_get_relationships_invalid_type():
    """An unrecognised relationship_type filter should return an error."""
    with patch("src.tools.get_relationships.require_auth", return_value=_FAKE_USER):
        result = await get_relationships(node_id=NODE_ID, relationship_type="buddies")

    assert result["error"] is True
    assert "buddies" in result["message"]
    for valid in ("derived_from", "supersedes", "conflicts_with", "related_to"):
        assert valid in result["message"], f"Expected valid type {valid!r} in error message"


@pytest.mark.asyncio
async def test_get_relationships_success():
    """Happy path: service returns relationships serialized as a list with count."""
    rel = _make_relationship_read()
    mock_session = MagicMock()
    mock_gen = AsyncMock()

    with (
        patch("src.tools.get_relationships.require_auth", return_value=_FAKE_USER),
        patch("src.tools.get_relationships.get_db_session", return_value=(mock_session, mock_gen)),
        patch("src.tools.get_relationships.release_db_session", new_callable=AsyncMock),
        patch(
            "src.tools.get_relationships.get_relationships_service",
            new_callable=AsyncMock,
            return_value=[rel],
        ),
    ):
        result = await get_relationships(node_id=NODE_ID)

    assert "error" not in result
    assert result["count"] == 1
    assert len(result["relationships"]) == 1
    assert result["relationships"][0]["id"] == REL_ID
    assert result["relationships"][0]["relationship_type"] == "derived_from"
    assert "provenance_chain" not in result


@pytest.mark.asyncio
async def test_get_relationships_with_provenance():
    """With include_provenance=True, result includes a provenance_chain from trace_provenance."""
    rel = _make_relationship_read()
    stub = _make_node_stub()
    provenance_steps = [
        {"hop": 1, "node": stub, "relationship": rel},
    ]

    mock_session = MagicMock()
    mock_gen = AsyncMock()

    with (
        patch("src.tools.get_relationships.require_auth", return_value=_FAKE_USER),
        patch("src.tools.get_relationships.get_db_session", return_value=(mock_session, mock_gen)),
        patch("src.tools.get_relationships.release_db_session", new_callable=AsyncMock),
        patch(
            "src.tools.get_relationships.get_relationships_service",
            new_callable=AsyncMock,
            return_value=[rel],
        ),
        patch(
            "src.tools.get_relationships.trace_provenance",
            new_callable=AsyncMock,
            return_value=provenance_steps,
        ),
    ):
        result = await get_relationships(node_id=NODE_ID, include_provenance=True)

    assert "error" not in result
    assert result["count"] == 1
    assert "provenance_chain" in result
    assert len(result["provenance_chain"]) == 1
    step = result["provenance_chain"][0]
    assert step["hop"] == 1
    assert step["node"]["id"] == NODE_ID
    assert step["relationship"]["id"] == REL_ID


@pytest.mark.asyncio
async def test_get_relationships_node_not_found():
    """When the service raises MemoryNotFoundError the tool returns a descriptive error."""
    from memoryhub.services.exceptions import MemoryNotFoundError

    missing_id = uuid.UUID(NODE_ID)
    mock_session = MagicMock()
    mock_gen = AsyncMock()

    with (
        patch("src.tools.get_relationships.require_auth", return_value=_FAKE_USER),
        patch("src.tools.get_relationships.get_db_session", return_value=(mock_session, mock_gen)),
        patch("src.tools.get_relationships.release_db_session", new_callable=AsyncMock),
        patch(
            "src.tools.get_relationships.get_relationships_service",
            new_callable=AsyncMock,
            side_effect=MemoryNotFoundError(missing_id),
        ),
    ):
        result = await get_relationships(node_id=NODE_ID)

    assert result["error"] is True
    assert str(missing_id) in result["message"]
    assert "existing" in result["message"] or "node_id" in result["message"]
