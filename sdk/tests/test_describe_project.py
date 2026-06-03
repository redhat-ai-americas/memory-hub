"""Tests for MemoryHubClient.describe_project."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from unittest.mock import AsyncMock

import pytest

from memoryhub.client import MemoryHubClient


# ── Fake MCP response types (mirrors test_client.py) ─────────────────────────


@dataclass
class FakeContent:
    text: str
    type: str = "text"


@dataclass
class FakeCallToolResult:
    content: list = field(default_factory=list)
    structured_content: dict | None = None
    data: object = None
    is_error: bool = False
    meta: dict | None = None


# ── Helpers ──────────────────────────────────────────────────────────────────


SAMPLE_PROJECT = {
    "name": "memory-hub",
    "description": "Kubernetes-native agent memory",
    "members": [
        {"user_id": "wjackson", "role": "admin"},
        {"user_id": "agent-01", "role": "member"},
    ],
}


def _make_client() -> MemoryHubClient:
    return MemoryHubClient(url="https://fake.example.com/mcp/", api_key="mh-dev-test")


def _payload(mock_mcp) -> dict:
    """Merge top-level args and options for easy assertions."""
    args = mock_mcp.call_tool.call_args[0][1]
    flat = {k: v for k, v in args.items() if k != "options"}
    flat.update(args.get("options") or {})
    return flat


# ── Tests ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_describe_project_dispatches_correct_action():
    """describe_project sends action='describe_project' with project_id."""
    c = _make_client()
    mock_mcp = AsyncMock()
    c._mcp = mock_mcp

    mock_mcp.call_tool.return_value = FakeCallToolResult(
        content=[FakeContent(text=json.dumps(SAMPLE_PROJECT))],
    )

    result = await c.describe_project("memory-hub")

    tool_name = mock_mcp.call_tool.call_args[0][0]
    assert tool_name == "memory"

    payload = mock_mcp.call_tool.call_args[0][1]
    assert payload["action"] == "describe_project"
    assert payload["project_id"] == "memory-hub"


@pytest.mark.asyncio
async def test_describe_project_returns_raw_dict():
    """Result is a raw dict, not a Pydantic model."""
    c = _make_client()
    mock_mcp = AsyncMock()
    c._mcp = mock_mcp

    mock_mcp.call_tool.return_value = FakeCallToolResult(
        content=[FakeContent(text=json.dumps(SAMPLE_PROJECT))],
    )

    result = await c.describe_project("memory-hub")

    assert isinstance(result, dict)
    assert result["name"] == "memory-hub"
    assert len(result["members"]) == 2
    assert result["members"][0]["user_id"] == "wjackson"
    assert result["members"][0]["role"] == "admin"


@pytest.mark.asyncio
async def test_describe_project_minimal_response():
    """Handles a project with no description or members."""
    c = _make_client()
    mock_mcp = AsyncMock()
    c._mcp = mock_mcp

    minimal = {"name": "empty-proj", "members": []}
    mock_mcp.call_tool.return_value = FakeCallToolResult(
        content=[FakeContent(text=json.dumps(minimal))],
    )

    result = await c.describe_project("empty-proj")

    assert result["name"] == "empty-proj"
    assert result["members"] == []
