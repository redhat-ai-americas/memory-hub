"""Tests for memoryhub.client.MemoryHubClient."""

from __future__ import annotations

from dataclasses import dataclass, field
from unittest.mock import AsyncMock, patch

import pytest

from memoryhub.client import MemoryHubClient
from memoryhub.config import ProjectConfig, RetrievalDefaults
from memoryhub.exceptions import ConnectionFailedError, MemoryHubError, NotFoundError, ToolError
from memoryhub.models import ContradictionResult, HistoryResult, Memory, SearchResult, WriteResult

# ── Fake MCP response types ──────────────────────────────────────────────────


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

MINIMAL_MEMORY = {
    "id": "mem-001",
    "content": "Use Podman, not Docker.",
    "scope": "user",
    "owner_id": "wjackson",
    "weight": 0.9,
    "is_current": True,
    "version": 1,
    "storage_type": "inline",
}

MINIMAL_CURATION = {
    "blocked": False,
    "similar_count": 0,
    "flags": [],
}


def _make_client() -> MemoryHubClient:
    return MemoryHubClient(
        url="https://fake.example.com/mcp/",
        auth_url="https://fake.example.com",
        client_id="test",
        client_secret="test-secret",
    )


@pytest.fixture
async def client():
    """Return a (MemoryHubClient, mock_mcp) pair with _mcp pre-injected."""
    c = _make_client()
    mock_mcp = AsyncMock()
    c._mcp = mock_mcp
    return c, mock_mcp


# ── from_env ─────────────────────────────────────────────────────────────────


def test_from_env(monkeypatch):
    monkeypatch.setenv("MEMORYHUB_URL", "https://mcp.example.com/mcp/")
    monkeypatch.setenv("MEMORYHUB_AUTH_URL", "https://auth.example.com")
    monkeypatch.setenv("MEMORYHUB_CLIENT_ID", "my-client")
    monkeypatch.setenv("MEMORYHUB_CLIENT_SECRET", "s3cr3t")

    c = MemoryHubClient.from_env()
    assert c._url == "https://mcp.example.com/mcp/"
    assert c._auth._auth_url == "https://auth.example.com"
    assert c._auth._client_id == "my-client"


def test_from_env_missing_vars(monkeypatch):
    env_vars = (
        "MEMORYHUB_URL", "MEMORYHUB_AUTH_URL",
        "MEMORYHUB_CLIENT_ID", "MEMORYHUB_CLIENT_SECRET",
    )
    for var in env_vars:
        monkeypatch.delenv(var, raising=False)

    with pytest.raises(MemoryHubError) as exc_info:
        MemoryHubClient.from_env()

    msg = str(exc_info.value)
    assert "MEMORYHUB_URL" in msg
    assert "MEMORYHUB_AUTH_URL" in msg
    assert "MEMORYHUB_CLIENT_ID" in msg
    assert "MEMORYHUB_CLIENT_SECRET" in msg


# ── search ───────────────────────────────────────────────────────────────────


async def test_search(client):
    c, mock_mcp = client
    mock_mcp.call_tool.return_value = FakeCallToolResult(
        structured_content={
            "results": [MINIMAL_MEMORY],
            "total_matching": 1,
            "has_more": False,
        }
    )

    result = await c.search("Podman vs Docker")

    assert isinstance(result, SearchResult)
    assert len(result.results) == 1
    assert result.results[0].id == "mem-001"
    assert result.total_matching == 1
    assert result.has_more is False

    mock_mcp.call_tool.assert_awaited_once()
    call_args = mock_mcp.call_tool.call_args
    assert call_args[0][0] == "search_memory"
    assert call_args[0][1]["query"] == "Podman vs Docker"


async def test_search_defaults_pass_through_new_params(client):
    """Default call must forward mode/max_response_tokens/include_branches."""
    c, mock_mcp = client
    mock_mcp.call_tool.return_value = FakeCallToolResult(
        structured_content={"results": [], "total_matching": 0, "has_more": False}
    )

    await c.search("any")

    forwarded = mock_mcp.call_tool.call_args[0][1]
    assert forwarded["mode"] == "full"
    assert forwarded["max_response_tokens"] == 4000
    assert forwarded["include_branches"] is False


async def test_search_explicit_new_params(client):
    """Caller-supplied mode/budget/include_branches propagate."""
    c, mock_mcp = client
    mock_mcp.call_tool.return_value = FakeCallToolResult(
        structured_content={"results": [], "total_matching": 0, "has_more": False}
    )

    await c.search(
        "any",
        mode="index",
        max_response_tokens=1500,
        include_branches=True,
    )

    forwarded = mock_mcp.call_tool.call_args[0][1]
    assert forwarded["mode"] == "index"
    assert forwarded["max_response_tokens"] == 1500
    assert forwarded["include_branches"] is True


async def test_search_applies_project_config_retrieval_defaults():
    """Loaded project config fills in unset search() args."""
    pc = ProjectConfig(
        retrieval_defaults=RetrievalDefaults(
            max_results=25, max_response_tokens=8000, default_mode="index"
        )
    )
    c = MemoryHubClient(
        url="https://fake.example.com/mcp/",
        auth_url="https://fake.example.com",
        client_id="test",
        client_secret="test-secret",
        project_config=pc,
    )
    mock_mcp = AsyncMock()
    mock_mcp.call_tool.return_value = FakeCallToolResult(
        structured_content={"results": [], "total_matching": 0, "has_more": False}
    )
    c._mcp = mock_mcp

    await c.search("anything")

    forwarded = mock_mcp.call_tool.call_args[0][1]
    assert forwarded["max_results"] == 25
    assert forwarded["max_response_tokens"] == 8000
    assert forwarded["mode"] == "index"


async def test_search_explicit_args_override_project_config():
    """Caller-supplied args win over project config defaults."""
    pc = ProjectConfig(
        retrieval_defaults=RetrievalDefaults(
            max_results=25, max_response_tokens=8000, default_mode="index"
        )
    )
    c = MemoryHubClient(
        url="https://fake.example.com/mcp/",
        auth_url="https://fake.example.com",
        client_id="test",
        client_secret="test-secret",
        project_config=pc,
    )
    mock_mcp = AsyncMock()
    mock_mcp.call_tool.return_value = FakeCallToolResult(
        structured_content={"results": [], "total_matching": 0, "has_more": False}
    )
    c._mcp = mock_mcp

    await c.search("anything", max_results=5, max_response_tokens=500, mode="full_only")

    forwarded = mock_mcp.call_tool.call_args[0][1]
    assert forwarded["max_results"] == 5
    assert forwarded["max_response_tokens"] == 500
    assert forwarded["mode"] == "full_only"


def test_from_env_auto_discovers_config(monkeypatch, tmp_path):
    """from_env() with auto-discovery picks up a .memoryhub.yaml from cwd."""
    monkeypatch.setenv("MEMORYHUB_URL", "https://mcp.example.com/mcp/")
    monkeypatch.setenv("MEMORYHUB_AUTH_URL", "https://auth.example.com")
    monkeypatch.setenv("MEMORYHUB_CLIENT_ID", "my-client")
    monkeypatch.setenv("MEMORYHUB_CLIENT_SECRET", "s3cr3t")
    (tmp_path / ".memoryhub.yaml").write_text(
        "retrieval_defaults:\n  max_results: 42\n"
    )
    monkeypatch.chdir(tmp_path)

    c = MemoryHubClient.from_env()

    assert c._project_config.retrieval_defaults.max_results == 42


def test_from_env_can_opt_out_of_auto_discover(monkeypatch, tmp_path):
    """auto_discover_config=False uses all-default config even if a file exists."""
    monkeypatch.setenv("MEMORYHUB_URL", "https://mcp.example.com/mcp/")
    monkeypatch.setenv("MEMORYHUB_AUTH_URL", "https://auth.example.com")
    monkeypatch.setenv("MEMORYHUB_CLIENT_ID", "my-client")
    monkeypatch.setenv("MEMORYHUB_CLIENT_SECRET", "s3cr3t")
    (tmp_path / ".memoryhub.yaml").write_text(
        "retrieval_defaults:\n  max_results: 42\n"
    )
    monkeypatch.chdir(tmp_path)

    c = MemoryHubClient.from_env(auto_discover_config=False)

    assert c._project_config.retrieval_defaults.max_results == 10


async def test_search_nested_branches_round_trip(client):
    """Nested branches in the response land on the Memory via extra='allow'."""
    c, mock_mcp = client
    parent_with_branches = {
        **MINIMAL_MEMORY,
        "id": "mem-parent",
        "has_rationale": True,
        "branches": [
            {
                **MINIMAL_MEMORY,
                "id": "mem-branch",
                "parent_id": "mem-parent",
                "branch_type": "rationale",
                "content": "Podman is rootless by default.",
            }
        ],
    }
    mock_mcp.call_tool.return_value = FakeCallToolResult(
        structured_content={
            "results": [parent_with_branches],
            "total_matching": 1,
            "has_more": False,
        }
    )

    result = await c.search("Podman rationale", include_branches=True)

    assert result.results[0].id == "mem-parent"
    # Pydantic extra='allow' exposes the nested branches as an attribute.
    branches = result.results[0].model_extra["branches"]
    assert len(branches) == 1
    assert branches[0]["id"] == "mem-branch"


# ── read ─────────────────────────────────────────────────────────────────────


async def test_read(client):
    c, mock_mcp = client
    mock_mcp.call_tool.return_value = FakeCallToolResult(
        structured_content=MINIMAL_MEMORY
    )

    result = await c.read("mem-001")

    assert isinstance(result, Memory)
    assert result.id == "mem-001"
    assert result.content == "Use Podman, not Docker."

    call_args = mock_mcp.call_tool.call_args
    assert call_args[0][0] == "read_memory"
    assert call_args[0][1]["memory_id"] == "mem-001"


# ── write ─────────────────────────────────────────────────────────────────────


async def test_write(client):
    c, mock_mcp = client
    mock_mcp.call_tool.return_value = FakeCallToolResult(
        structured_content={
            "memory": MINIMAL_MEMORY,
            "curation": MINIMAL_CURATION,
        }
    )

    result = await c.write("Use Podman, not Docker.", scope="user", weight=0.9)

    assert isinstance(result, WriteResult)
    assert result.memory.id == "mem-001"
    assert result.curation.blocked is False
    assert result.curation.similar_count == 0

    call_args = mock_mcp.call_tool.call_args
    assert call_args[0][0] == "write_memory"
    assert call_args[0][1]["content"] == "Use Podman, not Docker."
    assert call_args[0][1]["scope"] == "user"


# ── update ───────────────────────────────────────────────────────────────────


async def test_update(client):
    c, mock_mcp = client
    updated = {**MINIMAL_MEMORY, "content": "Always use Podman, never Docker.", "version": 2}
    mock_mcp.call_tool.return_value = FakeCallToolResult(structured_content=updated)

    result = await c.update("mem-001", content="Always use Podman, never Docker.")

    assert isinstance(result, Memory)
    assert result.version == 2
    assert "never Docker" in result.content

    call_args = mock_mcp.call_tool.call_args
    assert call_args[0][0] == "update_memory"
    assert call_args[0][1]["memory_id"] == "mem-001"


# ── get_history ───────────────────────────────────────────────────────────────


async def test_get_history(client):
    c, mock_mcp = client
    mock_mcp.call_tool.return_value = FakeCallToolResult(
        structured_content={
            "memory_id": "mem-001",
            "versions": [
                {"id": "mem-001", "version": 1, "content": "Use Podman.", "is_current": True},
            ],
            "total_versions": 1,
            "has_more": False,
            "offset": 0,
        }
    )

    result = await c.get_history("mem-001")

    assert isinstance(result, HistoryResult)
    assert result.memory_id == "mem-001"
    assert len(result.versions) == 1
    assert result.versions[0].version == 1

    call_args = mock_mcp.call_tool.call_args
    assert call_args[0][0] == "get_memory_history"
    assert call_args[0][1]["memory_id"] == "mem-001"


# ── report_contradiction ──────────────────────────────────────────────────────


async def test_report_contradiction(client):
    c, mock_mcp = client
    mock_mcp.call_tool.return_value = FakeCallToolResult(
        structured_content={
            "memory_id": "mem-001",
            "contradiction_count": 2,
            "threshold": 5,
            "revision_triggered": False,
            "message": "Contradiction logged.",
        }
    )

    result = await c.report_contradiction("mem-001", "Team is now using Docker on this project.")

    assert isinstance(result, ContradictionResult)
    assert result.memory_id == "mem-001"
    assert result.contradiction_count == 2
    assert result.revision_triggered is False

    call_args = mock_mcp.call_tool.call_args
    assert call_args[0][0] == "report_contradiction"
    assert call_args[0][1]["memory_id"] == "mem-001"


# ── error handling ────────────────────────────────────────────────────────────


async def test_tool_error_raised(client):
    c, mock_mcp = client
    mock_mcp.call_tool.return_value = FakeCallToolResult(
        is_error=True,
        content=[FakeContent("Internal server error: database unavailable")],
    )

    with pytest.raises(ToolError) as exc_info:
        await c.search("anything")

    assert exc_info.value.tool_name == "search_memory"
    assert "database unavailable" in exc_info.value.detail


async def test_not_found_error(client):
    c, mock_mcp = client
    mock_mcp.call_tool.return_value = FakeCallToolResult(
        is_error=True,
        content=[FakeContent("Memory not found: mem-999")],
    )

    with pytest.raises(NotFoundError) as exc_info:
        await c.read("mem-999")

    assert exc_info.value.memory_id == "mem-999"


async def test_connection_error_without_context_manager():
    c = _make_client()
    # _mcp is None — no context manager entered

    with pytest.raises(ConnectionFailedError, match="async with client"):
        await c.search("anything")


# ── None-arg stripping ────────────────────────────────────────────────────────


async def test_none_args_stripped(client):
    """None-valued arguments must not be forwarded to call_tool."""
    c, mock_mcp = client
    mock_mcp.call_tool.return_value = FakeCallToolResult(
        structured_content={
            "results": [],
            "total_matching": 0,
            "has_more": False,
        }
    )

    # scope and owner_id are None — they should be absent from the args dict
    await c.search("query", scope=None, owner_id=None)

    call_args = mock_mcp.call_tool.call_args
    forwarded = call_args[0][1]
    assert "scope" not in forwarded
    assert "owner_id" not in forwarded
    # Non-None values must still be present
    assert forwarded["query"] == "query"


# ── sync wrapper ──────────────────────────────────────────────────────────────


def test_search_sync():
    """search_sync must work end-to-end without an async context manager."""
    c = _make_client()

    # The client stores the Client(...) instance as self._mcp, so call_tool
    # must be configured on the object returned by the Client constructor
    # (not the value returned by __aenter__).
    mock_mcp = AsyncMock()
    mock_mcp.call_tool.return_value = FakeCallToolResult(
        structured_content={
            "results": [MINIMAL_MEMORY],
            "total_matching": 1,
            "has_more": False,
        }
    )
    mock_mcp.__aenter__.return_value = mock_mcp
    mock_mcp.__aexit__.return_value = None

    with patch("memoryhub.client.Client", return_value=mock_mcp):
        result = c.search_sync("Podman")

    assert isinstance(result, SearchResult)
    assert result.results[0].id == "mem-001"
