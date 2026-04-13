"""E2E test for the PKCE broker flow (#81).

Drives a headless Chromium browser through the full OAuth 2.1 authorization
code + PKCE flow against a live cluster:

  1. Generate PKCE verifier/challenge pair
  2. GET /authorize → 302 → OpenShift OAuth login
  3. Fill htpasswd credentials and submit
  4. Handle consent screen (first-login approval)
  5. Intercept callback redirect, extract authorization code
  6. POST /token with code + code_verifier
  7. Verify JWT claims (sub, tenant_id, scopes, identity_type)
  8. Call MCP search_memory with the Bearer token

Prerequisites:
  - Live cluster with memoryhub-auth and memory-hub-mcp deployed
  - OC_USER / OC_PASSWORD set in the repo-root .env
  - pip install playwright pytest-timeout && playwright install chromium

Run:
  pytest memoryhub-auth/tests/integration/test_pkce_e2e.py -v --timeout=60
"""

import base64
import contextlib
import hashlib
import json
import os
import re
import secrets
import subprocess
from urllib.parse import parse_qs, urlencode, urlparse

import httpx
import jwt as pyjwt
import pytest

# Skip the entire module if Playwright is not installed.
pytest.importorskip("playwright", reason="playwright not installed")
from playwright.async_api import async_playwright  # noqa: E402

# ---------------------------------------------------------------------------
# Cluster endpoints (overridable via env)
# ---------------------------------------------------------------------------

AUTH_URL = os.getenv(
    "AUTH_SERVER_URL",
    "https://auth-server-memoryhub-auth.apps.cluster-n7pd5.n7pd5.sandbox5167.opentlc.com",
)
MCP_URL = os.getenv(
    "MCP_SERVER_URL",
    "https://memory-hub-mcp-memory-hub-mcp.apps.cluster-n7pd5.n7pd5.sandbox5167.opentlc.com/mcp/",
)

# ---------------------------------------------------------------------------
# Load credentials from repo-root .env
# ---------------------------------------------------------------------------

_ENV_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "..", ".env")
# Minimal .env loader — not a full parser (no multiline, no single-quote
# handling).  Enough for OC_USER / OC_PASSWORD in this test context.
if os.path.isfile(_ENV_PATH):
    with open(_ENV_PATH) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                os.environ.setdefault(_k.strip(), _v.strip().strip('"'))

OC_USER = os.getenv("OC_USER")
OC_PASSWORD = os.getenv("OC_PASSWORD")
# IDP to select on the OpenShift login picker (e.g. "htpasswd", "kube:admin").
# Defaults to "kube:admin" for kubeadmin, "htpasswd" for everyone else.
OC_IDP = os.getenv(
    "OC_IDP",
    "kube:admin" if OC_USER == "kubeadmin" else "htpasswd",
)

# Test OAuth client
CLIENT_ID = "e2e-test"
REDIRECT_URI = "https://localhost:9999/callback"

pytestmark = [
    pytest.mark.skipif(
        not OC_USER or not OC_PASSWORD,
        reason="OC_USER / OC_PASSWORD not set",
    ),
    pytest.mark.asyncio,
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _pkce_pair() -> tuple[str, str]:
    """Generate a valid PKCE S256 verifier + challenge."""
    verifier = base64.urlsafe_b64encode(os.urandom(32)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()
    return verifier, challenge


def _get_admin_key() -> str | None:
    """Retrieve AUTH_ADMIN_KEY from env or from the cluster secret."""
    key = os.getenv("AUTH_ADMIN_KEY")
    if key:
        return key
    result = subprocess.run(
        [
            "oc", "get", "secret", "auth-admin-key",
            "-n", "memoryhub-auth",
            "-o", "jsonpath={.data.AUTH_ADMIN_KEY}",
        ],
        capture_output=True,
        text=True,
        timeout=15,
    )
    if result.returncode == 0 and result.stdout:
        return base64.b64decode(result.stdout).decode().strip()
    return None


async def _ensure_e2e_client(http: httpx.AsyncClient) -> None:
    """Register the e2e-test public OAuth client (idempotent)."""
    admin_key = _get_admin_key()
    if not admin_key:
        pytest.skip("Cannot determine AUTH_ADMIN_KEY — cannot register e2e client")

    headers = {"X-Admin-Key": admin_key}

    # Already registered?
    resp = await http.get(
        f"{AUTH_URL}/admin/clients/{CLIENT_ID}", headers=headers,
    )
    if resp.status_code == 200:
        return

    resp = await http.post(
        f"{AUTH_URL}/admin/clients",
        headers={**headers, "Content-Type": "application/json"},
        json={
            "client_id": CLIENT_ID,
            "client_name": "E2E Test Client",
            "tenant_id": "default",
            "default_scopes": ["memory:read:user", "memory:write:user"],
            "redirect_uris": [REDIRECT_URI],
            "public": True,
        },
    )
    # 201 = created, 409 = already exists (race condition)
    assert resp.status_code in (201, 409), (
        f"Failed to register e2e client: {resp.status_code} {resp.text}"
    )


def _parse_sse_messages(text: str) -> list[dict]:
    """Extract JSON-RPC messages from an SSE response body."""
    messages = []
    for line in text.split("\n"):
        if line.startswith("data:"):
            data = line[5:].strip()
            if data:
                with contextlib.suppress(json.JSONDecodeError):
                    messages.append(json.loads(data))
    return messages


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------


@pytest.mark.timeout(60)
async def test_pkce_e2e_full_flow():
    """Drive the complete PKCE broker flow through a real browser."""
    verifier, challenge = _pkce_pair()
    state = secrets.token_urlsafe(16)

    async with httpx.AsyncClient(verify=False, timeout=30.0) as http:
        # -- Step 0: ensure the e2e-test client is registered --
        await _ensure_e2e_client(http)

        # -- Step 1: build the authorize URL --
        qs = urlencode({
            "response_type": "code",
            "client_id": CLIENT_ID,
            "redirect_uri": REDIRECT_URI,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": state,
        })
        authorize_url = f"{AUTH_URL}/authorize?{qs}"

        # -- Steps 2–5: browser automation --
        captured_url: str | None = None
        request_log: list[str] = []

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(ignore_https_errors=True)
            page = await context.new_page()

            # Capture ALL requests for diagnostics and to catch the
            # callback URL even if route interception misses it.
            page.on("request", lambda req: request_log.append(req.url))

            # Intercept the final redirect to localhost:9999 (nothing
            # listens there).  Use regex for reliable matching.
            async def _intercept(route):
                nonlocal captured_url
                captured_url = route.request.url
                await route.fulfill(status=200, body="OK")

            await page.route(
                re.compile(r"https?://localhost:9999/"), _intercept,
            )

            # Navigate → /authorize → 302 → OpenShift login/IDP page
            await page.goto(
                authorize_url, wait_until="networkidle", timeout=20_000,
            )

            # -- Step 3: handle IDP selection + login form --
            # If the cluster has multiple IDPs, OpenShift shows a picker
            # page first.  Click the matching IDP to proceed.
            idp_link = page.locator(f"a[title='Log in with {OC_IDP}']")
            if await idp_link.is_visible(timeout=3_000):
                await idp_link.click()
                await page.wait_for_load_state(
                    "networkidle", timeout=10_000,
                )

            await page.locator("#inputUsername").fill(OC_USER)
            await page.locator("#inputPassword").fill(OC_PASSWORD)
            await page.locator(
                "button[type='submit'], input[type='submit']",
            ).first.click()

            # After submit the browser either:
            #   (a) lands on a consent/approve page  (first login)
            #   (b) follows the full redirect chain  (already approved)
            # Wait for the page to settle.
            await page.wait_for_load_state("networkidle", timeout=15_000)

            # -- Step 4: handle consent screen if present --
            if captured_url is None:
                # Check if we're on a consent page or an error page.
                current = page.url or ""
                approve = page.locator("input[name='approve']")
                if await approve.is_visible(timeout=2_000):
                    await approve.click()
                    await page.wait_for_load_state(
                        "networkidle", timeout=15_000,
                    )
                elif "chrome-error" not in current:
                    # Might be an error page from our auth server —
                    # wait a bit more for a slow redirect chain.
                    await page.wait_for_timeout(3_000)

            # Fall back: check request log for the callback URL in
            # case route interception didn't fire.
            if captured_url is None:
                for url in request_log:
                    if "localhost:9999" in url:
                        captured_url = url
                        break

            # -- Debug: if still no callback URL, report everything --
            if captured_url is None:
                debug_url = page.url
                debug_content = await page.content()
                debug_path = "/tmp/pkce_e2e_debug.png"
                await page.screenshot(path=debug_path)
                await browser.close()
                # Filter request log to interesting entries
                interesting = [
                    u for u in request_log
                    if "healthz" not in u and "favicon" not in u
                ]
                raise AssertionError(
                    f"Callback redirect never intercepted.\n"
                    f"Final URL: {debug_url!r}\n"
                    f"Screenshot: {debug_path}\n"
                    f"Page snippet: {debug_content[:500]}\n"
                    f"Request log ({len(interesting)} entries):\n"
                    + "\n".join(f"  {u}" for u in interesting[-20:])
                )

            await browser.close()
        params = parse_qs(urlparse(captured_url).query)
        assert "code" in params, (
            f"No 'code' parameter in callback URL: {captured_url}"
        )
        assert params["state"][0] == state, (
            f"State mismatch: expected {state!r}, got {params['state'][0]!r}"
        )
        auth_code = params["code"][0]

        # -- Step 6: exchange code for tokens --
        token_resp = await http.post(
            f"{AUTH_URL}/token",
            data={
                "grant_type": "authorization_code",
                "code": auth_code,
                "client_id": CLIENT_ID,
                "redirect_uri": REDIRECT_URI,
                "code_verifier": verifier,
            },
        )
        assert token_resp.status_code == 200, (
            f"Token exchange failed: {token_resp.status_code} {token_resp.text}"
        )
        token_data = token_resp.json()
        assert token_data["token_type"] == "bearer"
        assert "refresh_token" in token_data
        access_token = token_data["access_token"]

        # -- Step 7: verify JWT claims --

        # 7a: decode without signature check to inspect payload
        claims = pyjwt.decode(
            access_token, options={"verify_signature": False},
        )
        # The OpenShift user-info API may return a different name than
        # the login username (e.g., "kube:admin" for login "kubeadmin").
        assert claims.get("sub"), f"JWT sub claim is empty: {claims}"
        assert claims["identity_type"] == "user"
        assert claims["tenant_id"] == "default"
        assert "memory:read:user" in claims["scopes"]
        assert "memory:write:user" in claims["scopes"]

        # 7b: full signature verification via JWKS
        jwks_resp = await http.get(f"{AUTH_URL}/.well-known/jwks.json")
        assert jwks_resp.status_code == 200
        jwks_data = jwks_resp.json()
        assert jwks_data.get("keys"), "JWKS returned no keys"

        # Match the signing key by kid from the JWT header
        header = pyjwt.get_unverified_header(access_token)
        kid = header.get("kid")
        matching_key = next(
            (k for k in jwks_data["keys"] if k.get("kid") == kid),
            jwks_data["keys"][0],
        )
        pub_key = pyjwt.PyJWK(matching_key).key
        verified = pyjwt.decode(
            access_token, pub_key, algorithms=["RS256"], audience="memoryhub",
        )
        assert verified["sub"] == claims["sub"]

        # -- Step 8: verify the token is accepted by the MCP server --
        mcp_headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }

        # 8a: MCP initialize — proves the JWT is accepted at transport level
        init_resp = await http.post(
            MCP_URL,
            headers=mcp_headers,
            json={
                "jsonrpc": "2.0",
                "id": "e2e-init",
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "e2e-test", "version": "0.1.0"},
                },
            },
        )
        assert init_resp.status_code == 200, (
            f"MCP server rejected the token: "
            f"{init_resp.status_code} {init_resp.text[:300]}"
        )
        mcp_session_id = init_resp.headers.get("mcp-session-id")

        # 8b: send initialized notification
        notif_headers = {**mcp_headers}
        if mcp_session_id:
            notif_headers["mcp-session-id"] = mcp_session_id
        notif_resp = await http.post(
            MCP_URL,
            headers=notif_headers,
            json={
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
            },
        )
        assert notif_resp.status_code in (200, 202, 204), (
            f"notifications/initialized failed: "
            f"{notif_resp.status_code} {notif_resp.text[:200]}"
        )

        # 8c: call search_memory
        search_headers = {**mcp_headers}
        if mcp_session_id:
            search_headers["mcp-session-id"] = mcp_session_id
        search_resp = await http.post(
            MCP_URL,
            headers=search_headers,
            json={
                "jsonrpc": "2.0",
                "id": "e2e-search",
                "method": "tools/call",
                "params": {
                    "name": "search_memory",
                    "arguments": {"query": "e2e test verification"},
                },
            },
        )
        # HTTP 200 proves the JWT was accepted at the transport level.
        # The tool itself may return a JSON-RPC error (e.g. "must call
        # register_session first") — that's fine; it still proves the
        # bearer token passed transport auth.
        assert search_resp.status_code == 200, (
            f"MCP search_memory transport-level failure: "
            f"{search_resp.status_code} {search_resp.text[:300]}"
        )
        # Response may be SSE (text/event-stream) or plain JSON
        messages = _parse_sse_messages(search_resp.text)
        if not messages:
            with contextlib.suppress(Exception):
                messages = [search_resp.json()]
        assert messages, (
            f"No JSON-RPC messages in MCP response: {search_resp.text[:300]}"
        )
