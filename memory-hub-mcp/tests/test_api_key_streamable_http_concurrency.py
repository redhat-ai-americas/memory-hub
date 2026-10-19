"""Exercise API-key session isolation over real Streamable HTTP connections.

This uses two independent FastMCP clients against a local HTTP server. Only
project lookup and push setup are stubbed; registration, Context injection,
identity resolution, transport session IDs, and disconnect cleanup use the
production FastMCP request path.
"""

from __future__ import annotations

import asyncio
import importlib
import socket
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any, AsyncIterator

import pytest
import uvicorn
from fastmcp import Client, Context, FastMCP

from src.core.authz import get_claims_from_context
from src.tools import auth


@asynccontextmanager
async def _serve_streamable_http(server: FastMCP) -> AsyncIterator[str]:
    """Run a stateful Streamable HTTP app on an ephemeral loopback port."""
    app = server.http_app(
        path="/mcp/",
        transport="http",
        stateless_http=False,
    )
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    port = listener.getsockname()[1]

    http_server = uvicorn.Server(
        uvicorn.Config(app, log_level="critical", access_log=False)
    )
    serve_task = asyncio.create_task(http_server.serve(sockets=[listener]))
    try:
        for _ in range(500):
            if http_server.started:
                break
            if serve_task.done():
                await serve_task
                raise RuntimeError("Streamable HTTP test server stopped during startup")
            await asyncio.sleep(0.01)
        else:
            raise TimeoutError("Streamable HTTP test server did not start")

        yield f"http://127.0.0.1:{port}/mcp/"
    finally:
        http_server.should_exit = True
        try:
            await asyncio.wait_for(serve_task, timeout=5)
        finally:
            listener.close()


def _result_data(result: Any) -> dict[str, Any]:
    """Extract FastMCP's structured tool output, failing on unexpected shapes."""
    assert not result.is_error, result
    data = result.data if result.data is not None else result.structured_content
    assert isinstance(data, dict), f"Expected structured tool output, got {data!r}"
    return data


@pytest.mark.asyncio
async def test_two_streamable_http_clients_keep_api_key_sessions_isolated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    register_module = importlib.import_module("src.tools.register_session")
    auth.clear_session()

    users = {
        "api-key-alice": {
            "user_id": "alice",
            "name": "Alice",
            "tenant_id": "tenant-alice",
            "scopes": ["user", "project"],
            "project_memberships": ["project-alice"],
        },
        "api-key-bob": {
            "user_id": "bob",
            "name": "Bob",
            "tenant_id": "tenant-bob",
            "scopes": ["user"],
            "project_memberships": ["project-bob"],
        },
    }

    async def resolve_project_memberships(user: dict[str, Any]) -> list[str]:
        return list(user["project_memberships"])

    async def no_project_lookup(*_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
        return []

    async def no_push_setup(*_args: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(
        register_module,
        "authenticate",
        lambda api_key: users.get(api_key),
    )
    monkeypatch.setattr(
        register_module, "_resolve_project_memberships", resolve_project_memberships
    )
    monkeypatch.setattr(register_module, "_fetch_user_projects", no_project_lookup)
    monkeypatch.setattr(register_module, "_start_push_for_session", no_push_setup)
    monkeypatch.setattr(
        register_module,
        "AppSettings",
        lambda: SimpleNamespace(session_ttl_seconds=3600),
    )

    test_server = FastMCP("MemoryHub API-key concurrency integration test")
    test_server.add_tool(register_module.register_session)

    @test_server.tool()
    async def session_identity(ctx: Context) -> dict[str, Any]:
        claims = get_claims_from_context()
        return {
            "user_id": claims["sub"],
            "tenant_id": claims["tenant_id"],
            "project_memberships": claims["project_memberships"],
            "session_id": auth.get_session_id(),
            "default_driver_id": auth.get_default_driver_id(),
            "mcp_session_id": ctx.session_id,
        }

    try:
        async with _serve_streamable_http(test_server) as server_url:
            async with Client(server_url) as bob_client:
                async with Client(server_url) as alice_client:
                    # Register concurrently so the test exercises overlapping
                    # requests from two distinct stateful MCP transports.
                    alice_registration, bob_registration = await asyncio.gather(
                        alice_client.call_tool(
                            "register_session",
                            {"api_key": "api-key-alice", "default_driver_id": "driver-alice"},
                        ),
                        bob_client.call_tool(
                            "register_session",
                            {"api_key": "api-key-bob", "default_driver_id": "driver-bob"},
                        ),
                    )
                    alice_session = _result_data(alice_registration)
                    bob_session = _result_data(bob_registration)
                    assert alice_session["user_id"] == "alice"
                    assert bob_session["user_id"] == "bob"
                    assert alice_session["session_id"] != bob_session["session_id"]

                    alice_identity_result, bob_identity_result = await asyncio.gather(
                        alice_client.call_tool("session_identity"),
                        bob_client.call_tool("session_identity"),
                    )
                    alice_identity = _result_data(alice_identity_result)
                    bob_identity = _result_data(bob_identity_result)

                    assert {
                        key: value for key, value in alice_identity.items()
                        if key != "mcp_session_id"
                    } == {
                        "user_id": "alice",
                        "tenant_id": "tenant-alice",
                        "project_memberships": ["project-alice"],
                        "session_id": alice_session["session_id"],
                        "default_driver_id": "driver-alice",
                    }
                    assert {
                        key: value for key, value in bob_identity.items()
                        if key != "mcp_session_id"
                    } == {
                        "user_id": "bob",
                        "tenant_id": "tenant-bob",
                        "project_memberships": ["project-bob"],
                        "session_id": bob_session["session_id"],
                        "default_driver_id": "driver-bob",
                    }
                    assert alice_identity["mcp_session_id"]
                    assert bob_identity["mcp_session_id"]
                    assert alice_identity["mcp_session_id"] != bob_identity["mcp_session_id"]

                # Closing Alice's transport must remove only Alice's binding.
                assert alice_identity["mcp_session_id"] not in auth._sessions_by_mcp_session
                assert bob_identity["mcp_session_id"] in auth._sessions_by_mcp_session
                bob_after_alice_disconnect = _result_data(
                    await bob_client.call_tool("session_identity")
                )
                assert bob_after_alice_disconnect == bob_identity
    finally:
        auth.clear_session()
