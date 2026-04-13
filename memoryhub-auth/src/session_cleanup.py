"""Periodic cleanup of expired auth sessions."""
import logging
from datetime import datetime, timezone

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import AuthSession

log = logging.getLogger("memoryhub-auth.session_cleanup")


async def cleanup_expired_sessions(session: AsyncSession) -> int:
    """Delete expired auth sessions. Returns count of deleted rows."""
    now = datetime.now(timezone.utc)
    result = await session.execute(
        delete(AuthSession).where(AuthSession.expires_at < now)
    )
    await session.commit()
    deleted = result.rowcount
    if deleted > 0:
        log.info("Cleaned up %d expired auth sessions", deleted)
    return deleted
