"""Tests for the session_cleanup module."""
import secrets
from datetime import UTC, datetime, timedelta

import pytest

from src.models import AuthSession
from src.session_cleanup import cleanup_expired_sessions


def _make_session(*, expired: bool, session_id: str | None = None) -> AuthSession:
    """Build an AuthSession with either a past or future expiry."""
    now = datetime.now(UTC)
    expires_at = now - timedelta(minutes=5) if expired else now + timedelta(minutes=10)

    return AuthSession(
        session_id=session_id or secrets.token_hex(32),
        client_id="test-agent",
        client_redirect_uri="https://example.com/callback",
        client_state="state-xyz",
        code_challenge="E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM",
        code_challenge_method="S256",
        status="pending",
        created_at=now,
        expires_at=expires_at,
    )


class TestCleanupExpiredSessions:
    @pytest.mark.asyncio
    async def test_deletes_expired_session(self, db_session):
        expired = _make_session(expired=True)
        db_session.add(expired)
        await db_session.commit()

        deleted = await cleanup_expired_sessions(db_session)

        assert deleted == 1, f"Expected 1 deleted, got {deleted}"
        remaining = await db_session.get(AuthSession, expired.session_id)
        assert remaining is None

    @pytest.mark.asyncio
    async def test_keeps_active_session(self, db_session):
        active = _make_session(expired=False)
        db_session.add(active)
        await db_session.commit()

        deleted = await cleanup_expired_sessions(db_session)

        assert deleted == 0, f"Expected 0 deleted, got {deleted}"
        remaining = await db_session.get(AuthSession, active.session_id)
        assert remaining is not None

    @pytest.mark.asyncio
    async def test_mixed_sessions(self, db_session):
        expired1 = _make_session(expired=True)
        expired2 = _make_session(expired=True)
        active = _make_session(expired=False)
        db_session.add_all([expired1, expired2, active])
        await db_session.commit()

        deleted = await cleanup_expired_sessions(db_session)

        assert deleted == 2, f"Expected 2 deleted, got {deleted}"
        assert await db_session.get(AuthSession, active.session_id) is not None
        assert await db_session.get(AuthSession, expired1.session_id) is None
        assert await db_session.get(AuthSession, expired2.session_id) is None

    @pytest.mark.asyncio
    async def test_no_sessions_returns_zero(self, db_session):
        deleted = await cleanup_expired_sessions(db_session)
        assert deleted == 0
