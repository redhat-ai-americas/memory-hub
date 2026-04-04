"""Tests for create_relationship tool."""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.tools.create_relationship import create_relationship

# Stable UUIDs for use across tests
SOURCE_ID = "aaaaaaaa-0000-0000-0000-000000000001"
TARGET_ID = "bbbbbbbb-0000-0000-0000-000000000002"
REL_ID = "cccccccc-0000-0000-0000-000000000003"

_FAKE_USER = {"user_id": "test-user", "scopes": ["user"]}


def _make_relationship_read():
    """Build a minimal RelationshipRead for mock returns."""
    from memoryhub.models.schemas import RelationshipRead, RelationshipType

    return RelationshipRead(
        id=uuid.UUID(REL_ID),
        source_id=uuid.UUID(SOURCE_ID),
        target_id=uuid.UUID(TARGET_ID),
        relationship_type=RelationshipType.related_to,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        created_by="test-user",
    )


@pytest.mark.asyncio
async def test_create_relationship_requires_auth():
    """Unauthenticated call should return an error dict."""
    with patch("src.tools.create_relationship.require_auth", side_effect=RuntimeError("No session registered.")):
        result = await create_relationship(
            source_id=SOURCE_ID,
            target_id=TARGET_ID,
            relationship_type="related_to",
        )

    assert result["error"] is True
    assert "No session registered" in result["message"]


@pytest.mark.asyncio
async def test_create_relationship_invalid_type():
    """An unrecognised relationship_type should return an error listing valid types."""
    with patch("src.tools.create_relationship.require_auth", return_value=_FAKE_USER):
        result = await create_relationship(
            source_id=SOURCE_ID,
            target_id=TARGET_ID,
            relationship_type="best_friends",
        )

    assert result["error"] is True
    assert "best_friends" in result["message"]
    # Valid types should be listed to help the caller recover
    for valid in ("derived_from", "supersedes", "conflicts_with", "related_to"):
        assert valid in result["message"], f"Expected valid type {valid!r} in error message"


@pytest.mark.asyncio
async def test_create_relationship_invalid_source_uuid():
    """A malformed source_id should return an error before hitting the service."""
    with patch("src.tools.create_relationship.require_auth", return_value=_FAKE_USER):
        result = await create_relationship(
            source_id="not-a-uuid",
            target_id=TARGET_ID,
            relationship_type="related_to",
        )

    assert result["error"] is True
    assert "source_id" in result["message"]
    assert "not-a-uuid" in result["message"]


@pytest.mark.asyncio
async def test_create_relationship_invalid_target_uuid():
    """A malformed target_id should return an error."""
    with patch("src.tools.create_relationship.require_auth", return_value=_FAKE_USER):
        result = await create_relationship(
            source_id=SOURCE_ID,
            target_id="bad-id",
            relationship_type="related_to",
        )

    assert result["error"] is True
    assert "target_id" in result["message"]
    assert "bad-id" in result["message"]


@pytest.mark.asyncio
async def test_create_relationship_self_reference():
    """source_id == target_id should return a clear self-referential error."""
    with patch("src.tools.create_relationship.require_auth", return_value=_FAKE_USER):
        result = await create_relationship(
            source_id=SOURCE_ID,
            target_id=SOURCE_ID,
            relationship_type="related_to",
        )

    assert result["error"] is True
    assert "self-referential" in result["message"] or "same" in result["message"].lower() or "different" in result["message"]


@pytest.mark.asyncio
async def test_create_relationship_success():
    """Happy path: service returns a RelationshipRead which is serialized to a dict."""
    rel = _make_relationship_read()

    mock_session = MagicMock()
    mock_gen = AsyncMock()

    with (
        patch("src.tools.create_relationship.require_auth", return_value=_FAKE_USER),
        patch("src.tools.create_relationship.get_db_session", return_value=(mock_session, mock_gen)),
        patch("src.tools.create_relationship.release_db_session", new_callable=AsyncMock),
        patch(
            "src.tools.create_relationship.create_relationship_service",
            new_callable=AsyncMock,
            return_value=rel,
        ),
    ):
        result = await create_relationship(
            source_id=SOURCE_ID,
            target_id=TARGET_ID,
            relationship_type="related_to",
        )

    assert "error" not in result
    assert result["id"] == REL_ID
    assert result["source_id"] == SOURCE_ID
    assert result["target_id"] == TARGET_ID
    assert result["relationship_type"] == "related_to"
    assert result["created_by"] == "test-user"


@pytest.mark.asyncio
async def test_create_relationship_node_not_found():
    """When the service raises MemoryNotFoundError the tool returns a descriptive error."""
    from memoryhub.services.exceptions import MemoryNotFoundError

    missing_id = uuid.UUID(SOURCE_ID)
    mock_session = MagicMock()
    mock_gen = AsyncMock()

    with (
        patch("src.tools.create_relationship.require_auth", return_value=_FAKE_USER),
        patch("src.tools.create_relationship.get_db_session", return_value=(mock_session, mock_gen)),
        patch("src.tools.create_relationship.release_db_session", new_callable=AsyncMock),
        patch(
            "src.tools.create_relationship.create_relationship_service",
            new_callable=AsyncMock,
            side_effect=MemoryNotFoundError(missing_id),
        ),
    ):
        result = await create_relationship(
            source_id=SOURCE_ID,
            target_id=TARGET_ID,
            relationship_type="related_to",
        )

    assert result["error"] is True
    assert str(missing_id) in result["message"]
    # Should advise the caller to verify both IDs
    assert "source_id" in result["message"] or "target_id" in result["message"] or "existing" in result["message"]


@pytest.mark.asyncio
async def test_create_relationship_duplicate():
    """When the service raises ValueError (duplicate edge) the tool surfaces the message."""
    mock_session = MagicMock()
    mock_gen = AsyncMock()

    with (
        patch("src.tools.create_relationship.require_auth", return_value=_FAKE_USER),
        patch("src.tools.create_relationship.get_db_session", return_value=(mock_session, mock_gen)),
        patch("src.tools.create_relationship.release_db_session", new_callable=AsyncMock),
        patch(
            "src.tools.create_relationship.create_relationship_service",
            new_callable=AsyncMock,
            side_effect=ValueError("Relationship already exists between these nodes"),
        ),
    ):
        result = await create_relationship(
            source_id=SOURCE_ID,
            target_id=TARGET_ID,
            relationship_type="related_to",
        )

    assert result["error"] is True
    assert "already exists" in result["message"]
