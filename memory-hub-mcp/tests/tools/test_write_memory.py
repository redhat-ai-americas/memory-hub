"""Tests for write_memory tool."""

import inspect

import pytest

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
        result = await write_memory(
            content="orphan branch attempt",
            scope="user",
            branch_type="rationale",
        )
    finally:
        auth_mod._current_session = None

    assert result["error"] is True
    assert "parent_id is required" in result["message"]
    assert "branch_type" in result["message"]


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
        result = await write_memory(
            content="branch with no type",
            scope="user",
            parent_id=str(_uuid.uuid4()),
        )
    finally:
        auth_mod._current_session = None

    assert result["error"] is True
    assert "branch_type is required" in result["message"]
