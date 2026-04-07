"""Tests for set_session_focus tool."""

import inspect
from datetime import date
from unittest.mock import AsyncMock, patch

import fakeredis.aioredis
import pytest

from memoryhub_core.config import ValkeySettings
from memoryhub_core.services.embeddings import MockEmbeddingService
from memoryhub_core.services.valkey_client import (
    ValkeyClient,
    ValkeyUnavailableError,
    decode_vector,
    set_valkey_client,
)
from src.tools.set_session_focus import set_session_focus

set_session_focus_fn = set_session_focus  # Decorator returns the function directly


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
        "src.tools.set_session_focus.get_claims_from_context",
        return_value=claims,
    ) as mocker:
        yield mocker


@pytest.fixture
def mock_embedding_service():
    """Force the tool to use the deterministic MockEmbeddingService."""
    with patch(
        "src.tools.set_session_focus.get_embedding_service",
        return_value=MockEmbeddingService(),
    ):
        yield


# ---------------------------------------------------------------------------
# Structural assertions
# ---------------------------------------------------------------------------


def test_set_session_focus_is_importable():
    """Verify the tool module imports and the decorated function exists."""
    assert set_session_focus is not None
    assert callable(set_session_focus)


def test_set_session_focus_has_required_parameters():
    """Both focus and project must be required (no default)."""
    sig = inspect.signature(set_session_focus)
    params = sig.parameters

    assert "focus" in params
    assert "project" in params
    assert "ctx" in params

    assert params["focus"].default is inspect.Parameter.empty
    assert params["project"].default is inspect.Parameter.empty


@pytest.mark.asyncio
async def test_set_session_focus_has_write_annotations():
    """Verify the tool is annotated as a write operation, not idempotent.

    A retry appends a new history entry, so it is not idempotent. It is not
    destructive because the old history entry is preserved. Exposing these
    hints correctly lets the consuming agent's harness surface the operation
    the right way.
    """
    from src.core.app import mcp

    tool = await mcp.get_tool("set_session_focus")
    assert tool is not None, "set_session_focus must be registered with the mcp instance"

    annotations = tool.annotations
    assert annotations is not None
    assert annotations.readOnlyHint is False
    assert annotations.destructiveHint is False
    assert annotations.idempotentHint is False
    assert annotations.openWorldHint is False


# ---------------------------------------------------------------------------
# Behavioural assertions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rejects_empty_focus(fake_valkey, mock_claims, mock_embedding_service):
    from fastmcp.exceptions import ToolError

    ctx = AsyncMock()
    with pytest.raises(ToolError, match="focus must not be empty"):
        await set_session_focus_fn(focus="", project="memory-hub", ctx=ctx)

    with pytest.raises(ToolError, match="focus must not be empty"):
        await set_session_focus_fn(focus="   ", project="memory-hub", ctx=ctx)


@pytest.mark.asyncio
async def test_rejects_empty_project(fake_valkey, mock_claims, mock_embedding_service):
    from fastmcp.exceptions import ToolError

    ctx = AsyncMock()
    with pytest.raises(ToolError, match="project must not be empty"):
        await set_session_focus_fn(focus="deployment", project="", ctx=ctx)


@pytest.mark.asyncio
async def test_rejects_unauthenticated_caller(fake_valkey, mock_embedding_service):
    from fastmcp.exceptions import ToolError

    from src.core.authz import AuthenticationError

    ctx = AsyncMock()
    with patch(
        "src.tools.set_session_focus.get_claims_from_context",
        side_effect=AuthenticationError("no identity"),
    ):
        with pytest.raises(ToolError, match="No authenticated session"):
            await set_session_focus_fn(
                focus="deployment", project="memory-hub", ctx=ctx
            )


@pytest.mark.asyncio
async def test_writes_session_and_history_records(
    fake_valkey, mock_claims, mock_embedding_service
):
    ctx = AsyncMock()
    result = await set_session_focus_fn(
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
    import json

    entry = json.loads(history_raw[0])
    assert entry["focus"] == "MCP server deployment to OpenShift"
    assert entry["user_id"] == "wjackson"


@pytest.mark.asyncio
async def test_focus_is_stripped_before_storage(
    fake_valkey, mock_claims, mock_embedding_service
):
    ctx = AsyncMock()
    result = await set_session_focus_fn(
        focus="  deployment  ",
        project="  memory-hub  ",
        ctx=ctx,
    )
    assert result["focus"] == "deployment"
    assert result["project"] == "memory-hub"


@pytest.mark.asyncio
async def test_second_call_appends_new_history_entry(
    fake_valkey, mock_claims, mock_embedding_service
):
    """Updating focus mid-session should overwrite the active-session hash
    but preserve the history log."""
    ctx = AsyncMock()
    await set_session_focus_fn(focus="deployment", project="memory-hub", ctx=ctx)
    await set_session_focus_fn(focus="auth tokens", project="memory-hub", ctx=ctx)

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
async def test_valkey_unavailable_surfaces_tool_error(
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
        await set_session_focus_fn(
            focus="deployment", project="memory-hub", ctx=ctx
        )
