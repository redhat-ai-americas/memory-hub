"""JWT verification for the production MCP HTTP transport.

Bearer requests are verified before MCP sees them. Requests without an
Authorization header retain the existing register_session(api_key) contract.
"""

import os
import time
from urllib.parse import urlsplit

from fastmcp.server.auth.providers.jwt import JWTVerifier
from mcp.server.auth.middleware.auth_context import AuthContextMiddleware
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
from starlette.authentication import AuthCredentials
from starlette.middleware import Middleware
from starlette.responses import JSONResponse


def _valid_claims(claims: dict, now: float) -> bool:
    """Require the claims issued by memoryhub-auth, in addition to JWTVerifier checks."""
    return (
        isinstance(claims.get("sub"), str)
        and bool(claims["sub"])
        and isinstance(claims.get("tenant_id"), str)
        and bool(claims["tenant_id"])
        and claims.get("identity_type") in ("user", "service")
        and isinstance(claims.get("scopes"), list)
        and all(isinstance(scope, str) for scope in claims["scopes"])
        and type(claims.get("exp")) is int
        and claims["exp"] > now
        and type(claims.get("iat")) is int
        and claims["iat"] <= now
        and ("nbf" not in claims or (type(claims["nbf"]) is int and claims["nbf"] <= now))
    )


class VerifiedJWTMiddleware:
    """Accept a verified Bearer token or defer to MCP's API-key session flow."""

    def __init__(self, app, verifier: JWTVerifier):
        self.app = app
        self.verifier = verifier

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = [(k.lower(), v) for k, v in scope.get("headers", []) if k.lower() == b"authorization"]
        if headers:
            header = headers[0][1].decode("latin-1") if len(headers) == 1 else ""
            scheme, separator, token = header.partition(" ")
            if scheme.lower() != "bearer" or not separator or not token or token.strip() != token:
                await JSONResponse({"error": "invalid_token"}, status_code=401)(scope, receive, send)
                return
            access_token = await self.verifier.verify_token(token)
            if access_token is None or not _valid_claims(access_token.claims, time.time()):
                await JSONResponse({"error": "invalid_token"}, status_code=401)(scope, receive, send)
                return
            # FastMCP's get_access_token() reads this exact SDK user object.
            scope["user"] = AuthenticatedUser(access_token)
            scope["auth"] = AuthCredentials(access_token.claims["scopes"])

        await self.app(scope, receive, send)


def create_http_middleware() -> list[Middleware]:
    """Build the verifier used by Containerfile's src.main HTTP entrypoint.

    HTTP startup fails closed if auth-service configuration is incomplete.
    API-key clients still use register_session on this same endpoint.
    """
    jwks_uri = os.getenv("AUTH_JWKS_URI")
    issuer = os.getenv("AUTH_ISSUER")
    audience = os.getenv("AUTH_AUDIENCE")
    if not all((jwks_uri, issuer, audience)):
        raise RuntimeError("HTTP MCP requires AUTH_JWKS_URI, AUTH_ISSUER and AUTH_AUDIENCE")
    if any(
        urlsplit(value).scheme not in {"http", "https"} or not urlsplit(value).hostname for value in (jwks_uri, issuer)
    ):
        raise RuntimeError("HTTP MCP requires valid AUTH_JWKS_URI and AUTH_ISSUER URLs")
    verifier = JWTVerifier(jwks_uri=jwks_uri, issuer=issuer, audience=audience, algorithm="RS256")
    return [
        Middleware(VerifiedJWTMiddleware, verifier=verifier),
        Middleware(AuthContextMiddleware),
    ]
