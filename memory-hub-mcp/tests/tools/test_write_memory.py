"""Tests for write_memory tool."""

import inspect

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
