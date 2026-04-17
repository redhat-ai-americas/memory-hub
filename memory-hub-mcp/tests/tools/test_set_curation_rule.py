"""Tests for set_curation_rule tool."""

import inspect
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastmcp.exceptions import ToolError

import src.tools.auth as auth_mod
from src.tools.set_curation_rule import set_curation_rule


def test_set_curation_rule_is_decorated():
    """Verify set_curation_rule is a decorated MCP tool."""
    assert callable(set_curation_rule)


def test_set_curation_rule_is_async():
    """The tool function must be async."""
    assert inspect.iscoroutinefunction(set_curation_rule)


def test_set_curation_rule_has_required_parameters():
    """Verify the function signature includes all expected parameters."""
    sig = inspect.signature(set_curation_rule)
    param_names = set(sig.parameters.keys())

    required = {"name"}
    assert required.issubset(param_names), (
        f"Missing required params: {required - param_names}"
    )

    optional = {
        "tier",
        "action",
        "config",
        "scope_filter",
        "enabled",
        "priority",
        "ctx",
    }
    assert optional.issubset(param_names), (
        f"Missing optional params: {optional - param_names}"
    )


def test_set_curation_rule_default_values():
    """Verify default values for optional parameters."""
    sig = inspect.signature(set_curation_rule)
    params = sig.parameters

    assert params["tier"].default == "embedding"
    assert params["action"].default == "flag"
    assert params["config"].default is None
    assert params["scope_filter"].default is None
    assert params["enabled"].default is True
    assert params["priority"].default == 10


@pytest.mark.asyncio
async def test_set_curation_rule_requires_auth():
    """Unauthenticated calls raise ToolError."""
    auth_mod._current_session = None
    with pytest.raises(ToolError):
        await set_curation_rule(name="my_rule")


@pytest.mark.asyncio
async def test_set_curation_rule_invalid_tier():
    """Invalid tier raises ToolError with valid options."""
    with pytest.raises(ToolError, match="regex"):
        await set_curation_rule(name="my_rule", tier="magic")


@pytest.mark.asyncio
async def test_set_curation_rule_invalid_action():
    """Invalid action raises ToolError with valid options."""
    with pytest.raises(ToolError, match="flag"):
        await set_curation_rule(name="my_rule", action="destroy")


@pytest.mark.asyncio
async def test_set_curation_rule_protected_system_rule():
    """Cannot override a protected system rule."""
    mock_protected = MagicMock()
    mock_protected.layer = "system"

    mock_session = AsyncMock()
    mock_execute = AsyncMock()
    mock_execute.scalar_one_or_none.return_value = mock_protected
    mock_session.execute.return_value = mock_execute
    mock_gen = AsyncMock()

    with (
        patch(
            "src.tools.set_curation_rule.get_db_session",
            return_value=(mock_session, mock_gen),
        ),
        patch("src.tools.set_curation_rule.release_db_session", new_callable=AsyncMock),
        pytest.raises(ToolError, match="protected"),
    ):
        await set_curation_rule(name="secrets_scan")


@pytest.mark.asyncio
async def test_set_curation_rule_create_success():
    """Creating a new rule returns created=True."""
    mock_rule = MagicMock()
    mock_rule.id = uuid.uuid4()
    mock_rule.name = "my_threshold"
    mock_rule.tier = "embedding"
    mock_rule.action = "flag"
    mock_rule.config = {"threshold": 0.98}
    mock_rule.scope_filter = None
    mock_rule.layer = "user"
    mock_rule.owner_id = "test"
    mock_rule.override = False
    mock_rule.enabled = True
    mock_rule.priority = 10
    mock_rule.trigger = "on_write"
    mock_rule.description = None
    mock_rule.tenant_id = "default"
    mock_rule.created_at = "2026-04-04T00:00:00Z"
    mock_rule.updated_at = "2026-04-04T00:00:00Z"

    # First execute returns None for protected check,
    # second returns None for existing check
    mock_session = AsyncMock()
    execute_results = [
        MagicMock(scalar_one_or_none=MagicMock(return_value=None)),  # protected check
        MagicMock(scalar_one_or_none=MagicMock(return_value=None)),  # existing check
    ]
    mock_session.execute = AsyncMock(side_effect=execute_results)
    mock_gen = AsyncMock()

    with (
        patch(
            "src.tools.set_curation_rule.get_db_session",
            return_value=(mock_session, mock_gen),
        ),
        patch("src.tools.set_curation_rule.release_db_session", new_callable=AsyncMock),
        patch(
            "src.tools.set_curation_rule.create_rule",
            new_callable=AsyncMock,
            return_value=mock_rule,
        ) as mock_create,
    ):
        result = await set_curation_rule(
            name="my_threshold", config={"threshold": 0.98}
        )
    assert result["created"] is True
    assert result["updated"] is False
    # Phase 3 (#46): the tool must forward tenant_id from claims to
    # create_rule. No JWT is set in this test so the auth path falls back
    # to session identity, which maps tenant_id to "default".
    _, kwargs = mock_create.call_args
    assert kwargs.get("tenant_id") == "default"
