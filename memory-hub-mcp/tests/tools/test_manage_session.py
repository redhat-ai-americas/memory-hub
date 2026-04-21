"""Tests for the consolidated manage_session tool.

Migrated from test_set_session_focus.py and test_get_focus_history.py as part
of the tool consolidation that replaced get_session, set_session_focus, and
get_focus_history with a single action-dispatch interface.
"""

import inspect
import json
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import fakeredis.aioredis
import pytest

from memoryhub_core.config import ValkeySettings
from memoryhub_core.services.embeddings import MockEmbeddingService
from memoryhub_core.services.valkey_client import (
    ValkeyClient,
    decode_vector,
    set_valkey_client,
)
from src.tools.manage_session import manage_session


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def _reset_valkey_client():
    """Reset the module-level Valkey client singleton between tests."""
    set_valkey_client(None)
    yield
    set_valkey_client(None)


@pytest.fixture
def fake_valkey(_reset_valkey_client):
    """Install a fakeredis-backed ValkeyClient as the process default."""
    fake = fakeredis.aioredis.FakeRedis(decode_responses=True)
    client = ValkeyClient(settings=ValkeySettings(), client=fake)
    set_valkey_client(client)
    return client


@pytest.fixture
def mock_claims():
    """Patch get_claims_from_context to return a stable identity."""
    claims = {
        "sub": "wjackson",
        "identity_type": "user",
        "tenant_id": "default",
        "scopes": ["memory:read:user", "memory:write:user"],
    }
    with patch(
        "src.tools.manage_session.get_claims_from_context",
        return_value=claims,
    ) as mocker:
        yield mocker


@pytest.fixture
def mock_embedding_service():
    """Force the tool to use the deterministic MockEmbeddingService."""
    with patch(
        "src.tools.manage_session.get_embedding_service",
        return_value=MockEmbeddingService(),
    ):
        yield


async def _seed_history(fake, project: str, day: date, entries: list[dict]) -> None:
    """Write history entries directly into fakeredis for test setup."""
    key = f"memoryhub:session_focus_history:{project}:{day.isoformat()}"
    for entry in entries:
        await fake.lpush(key, json.dumps(entry))


# ---------------------------------------------------------------------------
# Structural assertions
# ---------------------------------------------------------------------------


def test_manage_session_is_importable():
    assert manage_session is not None
    assert callable(manage_session)


def test_manage_session_has_action_parameter():
    sig = inspect.signature(manage_session)
    params = sig.parameters

    assert "action" in params
    assert params["action"].default is inspect.Parameter.empty


def test_manage_session_optional_params_have_defaults():
    """focus, project, start_date, end_date are all optional (None default)."""
    sig = inspect.signature(manage_session)
    params = sig.parameters

    for name in ("focus", "project", "start_date", "end_date"):
        assert name in params, f"Expected parameter '{name}' in manage_session"
        assert params[name].default is None, (
            f"Expected '{name}' to default to None"
        )


@pytest.mark.asyncio
async def test_manage_session_has_expected_annotations():
    """Verify the registered annotations on the consolidated tool."""
    from src.core.app import mcp

    tool = await mcp.get_tool("manage_session")
    assert tool is not None, "manage_session must be registered with the mcp instance"

    annotations = tool.annotations
    assert annotations is not None
    assert annotations.readOnlyHint is False
    assert annotations.destructiveHint is False
    assert annotations.idempotentHint is False
    assert annotations.openWorldHint is False


# ---------------------------------------------------------------------------
# Invalid action dispatch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rejects_invalid_action():
    from fastmcp.exceptions import ToolError

    ctx = AsyncMock()
    with pytest.raises(ToolError, match="Invalid action"):
        await manage_session(action="not_a_real_action", ctx=ctx)


# ---------------------------------------------------------------------------
# action='set_focus' — migrated from test_set_session_focus.py
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_set_focus_rejects_empty_focus(fake_valkey, mock_claims, mock_embedding_service):
    from fastmcp.exceptions import ToolError

    ctx = AsyncMock()
    with pytest.raises(ToolError, match="focus"):
        await manage_session(action="set_focus", focus="", project="memory-hub", ctx=ctx)

    with pytest.raises(ToolError, match="focus"):
        await manage_session(action="set_focus", focus="   ", project="memory-hub", ctx=ctx)


@pytest.mark.asyncio
async def test_set_focus_rejects_empty_project(fake_valkey, mock_claims, mock_embedding_service):
    from fastmcp.exceptions import ToolError

    ctx = AsyncMock()
    with pytest.raises(ToolError, match="project"):
        await manage_session(action="set_focus", focus="deployment", project="", ctx=ctx)


@pytest.mark.asyncio
async def test_set_focus_rejects_unauthenticated_caller(fake_valkey, mock_embedding_service):
    from fastmcp.exceptions import ToolError

    from src.core.authz import AuthenticationError

    ctx = AsyncMock()
    with patch(
        "src.tools.manage_session.get_claims_from_context",
        side_effect=AuthenticationError("no identity"),
    ):
        with pytest.raises(ToolError, match="No authenticated session"):
            await manage_session(
                action="set_focus", focus="deployment", project="memory-hub", ctx=ctx
            )


@pytest.mark.asyncio
async def test_set_focus_writes_session_and_history_records(
    fake_valkey, mock_claims, mock_embedding_service
):
    ctx = AsyncMock()
    result = await manage_session(
        action="set_focus",
        focus="MCP server deployment to OpenShift",
        project="memory-hub",
        ctx=ctx,
    )

    assert result["session_id"] == "wjackson"
    assert result["user_id"] == "wjackson"
    assert result["project"] == "memory-hub"
    assert result["focus"] == "MCP server deployment to OpenShift"
    assert "expires_at" in result
    assert "recorded" in result["message"]

    # Verify the underlying Valkey state
    fake = fake_valkey._client
    session_data = await fake.hgetall("memoryhub:sessions:wjackson")
    assert session_data["focus"] == "MCP server deployment to OpenShift"
    assert session_data["project"] == "memory-hub"
    assert session_data["user_id"] == "wjackson"

    # Embedding round-trips through the vector codec
    decoded = decode_vector(session_data["focus_vector"])
    assert len(decoded) == 384  # MockEmbeddingService dim matches production

    # History entry exists for today
    today_key_prefix = "memoryhub:session_focus_history:memory-hub:"
    keys = [k async for k in fake.scan_iter(match=f"{today_key_prefix}*")]
    assert len(keys) == 1
    history_raw = await fake.lrange(keys[0], 0, -1)
    assert len(history_raw) == 1
    entry = json.loads(history_raw[0])
    assert entry["focus"] == "MCP server deployment to OpenShift"
    assert entry["user_id"] == "wjackson"


@pytest.mark.asyncio
async def test_set_focus_strips_whitespace(fake_valkey, mock_claims, mock_embedding_service):
    ctx = AsyncMock()
    result = await manage_session(
        action="set_focus",
        focus="  deployment  ",
        project="  memory-hub  ",
        ctx=ctx,
    )
    assert result["focus"] == "deployment"
    assert result["project"] == "memory-hub"


@pytest.mark.asyncio
async def test_set_focus_second_call_appends_new_history_entry(
    fake_valkey, mock_claims, mock_embedding_service
):
    """Updating focus mid-session overwrites the active-session hash but
    preserves the history log."""
    ctx = AsyncMock()
    await manage_session(action="set_focus", focus="deployment", project="memory-hub", ctx=ctx)
    await manage_session(action="set_focus", focus="auth tokens", project="memory-hub", ctx=ctx)

    fake = fake_valkey._client
    session_data = await fake.hgetall("memoryhub:sessions:wjackson")
    assert session_data["focus"] == "auth tokens"  # hash was overwritten

    keys = [
        k
        async for k in fake.scan_iter(
            match="memoryhub:session_focus_history:memory-hub:*"
        )
    ]
    assert len(keys) == 1
    history_raw = await fake.lrange(keys[0], 0, -1)
    assert len(history_raw) == 2  # history preserves both declarations


@pytest.mark.asyncio
async def test_set_focus_valkey_unavailable_surfaces_tool_error(
    mock_claims, mock_embedding_service, _reset_valkey_client
):
    """If the backend is unreachable, the tool should raise ToolError with
    guidance, not swallow the failure silently."""
    from fastmcp.exceptions import ToolError

    class BrokenClient:
        def pipeline(self, transaction=True):
            from redis.exceptions import ConnectionError as RedisConnectionError

            raise RedisConnectionError("backend unreachable")

        async def aclose(self):
            pass

    broken = ValkeyClient(settings=ValkeySettings(), client=BrokenClient())
    set_valkey_client(broken)

    ctx = AsyncMock()
    with pytest.raises(ToolError, match="Session focus store is unavailable"):
        await manage_session(
            action="set_focus", focus="deployment", project="memory-hub", ctx=ctx
        )


# ---------------------------------------------------------------------------
# action='focus_history' — migrated from test_get_focus_history.py
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_focus_history_rejects_empty_project(fake_valkey, mock_claims):
    from fastmcp.exceptions import ToolError

    ctx = AsyncMock()
    with pytest.raises(ToolError, match="project"):
        await manage_session(action="focus_history", project="", ctx=ctx)


@pytest.mark.asyncio
async def test_focus_history_rejects_unauthenticated_caller(fake_valkey):
    from fastmcp.exceptions import ToolError

    from src.core.authz import AuthenticationError

    ctx = AsyncMock()
    with patch(
        "src.tools.manage_session.get_claims_from_context",
        side_effect=AuthenticationError("no identity"),
    ):
        with pytest.raises(ToolError, match="No authenticated session"):
            await manage_session(action="focus_history", project="memory-hub", ctx=ctx)


@pytest.mark.asyncio
async def test_focus_history_rejects_malformed_dates(fake_valkey, mock_claims):
    from fastmcp.exceptions import ToolError

    ctx = AsyncMock()
    with pytest.raises(ToolError, match="Invalid start_date format"):
        await manage_session(
            action="focus_history", project="memory-hub", start_date="not-a-date", ctx=ctx
        )
    with pytest.raises(ToolError, match="Invalid end_date format"):
        await manage_session(
            action="focus_history", project="memory-hub", end_date="2026/04/07", ctx=ctx
        )


@pytest.mark.asyncio
async def test_focus_history_rejects_inverted_date_range(fake_valkey, mock_claims):
    from fastmcp.exceptions import ToolError

    ctx = AsyncMock()
    with pytest.raises(ToolError, match="is after end_date"):
        await manage_session(
            action="focus_history",
            project="memory-hub",
            start_date="2026-04-10",
            end_date="2026-04-05",
            ctx=ctx,
        )


@pytest.mark.asyncio
async def test_focus_history_empty_returns_zero_histogram(fake_valkey, mock_claims):
    ctx = AsyncMock()
    result = await manage_session(
        action="focus_history",
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
async def test_focus_history_aggregates_single_day(fake_valkey, mock_claims):
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
    result = await manage_session(
        action="focus_history",
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
async def test_focus_history_aggregates_across_date_range(fake_valkey, mock_claims):
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
    result = await manage_session(
        action="focus_history",
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
async def test_focus_history_respects_project_boundary(fake_valkey, mock_claims):
    fake = fake_valkey._client
    day = date(2026, 4, 7)
    await _seed_history(
        fake, "memory-hub", day, [{"focus": "deployment"}, {"focus": "deployment"}]
    )
    await _seed_history(
        fake, "other-project", day, [{"focus": "deployment"}, {"focus": "deployment"}]
    )

    ctx = AsyncMock()
    result = await manage_session(
        action="focus_history",
        project="memory-hub",
        start_date="2026-04-07",
        end_date="2026-04-07",
        ctx=ctx,
    )
    assert result["total_sessions"] == 2


@pytest.mark.asyncio
async def test_focus_history_default_window_is_30_days_ending_today(fake_valkey, mock_claims):
    """With both dates omitted the window should be [today-30, today]."""
    ctx = AsyncMock()
    today = datetime.now(timezone.utc).date()

    result = await manage_session(action="focus_history", project="memory-hub", ctx=ctx)

    assert result["end_date"] == today.isoformat()
    assert result["start_date"] == (today - timedelta(days=30)).isoformat()


@pytest.mark.asyncio
async def test_focus_history_default_start_is_30_days_before_provided_end(
    fake_valkey, mock_claims
):
    """With only end_date set, start_date should default to end - 30 days."""
    ctx = AsyncMock()
    result = await manage_session(
        action="focus_history",
        project="memory-hub",
        end_date="2026-04-07",
        ctx=ctx,
    )
    assert result["end_date"] == "2026-04-07"
    assert result["start_date"] == (date(2026, 4, 7) - timedelta(days=30)).isoformat()


@pytest.mark.asyncio
async def test_focus_history_skips_entries_with_missing_focus(fake_valkey, mock_claims):
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
    result = await manage_session(
        action="focus_history",
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
async def test_focus_history_valkey_unavailable_surfaces_tool_error(
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
        await manage_session(
            action="focus_history",
            project="memory-hub",
            start_date="2026-04-07",
            end_date="2026-04-07",
            ctx=ctx,
        )
