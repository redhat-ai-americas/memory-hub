"""Tests for driver_id resolution (#66).

Verifies the three-tier fallback: per-request > session default > actor_id.
"""

from datetime import UTC, datetime, timedelta

from src.tools._deps import resolve_driver_id
from src.tools.auth import (
    clear_session,
    get_default_driver_id,
    set_default_driver_id,
    set_session,
)


def _make_claims(sub: str = "agent-bot") -> dict:
    return {"sub": sub, "scopes": ["user"]}


class TestResolveDriverId:
    """resolve_driver_id three-tier fallback."""

    def setup_method(self):
        clear_session()

    def teardown_method(self):
        clear_session()

    def test_autonomous_no_defaults(self):
        """No session default, no per-request -- returns claims['sub']."""
        claims = _make_claims("agent-bot")
        assert resolve_driver_id(None, claims) == "agent-bot"

    def test_session_default(self):
        """Session default set -- returns session default."""
        set_session({"user_id": "agent-bot", "name": "Bot", "scopes": ["user"]})
        set_default_driver_id("human-alice")
        claims = _make_claims("agent-bot")
        assert resolve_driver_id(None, claims) == "human-alice"

    def test_per_request_overrides_session(self):
        """Per-request driver_id overrides session default."""
        set_session({"user_id": "agent-bot", "name": "Bot", "scopes": ["user"]})
        set_default_driver_id("human-alice")
        claims = _make_claims("agent-bot")
        assert resolve_driver_id("human-bob", claims) == "human-bob"

    def test_per_request_overrides_no_session(self):
        """Per-request driver_id works without a session default."""
        claims = _make_claims("agent-bot")
        assert resolve_driver_id("human-carol", claims) == "human-carol"


class TestGetDefaultDriverId:
    """get_default_driver_id expiry behavior."""

    def setup_method(self):
        clear_session()

    def teardown_method(self):
        clear_session()

    def test_returns_none_when_unset(self):
        assert get_default_driver_id() is None

    def test_returns_value_when_set(self):
        set_session({"user_id": "bot", "name": "Bot", "scopes": []})
        set_default_driver_id("human-alice")
        assert get_default_driver_id() == "human-alice"

    def test_returns_none_after_session_expires(self):
        """Expired session means driver_id is no longer valid."""
        set_session({"user_id": "bot", "name": "Bot", "scopes": []}, ttl_seconds=1)
        set_default_driver_id("human-alice")

        # Force expiry by manipulating the module-level variable
        import src.tools.auth as auth_mod
        auth_mod._session_expires_at = datetime.now(UTC) - timedelta(seconds=10)

        assert get_default_driver_id() is None

    def test_clear_session_resets_driver_id(self):
        set_session({"user_id": "bot", "name": "Bot", "scopes": []})
        set_default_driver_id("human-alice")
        clear_session()
        assert get_default_driver_id() is None
