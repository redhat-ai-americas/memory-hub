"""Tests for read_memory tool."""

import inspect

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

    optional = {"depth", "include_versions", "ctx"}
    assert optional.issubset(param_names), (
        f"Missing optional params: {optional - param_names}"
    )


def test_read_memory_default_values():
    """Verify default values for optional parameters."""
    sig = inspect.signature(read_memory)
    params = sig.parameters

    assert params["depth"].default == 0
    assert params["include_versions"].default is False
