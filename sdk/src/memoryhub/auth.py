"""MemoryHub SDK authentication."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

import httpx
import jwt  # pyjwt — decode only, no verification needed

from memoryhub.exceptions import AuthenticationError

_EXPIRY_BUFFER_SECONDS = 30


@dataclass
class _TokenState:
    """Cached token state."""

    access_token: str | None = None
    refresh_token: str | None = None
    expires_at: float = 0.0  # unix timestamp

    @property
    def is_expired(self) -> bool:
        return time.time() >= (self.expires_at - _EXPIRY_BUFFER_SECONDS)


class MemoryHubAuth(httpx.Auth):
    """httpx.Auth implementation for MemoryHub OAuth 2.1 client_credentials.

    Fetches and refreshes tokens automatically. Pass this to FastMCP's
    Client(auth=...) parameter.
    """

    requires_response_body = True  # needed for 401 retry flow

    def __init__(
        self,
        auth_url: str,
        client_id: str,
        client_secret: str,
    ) -> None:
        self._auth_url = auth_url.rstrip("/")
        self._client_id = client_id
        self._client_secret = client_secret
        self._state = _TokenState()
        self._lock = asyncio.Lock()

    async def _fetch_token_client_credentials(self) -> _TokenState:
        """Fetch a new token via client_credentials grant."""
        async with httpx.AsyncClient() as http:
            resp = await http.post(
                f"{self._auth_url}/token",
                data={
                    "grant_type": "client_credentials",
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                },
            )
        if resp.status_code != 200:
            is_json = resp.headers.get("content-type", "").startswith("application/json")
            body = resp.json() if is_json else {}
            raise AuthenticationError(
                f"Token request failed ({resp.status_code}): "
                f"{body.get('error_description', body.get('error', resp.text))}"
            )
        return self._parse_token_response(resp.json())

    async def _refresh_token(self) -> _TokenState:
        """Refresh the access token using the refresh token."""
        if not self._state.refresh_token:
            return await self._fetch_token_client_credentials()

        async with httpx.AsyncClient() as http:
            resp = await http.post(
                f"{self._auth_url}/token",
                data={
                    "grant_type": "refresh_token",
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "refresh_token": self._state.refresh_token,
                },
            )
        if resp.status_code != 200:
            # Refresh failed — fall back to full client_credentials
            return await self._fetch_token_client_credentials()
        return self._parse_token_response(resp.json())

    def _parse_token_response(self, data: dict) -> _TokenState:
        """Parse token endpoint response into _TokenState."""
        access_token = data["access_token"]

        # Decode JWT to get exp claim (no verification — we trust the auth server)
        try:
            claims = jwt.decode(access_token, options={"verify_signature": False})
            expires_at = float(claims["exp"])
        except (jwt.DecodeError, KeyError):
            # Fallback: use expires_in from response
            expires_at = time.time() + data.get("expires_in", 300)

        state = _TokenState(
            access_token=access_token,
            refresh_token=data.get("refresh_token"),
            expires_at=expires_at,
        )
        return state

    async def _ensure_token(self) -> str:
        """Ensure we have a valid (non-expired) access token."""
        async with self._lock:
            if self._state.access_token is None:
                self._state = await self._fetch_token_client_credentials()
            elif self._state.is_expired:
                self._state = await self._refresh_token()
            if self._state.access_token is None:
                raise AuthenticationError("Failed to obtain access token")
            return self._state.access_token

    async def async_auth_flow(self, request: httpx.Request):
        """httpx auth flow: inject Bearer token, retry once on 401."""
        token = await self._ensure_token()
        request.headers["Authorization"] = f"Bearer {token}"
        response = yield request

        if response is not None and response.status_code == 401:
            # Token might have been revoked server-side — force refresh
            async with self._lock:
                self._state = await self._refresh_token()
            request.headers["Authorization"] = f"Bearer {self._state.access_token}"
            yield request
