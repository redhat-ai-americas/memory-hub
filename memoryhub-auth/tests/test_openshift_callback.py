"""Tests for GET /oauth/openshift/callback — OpenShift broker callback."""

import secrets
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from src.config import settings
from src.models import AuthSession


def _create_pending_session(**overrides) -> AuthSession:
    """Build a pending AuthSession with sensible defaults."""
    defaults = dict(
        session_id=secrets.token_hex(32),
        client_id="test-agent",
        client_redirect_uri="https://example.com/callback",
        client_state="original-client-state",
        code_challenge="dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk",
        code_challenge_method="S256",
        status="pending",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
    )
    defaults.update(overrides)
    return AuthSession(**defaults)


def _mock_openshift_token_ok():
    """Mock a successful OpenShift token exchange."""
    mock_resp = AsyncMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"access_token": "opaque-os-token-xyz"}
    return mock_resp


def _mock_openshift_userinfo_ok(username="testuser"):
    """Mock a successful OpenShift user-info response."""
    mock_resp = AsyncMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"metadata": {"name": username}}
    return mock_resp


@pytest.fixture(autouse=True)
def _configure_broker(monkeypatch):
    """Set OpenShift broker URLs for all tests."""
    monkeypatch.setattr(settings, "openshift_oauth_token_url", "https://openshift.example.com/oauth/token")
    monkeypatch.setattr(settings, "openshift_user_info_url", "https://openshift.example.com/apis/user.openshift.io/v1/users/~")
    monkeypatch.setattr(settings, "openshift_oauth_client_id", "memoryhub-auth-broker")
    monkeypatch.setattr(settings, "openshift_oauth_client_secret", "broker-secret")
    monkeypatch.setattr(settings, "openshift_oauth_authorize_url", "https://openshift.example.com/oauth/authorize")


@pytest.mark.asyncio
class TestCallbackHappyPath:
    async def test_redirects_to_client_with_code(self, client, sample_client, db_engine):
        # Insert a pending session
        factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
        async with factory() as sess:
            auth_sess = _create_pending_session()
            sess.add(auth_sess)
            await sess.commit()
            session_id = auth_sess.session_id

        with patch("src.routes.openshift_callback._exchange_openshift_code", new_callable=AsyncMock) as mock_exchange, \
             patch("src.routes.openshift_callback._resolve_openshift_user", new_callable=AsyncMock) as mock_resolve:
            mock_exchange.return_value = "opaque-token"
            mock_resolve.return_value = "alice"

            resp = await client.get(
                "/oauth/openshift/callback",
                params={"code": "os-code-123", "state": session_id},
                follow_redirects=False,
            )

        assert resp.status_code == 302
        location = resp.headers["location"]
        assert location.startswith("https://example.com/callback?")
        assert "code=" in location
        assert "state=original-client-state" in location

    async def test_session_updated_to_ready(self, client, sample_client, db_engine):
        factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
        async with factory() as sess:
            auth_sess = _create_pending_session()
            sess.add(auth_sess)
            await sess.commit()
            session_id = auth_sess.session_id

        with patch("src.routes.openshift_callback._exchange_openshift_code", new_callable=AsyncMock) as mock_exchange, \
             patch("src.routes.openshift_callback._resolve_openshift_user", new_callable=AsyncMock) as mock_resolve:
            mock_exchange.return_value = "opaque-token"
            mock_resolve.return_value = "bob"

            await client.get(
                "/oauth/openshift/callback",
                params={"code": "os-code", "state": session_id},
                follow_redirects=False,
            )

        async with factory() as sess:
            result = await sess.execute(
                select(AuthSession).where(AuthSession.session_id == session_id)
            )
            updated = result.scalar_one()
            assert updated.status == "ready"
            assert updated.subject == "bob"
            assert updated.identity_type == "user"
            assert updated.tenant_id == "default"
            assert updated.scopes == ["memory:read:user", "memory:write:user"]
            assert updated.code_hash is not None


@pytest.mark.asyncio
class TestCallbackValidation:
    async def test_unknown_session_rejected(self, client, sample_client):
        resp = await client.get(
            "/oauth/openshift/callback",
            params={"code": "abc", "state": "nonexistent-session-id"},
        )
        assert resp.status_code == 400
        assert resp.json()["error"] == "invalid_request"

    async def test_expired_session_rejected(self, client, sample_client, db_engine):
        factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
        async with factory() as sess:
            auth_sess = _create_pending_session(
                expires_at=datetime.now(timezone.utc) - timedelta(minutes=1)
            )
            sess.add(auth_sess)
            await sess.commit()
            session_id = auth_sess.session_id

        resp = await client.get(
            "/oauth/openshift/callback",
            params={"code": "abc", "state": session_id},
        )
        assert resp.status_code == 400
        assert "expired" in resp.json()["error_description"]

    async def test_already_used_session_rejected(self, client, sample_client, db_engine):
        """Session in 'ready' or 'used' status should not be found."""
        factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
        async with factory() as sess:
            auth_sess = _create_pending_session(status="used")
            sess.add(auth_sess)
            await sess.commit()
            session_id = auth_sess.session_id

        resp = await client.get(
            "/oauth/openshift/callback",
            params={"code": "abc", "state": session_id},
        )
        assert resp.status_code == 400

    async def test_openshift_token_exchange_failure(self, client, sample_client, db_engine):
        factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
        async with factory() as sess:
            auth_sess = _create_pending_session()
            sess.add(auth_sess)
            await sess.commit()
            session_id = auth_sess.session_id

        with patch("src.routes.openshift_callback._exchange_openshift_code", new_callable=AsyncMock) as mock_exchange:
            from src.errors import OAuthError
            mock_exchange.side_effect = OAuthError(502, "server_error", "token exchange failed")

            resp = await client.get(
                "/oauth/openshift/callback",
                params={"code": "bad-code", "state": session_id},
            )

        assert resp.status_code == 502
        assert resp.json()["error"] == "server_error"

    async def test_openshift_userinfo_failure(self, client, sample_client, db_engine):
        factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
        async with factory() as sess:
            auth_sess = _create_pending_session()
            sess.add(auth_sess)
            await sess.commit()
            session_id = auth_sess.session_id

        with patch("src.routes.openshift_callback._exchange_openshift_code", new_callable=AsyncMock) as mock_exchange, \
             patch("src.routes.openshift_callback._resolve_openshift_user", new_callable=AsyncMock) as mock_resolve:
            mock_exchange.return_value = "opaque-token"
            from src.errors import OAuthError
            mock_resolve.side_effect = OAuthError(502, "server_error", "user-info failed")

            resp = await client.get(
                "/oauth/openshift/callback",
                params={"code": "os-code", "state": session_id},
            )

        assert resp.status_code == 502
