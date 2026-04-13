"""Tests for POST /token grant_type=authorization_code — PKCE verification."""

import base64
import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from src.models import AuthSession

from tests.conftest import TEST_CLIENT_SECRET


def _pkce_pair():
    """Generate a valid PKCE verifier/challenge pair."""
    verifier = base64.urlsafe_b64encode(os.urandom(32)).rstrip(b"=").decode()
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    return verifier, challenge


def _ready_session(client_id="test-agent", **overrides):
    """Build a ready AuthSession with a known code."""
    verifier, challenge = _pkce_pair()
    raw_code = secrets.token_urlsafe(32)
    code_hash = hashlib.sha256(raw_code.encode()).hexdigest()
    defaults = dict(
        session_id=secrets.token_hex(32),
        client_id=client_id,
        client_redirect_uri="https://example.com/callback",
        client_state="original-state",
        code_challenge=challenge,
        code_challenge_method="S256",
        code_hash=code_hash,
        subject="alice",
        identity_type="user",
        tenant_id="default",
        scopes=["memory:read:user", "memory:write:user"],
        status="ready",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
    )
    defaults.update(overrides)
    return AuthSession(**defaults), raw_code, verifier


@pytest.mark.asyncio
class TestAuthorizationCodeHappyPath:
    async def test_exchanges_code_for_tokens(self, client, sample_client, db_engine):
        factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
        auth_sess, raw_code, verifier = _ready_session()
        async with factory() as sess:
            sess.add(auth_sess)
            await sess.commit()

        resp = await client.post(
            "/token",
            data={
                "grant_type": "authorization_code",
                "client_id": "test-agent",
                "client_secret": TEST_CLIENT_SECRET,
                "code": raw_code,
                "redirect_uri": "https://example.com/callback",
                "code_verifier": verifier,
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "access_token" in body
        assert "refresh_token" in body
        assert body["token_type"] == "bearer"
        assert body["expires_in"] > 0
        assert "memory:read:user" in body["scope"]

    async def test_public_client_no_secret_required(self, client, public_client, db_engine):
        factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
        auth_sess, raw_code, verifier = _ready_session(client_id="librechat")
        auth_sess.client_redirect_uri = "https://librechat.example.com/api/mcp/memoryhub/oauth/callback"
        async with factory() as sess:
            sess.add(auth_sess)
            await sess.commit()

        resp = await client.post(
            "/token",
            data={
                "grant_type": "authorization_code",
                "client_id": "librechat",
                "code": raw_code,
                "redirect_uri": "https://librechat.example.com/api/mcp/memoryhub/oauth/callback",
                "code_verifier": verifier,
            },
        )
        assert resp.status_code == 200
        assert "access_token" in resp.json()

    async def test_jwt_claims_correct(self, client, sample_client, db_engine):
        import jwt as pyjwt
        from src.keys import get_public_key

        factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
        auth_sess, raw_code, verifier = _ready_session()
        async with factory() as sess:
            sess.add(auth_sess)
            await sess.commit()

        resp = await client.post(
            "/token",
            data={
                "grant_type": "authorization_code",
                "client_id": "test-agent",
                "client_secret": TEST_CLIENT_SECRET,
                "code": raw_code,
                "redirect_uri": "https://example.com/callback",
                "code_verifier": verifier,
            },
        )
        token = resp.json()["access_token"]
        claims = pyjwt.decode(
            token,
            get_public_key(),
            algorithms=["RS256"],
            audience="memoryhub",
        )
        assert claims["sub"] == "alice"
        assert claims["identity_type"] == "user"
        assert claims["tenant_id"] == "default"
        assert "memory:read:user" in claims["scopes"]


@pytest.mark.asyncio
class TestAuthorizationCodeValidation:
    async def test_missing_code(self, client, sample_client):
        resp = await client.post(
            "/token",
            data={
                "grant_type": "authorization_code",
                "client_id": "test-agent",
                "client_secret": TEST_CLIENT_SECRET,
                "redirect_uri": "https://example.com/callback",
                "code_verifier": "something",
            },
        )
        assert resp.status_code == 400
        assert resp.json()["error"] == "invalid_request"

    async def test_missing_code_verifier(self, client, sample_client):
        resp = await client.post(
            "/token",
            data={
                "grant_type": "authorization_code",
                "client_id": "test-agent",
                "client_secret": TEST_CLIENT_SECRET,
                "code": "some-code",
                "redirect_uri": "https://example.com/callback",
            },
        )
        assert resp.status_code == 400
        assert resp.json()["error"] == "invalid_request"

    async def test_invalid_code(self, client, sample_client):
        resp = await client.post(
            "/token",
            data={
                "grant_type": "authorization_code",
                "client_id": "test-agent",
                "client_secret": TEST_CLIENT_SECRET,
                "code": "nonexistent-code",
                "redirect_uri": "https://example.com/callback",
                "code_verifier": "something",
            },
        )
        assert resp.status_code == 400
        assert resp.json()["error"] == "invalid_grant"

    async def test_wrong_pkce_verifier(self, client, sample_client, db_engine):
        factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
        auth_sess, raw_code, _correct_verifier = _ready_session()
        async with factory() as sess:
            sess.add(auth_sess)
            await sess.commit()

        resp = await client.post(
            "/token",
            data={
                "grant_type": "authorization_code",
                "client_id": "test-agent",
                "client_secret": TEST_CLIENT_SECRET,
                "code": raw_code,
                "redirect_uri": "https://example.com/callback",
                "code_verifier": "wrong-verifier-value",
            },
        )
        assert resp.status_code == 400
        body = resp.json()
        assert body["error"] == "invalid_grant"
        assert "PKCE" in body["error_description"]

    async def test_redirect_uri_mismatch(self, client, sample_client, db_engine):
        factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
        auth_sess, raw_code, verifier = _ready_session()
        async with factory() as sess:
            sess.add(auth_sess)
            await sess.commit()

        resp = await client.post(
            "/token",
            data={
                "grant_type": "authorization_code",
                "client_id": "test-agent",
                "client_secret": TEST_CLIENT_SECRET,
                "code": raw_code,
                "redirect_uri": "https://evil.com/callback",
                "code_verifier": verifier,
            },
        )
        assert resp.status_code == 400
        assert "redirect_uri" in resp.json()["error_description"]

    async def test_client_id_mismatch(self, client, public_client, db_engine):
        """Code was issued for test-agent but librechat tries to redeem it."""
        factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
        auth_sess, raw_code, verifier = _ready_session(client_id="test-agent")
        async with factory() as sess:
            sess.add(auth_sess)
            await sess.commit()

        resp = await client.post(
            "/token",
            data={
                "grant_type": "authorization_code",
                "client_id": "librechat",
                "code": raw_code,
                "redirect_uri": "https://example.com/callback",
                "code_verifier": verifier,
            },
        )
        assert resp.status_code == 400
        assert "client_id" in resp.json()["error_description"]

    async def test_code_replay_rejected(self, client, sample_client, db_engine):
        """Same code submitted twice — second attempt must fail."""
        factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
        auth_sess, raw_code, verifier = _ready_session()
        async with factory() as sess:
            sess.add(auth_sess)
            await sess.commit()

        data = {
            "grant_type": "authorization_code",
            "client_id": "test-agent",
            "client_secret": TEST_CLIENT_SECRET,
            "code": raw_code,
            "redirect_uri": "https://example.com/callback",
            "code_verifier": verifier,
        }
        # First attempt succeeds
        resp1 = await client.post("/token", data=data)
        assert resp1.status_code == 200

        # Second attempt with same code fails
        resp2 = await client.post("/token", data=data)
        assert resp2.status_code == 400
        assert resp2.json()["error"] == "invalid_grant"

    async def test_expired_code_rejected(self, client, sample_client, db_engine):
        factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
        auth_sess, raw_code, verifier = _ready_session(
            expires_at=datetime.now(timezone.utc) - timedelta(minutes=1)
        )
        async with factory() as sess:
            sess.add(auth_sess)
            await sess.commit()

        resp = await client.post(
            "/token",
            data={
                "grant_type": "authorization_code",
                "client_id": "test-agent",
                "client_secret": TEST_CLIENT_SECRET,
                "code": raw_code,
                "redirect_uri": "https://example.com/callback",
                "code_verifier": verifier,
            },
        )
        assert resp.status_code == 400
        assert "expired" in resp.json()["error_description"]

    async def test_confidential_client_requires_secret(self, client, sample_client, db_engine):
        factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
        auth_sess, raw_code, verifier = _ready_session()
        async with factory() as sess:
            sess.add(auth_sess)
            await sess.commit()

        resp = await client.post(
            "/token",
            data={
                "grant_type": "authorization_code",
                "client_id": "test-agent",
                # No client_secret
                "code": raw_code,
                "redirect_uri": "https://example.com/callback",
                "code_verifier": verifier,
            },
        )
        assert resp.status_code == 400
        assert "client_secret" in resp.json()["error_description"]

    async def test_non_ascii_verifier_rejected(self, client, sample_client, db_engine):
        """Non-ASCII code_verifier should fail PKCE check, not crash with 500."""
        factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
        auth_sess, raw_code, _verifier = _ready_session()
        async with factory() as sess:
            sess.add(auth_sess)
            await sess.commit()

        resp = await client.post(
            "/token",
            data={
                "grant_type": "authorization_code",
                "client_id": "test-agent",
                "client_secret": TEST_CLIENT_SECRET,
                "code": raw_code,
                "redirect_uri": "https://example.com/callback",
                "code_verifier": "verifier-with-émojis-and-ünïcödé",
            },
        )
        assert resp.status_code == 400
        assert resp.json()["error"] == "invalid_grant"
