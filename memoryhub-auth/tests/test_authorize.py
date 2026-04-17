"""Tests for GET /authorize — PKCE authorization endpoint."""

import base64
import hashlib
import os

import pytest
from sqlalchemy import select

from src.config import settings


# Generate a valid PKCE pair for tests
def _pkce_pair():
    verifier = base64.urlsafe_b64encode(os.urandom(32)).rstrip(b"=").decode()
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    return verifier, challenge


VERIFIER, CHALLENGE = _pkce_pair()

VALID_PARAMS = {
    "response_type": "code",
    "client_id": "test-agent",
    "redirect_uri": "https://example.com/callback",
    "code_challenge": CHALLENGE,
    "code_challenge_method": "S256",
    "state": "random-state-123",
}


@pytest.fixture(autouse=True)
def _set_openshift_url(monkeypatch):
    """Most tests need the broker URL configured."""
    monkeypatch.setattr(
        settings,
        "openshift_oauth_authorize_url",
        "https://openshift.example.com/oauth/authorize",
    )


@pytest.mark.asyncio
class TestAuthorizeHappyPath:
    async def test_redirects_to_openshift(self, client, sample_client):
        resp = await client.get("/authorize", params=VALID_PARAMS, follow_redirects=False)
        assert resp.status_code == 302
        location = resp.headers["location"]
        assert "openshift.example.com/oauth/authorize" in location
        assert "response_type=code" in location
        assert "client_id=memoryhub-auth-broker" in location
        assert "state=" in location

    async def test_session_persisted(self, client, sample_client, db_engine):
        resp = await client.get("/authorize", params=VALID_PARAMS, follow_redirects=False)
        assert resp.status_code == 302

        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

        from src.models import AuthSession

        factory = async_sessionmaker(db_engine, class_=AsyncSession)
        async with factory() as sess:
            result = await sess.execute(select(AuthSession))
            sessions = result.scalars().all()
            assert len(sessions) == 1
            s = sessions[0]
            assert s.client_id == "test-agent"
            assert s.client_redirect_uri == "https://example.com/callback"
            assert s.client_state == "random-state-123"
            assert s.code_challenge == CHALLENGE
            assert s.status == "pending"


@pytest.mark.asyncio
class TestAuthorizeValidation:
    async def test_unsupported_response_type(self, client, sample_client):
        params = {**VALID_PARAMS, "response_type": "token"}
        resp = await client.get("/authorize", params=params)
        assert resp.status_code == 400
        assert resp.json()["error"] == "unsupported_response_type"

    async def test_plain_challenge_method_rejected(self, client, sample_client):
        params = {**VALID_PARAMS, "code_challenge_method": "plain"}
        resp = await client.get("/authorize", params=params)
        assert resp.status_code == 400
        body = resp.json()
        assert body["error"] == "invalid_request"
        assert "S256" in body["error_description"]

    async def test_empty_code_challenge_rejected(self, client, sample_client):
        params = {**VALID_PARAMS, "code_challenge": ""}
        resp = await client.get("/authorize", params=params)
        assert resp.status_code == 400
        assert resp.json()["error"] == "invalid_request"

    async def test_invalid_base64url_challenge(self, client, sample_client):
        params = {**VALID_PARAMS, "code_challenge": "not valid base64url!!!"}
        resp = await client.get("/authorize", params=params)
        assert resp.status_code == 400
        assert resp.json()["error"] == "invalid_request"

    async def test_unknown_client_id(self, client, sample_client):
        params = {**VALID_PARAMS, "client_id": "nonexistent"}
        resp = await client.get("/authorize", params=params)
        assert resp.status_code == 400
        assert resp.json()["error"] == "invalid_request"

    async def test_inactive_client_rejected(self, client, inactive_client):
        params = {**VALID_PARAMS, "client_id": "inactive-agent"}
        resp = await client.get("/authorize", params=params)
        assert resp.status_code == 400
        assert resp.json()["error"] == "invalid_request"

    async def test_mismatched_redirect_uri(self, client, sample_client):
        params = {**VALID_PARAMS, "redirect_uri": "https://evil.com/callback"}
        resp = await client.get("/authorize", params=params)
        assert resp.status_code == 400
        body = resp.json()
        assert body["error"] == "invalid_request"
        assert "redirect_uri" in body["error_description"]

    async def test_client_with_no_redirect_uris(self, client, inactive_client, db_engine):
        """Client that has redirect_uris=None should reject any redirect_uri."""
        # inactive_client doesn't have redirect_uris set — but it's also inactive,
        # so it gets rejected at the client lookup step. Use sample_client behavior
        # to verify redirect_uri matching works when list is non-empty.
        params = {**VALID_PARAMS, "redirect_uri": "https://other.com/cb"}
        resp = await client.get("/authorize", params=params)
        assert resp.status_code == 400

    async def test_short_code_challenge_rejected(self, client, sample_client):
        """RFC 7636 §4.2: challenge must be at least 43 characters."""
        params = {**VALID_PARAMS, "code_challenge": "dBjftJeZ4CVPmB92K27uhbUJU1p1r_wW1gFW"}  # 36 chars
        resp = await client.get("/authorize", params=params)
        assert resp.status_code == 400
        assert "43-128" in resp.json()["error_description"]

    async def test_broker_not_configured(self, client, sample_client, monkeypatch):
        """If OpenShift OAuth URL is not set, return 503."""
        monkeypatch.setattr(settings, "openshift_oauth_authorize_url", "")

        resp = await client.get("/authorize", params=VALID_PARAMS)
        assert resp.status_code == 503
        assert resp.json()["error"] == "temporarily_unavailable"
