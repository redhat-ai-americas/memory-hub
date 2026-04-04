"""Tests for set_curation_rule tool."""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.tools.set_curation_rule import set_curation_rule

_FAKE_USER = {"user_id": "test-user", "scopes": ["user"]}


def _make_curator_rule(name: str = "near_duplicate_threshold", layer: str = "user", override: bool = False):
    """Return a minimal CuratorRule ORM-like mock."""
    from memoryhub.models.curation import CuratorRule

    rule = MagicMock(spec=CuratorRule)
    rule.id = uuid.uuid4()
    rule.name = name
    rule.description = None
    rule.trigger = "on_write"
    rule.tier = "embedding"
    rule.config = {"threshold": 0.82}
    rule.action = "flag"
    rule.scope_filter = None
    rule.layer = layer
    rule.owner_id = "test-user" if layer == "user" else None
    rule.override = override
    rule.enabled = True
    rule.priority = 10
    rule.created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rule.updated_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return rule


@pytest.mark.asyncio
async def test_requires_auth():
    with patch("src.tools.set_curation_rule.require_auth", side_effect=RuntimeError("No session registered.")):
        result = await set_curation_rule(name="my_rule")

    assert result["error"] is True
    assert "No session registered" in result["message"]


@pytest.mark.asyncio
async def test_invalid_tier():
    with patch("src.tools.set_curation_rule.require_auth", return_value=_FAKE_USER):
        result = await set_curation_rule(name="my_rule", tier="neural")

    assert result["error"] is True
    assert "neural" in result["message"]
    assert "regex" in result["message"]
    assert "embedding" in result["message"]


@pytest.mark.asyncio
async def test_invalid_action():
    with patch("src.tools.set_curation_rule.require_auth", return_value=_FAKE_USER):
        result = await set_curation_rule(name="my_rule", action="delete")

    assert result["error"] is True
    assert "delete" in result["message"]
    assert "flag" in result["message"]


@pytest.mark.asyncio
async def test_empty_name():
    with patch("src.tools.set_curation_rule.require_auth", return_value=_FAKE_USER):
        result = await set_curation_rule(name="   ")

    assert result["error"] is True
    assert "name" in result["message"]


@pytest.mark.asyncio
async def test_blocked_by_protected_system_rule():
    """A system rule with override=True must prevent user rule creation with same name."""
    protected_rule = _make_curator_rule(name="secrets_scan", layer="system", override=True)
    mock_session = MagicMock()
    mock_gen = AsyncMock()

    # First query returns the protected rule; second query (existing user rule) is not reached.
    mock_session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=protected_rule)))

    with (
        patch("src.tools.set_curation_rule.require_auth", return_value=_FAKE_USER),
        patch("src.tools.set_curation_rule.get_db_session", return_value=(mock_session, mock_gen)),
        patch("src.tools.set_curation_rule.release_db_session", new_callable=AsyncMock),
    ):
        result = await set_curation_rule(name="secrets_scan")

    assert result["error"] is True
    assert "protected" in result["message"]
    assert "secrets_scan" in result["message"]


@pytest.mark.asyncio
async def test_creates_new_rule():
    """When no existing user rule exists, the tool creates one."""
    new_rule = _make_curator_rule(name="my_threshold")
    mock_session = MagicMock()
    mock_gen = AsyncMock()

    # First execute: no protected rule. Second execute: no existing user rule.
    mock_session.execute = AsyncMock(
        side_effect=[
            MagicMock(scalar_one_or_none=MagicMock(return_value=None)),  # protected check
            MagicMock(scalar_one_or_none=MagicMock(return_value=None)),  # existing user rule check
        ]
    )

    with (
        patch("src.tools.set_curation_rule.require_auth", return_value=_FAKE_USER),
        patch("src.tools.set_curation_rule.get_db_session", return_value=(mock_session, mock_gen)),
        patch("src.tools.set_curation_rule.release_db_session", new_callable=AsyncMock),
        patch(
            "src.tools.set_curation_rule.create_rule",
            new_callable=AsyncMock,
            return_value=new_rule,
        ),
    ):
        result = await set_curation_rule(
            name="my_threshold",
            tier="embedding",
            action="flag",
            config={"threshold": 0.82},
        )

    assert "error" not in result
    assert result["created"] is True
    assert result["updated"] is False
    assert result["rule"]["name"] == "my_threshold"


@pytest.mark.asyncio
async def test_updates_existing_rule():
    """When a user rule with the same name already exists, it is updated in place."""
    existing_rule = _make_curator_rule(name="my_threshold")
    mock_session = MagicMock()
    mock_gen = AsyncMock()
    mock_session.commit = AsyncMock()
    mock_session.refresh = AsyncMock()

    mock_session.execute = AsyncMock(
        side_effect=[
            MagicMock(scalar_one_or_none=MagicMock(return_value=None)),         # protected check
            MagicMock(scalar_one_or_none=MagicMock(return_value=existing_rule)), # existing user rule
        ]
    )

    with (
        patch("src.tools.set_curation_rule.require_auth", return_value=_FAKE_USER),
        patch("src.tools.set_curation_rule.get_db_session", return_value=(mock_session, mock_gen)),
        patch("src.tools.set_curation_rule.release_db_session", new_callable=AsyncMock),
    ):
        result = await set_curation_rule(
            name="my_threshold",
            tier="embedding",
            action="flag",
            config={"threshold": 0.85},
        )

    assert "error" not in result
    assert result["created"] is False
    assert result["updated"] is True
    # The existing_rule mock's attribute should have been updated
    assert existing_rule.config == {"threshold": 0.85}
