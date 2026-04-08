"""Tests for get_memory_history tool."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.tools.get_memory_history import get_memory_history


@pytest.mark.asyncio
async def test_get_memory_history_import():
    """Verify the tool imports and is callable."""
    assert get_memory_history is not None
    assert callable(get_memory_history)


@pytest.mark.asyncio
async def test_get_memory_history_invalid_uuid():
    """Test that an invalid UUID returns a clear error."""
    from fastmcp.exceptions import ToolError

    ctx = AsyncMock()
    with pytest.raises(ToolError, match="Invalid memory_id format"):
        await get_memory_history(memory_id="not-a-uuid", ctx=ctx)


def _fake_node(tenant_id: str = "default"):
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
        weight=0.9,
        scope=MemoryScope.USER,
        branch_type=None,
        owner_id="wjackson",
        tenant_id=tenant_id,
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


@pytest.mark.asyncio
async def test_get_memory_history_forwards_tenant_id_to_service():
    """Phase 4 (#46): the tool must forward claims.tenant_id into BOTH
    the read_memory (auth check) and the get_memory_history service
    calls so the SQL-level filter matches the caller's tenant."""
    fake_node = _fake_node(tenant_id="tenant_a")
    mock_session = MagicMock()
    mock_gen = AsyncMock()
    fake_claims = {
        "sub": "wjackson",
        "identity_type": "user",
        "tenant_id": "tenant_a",
        "scopes": ["memory:read:user", "memory:write:user"],
    }

    class _DumpableVersion:
        version = 1
        content = "v1"
        stub = "v1 stub"
        is_current = True
        id = uuid.uuid4()

        @property
        def created_at(self):
            import datetime as _dt
            return _dt.datetime.now(_dt.UTC)

    with (
        patch(
            "src.tools.get_memory_history.get_claims_from_context",
            return_value=fake_claims,
        ),
        patch(
            "src.tools.get_memory_history.get_db_session",
            return_value=(mock_session, mock_gen),
        ),
        patch(
            "src.tools.get_memory_history.release_db_session",
            new_callable=AsyncMock,
        ),
        patch(
            "src.tools.get_memory_history._read_memory",
            new_callable=AsyncMock,
            return_value=fake_node,
        ) as mock_read,
        patch(
            "src.tools.get_memory_history._get_memory_history",
            new_callable=AsyncMock,
            return_value={
                "versions": [_DumpableVersion()],
                "total_versions": 1,
                "has_more": False,
                "offset": 0,
            },
        ) as mock_history,
    ):
        await get_memory_history(memory_id=str(fake_node.id))

    _, read_kwargs = mock_read.call_args
    assert read_kwargs.get("tenant_id") == "tenant_a"
    _, history_kwargs = mock_history.call_args
    assert history_kwargs.get("tenant_id") == "tenant_a"
