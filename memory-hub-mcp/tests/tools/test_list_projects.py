"""Tests for list_projects tool."""

import inspect

import pytest
from fastmcp.exceptions import ToolError

from src.core.authz import AuthenticationError
from src.tools.list_projects import list_projects


def test_list_projects_is_decorated():
    """Verify list_projects is a decorated MCP tool."""
    assert hasattr(list_projects, "__fastmcp__"), (
        "list_projects should be decorated with @mcp.tool"
    )


def test_list_projects_is_async():
    """The tool function must be async."""
    assert inspect.iscoroutinefunction(list_projects)


def test_list_projects_has_parameters():
    """Verify the function signature includes expected parameters."""
    sig = inspect.signature(list_projects)
    param_names = set(sig.parameters.keys())
    assert "filter" in param_names


def test_list_projects_default_filter_value():
    """Verify filter defaults to 'mine'."""
    sig = inspect.signature(list_projects)
    assert sig.parameters["filter"].default == "mine"


def test_list_projects_read_only_annotation():
    """Verify tool annotations mark it as read-only."""
    meta = list_projects.__fastmcp__
    assert getattr(meta, "annotations", None) is not None
    assert meta.annotations.readOnlyHint is True


@pytest.mark.asyncio
async def test_list_projects_rejects_unauthenticated(monkeypatch):
    """Calling without a session raises ToolError."""

    def raise_auth():
        raise AuthenticationError("no session")

    monkeypatch.setattr(
        "src.tools.list_projects.get_claims_from_context", raise_auth,
    )

    with pytest.raises(ToolError, match="No authenticated session found"):
        await list_projects()


@pytest.mark.asyncio
async def test_list_projects_rejects_invalid_filter(monkeypatch):
    """Invalid filter value raises ToolError."""
    monkeypatch.setattr(
        "src.tools.list_projects.get_claims_from_context",
        lambda: {"sub": "test", "tenant_id": "default", "scopes": []},
    )

    with pytest.raises(ToolError, match="Invalid filter value"):
        await list_projects(filter="bogus")
