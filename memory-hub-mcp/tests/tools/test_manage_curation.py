"""Tests for manage_curation consolidated tool.

Covers all three actions:
  - report_contradiction
  - resolve_contradiction (new)
  - set_rule (formerly set_curation_rule)

Migrated from test_report_contradiction.py and test_set_curation_rule.py.
"""

import inspect
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastmcp.exceptions import ToolError

import src.tools.auth as auth_mod
from src.tools.manage_curation import manage_curation


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

MEMORY_UUID = "550e8400-e29b-41d4-a716-446655440000"
CONTRADICTION_UUID = "660e8400-e29b-41d4-a716-446655440001"

# Module paths for the consolidated tool (used in patch() calls).
_MOD = "src.tools.manage_curation"


# ---------------------------------------------------------------------------
# Smoke tests
# ---------------------------------------------------------------------------


def test_manage_curation_is_callable():
    """Verify the tool imports and is callable."""
    assert manage_curation is not None
    assert callable(manage_curation)


def test_manage_curation_is_async():
    """The tool function must be async."""
    assert inspect.iscoroutinefunction(manage_curation)


# ---------------------------------------------------------------------------
# Top-level action dispatch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invalid_action_raises_tool_error():
    """An unrecognised action value raises ToolError with a helpful message."""
    # Set up a valid session so we get past auth
    auth_mod._current_session = {
        "user_id": "test-user",
        "scopes": ["user"],
    }
    with pytest.raises(ToolError, match="Invalid action"):
        await manage_curation(action="do_the_thing")


# ---------------------------------------------------------------------------
# Authentication guard (shared across all actions)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_requires_auth_report_contradiction():
    """Unauthenticated calls raise ToolError for report_contradiction."""
    auth_mod._current_session = None
    with pytest.raises(ToolError, match="Authentication required"):
        await manage_curation(
            action="report_contradiction",
            memory_id=MEMORY_UUID,
            observed_behavior="User used Docker instead of Podman",
        )


@pytest.mark.asyncio
async def test_requires_auth_resolve_contradiction():
    """Unauthenticated calls raise ToolError for resolve_contradiction."""
    auth_mod._current_session = None
    with pytest.raises(ToolError, match="Authentication required"):
        await manage_curation(
            action="resolve_contradiction",
            contradiction_id=CONTRADICTION_UUID,
            resolution_action="accept_new",
        )


@pytest.mark.asyncio
async def test_requires_auth_set_rule():
    """Unauthenticated calls raise ToolError for set_rule."""
    auth_mod._current_session = None
    with pytest.raises(ToolError):
        await manage_curation(action="set_rule", name="my_rule")


# ===========================================================================
# action='report_contradiction'
# ===========================================================================


@pytest.mark.asyncio
async def test_report_contradiction_invalid_uuid():
    """An invalid memory_id UUID returns a clear error."""
    ctx = AsyncMock()
    with pytest.raises(ToolError, match="Invalid memory_id format"):
        await manage_curation(
            action="report_contradiction",
            memory_id="not-a-uuid",
            observed_behavior="User used Docker",
            ctx=ctx,
        )


@pytest.mark.asyncio
async def test_report_contradiction_empty_behavior():
    """Empty observed_behavior raises ToolError."""
    ctx = AsyncMock()
    with pytest.raises(ToolError, match="observed_behavior cannot be empty"):
        await manage_curation(
            action="report_contradiction",
            memory_id=MEMORY_UUID,
            observed_behavior="   ",
            ctx=ctx,
        )


@pytest.mark.asyncio
async def test_report_contradiction_missing_memory_id():
    """Missing memory_id raises ToolError."""
    ctx = AsyncMock()
    with pytest.raises(ToolError, match="requires memory_id"):
        await manage_curation(
            action="report_contradiction",
            observed_behavior="User used Docker instead of Podman",
            ctx=ctx,
        )


@pytest.mark.asyncio
async def test_report_contradiction_passes_reporter_from_session():
    """Reporter is taken from the authenticated session; returns expected payload."""
    mock_session = AsyncMock()
    mock_gen = AsyncMock()
    mock_gen.__anext__ = AsyncMock(side_effect=StopAsyncIteration)

    mock_memory = SimpleNamespace(scope="user", owner_id="test-user", tenant_id="default")

    with (
        patch(f"{_MOD}.get_db_session", return_value=(mock_session, mock_gen)),
        patch(f"{_MOD}.release_db_session", new_callable=AsyncMock),
        patch(
            f"{_MOD}._read_memory",
            new_callable=AsyncMock,
            return_value=mock_memory,
        ),
        patch(
            f"{_MOD}._report_contradiction",
            new_callable=AsyncMock,
            return_value=2,
        ) as mock_svc,
    ):
        result = await manage_curation(
            action="report_contradiction",
            memory_id=MEMORY_UUID,
            observed_behavior="User used Docker instead of Podman",
        )

    mock_svc.assert_awaited_once_with(
        memory_id=uuid.UUID(MEMORY_UUID),
        observed_behavior="User used Docker instead of Podman",
        confidence=0.7,
        reporter="test-user",
        session=mock_session,
    )
    assert result["contradiction_count"] == 2
    assert result["memory_id"] == MEMORY_UUID


# ===========================================================================
# action='resolve_contradiction'
# ===========================================================================


@pytest.mark.asyncio
async def test_resolve_contradiction_missing_contradiction_id():
    """Missing contradiction_id raises ToolError."""
    with pytest.raises(ToolError, match="requires contradiction_id"):
        await manage_curation(
            action="resolve_contradiction",
            resolution_action="accept_new",
        )


@pytest.mark.asyncio
async def test_resolve_contradiction_missing_resolution_action():
    """Missing resolution_action raises ToolError."""
    with pytest.raises(ToolError, match="requires resolution_action"):
        await manage_curation(
            action="resolve_contradiction",
            contradiction_id=CONTRADICTION_UUID,
        )


@pytest.mark.asyncio
async def test_resolve_contradiction_invalid_uuid():
    """An invalid UUID for contradiction_id raises ToolError."""
    with pytest.raises(ToolError, match="Invalid contradiction_id format"):
        await manage_curation(
            action="resolve_contradiction",
            contradiction_id="not-a-valid-uuid",
            resolution_action="accept_new",
        )


@pytest.mark.asyncio
async def test_resolve_contradiction_invalid_resolution_action():
    """An unrecognised resolution_action raises ToolError with valid options."""
    with pytest.raises(ToolError, match="Invalid resolution_action"):
        await manage_curation(
            action="resolve_contradiction",
            contradiction_id=CONTRADICTION_UUID,
            resolution_action="do_nothing",
        )


@pytest.mark.parametrize(
    "resolution_action",
    ["accept_new", "keep_old", "mark_both_invalid", "manual_merge"],
)
@pytest.mark.asyncio
async def test_resolve_contradiction_valid_actions(resolution_action):
    """Each valid resolution_action produces a resolved=True response."""
    resolved_at = datetime(2026, 4, 20, 12, 0, 0, tzinfo=timezone.utc)
    mock_report = MagicMock()
    mock_report.id = uuid.UUID(CONTRADICTION_UUID)
    mock_report.resolved_at = resolved_at
    mock_report.resolution_action = resolution_action
    mock_report.resolved_by = "test-user"

    mock_session = AsyncMock()
    mock_gen = AsyncMock()

    with (
        patch(f"{_MOD}.get_db_session", return_value=(mock_session, mock_gen)),
        patch(f"{_MOD}.release_db_session", new_callable=AsyncMock),
        patch(
            f"{_MOD}._resolve_contradiction",
            new_callable=AsyncMock,
            return_value=mock_report,
        ) as mock_svc,
    ):
        result = await manage_curation(
            action="resolve_contradiction",
            contradiction_id=CONTRADICTION_UUID,
            resolution_action=resolution_action,
        )

    mock_svc.assert_awaited_once_with(
        uuid.UUID(CONTRADICTION_UUID),
        mock_session,
        resolution_action=resolution_action,
        actor_id="test-user",
    )
    assert result["resolved"] is True
    assert result["contradiction_id"] == CONTRADICTION_UUID
    assert result["resolution_action"] == resolution_action
    assert result["resolved_at"] == resolved_at.isoformat()


@pytest.mark.asyncio
async def test_resolve_contradiction_includes_note_in_message():
    """resolution_note is appended to the response message."""
    resolved_at = datetime(2026, 4, 20, 12, 0, 0, tzinfo=timezone.utc)
    mock_report = MagicMock()
    mock_report.id = uuid.UUID(CONTRADICTION_UUID)
    mock_report.resolved_at = resolved_at
    mock_report.resolution_action = "keep_old"
    mock_report.resolved_by = "test-user"

    mock_session = AsyncMock()
    mock_gen = AsyncMock()

    with (
        patch(f"{_MOD}.get_db_session", return_value=(mock_session, mock_gen)),
        patch(f"{_MOD}.release_db_session", new_callable=AsyncMock),
        patch(
            f"{_MOD}._resolve_contradiction",
            new_callable=AsyncMock,
            return_value=mock_report,
        ),
    ):
        result = await manage_curation(
            action="resolve_contradiction",
            contradiction_id=CONTRADICTION_UUID,
            resolution_action="keep_old",
            resolution_note="One-off exception during migration",
        )

    assert "One-off exception during migration" in result["message"]


@pytest.mark.asyncio
async def test_resolve_contradiction_not_found_raises_tool_error():
    """ContradictionNotFoundError from the service is surfaced as ToolError."""
    from memoryhub_core.services.exceptions import ContradictionNotFoundError

    mock_session = AsyncMock()
    mock_gen = AsyncMock()

    with (
        patch(f"{_MOD}.get_db_session", return_value=(mock_session, mock_gen)),
        patch(f"{_MOD}.release_db_session", new_callable=AsyncMock),
        patch(
            f"{_MOD}._resolve_contradiction",
            new_callable=AsyncMock,
            side_effect=ContradictionNotFoundError("not found"),
        ),
        pytest.raises(ToolError, match=CONTRADICTION_UUID),
    ):
        await manage_curation(
            action="resolve_contradiction",
            contradiction_id=CONTRADICTION_UUID,
            resolution_action="accept_new",
        )


# ===========================================================================
# action='set_rule'
# ===========================================================================


def test_set_rule_has_required_parameters():
    """Verify the function signature includes all expected parameters."""
    sig = inspect.signature(manage_curation)
    param_names = set(sig.parameters.keys())

    # Top-level action dispatch param
    assert "action" in param_names

    # set_rule-specific params
    for param in ("name", "tier", "action_type", "config", "scope_filter", "enabled", "priority"):
        assert param in param_names, f"Missing param: {param!r}"


def test_set_rule_parameter_defaults():
    """Verify default values for set_rule parameters."""
    sig = inspect.signature(manage_curation)
    params = sig.parameters

    assert params["tier"].default == "embedding"
    assert params["action_type"].default == "flag"
    assert params["config"].default is None
    assert params["scope_filter"].default is None
    assert params["enabled"].default is True
    assert params["priority"].default == 10


@pytest.mark.asyncio
async def test_set_rule_invalid_tier():
    """Invalid tier raises ToolError naming valid options."""
    with pytest.raises(ToolError, match="regex"):
        await manage_curation(action="set_rule", name="my_rule", tier="magic")


@pytest.mark.asyncio
async def test_set_rule_invalid_action_type():
    """Invalid action_type raises ToolError naming valid options."""
    with pytest.raises(ToolError, match="flag"):
        await manage_curation(action="set_rule", name="my_rule", action_type="destroy")


@pytest.mark.asyncio
async def test_set_rule_missing_name():
    """Missing name raises ToolError."""
    with pytest.raises(ToolError, match="requires name"):
        await manage_curation(action="set_rule")


@pytest.mark.asyncio
async def test_set_rule_protected_system_rule():
    """Cannot override a protected system rule."""
    mock_protected = MagicMock()
    mock_protected.layer = "system"

    mock_session = AsyncMock()
    mock_execute = MagicMock()
    mock_execute.scalar_one_or_none.return_value = mock_protected
    mock_session.execute.return_value = mock_execute
    mock_gen = AsyncMock()

    with (
        patch(f"{_MOD}.get_db_session", return_value=(mock_session, mock_gen)),
        patch(f"{_MOD}.release_db_session", new_callable=AsyncMock),
        pytest.raises(ToolError, match="protected"),
    ):
        await manage_curation(action="set_rule", name="secrets_scan")


@pytest.mark.asyncio
async def test_set_rule_create_success():
    """Creating a new rule returns created=True and forwards tenant_id."""
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
    # second returns None for existing-rule check.
    mock_session = AsyncMock()
    execute_results = [
        MagicMock(scalar_one_or_none=MagicMock(return_value=None)),
        MagicMock(scalar_one_or_none=MagicMock(return_value=None)),
    ]
    mock_session.execute = AsyncMock(side_effect=execute_results)
    mock_gen = AsyncMock()

    with (
        patch(f"{_MOD}.get_db_session", return_value=(mock_session, mock_gen)),
        patch(f"{_MOD}.release_db_session", new_callable=AsyncMock),
        patch(
            f"{_MOD}.create_rule",
            new_callable=AsyncMock,
            return_value=mock_rule,
        ) as mock_create,
    ):
        result = await manage_curation(
            action="set_rule",
            name="my_threshold",
            config={"threshold": 0.98},
        )

    assert result["created"] is True
    assert result["updated"] is False
    # Phase 3 (#46): tool must forward tenant_id from claims to create_rule.
    # No JWT is set in this test so auth falls back to session identity, which
    # maps tenant_id to "default".
    _, kwargs = mock_create.call_args
    assert kwargs.get("tenant_id") == "default"
