"""Tests for get_similar_memories tool."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.tools.get_similar_memories import get_similar_memories

MEMORY_ID = "aaaaaaaa-0000-0000-0000-000000000001"
SIM_ID = "bbbbbbbb-0000-0000-0000-000000000002"

_FAKE_USER = {"user_id": "test-user", "scopes": ["user"]}


def _make_service_result(has_results: bool = True):
    if not has_results:
        return {"results": [], "total": 0, "has_more": False}
    return {
        "results": [
            {"id": uuid.UUID(SIM_ID), "stub": "A similar memory stub", "score": 0.92}
        ],
        "total": 1,
        "has_more": False,
    }


@pytest.mark.asyncio
async def test_requires_auth():
    with patch("src.tools.get_similar_memories.require_auth", side_effect=RuntimeError("No session registered.")):
        result = await get_similar_memories(memory_id=MEMORY_ID)

    assert result["error"] is True
    assert "No session registered" in result["message"]


@pytest.mark.asyncio
async def test_invalid_uuid():
    with patch("src.tools.get_similar_memories.require_auth", return_value=_FAKE_USER):
        result = await get_similar_memories(memory_id="not-a-uuid")

    assert result["error"] is True
    assert "not-a-uuid" in result["message"]
    assert "memory_id" in result["message"]


@pytest.mark.asyncio
async def test_success_with_results():
    mock_session = MagicMock()
    mock_gen = AsyncMock()

    with (
        patch("src.tools.get_similar_memories.require_auth", return_value=_FAKE_USER),
        patch("src.tools.get_similar_memories.get_db_session", return_value=(mock_session, mock_gen)),
        patch("src.tools.get_similar_memories.release_db_session", new_callable=AsyncMock),
        patch(
            "src.tools.get_similar_memories._get_similar_memories",
            new_callable=AsyncMock,
            return_value=_make_service_result(has_results=True),
        ),
    ):
        result = await get_similar_memories(memory_id=MEMORY_ID, threshold=0.80, max_results=10, offset=0)

    assert "error" not in result
    assert result["total"] == 1
    assert result["has_more"] is False
    assert len(result["results"]) == 1
    # UUIDs must be serialised to strings
    assert result["results"][0]["id"] == SIM_ID
    assert result["results"][0]["score"] == 0.92


@pytest.mark.asyncio
async def test_success_empty_results():
    mock_session = MagicMock()
    mock_gen = AsyncMock()

    with (
        patch("src.tools.get_similar_memories.require_auth", return_value=_FAKE_USER),
        patch("src.tools.get_similar_memories.get_db_session", return_value=(mock_session, mock_gen)),
        patch("src.tools.get_similar_memories.release_db_session", new_callable=AsyncMock),
        patch(
            "src.tools.get_similar_memories._get_similar_memories",
            new_callable=AsyncMock,
            return_value=_make_service_result(has_results=False),
        ),
    ):
        result = await get_similar_memories(memory_id=MEMORY_ID)

    assert "error" not in result
    assert result["total"] == 0
    assert result["results"] == []


@pytest.mark.asyncio
async def test_memory_not_found():
    from memoryhub.services.exceptions import MemoryNotFoundError

    missing_id = uuid.UUID(MEMORY_ID)
    mock_session = MagicMock()
    mock_gen = AsyncMock()

    with (
        patch("src.tools.get_similar_memories.require_auth", return_value=_FAKE_USER),
        patch("src.tools.get_similar_memories.get_db_session", return_value=(mock_session, mock_gen)),
        patch("src.tools.get_similar_memories.release_db_session", new_callable=AsyncMock),
        patch(
            "src.tools.get_similar_memories._get_similar_memories",
            new_callable=AsyncMock,
            side_effect=MemoryNotFoundError(missing_id),
        ),
    ):
        result = await get_similar_memories(memory_id=MEMORY_ID)

    assert result["error"] is True
    assert str(missing_id) in result["message"]
