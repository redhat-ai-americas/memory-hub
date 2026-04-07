"""Tests for get_focus_history tool."""

import inspect
import json
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import fakeredis.aioredis
import pytest

from memoryhub_core.config import ValkeySettings
from memoryhub_core.services.valkey_client import (
    ValkeyClient,
    set_valkey_client,
)
from src.tools.get_focus_history import get_focus_history

get_focus_history_fn = get_focus_history  # Decorator returns the function directly


@pytest.fixture
def _reset_valkey_client():
    set_valkey_client(None)
    yield
    set_valkey_client(None)


@pytest.fixture
def fake_valkey(_reset_valkey_client):
    fake = fakeredis.aioredis.FakeRedis(decode_responses=True)
    client = ValkeyClient(settings=ValkeySettings(), client=fake)
    set_valkey_client(client)
    return client


@pytest.fixture
def mock_claims():
    claims = {
        "sub": "wjackson",
        "identity_type": "user",
        "tenant_id": "default",
        "scopes": ["memory:read:user", "memory:write:user"],
    }
    with patch(
        "src.tools.get_focus_history.get_claims_from_context",
        return_value=claims,
    ) as mocker:
        yield mocker


async def _seed_history(fake, project: str, day: date, entries: list[dict]) -> None:
    key = f"memoryhub:session_focus_history:{project}:{day.isoformat()}"
    for entry in entries:
        await fake.lpush(key, json.dumps(entry))


# ---------------------------------------------------------------------------
# Structural assertions
# ---------------------------------------------------------------------------


def test_get_focus_history_is_importable():
    assert get_focus_history is not None
    assert callable(get_focus_history)


def test_get_focus_history_has_required_parameters():
    sig = inspect.signature(get_focus_history)
    params = sig.parameters

    assert "project" in params
    assert "start_date" in params
    assert "end_date" in params
    assert "ctx" in params

    # project is required; dates default to None
    assert params["project"].default is inspect.Parameter.empty
    assert params["start_date"].default is None
    assert params["end_date"].default is None


@pytest.mark.asyncio
async def test_get_focus_history_has_read_annotations():
    """Pure read, so readOnly and idempotent should both be True."""
    from src.core.app import mcp

    tool = await mcp.get_tool("get_focus_history")
    assert tool is not None

    annotations = tool.annotations
    assert annotations is not None
    assert annotations.readOnlyHint is True
    assert annotations.destructiveHint is False
    assert annotations.idempotentHint is True
    assert annotations.openWorldHint is False


# ---------------------------------------------------------------------------
# Behavioural assertions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rejects_empty_project(fake_valkey, mock_claims):
    from fastmcp.exceptions import ToolError

    ctx = AsyncMock()
    with pytest.raises(ToolError, match="project must not be empty"):
        await get_focus_history_fn(project="", ctx=ctx)


@pytest.mark.asyncio
async def test_rejects_unauthenticated_caller(fake_valkey):
    from fastmcp.exceptions import ToolError

    from src.core.authz import AuthenticationError

    ctx = AsyncMock()
    with patch(
        "src.tools.get_focus_history.get_claims_from_context",
        side_effect=AuthenticationError("no identity"),
    ):
        with pytest.raises(ToolError, match="No authenticated session"):
            await get_focus_history_fn(project="memory-hub", ctx=ctx)


@pytest.mark.asyncio
async def test_rejects_malformed_dates(fake_valkey, mock_claims):
    from fastmcp.exceptions import ToolError

    ctx = AsyncMock()
    with pytest.raises(ToolError, match="Invalid start_date format"):
        await get_focus_history_fn(
            project="memory-hub", start_date="not-a-date", ctx=ctx
        )
    with pytest.raises(ToolError, match="Invalid end_date format"):
        await get_focus_history_fn(
            project="memory-hub", end_date="2026/04/07", ctx=ctx
        )


@pytest.mark.asyncio
async def test_rejects_inverted_date_range(fake_valkey, mock_claims):
    from fastmcp.exceptions import ToolError

    ctx = AsyncMock()
    with pytest.raises(ToolError, match="is after end_date"):
        await get_focus_history_fn(
            project="memory-hub",
            start_date="2026-04-10",
            end_date="2026-04-05",
            ctx=ctx,
        )


@pytest.mark.asyncio
async def test_empty_history_returns_zero_histogram(fake_valkey, mock_claims):
    ctx = AsyncMock()
    result = await get_focus_history_fn(
        project="memory-hub",
        start_date="2026-04-01",
        end_date="2026-04-07",
        ctx=ctx,
    )
    assert result["project"] == "memory-hub"
    assert result["total_sessions"] == 0
    assert result["histogram"] == []
    assert result["start_date"] == "2026-04-01"
    assert result["end_date"] == "2026-04-07"


@pytest.mark.asyncio
async def test_aggregates_single_day(fake_valkey, mock_claims):
    fake = fake_valkey._client
    day = date(2026, 4, 7)
    await _seed_history(
        fake,
        "memory-hub",
        day,
        [
            {"focus": "deployment", "user_id": "wjackson"},
            {"focus": "deployment", "user_id": "wjackson"},
            {"focus": "auth", "user_id": "wjackson"},
        ],
    )

    ctx = AsyncMock()
    result = await get_focus_history_fn(
        project="memory-hub",
        start_date="2026-04-07",
        end_date="2026-04-07",
        ctx=ctx,
    )

    assert result["total_sessions"] == 3
    assert result["histogram"] == [
        {"focus": "deployment", "count": 2},
        {"focus": "auth", "count": 1},
    ]


@pytest.mark.asyncio
async def test_aggregates_across_date_range(fake_valkey, mock_claims):
    fake = fake_valkey._client
    await _seed_history(
        fake,
        "memory-hub",
        date(2026, 4, 5),
        [{"focus": "deployment"}, {"focus": "deployment"}, {"focus": "ui"}],
    )
    await _seed_history(
        fake,
        "memory-hub",
        date(2026, 4, 6),
        [{"focus": "deployment"}, {"focus": "auth"}],
    )
    await _seed_history(
        fake,
        "memory-hub",
        date(2026, 4, 7),
        [{"focus": "ui"}, {"focus": "auth"}, {"focus": "deployment"}],
    )

    ctx = AsyncMock()
    result = await get_focus_history_fn(
        project="memory-hub",
        start_date="2026-04-05",
        end_date="2026-04-07",
        ctx=ctx,
    )

    assert result["total_sessions"] == 8
    # Sort order: count desc, then alpha asc
    assert result["histogram"] == [
        {"focus": "deployment", "count": 4},
        {"focus": "auth", "count": 2},
        {"focus": "ui", "count": 2},
    ]


@pytest.mark.asyncio
async def test_respects_project_boundary(fake_valkey, mock_claims):
    fake = fake_valkey._client
    day = date(2026, 4, 7)
    await _seed_history(
        fake, "memory-hub", day, [{"focus": "deployment"}, {"focus": "deployment"}]
    )
    await _seed_history(
        fake, "other-project", day, [{"focus": "deployment"}, {"focus": "deployment"}]
    )

    ctx = AsyncMock()
    result = await get_focus_history_fn(
        project="memory-hub",
        start_date="2026-04-07",
        end_date="2026-04-07",
        ctx=ctx,
    )
    assert result["total_sessions"] == 2


@pytest.mark.asyncio
async def test_default_window_is_30_days_ending_today(fake_valkey, mock_claims):
    """With both dates omitted, the window should be [today-30, today]."""
    ctx = AsyncMock()
    today = datetime.now(timezone.utc).date()

    result = await get_focus_history_fn(project="memory-hub", ctx=ctx)

    assert result["end_date"] == today.isoformat()
    assert result["start_date"] == (today - timedelta(days=30)).isoformat()


@pytest.mark.asyncio
async def test_default_start_is_30_days_before_provided_end(fake_valkey, mock_claims):
    """With only end_date set, start_date should default to end - 30 days."""
    ctx = AsyncMock()
    result = await get_focus_history_fn(
        project="memory-hub",
        end_date="2026-04-07",
        ctx=ctx,
    )
    assert result["end_date"] == "2026-04-07"
    assert result["start_date"] == (date(2026, 4, 7) - timedelta(days=30)).isoformat()


@pytest.mark.asyncio
async def test_skips_entries_with_missing_focus(fake_valkey, mock_claims):
    fake = fake_valkey._client
    await _seed_history(
        fake,
        "memory-hub",
        date(2026, 4, 7),
        [
            {"focus": "deployment"},
            {"focus": ""},
            {"user_id": "wjackson"},  # no focus key at all
            {"focus": None},
        ],
    )

    ctx = AsyncMock()
    result = await get_focus_history_fn(
        project="memory-hub",
        start_date="2026-04-07",
        end_date="2026-04-07",
        ctx=ctx,
    )
    # total_sessions is the raw entry count from Valkey, regardless of whether
    # each entry had a usable focus key. The histogram drops the malformed ones.
    assert result["total_sessions"] == 4
    assert result["histogram"] == [{"focus": "deployment", "count": 1}]


@pytest.mark.asyncio
async def test_valkey_unavailable_surfaces_tool_error(
    mock_claims, _reset_valkey_client
):
    from fastmcp.exceptions import ToolError

    class BrokenClient:
        async def lrange(self, *args, **kwargs):
            from redis.exceptions import ConnectionError as RedisConnectionError

            raise RedisConnectionError("backend unreachable")

        async def aclose(self):
            pass

    broken = ValkeyClient(settings=ValkeySettings(), client=BrokenClient())
    set_valkey_client(broken)

    ctx = AsyncMock()
    with pytest.raises(ToolError, match="Session focus store is unavailable"):
        await get_focus_history_fn(
            project="memory-hub",
            start_date="2026-04-07",
            end_date="2026-04-07",
            ctx=ctx,
        )
