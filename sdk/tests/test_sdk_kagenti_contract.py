"""SDK contract test guarding the kagenti-adk integration (#208).

This test pins the SDK surface that kagenti-adk's
``MemoryHubMemoryStoreInstance`` (kagenti/adk PR #231) depends on. A
breaking change here means kagenti-adk's CI breaks; that is the cue
to either revert, ship a compat shim, or coordinate a downstream
update before the SDK release.

The test uses the SDK's existing mocked transport — no live
MemoryHub required. See ``planning/sdk-kagenti-contract-test.md`` for
the rationale.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from unittest.mock import AsyncMock

import pytest

# These imports are part of the contract — kagenti-adk uses every one of them.
# Renaming or relocating any of these would break the downstream consumer.
from memoryhub.client import MemoryHubClient
from memoryhub.exceptions import NotFoundError
from memoryhub.models import DeleteResult, Memory, SearchResult, WriteResult


@dataclass
class _FakeContent:
    text: str
    type: str = "text"


@dataclass
class _FakeCallToolResult:
    content: list = field(default_factory=list)
    structured_content: dict | None = None
    data: object = None
    is_error: bool = False
    meta: dict | None = None


_MEMORY = {
    "id": "mem-001",
    "content": "Use Podman, not Docker.",
    "scope": "user",
    "owner_id": "kagenti-ci",
    "weight": 0.9,
    "is_current": True,
    "version": 1,
    "storage_type": "inline",
}

_WRITE_OK = {
    "memory": _MEMORY,
    "curation": {"blocked": False, "similar_count": 0, "flags": []},
}

_WRITE_GATED = {
    "memory": None,
    "curation": {
        "blocked": False,
        "gated": True,
        "similar_count": 1,
        "flags": ["near_duplicate"],
        "reason": "near_duplicate",
        "existing_memory_id": "mem-existing",
    },
}


def _client_with_mock() -> tuple[MemoryHubClient, AsyncMock]:
    c = MemoryHubClient(url="https://fake.example.com/mcp/", api_key="mh-dev-test")
    mock = AsyncMock()
    c._mcp = mock
    return c, mock


# ── Constructor contract ────────────────────────────────────────────────────


def test_constructor_api_key_mode_accepts_url_and_api_key() -> None:
    """kagenti-adk's MemoryHubExtensionServer instantiates this way when
    the A2A extension fulfillment carries an API key."""
    c = MemoryHubClient(url="https://example.com/mcp/", api_key="mh-dev-abc")
    assert c._url == "https://example.com/mcp/"
    assert c._api_key == "mh-dev-abc"


def test_constructor_oauth_mode_accepts_full_oauth_params() -> None:
    """kagenti-adk's MemoryHubExtensionServer instantiates this way when
    the A2A extension fulfillment carries OAuth credentials."""
    c = MemoryHubClient(
        url="https://example.com/mcp/",
        auth_url="https://auth.example.com",
        client_id="kagenti-client",
        client_secret="kagenti-secret",
    )
    assert c._url == "https://example.com/mcp/"
    assert c._auth is not None


# ── search contract ─────────────────────────────────────────────────────────


async def test_search_signature_and_result_fields() -> None:
    """kagenti-adk calls
    ``store.search(query, scope=..., project_id=..., max_results=...)``
    and projects ``id``, ``content``, ``scope``, ``weight`` from each
    result. All four fields are load-bearing."""
    c, mock = _client_with_mock()
    mock.call_tool.return_value = _FakeCallToolResult(
        structured_content={
            "results": [_MEMORY],
            "total_matching": 1,
            "has_more": False,
        }
    )

    result = await c.search(
        "podman",
        scope="user",
        project_id="kagenti-tests",
        max_results=5,
    )

    assert isinstance(result, SearchResult)
    assert len(result.results) == 1
    m = result.results[0]
    assert m.id == "mem-001"
    assert m.content == "Use Podman, not Docker."
    assert m.scope == "user"
    assert m.weight == 0.9


# ── write contract (happy path + curation veto) ────────────────────────────


async def test_write_signature_and_happy_path() -> None:
    """kagenti-adk calls
    ``store.create(content, scope=..., weight=..., tags=...,
    project_id=...)`` which becomes ``client.write(...)``. It reads
    ``result.memory.id`` on success."""
    c, mock = _client_with_mock()
    mock.call_tool.return_value = _FakeCallToolResult(structured_content=_WRITE_OK)

    result = await c.write(
        "Use Podman, not Docker.",
        scope="user",
        weight=0.9,
        domains=["devops"],
        project_id="kagenti-tests",
    )

    assert isinstance(result, WriteResult)
    assert result.memory is not None
    assert result.memory.id == "mem-001"


async def test_write_curation_gated_exposes_reason() -> None:
    """kagenti-adk's MemoryHubMemoryStoreInstance.create raises
    MemoryRejectionError(result.curation.reason) when the write is
    gated. This contract requires that ``result.memory is None`` and
    ``result.curation.reason`` is a non-empty string in the gated
    response — both are read directly by the wrapper."""
    c, mock = _client_with_mock()
    mock.call_tool.return_value = _FakeCallToolResult(structured_content=_WRITE_GATED)

    result = await c.write("duplicate stuff", scope="user")

    assert result.memory is None
    assert result.curation.reason == "near_duplicate"


# ── read contract (success + NotFoundError) ─────────────────────────────────


async def test_read_returns_memory_with_required_fields() -> None:
    c, mock = _client_with_mock()
    mock.call_tool.return_value = _FakeCallToolResult(structured_content=_MEMORY)

    m = await c.read("mem-001")

    assert isinstance(m, Memory)
    assert m.id == "mem-001"
    assert m.content == "Use Podman, not Docker."
    assert m.scope == "user"
    assert m.weight == 0.9


async def test_read_raises_not_found_on_missing_id() -> None:
    """kagenti-adk's read() catches NotFoundError explicitly and returns
    None to its caller. Renaming or relocating this exception breaks
    that catch."""
    c, mock = _client_with_mock()
    mock.call_tool.return_value = _FakeCallToolResult(
        is_error=True,
        content=[_FakeContent("Memory not found: mem-missing")],
    )

    with pytest.raises(NotFoundError):
        await c.read("mem-missing")


# ── update contract ────────────────────────────────────────────────────────


async def test_update_signature_and_returns_new_version() -> None:
    """kagenti-adk does not currently update memories itself, but the
    public update() signature is part of the SDK surface we promised
    not to break. ``client.update(memory_id, content=...)`` must return
    a Memory with the new version visible."""
    c, mock = _client_with_mock()
    mock.call_tool.return_value = _FakeCallToolResult(
        structured_content={**_MEMORY, "content": "Always Podman.", "version": 2}
    )

    m = await c.update("mem-001", content="Always Podman.")

    assert isinstance(m, Memory)
    assert m.version == 2
    assert m.content == "Always Podman."


# ── delete contract ────────────────────────────────────────────────────────


async def test_delete_returns_delete_result() -> None:
    c, mock = _client_with_mock()
    mock.call_tool.return_value = _FakeCallToolResult(
        structured_content={
            "deleted_id": "mem-001",
            "deleted": True,
            "versions_deleted": 1,
        }
    )

    result = await c.delete("mem-001")

    assert isinstance(result, DeleteResult)


async def test_delete_raises_not_found_on_missing_id() -> None:
    """``client.delete`` must raise NotFoundError on unknown id, same
    as ``read`` — kagenti-adk relies on a uniform contract for both."""
    c, mock = _client_with_mock()
    mock.call_tool.return_value = _FakeCallToolResult(
        is_error=True,
        content=[_FakeContent("Memory not found: mem-missing")],
    )

    with pytest.raises(NotFoundError):
        await c.delete("mem-missing")
