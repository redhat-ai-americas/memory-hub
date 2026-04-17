"""Tests for GET /oauth/openshift/callback — OpenShift broker callback."""

import secrets
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

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
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
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
                expires_at=datetime.now(UTC) - timedelta(minutes=1)
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


# ---------------------------------------------------------------------------
# b64-encoded username helpers
# ---------------------------------------------------------------------------


class TestDecodeGroupMember:
    """Unit tests for _decode_group_member and _user_in_group_members."""

    def test_plain_username(self):
        from src.routes.openshift_callback import _decode_group_member
        assert _decode_group_member("rdwj") == "rdwj"

    def test_b64_encoded_username(self):
        from src.routes.openshift_callback import _decode_group_member
        # "kube:admin" base64-encoded
        assert _decode_group_member("b64:a3ViZTphZG1pbg==") == "kube:admin"

    def test_invalid_b64_returns_original(self):
        from src.routes.openshift_callback import _decode_group_member
        assert _decode_group_member("b64:!!!invalid!!!") == "b64:!!!invalid!!!"

    def test_user_in_mixed_members(self):
        from src.routes.openshift_callback import _user_in_group_members
        members = ["b64:a3ViZTphZG1pbg==", "rdwj", "alice"]
        assert _user_in_group_members("kube:admin", members)
        assert _user_in_group_members("rdwj", members)
        assert _user_in_group_members("alice", members)
        assert not _user_in_group_members("bob", members)


# ---------------------------------------------------------------------------
# Group membership checks — unit tests for _check_group_membership
# ---------------------------------------------------------------------------


def _mock_group_response(status_code: int, users: list[str] | None = None):
    """Build a mock httpx response for the Groups API.

    Uses MagicMock (not AsyncMock) because httpx Response.json() and .text
    are synchronous — AsyncMock would return a coroutine.
    """
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.text = '{"users": []}'
    if users is not None:
        mock_resp.json.return_value = {"users": users}
    else:
        mock_resp.json.return_value = {"users": []}
    return mock_resp


@pytest.mark.asyncio
class TestCheckGroupMembership:
    """Unit tests for _check_group_membership."""

    async def test_no_group_configured_skips_check(self, monkeypatch):
        """When openshift_allowed_group is empty, no HTTP call is made."""
        monkeypatch.setattr(settings, "openshift_allowed_group", "")
        from src.routes.openshift_callback import _check_group_membership

        # If the function tried to make an HTTP call with no group configured,
        # it would fail because we haven't mocked httpx.  The fact that it
        # returns without error proves the short-circuit works.
        await _check_group_membership("some-token", "alice")

    async def test_user_in_group_succeeds(self, monkeypatch):
        """Group API returns 200 with user in .users — no error raised."""
        monkeypatch.setattr(settings, "openshift_allowed_group", "memoryhub-users")
        from src.routes.openshift_callback import _check_group_membership

        mock_client_instance = AsyncMock()
        mock_client_instance.get.return_value = _mock_group_response(200, ["alice", "bob"])
        mock_client_ctx = AsyncMock()
        mock_client_ctx.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch("src.routes.openshift_callback.httpx.AsyncClient", return_value=mock_client_ctx):
            await _check_group_membership("opaque-token", "alice")

        # Verify the correct URL and auth header were used
        mock_client_instance.get.assert_awaited_once()
        call_args = mock_client_instance.get.call_args
        assert "memoryhub-users" in call_args[0][0]
        assert call_args[1]["headers"]["Authorization"] == "Bearer opaque-token"

    async def test_user_in_group_b64_encoded(self, monkeypatch):
        """Group API returns b64-encoded username (colon in name) — succeeds."""
        monkeypatch.setattr(settings, "openshift_allowed_group", "memoryhub-users")
        from src.routes.openshift_callback import _check_group_membership

        # OpenShift encodes "kube:admin" as "b64:a3ViZTphZG1pbg==" in groups
        mock_client_instance = AsyncMock()
        mock_client_instance.get.return_value = _mock_group_response(
            200, ["b64:a3ViZTphZG1pbg==", "rdwj"]
        )
        mock_client_ctx = AsyncMock()
        mock_client_ctx.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch("src.routes.openshift_callback.httpx.AsyncClient", return_value=mock_client_ctx):
            await _check_group_membership("opaque-token", "kube:admin")

    async def test_user_not_in_group_raises_403(self, monkeypatch):
        """Group API returns 200 but user is NOT in .users — 403."""
        monkeypatch.setattr(settings, "openshift_allowed_group", "memoryhub-users")
        from src.errors import OAuthError
        from src.routes.openshift_callback import _check_group_membership

        mock_client_instance = AsyncMock()
        mock_client_instance.get.return_value = _mock_group_response(200, ["bob", "carol"])
        mock_client_ctx = AsyncMock()
        mock_client_ctx.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_ctx.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("src.routes.openshift_callback.httpx.AsyncClient", return_value=mock_client_ctx),
            pytest.raises(OAuthError) as exc_info,
        ):
            await _check_group_membership("opaque-token", "alice")

        assert exc_info.value.status_code == 403
        assert exc_info.value.error == "access_denied"

    async def test_group_api_failure_raises_502(self, monkeypatch):
        """Group API returns non-200 (e.g. 404) — 502 server_error."""
        monkeypatch.setattr(settings, "openshift_allowed_group", "nonexistent-group")
        from src.errors import OAuthError
        from src.routes.openshift_callback import _check_group_membership

        mock_client_instance = AsyncMock()
        mock_client_instance.get.return_value = _mock_group_response(404)
        mock_client_ctx = AsyncMock()
        mock_client_ctx.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_ctx.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("src.routes.openshift_callback.httpx.AsyncClient", return_value=mock_client_ctx),
            pytest.raises(OAuthError) as exc_info,
        ):
            await _check_group_membership("opaque-token", "alice")

        assert exc_info.value.status_code == 502
        assert exc_info.value.error == "server_error"

    async def test_empty_users_list_raises_403(self, monkeypatch):
        """Group API returns 200 with empty .users list — 403."""
        monkeypatch.setattr(settings, "openshift_allowed_group", "memoryhub-users")
        from src.errors import OAuthError
        from src.routes.openshift_callback import _check_group_membership

        mock_client_instance = AsyncMock()
        mock_client_instance.get.return_value = _mock_group_response(200, [])
        mock_client_ctx = AsyncMock()
        mock_client_ctx.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_ctx.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("src.routes.openshift_callback.httpx.AsyncClient", return_value=mock_client_ctx),
            pytest.raises(OAuthError) as exc_info,
        ):
            await _check_group_membership("opaque-token", "anyone")

        assert exc_info.value.status_code == 403
        assert exc_info.value.error == "access_denied"


@pytest.mark.asyncio
class TestCallbackGroupIntegration:
    """Callback-level tests verifying group membership wiring."""

    async def test_callback_succeeds_with_group_check_passing(
        self, client, sample_client, db_engine
    ):
        """Group check passes — callback completes and redirects."""
        factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
        async with factory() as sess:
            auth_sess = _create_pending_session()
            sess.add(auth_sess)
            await sess.commit()
            session_id = auth_sess.session_id

        with patch("src.routes.openshift_callback._exchange_openshift_code", new_callable=AsyncMock) as mock_exchange, \
             patch("src.routes.openshift_callback._resolve_openshift_user", new_callable=AsyncMock) as mock_resolve, \
             patch("src.routes.openshift_callback._check_group_membership", new_callable=AsyncMock) as mock_group:
            mock_exchange.return_value = "opaque-token"
            mock_resolve.return_value = "alice"
            # _check_group_membership mock returns None (no error) by default

            resp = await client.get(
                "/oauth/openshift/callback",
                params={"code": "os-code", "state": session_id},
                follow_redirects=False,
            )

        assert resp.status_code == 302
        mock_group.assert_awaited_once_with("opaque-token", "alice")

    async def test_callback_returns_403_when_user_not_in_group(
        self, client, sample_client, db_engine
    ):
        """Group check rejects user — callback surfaces the 403."""
        factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
        async with factory() as sess:
            auth_sess = _create_pending_session()
            sess.add(auth_sess)
            await sess.commit()
            session_id = auth_sess.session_id

        from src.errors import OAuthError

        with patch("src.routes.openshift_callback._exchange_openshift_code", new_callable=AsyncMock) as mock_exchange, \
             patch("src.routes.openshift_callback._resolve_openshift_user", new_callable=AsyncMock) as mock_resolve, \
             patch("src.routes.openshift_callback._check_group_membership", new_callable=AsyncMock) as mock_group:
            mock_exchange.return_value = "opaque-token"
            mock_resolve.return_value = "alice"
            mock_group.side_effect = OAuthError(
                403, "access_denied", "User is not a member of the required group"
            )

            resp = await client.get(
                "/oauth/openshift/callback",
                params={"code": "os-code", "state": session_id},
            )

        assert resp.status_code == 403
        assert resp.json()["error"] == "access_denied"
