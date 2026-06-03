"""Tests for list_memory compact response mode (#255)."""

import inspect
import uuid as _uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

import src.tools.auth as auth_mod
from src.tools.list_memory import list_memory


def _fake_list_item(content: str, weight: float = 0.8, *, branch_type=None):
    """Build a MemoryNodeRead for list_memory test fixtures."""
    from memoryhub_core.models.schemas import MemoryNodeRead, MemoryScope, StorageType

    return MemoryNodeRead(
        id=_uuid.uuid4(),
        parent_id=None,
        content=content,
        stub=content[:80],
        storage_type=StorageType.INLINE,
        content_ref=None,
        weight=weight,
        scope=MemoryScope.USER,
        branch_type=branch_type,
        owner_id="wjackson",
        tenant_id="default",
        is_current=True,
        version=1,
        previous_version_id=None,
        metadata=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        expires_at=None,
        has_children=False,
        has_rationale=False,
        branch_count=0,
    )


async def _run_list(items, **kwargs):
    """Run list_memory with patched dependencies and canned results."""
    mock_session = AsyncMock()
    mock_gen = AsyncMock()

    auth_mod._current_session = {
        "user_id": "wjackson",
        "scopes": ["user"],
        "identity_type": "user",
    }
    try:
        with (
            patch(
                "src.tools.list_memory.get_db_session",
                return_value=(mock_session, mock_gen),
            ),
            patch(
                "src.tools.list_memory.release_db_session",
                new_callable=AsyncMock,
            ),
            patch(
                "src.tools.list_memory.list_memories",
                new_callable=AsyncMock,
                return_value=(items, None),
            ),
            patch(
                "src.tools.list_memory.ROLE_ISOLATION_ENABLED",
                False,
            ),
            patch(
                "src.tools.list_memory.PROJECT_ISOLATION_ENABLED",
                False,
            ),
        ):
            return await list_memory(**kwargs)
    finally:
        auth_mod._current_session = None


def test_list_memory_verbose_parameter_defaults_true():
    """Verify the verbose parameter exists and defaults to True.

    The tool function defaults to True for backward compatibility with
    direct callers. The unified memory() dispatcher overrides this to
    False so agents get compact output by default (#255).
    """
    sig = inspect.signature(list_memory)
    params = sig.parameters
    assert "verbose" in params
    assert params["verbose"].default is True


@pytest.mark.asyncio
async def test_list_compact_explicit_returns_id_and_content():
    """Explicit verbose=False returns compact {id, content} entries."""
    item = _fake_list_item("Use Podman for containers")
    result = await _run_list([item], verbose=False)

    assert len(result["results"]) == 1
    entry = result["results"][0]
    assert "id" in entry
    assert "content" in entry
    assert entry["content"] == "Use Podman for containers"
    # Compact mode omits metadata
    assert "weight" not in entry
    assert "scope" not in entry
    assert "owner_id" not in entry
    assert "result_type" not in entry
    assert "created_at" not in entry


@pytest.mark.asyncio
async def test_list_verbose_true_returns_full_metadata():
    """verbose=True returns the full model_dump with all metadata fields."""
    item = _fake_list_item("Use Podman for containers", weight=0.9)
    result = await _run_list([item], verbose=True)

    entry = result["results"][0]
    assert "id" in entry
    assert "content" in entry
    assert "weight" in entry
    assert "scope" in entry
    assert "owner_id" in entry
    assert "result_type" in entry
    assert entry["result_type"] == "full"


@pytest.mark.asyncio
async def test_list_compact_multiple_items():
    """Compact mode works correctly for multiple items."""
    items = [
        _fake_list_item("First memory"),
        _fake_list_item("Second memory"),
        _fake_list_item("Third memory"),
    ]
    result = await _run_list(items, verbose=False)

    assert len(result["results"]) == 3
    for entry in result["results"]:
        assert set(entry.keys()) == {"id", "content"}


@pytest.mark.asyncio
async def test_list_compact_excludes_branches_by_default():
    """Compact mode still respects include_branches=False filtering."""
    parent = _fake_list_item("Parent memory")
    branch = _fake_list_item("Branch memory", branch_type="rationale")
    result = await _run_list([parent, branch], verbose=False)

    assert len(result["results"]) == 1
    assert result["results"][0]["content"] == "Parent memory"


@pytest.mark.asyncio
async def test_list_response_envelope_unchanged():
    """The response envelope (count, has_more, next_cursor) is unaffected
    by compact mode."""
    items = [_fake_list_item("A memory")]
    result = await _run_list(items, verbose=False)

    assert result["count"] == 1
    assert result["has_more"] is False
    assert result["next_cursor"] is None
