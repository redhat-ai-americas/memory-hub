"""Tests for persona MCP tools — WRIG-1483."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastmcp.exceptions import ToolError

from src.tools.compile_persona import compile_persona
from src.tools.edit_persona import edit_persona
from src.tools.get_persona import get_persona


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_claims():
    """Return standard authn claims."""
    return {
        "sub": "alice",
        "tenant_id": "default",
        "scopes": ["memory:read:user", "memory:write:user"],
    }


@pytest.fixture
def mock_db_session():
    session = AsyncMock()
    gen = AsyncMock()
    return session, gen


# ---------------------------------------------------------------------------
# get_persona tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_persona_unauthenticated():
    """Raises ToolError when session claims are absent."""
    with patch("src.tools.get_persona.get_claims_from_context", return_value=None):
        with pytest.raises(ToolError, match="Not authenticated"):
            await get_persona()


@pytest.mark.asyncio
async def test_get_persona_no_synopsis(mock_claims, mock_db_session):
    """Returns synopsis=None with a helpful message when no profile exists."""
    session, gen = mock_db_session

    empty_status = {
        "has_synopsis": False,
        "is_stale": True,
        "stale_reason": "no synopsis compiled yet",
        "source_fact_count": 0,
        "synopsis_id": None,
        "compiled_at": None,
        "version": None,
    }

    with (
        patch("src.tools.get_persona.get_claims_from_context", return_value=mock_claims),
        patch("src.tools.get_persona.get_db_session", new_callable=AsyncMock, return_value=(session, gen)),
        patch("src.tools.get_persona.release_db_session", new_callable=AsyncMock),
        patch("src.tools.get_persona.get_current_synopsis", new_callable=AsyncMock, return_value=None),
        patch("src.tools.get_persona.get_persona_status", new_callable=AsyncMock, return_value=empty_status),
    ):
        result = await get_persona()

    assert result["synopsis"] is None
    assert result["user_id"] == "alice"
    assert "compile" in result["message"].lower()


@pytest.mark.asyncio
async def test_get_persona_returns_synopsis(mock_claims, mock_db_session):
    """Returns synopsis content and inject_hint when a compiled profile exists."""
    session, gen = mock_db_session

    synopsis_id = uuid.uuid4()
    synopsis_content = "## Preferences\n- Async communication.\n"
    node = MagicMock()
    node.id = synopsis_id
    node.content = synopsis_content
    node.weight = 1.0
    node.scope = "user"
    node.version = 2
    node.updated_at = datetime(2026, 10, 1, tzinfo=UTC)
    node.metadata_ = {"source_fact_count": 5, "stale": False}

    status = {
        "has_synopsis": True,
        "is_stale": False,
        "stale_reason": None,
        "source_fact_count": 5,
        "compiled_fact_count": 5,
        "synopsis_id": str(synopsis_id),
        "compiled_at": "2026-10-01T00:00:00+00:00",
        "version": 2,
    }

    with (
        patch("src.tools.get_persona.get_claims_from_context", return_value=mock_claims),
        patch("src.tools.get_persona.get_db_session", new_callable=AsyncMock, return_value=(session, gen)),
        patch("src.tools.get_persona.release_db_session", new_callable=AsyncMock),
        patch("src.tools.get_persona.get_current_synopsis", new_callable=AsyncMock, return_value=node),
        patch("src.tools.get_persona.get_persona_status", new_callable=AsyncMock, return_value=status),
    ):
        result = await get_persona()

    assert result["synopsis"]["content"] == synopsis_content
    assert result["synopsis"]["weight"] == 1.0
    assert result["synopsis"]["id"] == str(synopsis_id)
    assert result["synopsis"]["version"] == 2
    assert result["source_fact_count"] == 5
    assert result["is_stale"] is False
    assert "inject_hint" in result
    # No stale_hint when not stale
    assert "stale_hint" not in result


@pytest.mark.asyncio
async def test_get_persona_stale_includes_stale_hint(mock_claims, mock_db_session):
    """When synopsis is stale, response includes is_stale=True and stale_hint."""
    session, gen = mock_db_session

    node = MagicMock()
    node.id = uuid.uuid4()
    node.content = "## Preferences\n- Old content.\n"
    node.weight = 1.0
    node.scope = "user"
    node.version = 1
    node.updated_at = datetime(2026, 9, 1, tzinfo=UTC)
    node.metadata_ = {"source_fact_count": 3, "stale": True}

    status = {
        "has_synopsis": True,
        "is_stale": True,
        "stale_reason": "new dreaming facts since last compile",
        "source_fact_count": 5,
        "compiled_fact_count": 3,
        "synopsis_id": str(node.id),
        "compiled_at": "2026-09-01T00:00:00+00:00",
        "version": 1,
    }

    with (
        patch("src.tools.get_persona.get_claims_from_context", return_value=mock_claims),
        patch("src.tools.get_persona.get_db_session", new_callable=AsyncMock, return_value=(session, gen)),
        patch("src.tools.get_persona.release_db_session", new_callable=AsyncMock),
        patch("src.tools.get_persona.get_current_synopsis", new_callable=AsyncMock, return_value=node),
        patch("src.tools.get_persona.get_persona_status", new_callable=AsyncMock, return_value=status),
    ):
        result = await get_persona()

    assert result["is_stale"] is True
    assert "stale_reason" in result
    assert "stale_hint" in result
    # Stale content is still returned — better than nothing
    assert result["synopsis"] is not None
    assert result["synopsis"]["content"] is not None


@pytest.mark.asyncio
async def test_get_persona_uses_session_user_by_default(mock_db_session):
    """When user_id is omitted, defaults to the authenticated sub."""
    session, gen = mock_db_session
    claims = {"sub": "bob", "tenant_id": "acme"}

    with (
        patch("src.tools.get_persona.get_claims_from_context", return_value=claims),
        patch("src.tools.get_persona.get_db_session", new_callable=AsyncMock, return_value=(session, gen)),
        patch("src.tools.get_persona.release_db_session", new_callable=AsyncMock),
        patch("src.tools.get_persona.get_current_synopsis", new_callable=AsyncMock, return_value=None) as mock_get,
        patch("src.tools.get_persona.get_persona_status", new_callable=AsyncMock, return_value={
            "has_synopsis": False, "is_stale": True, "stale_reason": "none",
            "source_fact_count": 0, "synopsis_id": None, "compiled_at": None, "version": None,
        }),
    ):
        await get_persona()

    mock_get.assert_awaited_once_with("bob", "acme", session, project_id=None)


# ---------------------------------------------------------------------------
# compile_persona tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_compile_persona_unauthenticated():
    """Raises ToolError when session claims are absent."""
    with patch("src.tools.compile_persona.get_claims_from_context", return_value=None):
        with pytest.raises(ToolError, match="Not authenticated"):
            await compile_persona()


@pytest.mark.asyncio
async def test_compile_persona_no_facts_raises_tool_error(mock_claims, mock_db_session):
    """Propagates ValueError from service as ToolError."""
    session, gen = mock_db_session

    with (
        patch("src.tools.compile_persona.get_claims_from_context", return_value=mock_claims),
        patch("src.tools.compile_persona.get_db_session", new_callable=AsyncMock, return_value=(session, gen)),
        patch("src.tools.compile_persona.release_db_session", new_callable=AsyncMock),
        patch("src.tools.compile_persona.compile_persona_synopsis", new_callable=AsyncMock,
              side_effect=ValueError("No behavioral dreaming facts found")),
    ):
        with pytest.raises(ToolError, match="No behavioral dreaming facts"):
            await compile_persona()


@pytest.mark.asyncio
async def test_compile_persona_happy_path(mock_claims, mock_db_session):
    """Returns compilation result dict on success."""
    session, gen = mock_db_session

    expected = {
        "synopsis_id": str(uuid.uuid4()),
        "user_id": "alice",
        "project_id": None,
        "source_fact_count": 7,
        "pin_count": 1,
        "version": 2,
        "previous_synopsis_id": str(uuid.uuid4()),
        "content": "## Preferences\n- Dark mode.\n",
        "compiled_at": "2026-10-07T10:00:00+00:00",
        "is_stale": False,
    }

    with (
        patch("src.tools.compile_persona.get_claims_from_context", return_value=mock_claims),
        patch("src.tools.compile_persona.get_db_session", new_callable=AsyncMock, return_value=(session, gen)),
        patch("src.tools.compile_persona.release_db_session", new_callable=AsyncMock),
        patch("src.tools.compile_persona.compile_persona_synopsis", new_callable=AsyncMock, return_value=expected),
    ):
        result = await compile_persona()

    assert result["synopsis_id"] == expected["synopsis_id"]
    assert result["source_fact_count"] == 7
    assert result["version"] == 2
    assert result["is_stale"] is False
    assert "## Preferences" in result["content"]


@pytest.mark.asyncio
async def test_compile_persona_explicit_user_and_project(mock_claims, mock_db_session):
    """Passes explicit user_id and project_id through to the service."""
    session, gen = mock_db_session

    with (
        patch("src.tools.compile_persona.get_claims_from_context", return_value=mock_claims),
        patch("src.tools.compile_persona.get_db_session", new_callable=AsyncMock, return_value=(session, gen)),
        patch("src.tools.compile_persona.release_db_session", new_callable=AsyncMock),
        patch("src.tools.compile_persona.compile_persona_synopsis", new_callable=AsyncMock,
              return_value={
                  "synopsis_id": str(uuid.uuid4()), "user_id": "carol", "project_id": "proj-x",
                  "source_fact_count": 3, "pin_count": 0, "version": 1,
                  "previous_synopsis_id": None, "content": "## Preferences\n- Fast.\n",
                  "compiled_at": "2026-10-07T10:00:00+00:00", "is_stale": False,
              }) as mock_compile,
    ):
        await compile_persona(user_id="carol", project_id="proj-x")

    call_kwargs = mock_compile.call_args.kwargs
    assert call_kwargs["project_id"] == "proj-x"
    assert "embedding_service" in call_kwargs
    mock_compile.assert_awaited_once()
    args = mock_compile.call_args.args
    assert args[0] == "carol"
    assert args[1] == "default"


# ---------------------------------------------------------------------------
# edit_persona tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_edit_persona_unauthenticated():
    """Raises ToolError when session claims are absent."""
    with patch("src.tools.edit_persona.get_claims_from_context", return_value=None):
        with pytest.raises(ToolError, match="Not authenticated"):
            await edit_persona(action="list_pins")


@pytest.mark.asyncio
async def test_edit_persona_unknown_action(mock_claims, mock_db_session):
    """Raises ToolError for unknown action values."""
    session, gen = mock_db_session

    with (
        patch("src.tools.edit_persona.get_claims_from_context", return_value=mock_claims),
        patch("src.tools.edit_persona.get_db_session", new_callable=AsyncMock, return_value=(session, gen)),
        patch("src.tools.edit_persona.release_db_session", new_callable=AsyncMock),
    ):
        with pytest.raises(ToolError, match="Unknown action"):
            await edit_persona(action="delete_pin")


@pytest.mark.asyncio
async def test_edit_persona_add_pin_no_content(mock_claims, mock_db_session):
    """Raises ToolError when add_pin is called without content."""
    session, gen = mock_db_session

    with (
        patch("src.tools.edit_persona.get_claims_from_context", return_value=mock_claims),
        patch("src.tools.edit_persona.get_db_session", new_callable=AsyncMock, return_value=(session, gen)),
        patch("src.tools.edit_persona.release_db_session", new_callable=AsyncMock),
    ):
        with pytest.raises(ToolError, match="content is required"):
            await edit_persona(action="add_pin", content=None)


@pytest.mark.asyncio
async def test_edit_persona_add_pin_happy_path(mock_claims, mock_db_session):
    """Calls add_user_pin and returns pin result dict."""
    session, gen = mock_db_session

    pin_result = {
        "pin_id": str(uuid.uuid4()),
        "content": "I prefer pair programming.",
        "user_id": "alice",
        "synopsis_id": None,
        "created_at": "2026-10-07T10:00:00+00:00",
        "note": "This fact will be preserved.",
    }

    with (
        patch("src.tools.edit_persona.get_claims_from_context", return_value=mock_claims),
        patch("src.tools.edit_persona.get_db_session", new_callable=AsyncMock, return_value=(session, gen)),
        patch("src.tools.edit_persona.release_db_session", new_callable=AsyncMock),
        patch("src.tools.edit_persona.add_user_pin", new_callable=AsyncMock, return_value=pin_result) as mock_add,
    ):
        result = await edit_persona(action="add_pin", content="I prefer pair programming.")

    assert result["content"] == "I prefer pair programming."
    assert "pin_id" in result
    mock_add.assert_awaited_once_with("alice", "default", "I prefer pair programming.", session)


@pytest.mark.asyncio
async def test_edit_persona_list_pins(mock_claims, mock_db_session):
    """Returns pin list with count when action=list_pins."""
    session, gen = mock_db_session

    pins = [
        {"id": str(uuid.uuid4()), "content": "Prefers dark mode.", "created_at": "2026-09-01"},
        {"id": str(uuid.uuid4()), "content": "Uses Rust for systems code.", "created_at": "2026-09-15"},
    ]

    with (
        patch("src.tools.edit_persona.get_claims_from_context", return_value=mock_claims),
        patch("src.tools.edit_persona.get_db_session", new_callable=AsyncMock, return_value=(session, gen)),
        patch("src.tools.edit_persona.release_db_session", new_callable=AsyncMock),
        patch("src.tools.edit_persona.get_user_pins", new_callable=AsyncMock, return_value=pins),
    ):
        result = await edit_persona(action="list_pins")

    assert result["count"] == 2
    assert len(result["pins"]) == 2
    assert result["user_id"] == "alice"


@pytest.mark.asyncio
async def test_edit_persona_uses_session_user_by_default(mock_db_session):
    """Defaults to the authenticated user when user_id is omitted."""
    session, gen = mock_db_session
    claims = {"sub": "carol", "tenant_id": "acme"}

    with (
        patch("src.tools.edit_persona.get_claims_from_context", return_value=claims),
        patch("src.tools.edit_persona.get_db_session", new_callable=AsyncMock, return_value=(session, gen)),
        patch("src.tools.edit_persona.release_db_session", new_callable=AsyncMock),
        patch("src.tools.edit_persona.get_user_pins", new_callable=AsyncMock, return_value=[]) as mock_pins,
    ):
        result = await edit_persona(action="list_pins")

    assert result["user_id"] == "carol"
    mock_pins.assert_awaited_once_with("carol", "acme", session)
