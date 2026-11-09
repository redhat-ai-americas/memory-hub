"""Bearer tokens are verified per call; clients without one are unaffected.

These run a real FastMCP server over HTTP, because the Authorization header
only exists on HTTP requests.
"""

import asyncio
import socket
import threading
import time
from unittest.mock import patch

import jwt
import pytest
import uvicorn
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastmcp import Client, FastMCP
from fastmcp.client.transports import StreamableHttpTransport
from fastmcp.exceptions import ToolError
from fastmcp.server.auth.providers.jwt import JWTVerifier
from src.core import authz, bearer
from src.core.bearer import BearerTokenMiddleware

ISSUER = "https://auth.memoryhub.test"
AUDIENCE = "memoryhub"


def _key():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    public = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    return pem, public


SIGNING_KEY, PUBLIC_KEY = _key()
OTHER_KEY, _ = _key()


def token(key=SIGNING_KEY, **claims) -> str:
    body = {
        "sub": "alice-agent",
        "tenant_id": "acme",
        "scope": "memory:read memory:write",
        "iss": ISSUER,
        "aud": AUDIENCE,
        "exp": int(time.time()) + 600,
        **claims,
    }
    return jwt.encode(body, key, algorithm="RS256")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def url():
    mcp = FastMCP("bearer-test")

    @mcp.tool
    def whoami() -> dict:
        claims = authz.get_claims_from_context()
        return {"sub": claims["sub"], "tenant_id": claims["tenant_id"], "scopes": claims["scopes"]}

    mcp.add_middleware(BearerTokenMiddleware())
    port = _free_port()
    server = uvicorn.Server(
        uvicorn.Config(mcp.http_app(path="/mcp/"), host="127.0.0.1", port=port, log_level="critical")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}/mcp/"
    server.should_exit = True
    thread.join(timeout=5)


@pytest.fixture
def verifier():
    v = JWTVerifier(public_key=PUBLIC_KEY.decode(), issuer=ISSUER, audience=AUDIENCE, algorithm="RS256")
    with patch.object(bearer, "_verifier", return_value=v):
        yield v


async def whoami(url, headers=None):
    async with Client(StreamableHttpTransport(url, headers=headers or {})) as client:
        return (await client.call_tool("whoami", {})).structured_content


async def test_a_signed_token_is_the_callers_identity(url, verifier):
    me = await whoami(url, {"Authorization": f"Bearer {token()}"})
    assert me["sub"] == "alice-agent" and me["tenant_id"] == "acme"
    assert set(me["scopes"]) == {"memory:read", "memory:write"}


@pytest.mark.parametrize(
    "bad",
    [
        pytest.param(lambda: token(key=OTHER_KEY), id="signed with another key"),
        pytest.param(lambda: jwt.encode({"sub": "admin", "aud": AUDIENCE, "iss": ISSUER}, "x" * 32), id="HS256"),
        pytest.param(lambda: token(exp=int(time.time()) - 60), id="expired"),
        pytest.param(lambda: token(aud="someone-else"), id="wrong audience"),
        pytest.param(lambda: token(iss="https://evil.test"), id="wrong issuer"),
        pytest.param(lambda: "not-a-jwt", id="garbage"),
    ],
)
async def test_a_token_that_does_not_verify_is_refused(url, verifier, bad):
    with pytest.raises(ToolError, match="Invalid or expired bearer token"):
        await whoami(url, {"Authorization": f"Bearer {bad()}"})


async def test_without_a_verifier_bearer_tokens_are_refused(url):
    with patch.object(bearer, "_verifier", return_value=None), pytest.raises(ToolError, match="does not accept bearer"):
        await whoami(url, {"Authorization": f"Bearer {token()}"})


async def test_clients_without_a_token_still_reach_the_tools(url, verifier):
    """API-key clients sign in with register_session; no 401 at the transport."""
    session_user = {"user_id": "bob-agent", "tenant_id": "acme", "scopes": ["memory:read"]}
    with patch.object(authz, "get_current_user", return_value=session_user):
        me = await whoami(url)
    assert me["sub"] == "bob-agent"


async def test_verified_claims_do_not_outlive_the_call(url, verifier):
    await whoami(url, {"Authorization": f"Bearer {token()}"})
    assert bearer.verified_bearer_claims() is None
    with patch.object(authz, "get_current_user", return_value=None), pytest.raises(ToolError):
        await whoami(url)


def test_the_production_server_verifies_tokens_without_transport_auth():
    import src.main as main

    assert main.mcp.auth is None  # API-key clients connect without a token
    assert any(isinstance(m, BearerTokenMiddleware) for m in main.mcp.middleware)


def test_concurrent_calls_keep_their_own_identity(url, verifier):
    async def both():
        return await asyncio.gather(
            whoami(url, {"Authorization": f"Bearer {token(sub='alice-agent')}"}),
            whoami(url, {"Authorization": f"Bearer {token(sub='carol-agent')}"}),
        )

    a, c = asyncio.run(both())
    assert (a["sub"], c["sub"]) == ("alice-agent", "carol-agent")
