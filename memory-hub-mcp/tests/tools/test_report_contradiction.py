"""Tests for report_contradiction tool."""

import uuid
import pytest
from unittest.mock import AsyncMock, patch

from src.tools.report_contradiction import report_contradiction


@pytest.mark.asyncio
async def test_report_contradiction_import():
    """Verify the tool imports and is callable."""
    assert report_contradiction is not None
    assert callable(report_contradiction)


@pytest.mark.asyncio
async def test_report_contradiction_invalid_uuid():
    """Test that an invalid UUID returns a clear error."""
    from fastmcp.exceptions import ToolError

    ctx = AsyncMock()
    with pytest.raises(ToolError, match="Invalid memory_id format"):
        await report_contradiction(
            memory_id="not-a-uuid",
            observed_behavior="User used Docker",
            ctx=ctx,
        )


@pytest.mark.asyncio
async def test_report_contradiction_empty_behavior():
    """Test that empty observed_behavior returns a clear error."""
    from fastmcp.exceptions import ToolError

    ctx = AsyncMock()
    with pytest.raises(ToolError, match="observed_behavior cannot be empty"):
        await report_contradiction(
            memory_id="550e8400-e29b-41d4-a716-446655440000",
            observed_behavior="   ",
            ctx=ctx,
        )


@pytest.mark.asyncio
async def test_report_contradiction_passes_reporter_from_session():
    """Test that reporter is taken from the authenticated session."""
    memory_id = "550e8400-e29b-41d4-a716-446655440000"
    mock_session = AsyncMock()
    mock_gen = AsyncMock()
    mock_gen.__anext__ = AsyncMock(side_effect=StopAsyncIteration)

    with (
        patch(
            "src.tools.report_contradiction.get_authenticated_owner",
            return_value="user-123",
        ),
        patch(
            "src.tools.report_contradiction.get_db_session",
            return_value=(mock_session, mock_gen),
        ),
        patch(
            "src.tools.report_contradiction._report_contradiction",
            new_callable=AsyncMock,
            return_value=2,
        ) as mock_svc,
    ):
        result = await report_contradiction(
            memory_id=memory_id,
            observed_behavior="User used Docker instead of Podman",
        )

    mock_svc.assert_awaited_once_with(
        memory_id=uuid.UUID(memory_id),
        observed_behavior="User used Docker instead of Podman",
        confidence=0.7,
        reporter="user-123",
        session=mock_session,
    )
    assert result["contradiction_count"] == 2
    assert result["memory_id"] == memory_id


@pytest.mark.asyncio
async def test_report_contradiction_reporter_defaults_to_unknown():
    """Test that reporter falls back to 'unknown' when no session is registered."""
    memory_id = "550e8400-e29b-41d4-a716-446655440000"
    mock_session = AsyncMock()
    mock_gen = AsyncMock()
    mock_gen.__anext__ = AsyncMock(side_effect=StopAsyncIteration)

    with (
        patch(
            "src.tools.report_contradiction.get_authenticated_owner",
            return_value=None,
        ),
        patch(
            "src.tools.report_contradiction.get_db_session",
            return_value=(mock_session, mock_gen),
        ),
        patch(
            "src.tools.report_contradiction._report_contradiction",
            new_callable=AsyncMock,
            return_value=1,
        ) as mock_svc,
    ):
        await report_contradiction(
            memory_id=memory_id,
            observed_behavior="User used Docker instead of Podman",
        )

    mock_svc.assert_awaited_once_with(
        memory_id=uuid.UUID(memory_id),
        observed_behavior="User used Docker instead of Podman",
        confidence=0.7,
        reporter="unknown",
        session=mock_session,
    )
