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

import hashlib
import json
import logging
import os
import time
from datetime import UTC, datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_TENANT_ID = os.environ.get("MEMORYHUB_DEFAULT_TENANT", "default")

# Module-level session state (one session per MCP process/connection).
_current_session: dict[str, Any] | None = None
_session_expires_at: datetime | None = None
_session_ttl_seconds: int = 3600
_session_id: str | None = None
_default_driver_id: str | None = None

# Loaded user records keyed by api_key for O(1) lookup.
_users_by_key: dict[str, dict[str, Any]] = {}
_users_loaded = False

# Cache for remote (auth-service) API key validations, keyed by SHA-256
# hash of the key.  Each entry is (user_dict, expiry_timestamp).
_remote_key_cache: dict[str, tuple[dict[str, Any], float]] = {}
_CACHE_TTL = 300  # 5 minutes


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
        for u in users:
            if "tenant_id" not in u:
                logger.warning(
                    "User %s missing tenant_id, will use default: %s",
                    u.get("user_id", "?"), DEFAULT_TENANT_ID,
                )
        _users_by_key = {u["api_key"]: u for u in users if "api_key" in u}
        logger.info("Loaded %d user record(s) for authentication", len(_users_by_key))
    except (json.JSONDecodeError, KeyError) as exc:
        logger.error("Failed to parse user config: %s", exc)

    _users_loaded = True


def authenticate(api_key: str) -> dict[str, Any] | None:
    """Validate an API key and return the user record, or None if invalid."""
    _load_users()
    return _users_by_key.get(api_key)


class AuthServiceUnavailableError(Exception):
    """Raised when the auth service cannot be reached for API key validation."""


async def authenticate_remote(api_key: str) -> dict[str, Any] | None:
    """Validate an API key via the auth service (fallback for keys not in ConfigMap).

    Returns the user dict on success, None if the key is definitively invalid,
    or raises AuthServiceUnavailableError on transient network failures.
    """
    key_hash = hashlib.sha256(api_key.encode()).hexdigest()
    cached = _remote_key_cache.get(key_hash)
    if cached is not None:
        user_dict, expiry = cached
        if time.time() < expiry:
            return user_dict
        del _remote_key_cache[key_hash]

    validate_url = os.environ.get("AUTH_API_KEY_VALIDATE_URL")
    if not validate_url:
        issuer = os.environ.get("AUTH_ISSUER")
        if issuer:
            validate_url = f"{issuer.rstrip('/')}/internal/validate-api-key"
    if not validate_url:
        return None

    service_key = os.environ.get("AUTH_INTERNAL_SERVICE_KEY", "")
    if not service_key:
        logger.warning("AUTH_INTERNAL_SERVICE_KEY not set; remote API key validation unavailable")
        return None

    try:
        import httpx

        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(
                validate_url,
                json={"api_key": api_key},
                headers={"X-Service-Key": service_key},
            )
        if resp.status_code == 401:
            return None
        if resp.status_code != 200:
            raise AuthServiceUnavailableError(
                f"Auth service returned {resp.status_code}"
            )
        data = resp.json()
        user_dict = {
            "user_id": data["user_id"],
            "name": data["name"],
            "identity_type": data.get("identity_type", "user"),
            "tenant_id": data.get("tenant_id", DEFAULT_TENANT_ID),
            "scopes": data["scopes"],
        }
        _remote_key_cache[key_hash] = (user_dict, time.time() + _CACHE_TTL)
        return user_dict
    except AuthServiceUnavailableError:
        raise
    except Exception as exc:
        raise AuthServiceUnavailableError(str(exc)) from exc


def set_session_id(sid: str) -> None:
    """Store the per-conversation session identifier (server-minted UUID)."""
    global _session_id
    _session_id = sid


def get_session_id() -> str | None:
    """Return the per-conversation session identifier, or None if not registered."""
    return _session_id


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


def set_default_driver_id(driver_id: str | None) -> None:
    """Store a session-level default driver_id for actor/driver plumbing.

    When an agent registers a session on behalf of a human user, the human's
    identity is set here so every subsequent write correctly attributes the
    upstream driver without requiring per-call driver_id parameters.
    """
    global _default_driver_id
    _default_driver_id = driver_id


def get_default_driver_id() -> str | None:
    """Return the session-level default driver_id, or None if expired/unset."""
    if _session_expires_at is not None and datetime.now(UTC) > _session_expires_at:
        return None
    return _default_driver_id


def clear_session() -> None:
    """Reset all module-level session state.

    Useful in tests and when explicitly ending a session. After calling
    this, all session-gated helpers (require_auth, get_default_driver_id,
    etc.) will return None or raise until a new session is registered.
    """
    global _current_session, _session_expires_at, _session_id, _default_driver_id
    _current_session = None
    _session_expires_at = None
    _session_id = None
    _default_driver_id = None
