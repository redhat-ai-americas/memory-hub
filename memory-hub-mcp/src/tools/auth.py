"""Session-based API key authentication for MemoryHub MCP.

Users call register_session(api_key=...) once at the start of a conversation.
The authenticated identity is stored in a module-level variable for that
process/session and used automatically by tools that need an owner identity.

Sessions have a configurable TTL (default 1 hour via MEMORYHUB_SESSION_TTL_SECONDS).
Every authenticated tool call auto-extends the session, so active agents never
hit expiry. Idle sessions expire and return a clear error directing re-registration.

User records are loaded from MEMORYHUB_USERS_FILE (path to JSON) or
MEMORYHUB_USERS_JSON (inline JSON string), falling back to
/config/users.json for OpenShift (mounted from the memoryhub-users ConfigMap).
"""

import json
import logging
import os
from datetime import UTC, datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)

# Module-level session state (one session per MCP process/connection).
_current_session: dict[str, Any] | None = None
_session_expires_at: datetime | None = None
_session_ttl_seconds: int = 3600

# Loaded user records keyed by api_key for O(1) lookup.
_users_by_key: dict[str, dict[str, Any]] = {}
_users_loaded = False


def _load_users() -> None:
    """Load user records from config. Called lazily on first auth attempt."""
    global _users_by_key, _users_loaded

    if _users_loaded:
        return

    raw: str | None = None

    # 1. Inline JSON env var (testing / CI)
    inline = os.environ.get("MEMORYHUB_USERS_JSON")
    if inline:
        raw = inline
        logger.debug("Loading users from MEMORYHUB_USERS_JSON env var")

    # 2. File path env var
    if raw is None:
        file_path = os.environ.get("MEMORYHUB_USERS_FILE")
        if file_path and os.path.isfile(file_path):
            with open(file_path) as f:
                raw = f.read()
            logger.debug("Loading users from MEMORYHUB_USERS_FILE: %s", file_path)

    # 3. OpenShift ConfigMap mount point
    if raw is None:
        default_path = "/config/users.json"
        if os.path.isfile(default_path):
            with open(default_path) as f:
                raw = f.read()
            logger.debug("Loading users from ConfigMap mount: %s", default_path)

    if raw is None:
        logger.warning(
            "No user config found. Set MEMORYHUB_USERS_FILE or MEMORYHUB_USERS_JSON. "
            "Authentication will always fail until users are configured."
        )
        _users_loaded = True
        return

    try:
        data = json.loads(raw)
        users: list[dict[str, Any]] = data.get("users", [])
        _users_by_key = {u["api_key"]: u for u in users if "api_key" in u}
        logger.info("Loaded %d user record(s) for authentication", len(_users_by_key))
    except (json.JSONDecodeError, KeyError) as exc:
        logger.error("Failed to parse user config: %s", exc)

    _users_loaded = True


def authenticate(api_key: str) -> dict[str, Any] | None:
    """Validate an API key and return the user record, or None if invalid."""
    _load_users()
    return _users_by_key.get(api_key)


def set_session(user: dict[str, Any], ttl_seconds: int = 3600) -> datetime:
    """Store the authenticated user for this session with a TTL.

    Returns the computed expires_at timestamp.
    """
    global _current_session, _session_expires_at, _session_ttl_seconds
    _current_session = user
    _session_ttl_seconds = ttl_seconds
    _session_expires_at = datetime.now(UTC) + timedelta(seconds=ttl_seconds)
    return _session_expires_at


def _extend_session() -> None:
    """Reset the session expiry on activity (auto-extend)."""
    global _session_expires_at
    if _session_expires_at is not None:
        _session_expires_at = datetime.now(UTC) + timedelta(seconds=_session_ttl_seconds)


def is_session_expired() -> bool:
    """Return True if the session has expired."""
    if _session_expires_at is None:
        return True
    return datetime.now(UTC) >= _session_expires_at


def get_session_expiry() -> dict[str, Any] | None:
    """Return session TTL info, or None if no session is registered."""
    if _session_expires_at is None:
        return None
    now = datetime.now(UTC)
    remaining = max(0, int((_session_expires_at - now).total_seconds()))
    return {
        "expires_at": _session_expires_at.isoformat(),
        "remaining_seconds": remaining,
        "ttl_seconds": _session_ttl_seconds,
        "expired": remaining == 0,
    }


def get_current_user() -> dict[str, Any] | None:
    """Return the currently authenticated user, or None if not registered.

    Auto-extends the session on access (active sessions don't expire).
    Returns None if the session has expired.
    """
    if _current_session is not None and not is_session_expired():
        _extend_session()
        return _current_session
    return None


def require_auth() -> dict[str, Any]:
    """Return the current user or raise a descriptive error.

    Raises:
        RuntimeError: If no session has been registered or the session
            has expired.
    """
    if _current_session is None:
        raise RuntimeError(
            "No session registered. Call register_session(api_key=...) "
            "at the start of every conversation to authenticate."
        )
    if is_session_expired():
        raise RuntimeError(
            "Session expired. Call register_session(api_key=...) to "
            "re-authenticate. Sessions auto-extend on activity but expire "
            f"after {_session_ttl_seconds} seconds of inactivity."
        )
    _extend_session()
    return _current_session


def has_scope(user: dict[str, Any], scope: str) -> bool:
    """Return True if the user has access to the given scope."""
    return scope in user.get("scopes", [])
