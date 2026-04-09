"""Tests for read_memory tool."""

import inspect
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from fastmcp.exceptions import ToolError

import src.tools.auth as auth_mod
from src.tools.read_memory import read_memory


def test_read_memory_is_decorated():
    """Verify read_memory is a decorated MCP tool."""
    assert hasattr(read_memory, "__fastmcp__"), (
        "read_memory should be decorated with @mcp.tool"
    )


def test_read_memory_is_async():
    """The tool function must be async."""
    assert inspect.iscoroutinefunction(read_memory)


def test_read_memory_has_required_parameters():
    """Verify the function signature includes all expected parameters."""
    sig = inspect.signature(read_memory)
    param_names = set(sig.parameters.keys())

    required = {"memory_id"}
    assert required.issubset(param_names), (
        f"Missing required params: {required - param_names}"
    )

    optional = {"include_versions", "ctx"}
    assert optional.issubset(param_names), (
        f"Missing optional params: {optional - param_names}"
    )


def test_read_memory_does_not_have_depth_parameter():
    """Regression for #50: depth was removed in favor of branch_count."""
    sig = inspect.signature(read_memory)
    assert "depth" not in sig.parameters


def test_read_memory_default_values():
    """Verify default values for optional parameters."""
    sig = inspect.signature(read_memory)
    params = sig.parameters

    assert params["include_versions"].default is False


def _fake_node(
    scope: str = "user",
    owner_id: str = "wjackson",
    branch_count: int = 0,
    tenant_id: str = "default",
):
    """Build a stand-in for the read_memory service return value."""
    import datetime as _dt

    from memoryhub_core.models.schemas import MemoryNodeRead, MemoryScope, StorageType

    return MemoryNodeRead(
        id=uuid.uuid4(),
        parent_id=None,
        content="memory content",
        stub="memory stub",
        storage_type=StorageType.INLINE,
        content_ref=None,
        weight=0.7,
        scope=MemoryScope(scope),
        branch_type=None,
        owner_id=owner_id,
        tenant_id=tenant_id,
        is_current=True,
        version=1,
        previous_version_id=None,
        metadata=None,
        created_at=_dt.datetime.now(_dt.UTC),
        updated_at=_dt.datetime.now(_dt.UTC),
        expires_at=None,
        has_children=branch_count > 0,
        has_rationale=False,
        branch_count=branch_count,
    )


@pytest.mark.asyncio
async def test_read_memory_emits_branch_count():
    """Regression for #50: response includes branch_count, not branches."""
    fake_node = _fake_node(branch_count=3)
    mock_session = AsyncMock()
    mock_gen = AsyncMock()

    auth_mod._current_session = {
        "user_id": "wjackson",
        "scopes": ["user"],
        "identity_type": "user",
    }
    try:
        with (
            patch("src.tools.read_memory.get_db_session", return_value=(mock_session, mock_gen)),
            patch("src.tools.read_memory.release_db_session", new_callable=AsyncMock),
            patch(
                "src.tools.read_memory._read_memory",
                new_callable=AsyncMock,
                return_value=fake_node,
            ),
        ):
            result = await read_memory(memory_id=str(fake_node.id))
    finally:
        auth_mod._current_session = None

    assert result.get("error") is not True
    assert result["branch_count"] == 3
    assert "branches" not in result


@pytest.mark.asyncio
async def test_read_memory_include_versions_unconditional():
    """Regression for #52: include_versions must be honored unconditionally.

    The previous behavior gated version_history on depth == 0; now that depth
    is gone, version_history must always be returned when include_versions is
    true. The mock here mirrors the real get_memory_history return shape (a
    dict with "versions" list + pagination keys) so the tool's iteration is
    exercised against the real contract, not a misleading list-shaped mock.
    """
    fake_node = _fake_node(branch_count=2)
    mock_session = AsyncMock()
    mock_gen = AsyncMock()

    class _DumpableHistory:
        def model_dump(self, mode="json"):
            return {"id": "v1", "version": 1}

    auth_mod._current_session = {
        "user_id": "wjackson",
        "scopes": ["user"],
        "identity_type": "user",
    }
    try:
        with (
            patch("src.tools.read_memory.get_db_session", return_value=(mock_session, mock_gen)),
            patch("src.tools.read_memory.release_db_session", new_callable=AsyncMock),
            patch(
                "src.tools.read_memory._read_memory",
                new_callable=AsyncMock,
                return_value=fake_node,
            ),
            patch(
                "src.tools.read_memory.get_memory_history",
                new_callable=AsyncMock,
                return_value={
                    "versions": [_DumpableHistory()],
                    "total_versions": 1,
                    "has_more": False,
                    "offset": 0,
                },
            ),
        ):
            result = await read_memory(
                memory_id=str(fake_node.id), include_versions=True
            )
    finally:
        auth_mod._current_session = None

    assert "version_history" in result
    assert result["version_history"]["total_versions"] == 1
    assert result["version_history"]["has_more"] is False
    assert len(result["version_history"]["versions"]) == 1
    assert result["version_history"]["versions"][0] == {"id": "v1", "version": 1}


@pytest.mark.asyncio
async def test_read_memory_unauthorized_for_other_owner():
    """Caller-vs-source authorization still rejects user-scope reads of other owners."""
    other_owner_node = _fake_node(scope="user", owner_id="someone-else")
    mock_session = AsyncMock()
    mock_gen = AsyncMock()

    auth_mod._current_session = {
        "user_id": "wjackson",
        "scopes": ["user"],
        "identity_type": "user",
    }
    try:
        with (
            patch("src.tools.read_memory.get_db_session", return_value=(mock_session, mock_gen)),
            patch("src.tools.read_memory.release_db_session", new_callable=AsyncMock),
            patch(
                "src.tools.read_memory._read_memory",
                new_callable=AsyncMock,
                return_value=other_owner_node,
            ),
            pytest.raises(ToolError, match="Not authorized"),
        ):
            await read_memory(memory_id=str(other_owner_node.id))
    finally:
        auth_mod._current_session = None


@pytest.mark.asyncio
async def test_read_memory_forwards_tenant_id_to_service():
    """Phase 4 (#46): the tool must forward the caller's tenant_id from
    claims into the read_memory service call so the SQL-level filter
    matches the caller's tenant."""
    from unittest.mock import MagicMock

    fake_node = _fake_node(tenant_id="tenant_a")
    mock_session = MagicMock()
    mock_gen = AsyncMock()
    fake_claims = {
        "sub": "wjackson",
        "identity_type": "user",
        "tenant_id": "tenant_a",
        "scopes": ["memory:read:user", "memory:write:user"],
    }

    with (
        patch(
            "src.tools.read_memory.get_claims_from_context",
            return_value=fake_claims,
        ),
        patch("src.tools.read_memory.get_db_session", return_value=(mock_session, mock_gen)),
        patch("src.tools.read_memory.release_db_session", new_callable=AsyncMock),
        patch(
            "src.tools.read_memory._read_memory",
            new_callable=AsyncMock,
            return_value=fake_node,
        ) as mock_read,
    ):
        result = await read_memory(memory_id=str(fake_node.id))

    assert result.get("error") is not True
    _, kwargs = mock_read.call_args
    assert kwargs.get("tenant_id") == "tenant_a", (
        f"Expected tenant_id='tenant_a' forwarded from claims into the read_memory "
        f"service call, got kwargs={kwargs}"
    )


@pytest.mark.asyncio
async def test_read_memory_include_versions_forwards_tenant_id():
    """include_versions=True also routes through get_memory_history; the
    tenant_id kwarg must be forwarded there too."""
    from unittest.mock import MagicMock

    fake_node = _fake_node(tenant_id="tenant_a")
    mock_session = MagicMock()
    mock_gen = AsyncMock()
    fake_claims = {
        "sub": "wjackson",
        "identity_type": "user",
        "tenant_id": "tenant_a",
        "scopes": ["memory:read:user", "memory:write:user"],
    }

    class _DumpableHistory:
        def model_dump(self, mode="json"):
            return {"id": "v1", "version": 1}

    with (
        patch(
            "src.tools.read_memory.get_claims_from_context",
            return_value=fake_claims,
        ),
        patch("src.tools.read_memory.get_db_session", return_value=(mock_session, mock_gen)),
        patch("src.tools.read_memory.release_db_session", new_callable=AsyncMock),
        patch(
            "src.tools.read_memory._read_memory",
            new_callable=AsyncMock,
            return_value=fake_node,
        ),
        patch(
            "src.tools.read_memory.get_memory_history",
            new_callable=AsyncMock,
            return_value={
                "versions": [_DumpableHistory()],
                "total_versions": 1,
                "has_more": False,
                "offset": 0,
            },
        ) as mock_history,
    ):
        await read_memory(
            memory_id=str(fake_node.id), include_versions=True
        )

    _, kwargs = mock_history.call_args
    assert kwargs.get("tenant_id") == "tenant_a", (
        f"Expected include_versions=True to forward tenant_id to get_memory_history, "
        f"got kwargs={kwargs}"
    )
