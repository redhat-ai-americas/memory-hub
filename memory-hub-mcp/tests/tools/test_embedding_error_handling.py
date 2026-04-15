"""Tests that embedding exceptions surface as structured ToolErrors (#119).

Each test verifies one tool + one embedding failure mode. The service layer is
mocked so these tests exercise only the tool-layer catch blocks, not the HTTP
client itself (that is covered in tests/test_services/test_embedding_errors.py).
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastmcp.exceptions import ToolError

import src.tools.auth as auth_mod
from memoryhub_core.services.exceptions import (
    EmbeddingContentTooLargeError,
    EmbeddingServiceUnavailableError,
)
from src.tools.search_memory import search_memory
from src.tools.set_session_focus import set_session_focus
from src.tools.write_memory import write_memory

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SESSION = {
    "user_id": "wjackson",
    "scopes": ["user"],
    "identity_type": "user",
}

_CLAIMS = {
    "sub": "wjackson",
    "identity_type": "user",
    "tenant_id": "default",
    "scopes": ["memory:write:user", "memory:read:user"],
}


def _embedding_service_mock(exc: Exception) -> MagicMock:
    """Return a mock embedding service whose embed() raises *exc*."""
    svc = MagicMock()
    svc.embed = AsyncMock(side_effect=exc)
    return svc


# ---------------------------------------------------------------------------
# write_memory tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_write_memory_content_too_large_raises_tool_error():
    """write_memory wraps EmbeddingContentTooLargeError as ToolError with
    a message that identifies the problem as an invalid content size."""
    exc = EmbeddingContentTooLargeError(content_length=50_000)

    auth_mod._current_session = _SESSION
    try:
        with (
            patch("src.tools.write_memory.get_claims_from_context", return_value=_CLAIMS),
            patch("src.tools.write_memory.get_db_session", return_value=(MagicMock(), AsyncMock())),
            patch("src.tools.write_memory.release_db_session", new_callable=AsyncMock),
            patch("src.tools.write_memory.get_embedding_service", return_value=_embedding_service_mock(exc)),
            patch(
                "src.tools.write_memory.create_memory",
                new_callable=AsyncMock,
                side_effect=exc,
            ),
        ):
            with pytest.raises(ToolError) as exc_info:
                await write_memory(content="test", scope="user")
    finally:
        auth_mod._current_session = None

    assert "Invalid content size" in str(exc_info.value), str(exc_info.value)


@pytest.mark.asyncio
async def test_write_memory_service_unavailable_raises_tool_error():
    """write_memory wraps EmbeddingServiceUnavailableError as ToolError with
    a message containing 'unavailable'."""
    exc = EmbeddingServiceUnavailableError(reason="connection refused")

    auth_mod._current_session = _SESSION
    try:
        with (
            patch("src.tools.write_memory.get_claims_from_context", return_value=_CLAIMS),
            patch("src.tools.write_memory.get_db_session", return_value=(MagicMock(), AsyncMock())),
            patch("src.tools.write_memory.release_db_session", new_callable=AsyncMock),
            patch("src.tools.write_memory.get_embedding_service", return_value=_embedding_service_mock(exc)),
            patch(
                "src.tools.write_memory.create_memory",
                new_callable=AsyncMock,
                side_effect=exc,
            ),
        ):
            with pytest.raises(ToolError) as exc_info:
                await write_memory(content="test", scope="user")
    finally:
        auth_mod._current_session = None

    assert "unavailable" in str(exc_info.value).lower(), str(exc_info.value)


# ---------------------------------------------------------------------------
# search_memory tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_memory_service_unavailable_raises_tool_error():
    """search_memory wraps EmbeddingServiceUnavailableError from the embed call
    as ToolError with a message containing 'unavailable'."""
    exc = EmbeddingServiceUnavailableError(reason="timed out")
    embedding_svc = _embedding_service_mock(exc)

    auth_mod._current_session = _SESSION
    try:
        with (
            patch("src.tools.search_memory.get_db_session", return_value=(MagicMock(), AsyncMock())),
            patch("src.tools.search_memory.release_db_session", new_callable=AsyncMock),
            patch("src.tools.search_memory.get_embedding_service", return_value=embedding_svc),
        ):
            with pytest.raises(ToolError) as exc_info:
                await search_memory(query="test query")
    finally:
        auth_mod._current_session = None

    assert "unavailable" in str(exc_info.value).lower(), str(exc_info.value)


# ---------------------------------------------------------------------------
# set_session_focus tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_set_session_focus_content_too_large_raises_tool_error():
    """set_session_focus wraps EmbeddingContentTooLargeError as ToolError with
    a message that starts with 'Invalid focus text'."""
    exc = EmbeddingContentTooLargeError(content_length=50_000)
    embedding_svc = _embedding_service_mock(exc)

    auth_mod._current_session = _SESSION
    try:
        with (
            patch("src.tools.set_session_focus.get_claims_from_context", return_value=_CLAIMS),
            patch("src.tools.set_session_focus.get_embedding_service", return_value=embedding_svc),
        ):
            with pytest.raises(ToolError) as exc_info:
                await set_session_focus(focus="test focus", project="test-proj")
    finally:
        auth_mod._current_session = None

    assert "Invalid focus text" in str(exc_info.value), str(exc_info.value)
