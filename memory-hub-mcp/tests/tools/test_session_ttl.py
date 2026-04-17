"""Tests for session TTL (#190).

Exercises the session lifecycle: registration with TTL, auto-extend on
activity, expiry detection, and clear error messages on expired sessions.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from src.tools.auth import (
    get_current_user,
    get_session_expiry,
    is_session_expired,
    require_auth,
    set_session,
)

_TEST_USER = {
    "user_id": "test-user",
    "name": "Test User",
    "scopes": ["user", "project"],
}


@pytest.fixture(autouse=True)
def _reset_session():
    """Clear module-level session state between tests."""
    import src.tools.auth as auth_mod

    auth_mod._current_session = None
    auth_mod._session_expires_at = None
    auth_mod._session_ttl_seconds = 3600
    yield
    auth_mod._current_session = None
    auth_mod._session_expires_at = None
    auth_mod._session_ttl_seconds = 3600


class TestSetSession:
    def test_returns_expires_at(self):
        before = datetime.now(UTC)
        expires_at = set_session(_TEST_USER, ttl_seconds=600)
        after = datetime.now(UTC)

        assert before + timedelta(seconds=600) <= expires_at
        assert expires_at <= after + timedelta(seconds=600)

    def test_default_ttl(self):
        before = datetime.now(UTC)
        expires_at = set_session(_TEST_USER)
        expected_min = before + timedelta(seconds=3600)
        assert expires_at >= expected_min


class TestSessionExpiry:
    def test_fresh_session_is_not_expired(self):
        set_session(_TEST_USER, ttl_seconds=600)
        assert not is_session_expired()

    def test_expired_session_detected(self):
        set_session(_TEST_USER, ttl_seconds=1)
        import src.tools.auth as auth_mod

        # Manually set expiry to the past
        auth_mod._session_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        assert is_session_expired()

    def test_no_session_is_expired(self):
        assert is_session_expired()


class TestAutoExtend:
    def test_get_current_user_extends_session(self):
        set_session(_TEST_USER, ttl_seconds=60)
        import src.tools.auth as auth_mod

        # Set expiry close to now (10s remaining)
        near_expiry = datetime.now(UTC) + timedelta(seconds=10)
        auth_mod._session_expires_at = near_expiry

        # Accessing the user should auto-extend
        user = get_current_user()
        assert user is not None
        assert auth_mod._session_expires_at > near_expiry

    def test_require_auth_extends_session(self):
        set_session(_TEST_USER, ttl_seconds=60)
        import src.tools.auth as auth_mod

        near_expiry = datetime.now(UTC) + timedelta(seconds=10)
        auth_mod._session_expires_at = near_expiry

        user = require_auth()
        assert user["user_id"] == "test-user"
        assert auth_mod._session_expires_at > near_expiry

    def test_expired_session_not_extended(self):
        set_session(_TEST_USER, ttl_seconds=1)
        import src.tools.auth as auth_mod

        auth_mod._session_expires_at = datetime.now(UTC) - timedelta(seconds=1)

        user = get_current_user()
        assert user is None


class TestRequireAuth:
    def test_no_session_raises(self):
        with pytest.raises(RuntimeError, match="No session registered"):
            require_auth()

    def test_expired_session_raises(self):
        set_session(_TEST_USER, ttl_seconds=1)
        import src.tools.auth as auth_mod

        auth_mod._session_expires_at = datetime.now(UTC) - timedelta(seconds=1)

        with pytest.raises(RuntimeError, match="Session expired"):
            require_auth()

    def test_expired_error_includes_ttl(self):
        set_session(_TEST_USER, ttl_seconds=300)
        import src.tools.auth as auth_mod

        auth_mod._session_expires_at = datetime.now(UTC) - timedelta(seconds=1)

        with pytest.raises(RuntimeError, match="300 seconds of inactivity"):
            require_auth()

    def test_active_session_succeeds(self):
        set_session(_TEST_USER, ttl_seconds=600)
        user = require_auth()
        assert user["user_id"] == "test-user"


class TestGetSessionExpiry:
    def test_no_session_returns_none(self):
        assert get_session_expiry() is None

    def test_active_session_returns_info(self):
        set_session(_TEST_USER, ttl_seconds=600)
        info = get_session_expiry()

        assert info is not None
        assert "expires_at" in info
        assert "remaining_seconds" in info
        assert "ttl_seconds" in info
        assert info["ttl_seconds"] == 600
        assert info["remaining_seconds"] > 0
        assert not info["expired"]

    def test_expired_session_returns_zero_remaining(self):
        set_session(_TEST_USER, ttl_seconds=1)
        import src.tools.auth as auth_mod

        auth_mod._session_expires_at = datetime.now(UTC) - timedelta(seconds=10)
        info = get_session_expiry()

        assert info is not None
        assert info["remaining_seconds"] == 0
        assert info["expired"]
