"""Bearer tokens are trusted only after their signature is verified.

The production server (``python -m src.main``) has no transport-level auth:
API-key clients connect without a token and sign in with register_session,
and a transport verifier would refuse them with 401. Bearer tokens therefore
have to be verified where they are used.

``BearerTokenMiddleware`` runs before every tool call. When the request
carries ``Authorization: Bearer …`` it verifies the token with the JWT
verifier configured from ``AUTH_JWKS_URI`` / ``AUTH_ISSUER`` /
``AUTH_AUDIENCE`` and makes the verified claims available to
``authz.get_claims_from_context`` for that call only. A token that does not
verify, or a token sent to a server with no verifier configured, refuses the
call. Requests without a bearer token are not affected.
"""

from __future__ import annotations

import logging
import os
import time
from contextvars import ContextVar
from typing import Any
from urllib.parse import quote

from fastmcp.exceptions import ToolError
from fastmcp.server.middleware import Middleware, MiddlewareContext

logger = logging.getLogger(__name__)

_verified_claims: ContextVar[dict[str, Any] | None] = ContextVar("memoryhub_verified_bearer_claims", default=None)


def verified_bearer_claims() -> dict[str, Any] | None:
    """Claims of this call's bearer token, if BearerTokenMiddleware verified it."""
    return _verified_claims.get()


def bearer_token() -> str | None:
    """The bearer token of the current HTTP request, if there is one."""
    try:
        from fastmcp.server.dependencies import get_http_request

        request = get_http_request()
    except Exception:  # no HTTP request: stdio or in-process
        return None
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        return None
    return header.split(" ", 1)[1].strip() or None


# QA 2026-11-09 RT2-CL-05: a signed token stays valid until it expires, so revoking a
# client did not stop tokens already issued to it. The issuing client is re-checked
# with the auth service (cached briefly) and the call fails closed when it cannot be.
CLIENT_CHECK_SECONDS = int(os.environ.get("MEMORYHUB_BEARER_CLIENT_CHECK_SECONDS", "30"))
_client_cache: dict[str, tuple[float, dict[str, Any] | None]] = {}


def _client_status_url(client_id: str) -> str | None:
    explicit = os.environ.get("MEMORYHUB_CLIENT_STATUS_URL")
    if explicit:
        return explicit.rstrip("/") + f"/{quote(client_id, safe='')}/status"
    validate = os.environ.get("AUTH_API_KEY_VALIDATE_URL", "")
    if not validate.endswith("/internal/validate-api-key"):
        return None
    return validate[: -len("validate-api-key")] + f"clients/{quote(client_id, safe='')}/status"


async def _client_status(client_id: str) -> dict[str, Any] | None:
    """Active client record from the auth service, or None when revoked/unknown."""
    cached = _client_cache.get(client_id)
    if cached is not None and time.time() - cached[0] < CLIENT_CHECK_SECONDS:
        return cached[1]
    url = _client_status_url(client_id)
    import httpx

    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.get(url, headers={"X-Service-Key": os.environ.get("AUTH_INTERNAL_SERVICE_KEY", "")})
    if response.status_code == 404:
        status = None
    else:
        response.raise_for_status()
        status = response.json()
    _client_cache[client_id] = (time.time(), status)
    return status


async def _enforce_client_state(claims: dict[str, Any]) -> None:
    """Refuse tokens of revoked clients, or of clients moved to another tenant; narrow scopes."""
    client_id = claims.get("azp") or claims.get("sub")
    if not client_id or _client_status_url(str(client_id)) is None:
        return  # no auth service to ask (local/stdio deployments)
    try:
        status = await _client_status(str(client_id))
    except Exception as exc:
        logger.warning("Could not confirm the client behind a bearer token: %s", exc)
        raise ToolError("Could not confirm this token's client with the auth service; try again.") from exc
    if status is None:
        raise ToolError("The client this token was issued to has been revoked.")
    if status.get("tenant_id") != claims.get("tenant_id"):
        raise ToolError("This token's tenant no longer matches its client.")
    allowed = set(status.get("scopes") or [])
    claims["scopes"] = [scope for scope in claims["scopes"] if scope in allowed]


def _token_scopes(claims: dict[str, Any], access: Any) -> list[str]:
    """Scopes of a verified token.

    The MemoryHub auth service issues a ``scopes`` list claim; FastMCP's verifier only
    reads the OAuth ``scope`` string, so relying on it alone left genuine tokens with no
    scopes (QA 2026-11-09 RT3-JWT-02). The claims are already signature-verified here.
    """
    raw = claims.get("scopes")
    if isinstance(raw, list):
        return [str(s) for s in raw]
    if isinstance(raw, str):
        return raw.split()
    return list(access.scopes or [])


def _verifier():
    from src.core.app import jwt_verifier

    return jwt_verifier


class BearerTokenMiddleware(Middleware):
    """Verify the caller's bearer token before the tool runs."""

    async def on_call_tool(self, context: MiddlewareContext, call_next):
        token = bearer_token()
        if token is None:
            return await call_next(context)
        verifier = _verifier()
        if verifier is None:
            raise ToolError(
                "This server does not accept bearer tokens: no verifier is configured "
                "(AUTH_JWKS_URI, AUTH_ISSUER). Sign in with register_session instead."
            )
        access = await verifier.verify_token(token)
        if access is None:
            logger.warning("Refused a tool call with a bearer token that did not verify")
            raise ToolError("Invalid or expired bearer token.")
        claims = dict(access.claims or {})
        claims.setdefault("sub", access.client_id)
        claims["scopes"] = _token_scopes(claims, access)
        await _enforce_client_state(claims)
        reset = _verified_claims.set(claims)
        try:
            return await call_next(context)
        finally:
            _verified_claims.reset(reset)
