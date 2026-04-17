"""Tests for get_similar_memories tool."""

import inspect
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from fastmcp.exceptions import ToolError

import src.tools.auth as auth_mod
from src.tools.get_similar_memories import get_similar_memories


def test_get_similar_memories_is_decorated():
    """Verify get_similar_memories is a decorated MCP tool."""
    assert callable(get_similar_memories)


def test_get_similar_memories_is_async():
    """The tool function must be async."""
    assert inspect.iscoroutinefunction(get_similar_memories)


def test_get_similar_memories_has_required_parameters():
    """Verify the function signature includes all expected parameters."""
    sig = inspect.signature(get_similar_memories)
    param_names = set(sig.parameters.keys())

    required = {"memory_id"}
    assert required.issubset(param_names), (
        f"Missing required params: {required - param_names}"
    )

    optional = {"threshold", "max_results", "offset", "ctx"}
    assert optional.issubset(param_names), (
        f"Missing optional params: {optional - param_names}"
    )


def test_get_similar_memories_default_values():
    """Verify default values for optional parameters."""
    sig = inspect.signature(get_similar_memories)
    params = sig.parameters

    assert params["threshold"].default == 0.80
    assert params["max_results"].default == 10
    assert params["offset"].default == 0


@pytest.mark.asyncio
async def test_get_similar_memories_requires_auth():
    """Unauthenticated calls raise ToolError."""
    auth_mod._current_session = None
    with pytest.raises(ToolError):
        await get_similar_memories(memory_id=str(uuid.uuid4()))


@pytest.mark.asyncio
async def test_get_similar_memories_invalid_uuid():
    """Bad UUID format raises ToolError with a clear message."""
    with pytest.raises(ToolError, match="Invalid memory_id format"):
        await get_similar_memories(memory_id="not-a-uuid")


@pytest.mark.asyncio
async def test_get_similar_memories_success():
    """Successful query returns paged results."""
    from types import SimpleNamespace

    mock_session = AsyncMock()
    mock_gen = AsyncMock()
    fake_source = SimpleNamespace(
        scope="user", owner_id="wjackson", tenant_id="default"
    )

    with (
        patch(
            "src.tools.get_similar_memories.get_db_session",
            return_value=(mock_session, mock_gen),
        ),
        patch(
            "src.tools.get_similar_memories.release_db_session", new_callable=AsyncMock
        ),
        patch(
            "src.tools.get_similar_memories.read_memory_service",
            new_callable=AsyncMock,
            return_value=fake_source,
        ),
        patch(
            "src.tools.get_similar_memories.get_similar_memories_service",
            new_callable=AsyncMock,
            return_value={"results": [], "total": 0, "has_more": False},
        ),
    ):
        # Authenticate as the source's owner so authorize_read passes.
        auth_mod._current_session = {
            "user_id": "wjackson",
            "scopes": ["user"],
            "identity_type": "user",
        }
        try:
            result = await get_similar_memories(memory_id=str(uuid.uuid4()))
        finally:
            auth_mod._current_session = None
    assert result["total"] == 0
    assert result["has_more"] is False


@pytest.mark.asyncio
async def test_get_similar_memories_returns_results_for_owner():
    """Regression for #47: results from the service must reach the caller.

    The previous post-fetch RBAC filter dropped every result because the
    service-layer items only contain {id, stub, score} -- not scope/owner_id --
    so the SimpleNamespace defaults rejected everything via authorize_read.
    Verify that when the caller owns the source, all returned items pass
    through unchanged.
    """
    from types import SimpleNamespace

    mock_session = AsyncMock()
    mock_gen = AsyncMock()
    fake_source = SimpleNamespace(
        scope="user", owner_id="wjackson", tenant_id="default"
    )
    sim_id = uuid.uuid4()
    service_results = {
        "results": [
            {"id": sim_id, "stub": "similar 1", "score": 0.92},
            {"id": uuid.uuid4(), "stub": "similar 2", "score": 0.85},
        ],
        "total": 2,
        "has_more": False,
    }

    with (
        patch(
            "src.tools.get_similar_memories.get_db_session",
            return_value=(mock_session, mock_gen),
        ),
        patch(
            "src.tools.get_similar_memories.release_db_session", new_callable=AsyncMock
        ),
        patch(
            "src.tools.get_similar_memories.read_memory_service",
            new_callable=AsyncMock,
            return_value=fake_source,
        ),
        patch(
            "src.tools.get_similar_memories.get_similar_memories_service",
            new_callable=AsyncMock,
            return_value=service_results,
        ),
    ):
        auth_mod._current_session = {
            "user_id": "wjackson",
            "scopes": ["user"],
            "identity_type": "user",
        }
        try:
            result = await get_similar_memories(memory_id=str(uuid.uuid4()))
        finally:
            auth_mod._current_session = None

    assert result.get("error") is not True
    assert "results" in result
    assert len(result["results"]) == 2
    assert result["total"] == 2
    # IDs must be JSON-serializable strings, not UUID objects
    assert all(isinstance(item["id"], str) for item in result["results"])


@pytest.mark.asyncio
async def test_get_similar_memories_unauthorized_for_other_owner():
    """Regression for #47: callers cannot read memories outside their scope.

    Even though the post-fetch filter is gone, caller-vs-source authorization
    must still reject reads of memories owned by other users at user scope.
    """
    from types import SimpleNamespace

    mock_session = AsyncMock()
    mock_gen = AsyncMock()
    other_owner_source = SimpleNamespace(
        scope="user", owner_id="someone-else", tenant_id="default"
    )

    auth_mod._current_session = {
        "user_id": "wjackson",
        "scopes": ["user"],
        "identity_type": "user",
    }
    try:
        with (
            patch(
                "src.tools.get_similar_memories.get_db_session",
                return_value=(mock_session, mock_gen),
            ),
            patch(
                "src.tools.get_similar_memories.release_db_session",
                new_callable=AsyncMock,
            ),
            patch(
                "src.tools.get_similar_memories.read_memory_service",
                new_callable=AsyncMock,
                return_value=other_owner_source,
            ),
            pytest.raises(ToolError, match="Not authorized"),
        ):
            await get_similar_memories(memory_id=str(uuid.uuid4()))
    finally:
        auth_mod._current_session = None


@pytest.mark.asyncio
async def test_get_similar_memories_forwards_tenant_id_to_service():
    """Phase 4 (#46): the tool must forward claims.tenant_id into both
    the read_memory_service (auth check) and the get_similar_memories
    service calls so the SQL-level tenant filter runs in the correct
    tenant."""
    from types import SimpleNamespace

    mock_session = AsyncMock()
    mock_gen = AsyncMock()
    fake_source = SimpleNamespace(
        scope="user", owner_id="wjackson", tenant_id="tenant_a"
    )
    fake_claims = {
        "sub": "wjackson",
        "identity_type": "user",
        "tenant_id": "tenant_a",
        "scopes": ["memory:read:user", "memory:write:user"],
    }

    with (
        patch(
            "src.tools.get_similar_memories.get_claims_from_context",
            return_value=fake_claims,
        ),
        patch(
            "src.tools.get_similar_memories.get_db_session",
            return_value=(mock_session, mock_gen),
        ),
        patch(
            "src.tools.get_similar_memories.release_db_session",
            new_callable=AsyncMock,
        ),
        patch(
            "src.tools.get_similar_memories.read_memory_service",
            new_callable=AsyncMock,
            return_value=fake_source,
        ) as mock_read,
        patch(
            "src.tools.get_similar_memories.get_similar_memories_service",
            new_callable=AsyncMock,
            return_value={"results": [], "total": 0, "has_more": False},
        ) as mock_similar,
    ):
        await get_similar_memories(memory_id=str(uuid.uuid4()))

    _, read_kwargs = mock_read.call_args
    assert read_kwargs.get("tenant_id") == "tenant_a", (
        "Expected tenant_id='tenant_a' in read_memory_service kwargs, "
        f"got {read_kwargs}"
    )
    _, similar_kwargs = mock_similar.call_args
    assert similar_kwargs.get("tenant_id") == "tenant_a", (
        f"Expected tenant_id='tenant_a' in get_similar_memories_service kwargs, "
        f"got {similar_kwargs}"
    )
