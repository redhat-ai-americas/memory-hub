"""Tests for suggest_merge tool."""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.tools.suggest_merge import suggest_merge

MEMORY_A = "aaaaaaaa-0000-0000-0000-000000000001"
MEMORY_B = "bbbbbbbb-0000-0000-0000-000000000002"
REL_ID = "cccccccc-0000-0000-0000-000000000003"

_FAKE_USER = {"user_id": "test-user", "scopes": ["user"]}


def _make_relationship_read():
    from memoryhub.models.schemas import RelationshipRead, RelationshipType

    return RelationshipRead(
        id=uuid.UUID(REL_ID),
        source_id=uuid.UUID(MEMORY_A),
        target_id=uuid.UUID(MEMORY_B),
        relationship_type=RelationshipType.conflicts_with,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        created_by="test-user",
        metadata_={"merge_suggested": True, "reasoning": "They overlap.", "suggested_by": "test-user"},
    )


@pytest.mark.asyncio
async def test_requires_auth():
    with patch("src.tools.suggest_merge.require_auth", side_effect=RuntimeError("No session registered.")):
        result = await suggest_merge(memory_a_id=MEMORY_A, memory_b_id=MEMORY_B, reasoning="Overlap.")

    assert result["error"] is True
    assert "No session registered" in result["message"]


@pytest.mark.asyncio
async def test_invalid_memory_a_uuid():
    with patch("src.tools.suggest_merge.require_auth", return_value=_FAKE_USER):
        result = await suggest_merge(memory_a_id="bad-id", memory_b_id=MEMORY_B, reasoning="Overlap.")

    assert result["error"] is True
    assert "memory_a_id" in result["message"]
    assert "bad-id" in result["message"]


@pytest.mark.asyncio
async def test_invalid_memory_b_uuid():
    with patch("src.tools.suggest_merge.require_auth", return_value=_FAKE_USER):
        result = await suggest_merge(memory_a_id=MEMORY_A, memory_b_id="bad-id", reasoning="Overlap.")

    assert result["error"] is True
    assert "memory_b_id" in result["message"]
    assert "bad-id" in result["message"]


@pytest.mark.asyncio
async def test_self_reference():
    with patch("src.tools.suggest_merge.require_auth", return_value=_FAKE_USER):
        result = await suggest_merge(memory_a_id=MEMORY_A, memory_b_id=MEMORY_A, reasoning="Overlap.")

    assert result["error"] is True
    assert "different" in result["message"] or "itself" in result["message"]


@pytest.mark.asyncio
async def test_empty_reasoning():
    with patch("src.tools.suggest_merge.require_auth", return_value=_FAKE_USER):
        result = await suggest_merge(memory_a_id=MEMORY_A, memory_b_id=MEMORY_B, reasoning="   ")

    assert result["error"] is True
    assert "reasoning" in result["message"]


@pytest.mark.asyncio
async def test_success():
    rel = _make_relationship_read()
    mock_session = MagicMock()
    mock_gen = AsyncMock()

    with (
        patch("src.tools.suggest_merge.require_auth", return_value=_FAKE_USER),
        patch("src.tools.suggest_merge.get_db_session", return_value=(mock_session, mock_gen)),
        patch("src.tools.suggest_merge.release_db_session", new_callable=AsyncMock),
        patch(
            "src.tools.suggest_merge.create_relationship_service",
            new_callable=AsyncMock,
            return_value=rel,
        ),
    ):
        result = await suggest_merge(
            memory_a_id=MEMORY_A,
            memory_b_id=MEMORY_B,
            reasoning="Both describe the same preference.",
        )

    assert "error" not in result
    assert result["merge_suggested"] is True
    assert "relationship" in result
    assert result["relationship"]["relationship_type"] == "conflicts_with"


@pytest.mark.asyncio
async def test_memory_not_found():
    from memoryhub.services.exceptions import MemoryNotFoundError

    missing_id = uuid.UUID(MEMORY_A)
    mock_session = MagicMock()
    mock_gen = AsyncMock()

    with (
        patch("src.tools.suggest_merge.require_auth", return_value=_FAKE_USER),
        patch("src.tools.suggest_merge.get_db_session", return_value=(mock_session, mock_gen)),
        patch("src.tools.suggest_merge.release_db_session", new_callable=AsyncMock),
        patch(
            "src.tools.suggest_merge.create_relationship_service",
            new_callable=AsyncMock,
            side_effect=MemoryNotFoundError(missing_id),
        ),
    ):
        result = await suggest_merge(
            memory_a_id=MEMORY_A, memory_b_id=MEMORY_B, reasoning="Overlap."
        )

    assert result["error"] is True
    assert str(missing_id) in result["message"]


@pytest.mark.asyncio
async def test_duplicate_suggestion():
    mock_session = MagicMock()
    mock_gen = AsyncMock()

    with (
        patch("src.tools.suggest_merge.require_auth", return_value=_FAKE_USER),
        patch("src.tools.suggest_merge.get_db_session", return_value=(mock_session, mock_gen)),
        patch("src.tools.suggest_merge.release_db_session", new_callable=AsyncMock),
        patch(
            "src.tools.suggest_merge.create_relationship_service",
            new_callable=AsyncMock,
            side_effect=ValueError("Relationship already exists"),
        ),
    ):
        result = await suggest_merge(
            memory_a_id=MEMORY_A, memory_b_id=MEMORY_B, reasoning="Overlap."
        )

    assert result["error"] is True
    assert "already exists" in result["message"]
