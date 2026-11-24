"""Cross-site request forgery guard for the dashboard API.

The dashboard authenticates people with the OAuth proxy's session cookie, which
a browser also attaches to requests that another site triggers. Requests that
change state are accepted only from the dashboard's own origin:

- ``Sec-Fetch-Site`` (sent by current browsers) must be ``same-origin`` or
  ``none``. ``same-site`` is refused on purpose: every Route under the
  cluster's ``*.apps`` domain is the same site, so another application there
  would otherwise get the dashboard cookie.
- ``Origin``, when present, must name the host the request was sent to (the
  ``Host`` or ``X-Forwarded-Host`` header) or one of ``MEMORYHUB_CORS_ORIGINS``.

The scheme is not compared: behind the proxy every request reaches the BFF
over plain HTTP, and the Routes redirect HTTP to HTTPS, so no page of the
same host is served over HTTP.

Requests carrying neither header do not come from a browser page, so no
browser cookie rides on them; they are left to the normal authentication.
Safe methods (GET, HEAD, OPTIONS) are never changed by this guard.
"""

from __future__ import annotations

from urllib.parse import urlsplit

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
ALLOWED_FETCH_SITES = frozenset({"same-origin", "none"})
_DEFAULT_PORTS = {"http": 80, "https": 443}


def _normalize(scheme: str, netloc: str) -> str | None:
    """`host:port` in lower case with the scheme's default port made explicit."""
    try:
        parts = urlsplit(f"{scheme}://{netloc}")
        port = parts.port or _DEFAULT_PORTS.get(scheme)
    except ValueError:
        return None
    if not parts.hostname or port is None:
        return None
    return f"{parts.hostname.lower()}:{port}"


def _origin_key(origin: str) -> str | None:
    parts = urlsplit(origin)
    if parts.scheme not in _DEFAULT_PORTS or not parts.netloc:
        return None
    return _normalize(parts.scheme, parts.netloc)


class CrossSiteRequestGuard:
    def __init__(self, app: ASGIApp, allowed_origins: list[str] | None = None) -> None:
        self.app = app
        self.allowed = {key for origin in (allowed_origins or []) if (key := _origin_key(origin.strip()))}

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] not in UNSAFE_METHODS:
            await self.app(scope, receive, send)
            return
        headers: dict[str, list[str]] = {}
        for key, value in scope.get("headers", []):
            headers.setdefault(key.decode("latin-1").lower(), []).append(value.decode("latin-1"))

        fetch_site = headers.get("sec-fetch-site", [])
        if fetch_site and (len(fetch_site) != 1 or fetch_site[0].strip().lower() not in ALLOWED_FETCH_SITES):
            await self._refuse(scope, receive, send)
            return

        origins = headers.get("origin", [])
        if origins:
            origin = _origin_key(origins[0].strip()) if len(origins) == 1 else None
            if origin is None or origin not in self._own_origins(origins[0], headers):
                await self._refuse(scope, receive, send)
                return

        await self.app(scope, receive, send)

    def _own_origins(self, origin: str, headers: dict[str, list[str]]) -> set[str]:
        # The page and the API share one origin; the proxy may pass the public
        # host as Host or as X-Forwarded-Host. A cross-site page cannot set either.
        scheme = urlsplit(origin.strip()).scheme
        hosts = headers.get("host", []) + [
            host.strip() for value in headers.get("x-forwarded-host", []) for host in value.split(",")
        ]
        own = {key for host in hosts if host and (key := _normalize(scheme, host))}
        return own | self.allowed

    @staticmethod
    async def _refuse(scope: Scope, receive: Receive, send: Send) -> None:
        response = JSONResponse({"detail": "Cross-site request refused"}, status_code=403)
        await response(scope, receive, send)
