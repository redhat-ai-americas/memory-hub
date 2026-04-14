"""RBAC enforcement integration tests against the live MemoryHub deployment.

These tests verify that authorization is correctly enforced end-to-end:
JWT authentication, scope-based filtering, and cross-user isolation.

Requires a running MemoryHub deployment. Skip if MEMORYHUB_URL is not set.

Run with:
    pytest tests/integration/test_rbac_live.py -v
"""

import os
import uuid

import httpx
import pytest

from memoryhub import MemoryHubClient
from memoryhub.exceptions import AuthenticationError, ToolError

MCP_URL = os.environ.get("MEMORYHUB_URL")
AUTH_URL = os.environ.get("MEMORYHUB_AUTH_URL")
WJACKSON_CLIENT_SECRET = os.environ.get("MEMORYHUB_TEST_WJACKSON_SECRET")
CURATOR_CLIENT_SECRET = os.environ.get("MEMORYHUB_TEST_CURATOR_SECRET")

_missing = [
    name
    for name, value in (
        ("MEMORYHUB_URL", MCP_URL),
        ("MEMORYHUB_AUTH_URL", AUTH_URL),
        ("MEMORYHUB_TEST_WJACKSON_SECRET", WJACKSON_CLIENT_SECRET),
        ("MEMORYHUB_TEST_CURATOR_SECRET", CURATOR_CLIENT_SECRET),
    )
    if not value
]

pytestmark = pytest.mark.integration

if _missing:
    pytestmark = [
        pytestmark,
        pytest.mark.skip(
            reason=("Live RBAC tests require env vars: " + ", ".join(_missing)),
        ),
    ]


def _check_deployment_reachable() -> bool:
    """Probe the auth server to see if the deployment is up."""
    if not AUTH_URL:
        return False
    try:
        resp = httpx.get(f"{AUTH_URL}/healthz", timeout=5)
        return resp.status_code == 200
    except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPError):
        return False


if not _missing and not _check_deployment_reachable():
    pytestmark = [
        pytestmark,
        pytest.mark.skip(reason="MemoryHub deployment unreachable"),
    ]


def _make_client(client_id: str, client_secret: str) -> MemoryHubClient:
    return MemoryHubClient(
        url=MCP_URL,
        auth_url=AUTH_URL,
        client_id=client_id,
        client_secret=client_secret,
    )


def _test_content(label: str) -> str:
    """Generate unique test content to avoid curation duplicate detection."""
    return f"[test] {label} {uuid.uuid4().hex[:12]}"


@pytest.fixture
async def wjackson_client():
    """SDK client authenticated as wjackson (user identity)."""
    client = _make_client("wjackson", WJACKSON_CLIENT_SECRET)
    async with client:
        yield client


@pytest.fixture
async def curator_client():
    """SDK client authenticated as curator-agent (service identity)."""
    client = _make_client("curator-agent", CURATOR_CLIENT_SECRET)
    async with client:
        yield client


# -- Tests ---------------------------------------------------------------


async def test_authenticated_search(wjackson_client: MemoryHubClient):
    """Authenticated search returns results; user-scope results belong to caller."""
    result = await wjackson_client.search("container runtime")
    # The deployment has pre-existing memories from real usage, so we
    # expect at least some results (the system has memories about Podman, etc.)
    assert result.results is not None

    for mem in result.results:
        if mem.scope == "user":
            assert mem.owner_id == "wjackson", (
                f"User-scope memory {mem.id} has owner_id={mem.owner_id!r}, expected 'wjackson'"
            )


async def test_write_and_read_user_scope(wjackson_client: MemoryHubClient):
    """Write a user-scope memory then read it back by ID."""
    content = _test_content("write-read-roundtrip")

    write_result = await wjackson_client.write(
        content=content,
        scope="user",
        owner_id="wjackson",
    )
    memory = write_result.memory
    assert memory.content == content
    assert memory.scope == "user"
    assert memory.owner_id == "wjackson"
    assert memory.version == 1

    # Read it back
    read_back = await wjackson_client.read(memory.id)
    assert read_back.id == memory.id
    assert read_back.content == content


async def test_update_own_memory(wjackson_client: MemoryHubClient):
    """Write a memory then update it; version should increment."""
    original = _test_content("update-original")
    write_result = await wjackson_client.write(
        content=original,
        scope="user",
        owner_id="wjackson",
    )
    memory_id = write_result.memory.id
    assert write_result.memory.version == 1

    updated_content = _test_content("update-revised")
    updated = await wjackson_client.update(memory_id, content=updated_content)
    assert updated.content == updated_content
    assert updated.version == 2


async def test_cross_user_read_denied(
    wjackson_client: MemoryHubClient,
    curator_client: MemoryHubClient,
):
    """A different identity cannot read another user's user-scope memory.

    wjackson writes a user-scope memory, then curator-agent (separate JWT
    identity) tries to read it. User-scope requires owner_id == caller,
    so the read is denied even though curator has blanket memory:read.
    """
    content = _test_content("cross-user-isolation")
    write_result = await wjackson_client.write(
        content=content,
        scope="user",
        owner_id="wjackson",
    )
    wjackson_memory_id = write_result.memory.id

    # curator-agent tries to read wjackson's user-scope memory — denied
    with pytest.raises(Exception) as exc_info:
        await curator_client.read(wjackson_memory_id)

    error_text = str(exc_info.value).lower()
    assert any(
        term in error_text
        for term in (
            "authorized",
            "denied",
            "not found",
            "error",
        )
    ), f"Expected authorization error, got: {exc_info.value}"


async def test_search_scope_filtering(wjackson_client: MemoryHubClient):
    """Searching with scope=user returns only the caller's user-scope memories."""
    # Write a memory so there's at least one result
    content = _test_content("scope-filter-check")
    await wjackson_client.write(
        content=content,
        scope="user",
        owner_id="wjackson",
    )

    result = await wjackson_client.search("scope-filter-check", scope="user")
    for mem in result.results:
        assert mem.scope == "user", (
            f"Expected scope='user', got scope={mem.scope!r} for memory {mem.id}"
        )
        assert mem.owner_id == "wjackson", (
            f"Expected owner_id='wjackson', got owner_id={mem.owner_id!r} "
            f"for user-scope memory {mem.id}"
        )


async def test_write_organizational_denied_for_user(
    wjackson_client: MemoryHubClient,
):
    """User identity cannot write organizational-scope even with the OAuth scope.

    wjackson has memory:write:organizational in JWT scopes, but authorize_write
    requires identity_type=='service' for organizational scope. User identities
    are blocked.
    """
    content = _test_content("org-scope-denied")
    with pytest.raises(Exception) as exc_info:
        await wjackson_client.write(
            content=content,
            scope="organizational",
            owner_id="wjackson",
        )

    error_text = str(exc_info.value).lower()
    assert any(
        term in error_text
        for term in (
            "authorized",
            "denied",
            "not authorized",
            "error",
        )
    ), f"Expected authorization error, got: {exc_info.value}"


async def test_history_own_memory(wjackson_client: MemoryHubClient):
    """Write and update a memory, then verify history shows both versions."""
    content_v1 = _test_content("history-v1")
    write_result = await wjackson_client.write(
        content=content_v1,
        scope="user",
        owner_id="wjackson",
    )
    memory_id = write_result.memory.id

    content_v2 = _test_content("history-v2")
    updated = await wjackson_client.update(memory_id, content=content_v2)

    # update creates a new version with a new ID; use it for history
    mem_with_history = await wjackson_client.read(
        updated.id,
        include_versions=True,
        history_max_versions=100,
    )
    vh = mem_with_history.version_history
    assert vh["total_versions"] >= 2, f"Expected at least 2 versions, got {vh['total_versions']}"
    assert len(vh["versions"]) >= 2

    # Versions should be ordered; verify both contents appear
    version_contents = {v["content"] for v in vh["versions"]}
    assert content_v1 in version_contents, "v1 content missing from history"
    assert content_v2 in version_contents, "v2 content missing from history"


async def test_invalid_credentials_rejected():
    """A client with wrong credentials cannot authenticate."""
    client = _make_client("wjackson", "wrong-secret-value")

    with pytest.raises((AuthenticationError, ToolError, Exception)) as exc_info:
        async with client:
            # If auth is lazy, force a call to trigger it
            await client.search("anything")

    # Verify the error is auth-related, not a random failure
    error_text = str(exc_info.value).lower()
    assert any(
        term in error_text
        for term in (
            "authentication",
            "unauthorized",
            "invalid",
            "denied",
            "401",
            "credentials",
        )
    ), f"Expected auth error, got: {exc_info.value}"
