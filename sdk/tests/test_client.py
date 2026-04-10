"""Tests for memoryhub.client.MemoryHubClient."""

from __future__ import annotations

from dataclasses import dataclass, field
from unittest.mock import AsyncMock, patch

import pytest

from memoryhub.client import MemoryHubClient
from memoryhub.config import ProjectConfig, RetrievalDefaults
from memoryhub.exceptions import (
    AuthenticationError,
    ConflictError,
    ConnectionFailedError,
    CurationVetoError,
    MemoryHubError,
    NotFoundError,
    PermissionDeniedError,
    ToolError,
    ValidationError,
)
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


async def test_search_no_focus_omits_focus_params_from_payload(client):
    """When focus is not passed, the SDK does NOT forward focus params.

    Keeping the wire format minimal helps the server distinguish "no
    focus declared" from "focus declared with default weight."
    """
    c, mock_mcp = client
    mock_mcp.call_tool.return_value = FakeCallToolResult(
        structured_content={"results": [], "total_matching": 0, "has_more": False}
    )

    await c.search("any query")

    forwarded = mock_mcp.call_tool.call_args[0][1]
    assert "focus" not in forwarded
    assert "session_focus_weight" not in forwarded


async def test_search_focus_string_forwards_with_default_weight(client):
    """Passing focus forwards both focus and session_focus_weight.

    The default weight comes from the project config's
    memory_loading.session_focus_weight (schema default 0.4).
    """
    c, mock_mcp = client
    mock_mcp.call_tool.return_value = FakeCallToolResult(
        structured_content={"results": [], "total_matching": 0, "has_more": False}
    )

    await c.search("any query", focus="OpenShift deployment")

    forwarded = mock_mcp.call_tool.call_args[0][1]
    assert forwarded["focus"] == "OpenShift deployment"
    assert forwarded["session_focus_weight"] == 0.4


async def test_search_explicit_session_focus_weight_overrides_default(client):
    c, mock_mcp = client
    mock_mcp.call_tool.return_value = FakeCallToolResult(
        structured_content={"results": [], "total_matching": 0, "has_more": False}
    )

    await c.search("query", focus="auth", session_focus_weight=0.2)

    forwarded = mock_mcp.call_tool.call_args[0][1]
    assert forwarded["focus"] == "auth"
    assert forwarded["session_focus_weight"] == 0.2


async def test_search_session_focus_weight_from_project_config():
    """Project config session_focus_weight is the default when caller omits."""
    from memoryhub.config import MemoryLoadingConfig

    pc = ProjectConfig(
        memory_loading=MemoryLoadingConfig(session_focus_weight=0.6),
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

    await c.search("query", focus="auth")

    forwarded = mock_mcp.call_tool.call_args[0][1]
    assert forwarded["session_focus_weight"] == 0.6


async def test_search_pivot_fields_round_trip_when_present(client):
    """Server-side pivot signal parses into the SearchResult fields."""
    c, mock_mcp = client
    mock_mcp.call_tool.return_value = FakeCallToolResult(
        structured_content={
            "results": [MINIMAL_MEMORY],
            "total_matching": 1,
            "has_more": False,
            "pivot_suggested": True,
            "pivot_reason": "query vector distance from session focus is 0.700 (threshold 0.55)",
        }
    )

    result = await c.search("question", focus="OpenShift deployment")

    assert result.pivot_suggested is True
    assert result.pivot_reason is not None
    assert "threshold" in result.pivot_reason
    assert result.focus_fallback_reason is None


async def test_search_pivot_fields_default_to_none_without_focus(client):
    """When the server omits pivot fields (no focus path), they parse as None."""
    c, mock_mcp = client
    mock_mcp.call_tool.return_value = FakeCallToolResult(
        structured_content={
            "results": [MINIMAL_MEMORY],
            "total_matching": 1,
            "has_more": False,
        }
    )

    result = await c.search("question")

    assert result.pivot_suggested is None
    assert result.pivot_reason is None
    assert result.focus_fallback_reason is None


async def test_search_focus_fallback_reason_round_trips(client):
    """When the server reports a reranker fallback, the SDK surfaces it."""
    c, mock_mcp = client
    mock_mcp.call_tool.return_value = FakeCallToolResult(
        structured_content={
            "results": [MINIMAL_MEMORY],
            "total_matching": 1,
            "has_more": False,
            "pivot_suggested": False,
            "pivot_reason": None,
            "focus_fallback_reason": (
                "reranker call failed (TimeoutError); falling back to cosine rank"
            ),
        }
    )

    result = await c.search("question", focus="something")

    assert result.focus_fallback_reason is not None
    assert "TimeoutError" in result.focus_fallback_reason


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


async def test_authentication_error_from_invalid_api_key(client):
    """_call() classifies 'Invalid API key' messages as AuthenticationError."""
    c, mock_mcp = client
    mock_mcp.call_tool.return_value = FakeCallToolResult(
        is_error=True,
        content=[FakeContent("Invalid API key. Contact your system administrator.")],
    )
    with pytest.raises(AuthenticationError, match="Invalid API key"):
        await c.search("anything")


async def test_authentication_error_from_no_session(client):
    """_call() classifies 'No authenticated session' messages as AuthenticationError."""
    c, mock_mcp = client
    mock_mcp.call_tool.return_value = FakeCallToolResult(
        is_error=True,
        content=[FakeContent("No authenticated session. Call register_session first.")],
    )
    with pytest.raises(AuthenticationError, match="No authenticated session"):
        await c.search("anything")


async def test_permission_denied_error(client):
    c, mock_mcp = client
    mock_mcp.call_tool.return_value = FakeCallToolResult(
        is_error=True,
        content=[FakeContent("Not authorized to read memory in scope 'enterprise'")],
    )
    with pytest.raises(PermissionDeniedError) as exc_info:
        await c.read("mem-001")
    assert exc_info.value.tool_name == "read_memory"
    assert "Not authorized" in exc_info.value.detail


async def test_permission_denied_access_denied_prefix(client):
    c, mock_mcp = client
    mock_mcp.call_tool.return_value = FakeCallToolResult(
        is_error=True,
        content=[FakeContent("Access denied: insufficient scope for this operation")],
    )
    with pytest.raises(PermissionDeniedError):
        await c.read("mem-001")


async def test_validation_error(client):
    c, mock_mcp = client
    mock_mcp.call_tool.return_value = FakeCallToolResult(
        is_error=True,
        content=[FakeContent("Invalid memory_id: not a valid UUID")],
    )
    with pytest.raises(ValidationError) as exc_info:
        await c.read("bad-id")
    assert exc_info.value.tool_name == "read_memory"


async def test_validation_error_must_be(client):
    c, mock_mcp = client
    mock_mcp.call_tool.return_value = FakeCallToolResult(
        is_error=True,
        content=[FakeContent("weight must be between 0 and 1")],
    )
    with pytest.raises(ValidationError):
        await c.write("test", scope="user", weight=5.0)


async def test_validation_error_cannot_be_empty(client):
    c, mock_mcp = client
    mock_mcp.call_tool.return_value = FakeCallToolResult(
        is_error=True,
        content=[FakeContent("content cannot be empty")],
    )
    with pytest.raises(ValidationError):
        await c.write("", scope="user")


async def test_conflict_error_already_exists(client):
    c, mock_mcp = client
    mock_mcp.call_tool.return_value = FakeCallToolResult(
        is_error=True,
        content=[FakeContent("Relationship already exists between these memories")],
    )
    with pytest.raises(ConflictError) as exc_info:
        await c._call("create_relationship", {"source_id": "a", "target_id": "b"})
    assert exc_info.value.tool_name == "create_relationship"


async def test_conflict_error_already_deleted(client):
    c, mock_mcp = client
    mock_mcp.call_tool.return_value = FakeCallToolResult(
        is_error=True,
        content=[FakeContent("Memory mem-001 already deleted")],
    )
    with pytest.raises(ConflictError):
        await c._call("delete_memory", {"memory_id": "mem-001"})


async def test_curation_veto_error(client):
    c, mock_mcp = client
    mock_mcp.call_tool.return_value = FakeCallToolResult(
        is_error=True,
        content=[FakeContent("Curation rule blocked: duplicate content detected")],
    )
    with pytest.raises(CurationVetoError) as exc_info:
        await c.write("duplicate stuff", scope="user")
    assert exc_info.value.tool_name == "write_memory"
    assert "Curation rule blocked" in exc_info.value.detail


async def test_generic_tool_error_fallback(client):
    """Messages that don't match any prefix fall through to generic ToolError."""
    c, mock_mcp = client
    mock_mcp.call_tool.return_value = FakeCallToolResult(
        is_error=True,
        content=[FakeContent("Something completely unexpected happened")],
    )
    with pytest.raises(ToolError) as exc_info:
        await c.search("anything")
    # Should NOT be a subclass — exactly ToolError
    assert type(exc_info.value) is ToolError


async def test_exception_hierarchy():
    """New exceptions are subclasses of ToolError and MemoryHubError."""
    assert issubclass(PermissionDeniedError, ToolError)
    assert issubclass(ValidationError, ToolError)
    assert issubclass(ConflictError, ToolError)
    assert issubclass(CurationVetoError, ToolError)
    assert issubclass(PermissionDeniedError, MemoryHubError)
    # AuthenticationError is NOT a subclass of ToolError (it's a sibling)
    assert not issubclass(AuthenticationError, ToolError)
    assert issubclass(AuthenticationError, MemoryHubError)


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


# ── session focus (#61) ──────────────────────────────────────────────────────


async def test_set_session_focus_forwards_arguments(client):
    """set_session_focus should forward focus + project to the MCP tool."""
    c, mock_mcp = client
    mock_mcp.call_tool.return_value = FakeCallToolResult(
        structured_content={
            "session_id": "wjackson",
            "user_id": "wjackson",
            "project": "memory-hub",
            "focus": "deployment",
            "expires_at": "2026-04-07T12:45:00+00:00",
            "message": "ok",
        }
    )

    result = await c.set_session_focus("deployment", "memory-hub")

    assert result["session_id"] == "wjackson"
    assert result["project"] == "memory-hub"
    assert result["focus"] == "deployment"

    mock_mcp.call_tool.assert_awaited_once()
    call_args = mock_mcp.call_tool.call_args
    assert call_args[0][0] == "set_session_focus"
    assert call_args[0][1] == {"focus": "deployment", "project": "memory-hub"}


async def test_get_focus_history_forwards_date_range(client):
    """get_focus_history should forward project/start_date/end_date."""
    c, mock_mcp = client
    mock_mcp.call_tool.return_value = FakeCallToolResult(
        structured_content={
            "project": "memory-hub",
            "start_date": "2026-04-01",
            "end_date": "2026-04-07",
            "total_sessions": 3,
            "histogram": [
                {"focus": "deployment", "count": 2},
                {"focus": "auth", "count": 1},
            ],
        }
    )

    result = await c.get_focus_history(
        "memory-hub",
        start_date="2026-04-01",
        end_date="2026-04-07",
    )

    assert result["total_sessions"] == 3
    assert result["histogram"][0] == {"focus": "deployment", "count": 2}

    forwarded = mock_mcp.call_tool.call_args[0][1]
    assert forwarded["project"] == "memory-hub"
    assert forwarded["start_date"] == "2026-04-01"
    assert forwarded["end_date"] == "2026-04-07"


async def test_get_focus_history_strips_none_dates(client):
    """When start_date/end_date are omitted they must be dropped from the
    outbound payload, not sent as explicit None (the tool expects absent =
    defaults applied server-side)."""
    c, mock_mcp = client
    mock_mcp.call_tool.return_value = FakeCallToolResult(
        structured_content={
            "project": "memory-hub",
            "start_date": "2026-03-08",
            "end_date": "2026-04-07",
            "total_sessions": 0,
            "histogram": [],
        }
    )

    await c.get_focus_history("memory-hub")

    forwarded = mock_mcp.call_tool.call_args[0][1]
    assert forwarded["project"] == "memory-hub"
    # None values are stripped by _call before sending
    assert "start_date" not in forwarded
    assert "end_date" not in forwarded


# ── project_id / domains forwarding (#164) ───────────────────────────────────


async def test_search_forwards_project_id_and_domains(client):
    """search() forwards project_id, domains, and domain_boost_weight."""
    c, mock_mcp = client
    mock_mcp.call_tool.return_value = FakeCallToolResult(
        structured_content={"results": [], "total_matching": 0, "has_more": False}
    )

    await c.search(
        "query",
        project_id="proj-123",
        domains=["React", "Spring Boot"],
        domain_boost_weight=0.5,
    )

    forwarded = mock_mcp.call_tool.call_args[0][1]
    assert forwarded["project_id"] == "proj-123"
    assert forwarded["domains"] == ["React", "Spring Boot"]
    assert forwarded["domain_boost_weight"] == 0.5


async def test_search_omits_campaign_params_when_none(client):
    """project_id, domains, domain_boost_weight are stripped when None."""
    c, mock_mcp = client
    mock_mcp.call_tool.return_value = FakeCallToolResult(
        structured_content={"results": [], "total_matching": 0, "has_more": False}
    )

    await c.search("query")

    forwarded = mock_mcp.call_tool.call_args[0][1]
    assert "project_id" not in forwarded
    assert "domains" not in forwarded
    assert "domain_boost_weight" not in forwarded


async def test_write_forwards_project_id_and_domains(client):
    """write() forwards project_id and domains."""
    c, mock_mcp = client
    mock_mcp.call_tool.return_value = FakeCallToolResult(
        structured_content={"memory": MINIMAL_MEMORY, "curation": MINIMAL_CURATION}
    )

    await c.write("content", project_id="proj-123", domains=["React"])

    forwarded = mock_mcp.call_tool.call_args[0][1]
    assert forwarded["project_id"] == "proj-123"
    assert forwarded["domains"] == ["React"]


async def test_update_forwards_project_id_and_domains(client):
    """update() forwards project_id and domains."""
    c, mock_mcp = client
    updated = {**MINIMAL_MEMORY, "version": 2}
    mock_mcp.call_tool.return_value = FakeCallToolResult(structured_content=updated)

    await c.update("mem-001", content="updated", project_id="proj-123", domains=["React"])

    forwarded = mock_mcp.call_tool.call_args[0][1]
    assert forwarded["project_id"] == "proj-123"
    assert forwarded["domains"] == ["React"]


# Shared response fixtures for parametrized #164 tests
_WRITE_RESPONSE = {
    "memory": MINIMAL_MEMORY,
    "curation": MINIMAL_CURATION,
}
_DELETE_RESPONSE = {
    "deleted_id": "mem-001",
    "total_deleted": 1,
    "versions_deleted": 1,
    "branches_deleted": 0,
}
_HISTORY_RESPONSE = {
    "memory_id": "mem-001",
    "versions": [],
    "total_versions": 0,
    "has_more": False,
    "offset": 0,
}
_CONTRADICTION_RESPONSE = {
    "memory_id": "mem-001",
    "contradiction_count": 1,
    "threshold": 5,
    "revision_triggered": False,
    "message": "ok",
}
_RELATIONSHIPS_RESPONSE = {
    "node_id": "mem-001",
    "relationships": [],
    "total": 0,
}
_CREATE_REL_KWARGS = {
    "source_id": "a",
    "target_id": "b",
    "relationship_type": "related",
}
_CREATE_REL_RESPONSE = {
    "id": "rel-1",
    "source_id": "a",
    "target_id": "b",
    "relationship_type": "related",
}
_MERGE_KWARGS = {
    "memory_a_id": "a",
    "memory_b_id": "b",
    "reasoning": "similar",
}


@pytest.mark.parametrize(
    "method,tool_name,call_kwargs,response",
    [
        ("read", "read_memory",
         {"memory_id": "mem-001"}, MINIMAL_MEMORY),
        ("write", "write_memory",
         {"content": "test"}, _WRITE_RESPONSE),
        ("update", "update_memory",
         {"memory_id": "mem-001", "content": "updated"},
         {**MINIMAL_MEMORY, "version": 2}),
        ("delete", "delete_memory",
         {"memory_id": "mem-001"}, _DELETE_RESPONSE),
        ("get_history", "get_memory_history",
         {"memory_id": "mem-001"}, _HISTORY_RESPONSE),
        ("report_contradiction", "report_contradiction",
         {"memory_id": "mem-001", "observed_behavior": "changed"},
         _CONTRADICTION_RESPONSE),
        ("get_similar", "get_similar_memories",
         {"memory_id": "mem-001"}, {"results": []}),
        ("get_relationships", "get_relationships",
         {"node_id": "mem-001"}, _RELATIONSHIPS_RESPONSE),
        ("create_relationship", "create_relationship",
         _CREATE_REL_KWARGS, _CREATE_REL_RESPONSE),
        ("suggest_merge", "suggest_merge",
         _MERGE_KWARGS, {"status": "suggested"}),
    ],
)
async def test_project_id_forwarded_when_provided(
    client, method, tool_name, call_kwargs, response,
):
    """project_id is forwarded to the MCP tool when provided."""
    c, mock_mcp = client
    mock_mcp.call_tool.return_value = FakeCallToolResult(
        structured_content=response,
    )

    func = getattr(c, method)
    await func(**call_kwargs, project_id="proj-123")

    forwarded = mock_mcp.call_tool.call_args[0][1]
    assert forwarded["project_id"] == "proj-123"


@pytest.mark.parametrize(
    "method,call_kwargs,response",
    [
        ("read",
         {"memory_id": "mem-001"}, MINIMAL_MEMORY),
        ("delete",
         {"memory_id": "mem-001"}, _DELETE_RESPONSE),
        ("get_history",
         {"memory_id": "mem-001"}, _HISTORY_RESPONSE),
        ("report_contradiction",
         {"memory_id": "mem-001", "observed_behavior": "changed"},
         _CONTRADICTION_RESPONSE),
        ("get_similar",
         {"memory_id": "mem-001"}, {"results": []}),
        ("get_relationships",
         {"node_id": "mem-001"}, _RELATIONSHIPS_RESPONSE),
        ("create_relationship",
         _CREATE_REL_KWARGS, _CREATE_REL_RESPONSE),
        ("suggest_merge",
         _MERGE_KWARGS, {"status": "suggested"}),
    ],
)
async def test_project_id_omitted_when_none(
    client, method, call_kwargs, response,
):
    """project_id is stripped from payload when not provided."""
    c, mock_mcp = client
    mock_mcp.call_tool.return_value = FakeCallToolResult(
        structured_content=response,
    )

    await getattr(c, method)(**call_kwargs)

    forwarded = mock_mcp.call_tool.call_args[0][1]
    assert "project_id" not in forwarded


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


# ── Pattern E (#62) push notification SDK wiring ─────────────────────────────


def _make_push_enabled_config() -> ProjectConfig:
    """ProjectConfig with live_subscription enabled for #62 tests."""
    from memoryhub.config import MemoryLoadingConfig

    return ProjectConfig(
        memory_loading=MemoryLoadingConfig(live_subscription=True),
    )


def _make_push_client() -> MemoryHubClient:
    """Construct a client whose project config opts into Pattern E push."""
    return MemoryHubClient(
        url="https://fake.example.com/mcp/",
        auth_url="https://fake.example.com",
        client_id="test",
        client_secret="test-secret",
        project_config=_make_push_enabled_config(),
    )


@pytest.mark.asyncio
async def test_message_handler_constructed_when_live_subscription_enabled():
    """When the project config opts into Pattern E, __aenter__ should pass
    a memoryhub message handler to the underlying FastMCP Client so that
    incoming ResourceUpdatedNotification messages reach our callback path."""
    c = _make_push_client()

    mock_mcp = AsyncMock()
    mock_mcp.__aenter__.return_value = mock_mcp
    mock_mcp.__aexit__.return_value = None

    with patch("memoryhub.client.Client", return_value=mock_mcp) as client_ctor:
        async with c:
            pass

    # The Client constructor should have been called with a non-None
    # message_handler keyword argument.
    _, kwargs = client_ctor.call_args
    assert kwargs.get("message_handler") is not None


@pytest.mark.asyncio
async def test_message_handler_omitted_when_live_subscription_disabled():
    """Default project config has live_subscription=False; in that case the
    SDK must NOT install a notification handler so projects that haven't
    opted into Pattern E pay zero overhead."""
    c = _make_client()  # default config = live_subscription False

    mock_mcp = AsyncMock()
    mock_mcp.__aenter__.return_value = mock_mcp
    mock_mcp.__aexit__.return_value = None

    with patch("memoryhub.client.Client", return_value=mock_mcp) as client_ctor:
        async with c:
            pass

    _, kwargs = client_ctor.call_args
    assert kwargs.get("message_handler") is None


@pytest.mark.asyncio
async def test_on_memory_updated_callback_fires_for_memoryhub_uri():
    """The handler should route ResourceUpdatedNotification with a
    memoryhub:// URI to every registered callback. Verifies the URI is
    coerced to str (not Pydantic AnyUrl) before being passed."""
    import mcp.types as mt

    c = _make_push_client()
    received_uris: list[str] = []

    async def callback(uri: str) -> None:
        received_uris.append(uri)

    c.on_memory_updated(callback)

    mock_mcp = AsyncMock()
    mock_mcp.__aenter__.return_value = mock_mcp
    mock_mcp.__aexit__.return_value = None

    with patch("memoryhub.client.Client", return_value=mock_mcp):
        async with c:
            assert c._message_handler is not None
            await c._message_handler.on_resource_updated(
                mt.ResourceUpdatedNotification(
                    method="notifications/resources/updated",
                    params=mt.ResourceUpdatedNotificationParams(
                        uri="memoryhub://memory/abc-123"
                    ),
                )
            )

    assert received_uris == ["memoryhub://memory/abc-123"]


@pytest.mark.asyncio
async def test_callback_ignores_non_memoryhub_uris():
    """If another MCP source emits ResourceUpdatedNotification for a
    different URI scheme (e.g., file://), our handler should ignore it
    rather than calling the user's callback with foreign URIs."""
    import mcp.types as mt

    c = _make_push_client()
    received_uris: list[str] = []

    async def callback(uri: str) -> None:
        received_uris.append(uri)

    c.on_memory_updated(callback)

    mock_mcp = AsyncMock()
    mock_mcp.__aenter__.return_value = mock_mcp
    mock_mcp.__aexit__.return_value = None

    with patch("memoryhub.client.Client", return_value=mock_mcp):
        async with c:
            await c._message_handler.on_resource_updated(
                mt.ResourceUpdatedNotification(
                    method="notifications/resources/updated",
                    params=mt.ResourceUpdatedNotificationParams(
                        uri="file:///etc/passwd"
                    ),
                )
            )

    assert received_uris == []


@pytest.mark.asyncio
async def test_multiple_callbacks_all_fire_in_registration_order():
    import mcp.types as mt

    c = _make_push_client()
    order: list[str] = []

    async def cb1(uri: str) -> None:
        order.append(f"cb1:{uri}")

    async def cb2(uri: str) -> None:
        order.append(f"cb2:{uri}")

    c.on_memory_updated(cb1)
    c.on_memory_updated(cb2)

    mock_mcp = AsyncMock()
    mock_mcp.__aenter__.return_value = mock_mcp
    mock_mcp.__aexit__.return_value = None

    with patch("memoryhub.client.Client", return_value=mock_mcp):
        async with c:
            await c._message_handler.on_resource_updated(
                mt.ResourceUpdatedNotification(
                    method="notifications/resources/updated",
                    params=mt.ResourceUpdatedNotificationParams(
                        uri="memoryhub://memory/x"
                    ),
                )
            )

    assert order == ["cb1:memoryhub://memory/x", "cb2:memoryhub://memory/x"]


@pytest.mark.asyncio
async def test_callback_exception_does_not_block_others():
    """If one callback raises, the handler should log and continue dispatching
    to subsequent callbacks rather than aborting the chain."""
    import mcp.types as mt

    c = _make_push_client()
    received: list[str] = []

    async def bad(uri: str) -> None:
        raise RuntimeError("simulated callback failure")

    async def good(uri: str) -> None:
        received.append(uri)

    c.on_memory_updated(bad)
    c.on_memory_updated(good)

    mock_mcp = AsyncMock()
    mock_mcp.__aenter__.return_value = mock_mcp
    mock_mcp.__aexit__.return_value = None

    with patch("memoryhub.client.Client", return_value=mock_mcp):
        async with c:
            await c._message_handler.on_resource_updated(
                mt.ResourceUpdatedNotification(
                    method="notifications/resources/updated",
                    params=mt.ResourceUpdatedNotificationParams(
                        uri="memoryhub://memory/x"
                    ),
                )
            )

    assert received == ["memoryhub://memory/x"]


@pytest.mark.asyncio
async def test_pre_connect_callback_replays_into_handler():
    """Callbacks registered before __aenter__ should be replayed onto the
    handler when the connection opens. Otherwise users have to register
    callbacks after entering the context manager, which is awkward."""
    import mcp.types as mt

    c = _make_push_client()
    received: list[str] = []

    async def callback(uri: str) -> None:
        received.append(uri)

    # Register BEFORE __aenter__ — handler doesn't exist yet.
    c.on_memory_updated(callback)
    assert c._message_handler is None
    assert len(c._pending_callbacks) == 1

    mock_mcp = AsyncMock()
    mock_mcp.__aenter__.return_value = mock_mcp
    mock_mcp.__aexit__.return_value = None

    with patch("memoryhub.client.Client", return_value=mock_mcp):
        async with c:
            assert c._message_handler is not None
            await c._message_handler.on_resource_updated(
                mt.ResourceUpdatedNotification(
                    method="notifications/resources/updated",
                    params=mt.ResourceUpdatedNotificationParams(
                        uri="memoryhub://memory/x"
                    ),
                )
            )

    assert received == ["memoryhub://memory/x"]
