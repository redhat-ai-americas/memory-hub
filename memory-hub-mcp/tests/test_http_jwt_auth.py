"""Exercise Containerfile's src.main verifier wiring with real signed JWTs."""

import base64
import json
import time
from unittest.mock import patch

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastmcp.server.auth.providers.jwt import JWTVerifier
from fastmcp.server.http import RequestContextMiddleware
from src.core.authz import get_claims_from_context
from src.core.http_auth import VerifiedJWTMiddleware, create_http_middleware
from src.main import main, mcp
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.responses import JSONResponse
from starlette.routing import Route


def _b64_int(value: int) -> str:
    return base64.urlsafe_b64encode(value.to_bytes((value.bit_length() + 7) // 8, "big")).decode().rstrip("=")


def _alter_payload(token: str, **changes) -> str:
    header, body, signature = token.split(".")
    claims = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    claims.update(changes)
    body = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return ".".join((header, body, signature))


@pytest.mark.asyncio
async def test_production_http_verifier_rejects_tampered_tokens(monkeypatch):
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_numbers = private_key.public_key().public_numbers()
    jwks = {
        "keys": [
            {
                "kty": "RSA",
                "kid": "test-key",
                "alg": "RS256",
                "use": "sig",
                "n": _b64_int(public_numbers.n),
                "e": _b64_int(public_numbers.e),
            }
        ]
    }
    jwks_client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=jwks)))
    real_verifier = JWTVerifier
    monkeypatch.setenv("AUTH_JWKS_URI", "https://auth.example/jwks")
    monkeypatch.setenv("AUTH_ISSUER", "https://auth.example")
    monkeypatch.setenv("AUTH_AUDIENCE", "memoryhub")
    monkeypatch.setattr(
        "src.core.http_auth.JWTVerifier",
        lambda **kwargs: real_verifier(**kwargs, http_client=jwks_client),
    )

    # src.main.main is the production entrypoint used by Containerfile.
    monkeypatch.setenv("MCP_TRANSPORT", "http")
    with patch.object(mcp, "run") as run:
        main()
    middleware = run.call_args.kwargs["middleware"]
    assert middleware[0].cls is VerifiedJWTMiddleware

    async def probe(request):
        claims = get_claims_from_context()
        return JSONResponse({"sub": claims["sub"], "tenant_id": claims["tenant_id"], "scopes": claims["scopes"]})

    app = Starlette(
        routes=[Route("/probe", probe)],
        middleware=[
            Middleware(RequestContextMiddleware),
            *middleware,
        ],
    )
    app.state.transport_type = "streamable-http"
    now = int(time.time())
    claims = {
        "sub": "alice",
        "tenant_id": "tenant-a",
        "identity_type": "user",
        "scopes": ["memory:read:user"],
        "iat": now,
        "exp": now + 3600,
        "iss": "https://auth.example",
        "aud": "memoryhub",
    }
    valid = jwt.encode(claims, private_key, algorithm="RS256", headers={"kid": "test-key"})
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    invalid = {
        "forged_signature": jwt.encode(claims, other_key, algorithm="RS256", headers={"kid": "test-key"}),
        "unsigned": jwt.encode(claims, key="", algorithm="none", headers={"kid": "test-key"}),
        "issuer": jwt.encode(
            {**claims, "iss": "https://evil.example"}, private_key, algorithm="RS256", headers={"kid": "test-key"}
        ),
        "audience": jwt.encode({**claims, "aud": "other"}, private_key, algorithm="RS256", headers={"kid": "test-key"}),
        "expired": jwt.encode({**claims, "exp": now - 1}, private_key, algorithm="RS256", headers={"kid": "test-key"}),
        "tenant": _alter_payload(valid, tenant_id="tenant-b"),
        "admin_scope": _alter_payload(valid, scopes=["memory:admin"]),
        "subject": _alter_payload(valid, sub="admin"),
    }
    for claim in ("sub", "tenant_id", "identity_type", "scopes", "iat", "exp"):
        invalid[f"missing_{claim}"] = jwt.encode(
            {key: value for key, value in claims.items() if key != claim},
            private_key,
            algorithm="RS256",
            headers={"kid": "test-key"},
        )
    invalid["future_nbf"] = jwt.encode(
        {**claims, "nbf": now + 3600}, private_key,
        algorithm="RS256", headers={"kid": "test-key"},
    )
    async with (
        jwks_client,
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://mcp.test") as client,
    ):
        accepted = await client.get("/probe", headers={"Authorization": f"Bearer {valid}"})
        assert accepted.status_code == 200, accepted.text
        assert accepted.json() == {"sub": "alice", "tenant_id": "tenant-a", "scopes": ["memory:read:user"]}
        without_bearer = await client.get("/probe")
        assert without_bearer.status_code == 200  # legacy API-key session path
        assert without_bearer.json()["sub"] != "alice"
        for case, token in invalid.items():
            denied = await client.get("/probe", headers={"Authorization": f"Bearer {token}"})
            assert denied.status_code == 401, (case, denied.text)

        # Exercise the actual production FastMCP HTTP app, not only the probe.
        production_app = mcp.http_app(path="/mcp/", middleware=middleware, stateless_http=True)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=production_app), base_url="http://mcp.test"
        ) as production:
            for case, token in invalid.items():
                denied = await production.post("/mcp/", headers={"Authorization": f"Bearer {token}"}, json={})
                assert denied.status_code == 401, (case, denied.text)


def test_http_startup_requires_complete_verifier_config(monkeypatch):
    monkeypatch.delenv("AUTH_JWKS_URI", raising=False)
    monkeypatch.setenv("AUTH_ISSUER", "https://auth.example")
    monkeypatch.setenv("AUTH_AUDIENCE", "memoryhub")
    with pytest.raises(RuntimeError, match="AUTH_JWKS_URI"):
        create_http_middleware()
    monkeypatch.setenv("AUTH_JWKS_URI", "__AUTH_JWKS_URI__")
    with pytest.raises(RuntimeError, match="valid AUTH_JWKS_URI"):
        create_http_middleware()
