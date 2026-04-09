"""Tests for write_memory tool."""

import inspect

import pytest
from fastmcp.exceptions import ToolError

import src.tools.auth as auth_mod
from src.tools.write_memory import write_memory


def test_write_memory_is_decorated():
    """Verify write_memory is a decorated MCP tool."""
    assert hasattr(write_memory, "__fastmcp__"), (
        "write_memory should be decorated with @mcp.tool"
    )


def test_write_memory_is_async():
    """The tool function must be async."""
    assert inspect.iscoroutinefunction(write_memory)


def test_write_memory_has_required_parameters():
    """Verify the function signature includes all expected parameters."""
    sig = inspect.signature(write_memory)
    param_names = set(sig.parameters.keys())

    required = {"content", "scope", "owner_id"}
    assert required.issubset(param_names), (
        f"Missing required params: {required - param_names}"
    )

    optional = {"weight", "parent_id", "branch_type", "metadata", "ctx"}
    assert optional.issubset(param_names), (
        f"Missing optional params: {optional - param_names}"
    )


def test_write_memory_default_values():
    """Verify default values for optional parameters."""
    sig = inspect.signature(write_memory)
    params = sig.parameters

    assert params["weight"].default == 0.7
    assert params["parent_id"].default is None
    assert params["branch_type"].default is None
    assert params["metadata"].default is None


@pytest.mark.asyncio
async def test_write_memory_rejects_orphan_branch():
    """Regression for #48: branch_type without parent_id is invalid.

    A branch must attach to a parent memory. The previous validation only
    rejected the inverse (parent_id without branch_type), accepting orphans
    silently and producing memory nodes that claimed to be branches but had
    no parent.
    """
    auth_mod._current_session = {
        "user_id": "wjackson",
        "scopes": ["user"],
        "identity_type": "user",
    }
    try:
        with pytest.raises(ToolError) as exc_info:
            await write_memory(
                content="orphan branch attempt",
                scope="user",
                branch_type="rationale",
            )
    finally:
        auth_mod._current_session = None

    assert "parent_id is required" in str(exc_info.value), str(exc_info.value)
    assert "branch_type" in str(exc_info.value), str(exc_info.value)


@pytest.mark.asyncio
async def test_write_memory_still_rejects_parent_without_branch_type():
    """The inverse guard must still fire: parent_id without branch_type is invalid."""
    import uuid as _uuid

    auth_mod._current_session = {
        "user_id": "wjackson",
        "scopes": ["user"],
        "identity_type": "user",
    }
    try:
        with pytest.raises(ToolError) as exc_info:
            await write_memory(
                content="branch with no type",
                scope="user",
                parent_id=str(_uuid.uuid4()),
            )
    finally:
        auth_mod._current_session = None

    assert "branch_type is required" in str(exc_info.value), str(exc_info.value)


@pytest.mark.asyncio
async def test_write_memory_forwards_tenant_id_to_service():
    """Phase 3 (#46): the tool must forward the caller's tenant_id from
    claims into create_memory so the persisted row carries the correct
    tenant rather than falling through to the column server_default."""
    import datetime as _dt
    import uuid as _uuid
    from unittest.mock import AsyncMock, MagicMock, patch

    from memoryhub_core.models.schemas import MemoryNodeRead, MemoryScope, StorageType

    fake_node = MemoryNodeRead(
        id=_uuid.uuid4(),
        parent_id=None,
        content="hello",
        stub="hello",
        storage_type=StorageType.INLINE,
        content_ref=None,
        weight=0.7,
        scope=MemoryScope.USER,
        branch_type=None,
        owner_id="wjackson",
        tenant_id="tenant_a",
        is_current=True,
        version=1,
        previous_version_id=None,
        metadata=None,
        created_at=_dt.datetime.now(_dt.UTC),
        updated_at=_dt.datetime.now(_dt.UTC),
        expires_at=None,
        has_children=False,
        has_rationale=False,
        branch_count=0,
    )
    fake_curation = {
        "blocked": False,
        "reason": None,
        "detail": None,
        "similar_count": 0,
        "nearest_id": None,
        "nearest_score": None,
        "flags": [],
    }

    mock_session = MagicMock()
    mock_gen = AsyncMock()
    fake_claims = {
        "sub": "wjackson",
        "identity_type": "user",
        "tenant_id": "tenant_a",
        "scopes": ["memory:write:user", "memory:read:user"],
    }

    with (
        patch(
            "src.tools.write_memory.get_claims_from_context",
            return_value=fake_claims,
        ),
        patch(
            "src.tools.write_memory.get_db_session",
            return_value=(mock_session, mock_gen),
        ),
        patch(
            "src.tools.write_memory.release_db_session",
            new_callable=AsyncMock,
        ),
        patch(
            "src.tools.write_memory.get_embedding_service",
            return_value=MagicMock(),
        ),
        patch(
            "src.tools.write_memory.create_memory",
            new_callable=AsyncMock,
            return_value=(fake_node, fake_curation),
        ) as mock_create_memory,
        patch(
            "src.tools.write_memory.broadcast_after_write",
            new_callable=AsyncMock,
        ),
    ):
        result = await write_memory(
            content="hello",
            scope="user",
            owner_id="wjackson",
        )

    assert "error" not in result or result.get("error") is not True
    _, kwargs = mock_create_memory.call_args
    assert kwargs.get("tenant_id") == "tenant_a", (
        f"Expected tenant_id='tenant_a' forwarded from claims into create_memory, "
        f"got kwargs={kwargs}"
    )
