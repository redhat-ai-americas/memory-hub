"""Session-based API key authentication for MemoryHub MCP.

Users call register_session(api_key=...) once per MCP client session. The
authenticated identity is bound to FastMCP's session ID, so simultaneous
clients handled by one process keep independent identities and session data.

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
import threading
import time
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_TENANT_ID = os.environ.get("MEMORYHUB_DEFAULT_TENANT", "default")

@dataclass
class _SessionState:
    """Application session state bound to one FastMCP transport session."""

    user: dict[str, Any] | None
    expires_at: datetime
    ttl_seconds: int
    session_id: str | None = None
    default_driver_id: str | None = None


# FastMCP provides a stable session_id for each stateful MCP client session.
# Keying the in-process map by that ID isolates clients sharing one server
# process. This deployment runs one MCP process per pod; multi-process session
# sharing would require a shared session-state backend.
_sessions_by_mcp_session: dict[str, _SessionState] = {}
_sessions_lock = threading.RLock()
_SESSION_CLEANUP_MARKER = "_memoryhub_auth_cleanup_registered"

# Compatibility state for direct Python calls and legacy unit tests that invoke
# tools outside FastMCP. This process-global fallback is unsafe for concurrent
# MCP clients; real MCP requests must use a FastMCP context.
_current_session: dict[str, Any] | None = None
_legacy_fallback_warning_logged = False
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


def _get_active_context() -> Any | None:
    """Return the FastMCP context for this request, if one is active."""
    try:
        from fastmcp.server.dependencies import get_context

        return get_context()
    except (ImportError, RuntimeError):
        return None


def _mcp_session_key(ctx: Any | None = None) -> str | None:
    """Get the stable FastMCP session ID for the active request."""
    active_context = ctx if ctx is not None else _get_active_context()
    if active_context is None:
        return None
    try:
        session_id = active_context.session_id
    except (AttributeError, RuntimeError):
        return None
    return str(session_id) if session_id else None


def get_mcp_session_id(ctx: Any | None = None) -> str | None:
    """Return the active MCP transport session ID, if one is established."""
    return _mcp_session_key(ctx)


def _register_session_cleanup(ctx: Any | None, mcp_session_id: str) -> None:
    """Remove the binding on disconnect; TTL handles abrupt disconnects.

    FastMCP 3.4.2 has no public session-close callback, so this uses the
    session's private ``_exit_stack``. The registration-level lifecycle test
    protects this integration when the FastMCP dependency is upgraded.
    """
    if ctx is None:
        return
    try:
        session = ctx.session
        exit_stack = getattr(session, "_exit_stack", None)
    except (AttributeError, RuntimeError):
        exit_stack = None
        session = None
    if exit_stack is None:
        return

    with _sessions_lock:
        if getattr(session, _SESSION_CLEANUP_MARKER, False):
            return
        try:
            setattr(session, _SESSION_CLEANUP_MARKER, True)
            marker_set = True
        except (AttributeError, TypeError):
            # Keep cleanup functional for session objects that disallow
            # attributes; they cannot deduplicate callbacks across setters.
            marker_set = False

    async def cleanup() -> None:
        with _sessions_lock:
            _sessions_by_mcp_session.pop(mcp_session_id, None)
            if marker_set:
                try:
                    delattr(session, _SESSION_CLEANUP_MARKER)
                except AttributeError:
                    pass

    try:
        exit_stack.push_async_callback(cleanup)
    except Exception:
        if marker_set:
            with _sessions_lock:
                try:
                    delattr(session, _SESSION_CLEANUP_MARKER)
                except AttributeError:
                    pass
        raise


def _warn_legacy_fallback() -> None:
    """Warn once when process-global compatibility state is used."""
    global _legacy_fallback_warning_logged
    with _sessions_lock:
        if _legacy_fallback_warning_logged:
            return
        _legacy_fallback_warning_logged = True
    logger.warning(
        "Using process-global legacy session state without a FastMCP context; "
        "this compatibility path is for direct Python/test calls and is unsafe "
        "for concurrent MCP clients."
    )


def _configured_session_ttl_seconds() -> int:
    """Return the configured inactivity TTL for per-MCP-session metadata."""
    from memoryhub_core.config import AppSettings

    return AppSettings().session_ttl_seconds


def set_session_id(
    sid: str,
    ctx: Any | None = None,
    *,
    ttl_seconds: int | None = None,
) -> None:
    """Store the MemoryHub application session ID for this MCP session."""
    active_context = ctx if ctx is not None else _get_active_context()
    mcp_session_id = _mcp_session_key(active_context)
    if mcp_session_id is None:
        if active_context is None and ctx is None:
            _warn_legacy_fallback()
            global _session_id
            _session_id = sid
            return
        raise RuntimeError("An active MCP session is required to store session state.")
    ttl = ttl_seconds if ttl_seconds is not None else _configured_session_ttl_seconds()
    expires_at = datetime.now(UTC) + timedelta(seconds=ttl)
    with _sessions_lock:
        state = _sessions_by_mcp_session.get(mcp_session_id)
        if state is None:
            state = _SessionState(
                user=None,
                expires_at=expires_at,
                ttl_seconds=ttl,
            )
            _sessions_by_mcp_session[mcp_session_id] = state
        else:
            state.expires_at = expires_at
            state.ttl_seconds = ttl
        state.session_id = sid
    _register_session_cleanup(active_context, mcp_session_id)


def get_session_id(ctx: Any | None = None) -> str | None:
    """Return this MCP session's MemoryHub session ID, if registered."""
    active_context = ctx if ctx is not None else _get_active_context()
    mcp_session_id = _mcp_session_key(active_context)
    if mcp_session_id is None:
        return _session_id if active_context is None and ctx is None else None
    with _sessions_lock:
        state = _sessions_by_mcp_session.get(mcp_session_id)
        if state is None or datetime.now(UTC) >= state.expires_at:
            return None
        return state.session_id


def set_session(
    user: dict[str, Any],
    ttl_seconds: int = 3600,
    *,
    ctx: Any | None = None,
    session_id: str | None = None,
    default_driver_id: str | None = None,
) -> datetime:
    """Bind the authenticated user to this MCP session with an inactivity TTL."""
    active_context = ctx if ctx is not None else _get_active_context()
    mcp_session_id = _mcp_session_key(active_context)
    if mcp_session_id is None:
        if active_context is None and ctx is None:
            _warn_legacy_fallback()
            global _current_session, _session_expires_at, _session_ttl_seconds
            global _session_id, _default_driver_id
            _current_session = user
            _session_ttl_seconds = ttl_seconds
            _session_expires_at = datetime.now(UTC) + timedelta(seconds=ttl_seconds)
            _session_id = session_id
            _default_driver_id = default_driver_id
            return _session_expires_at
        raise RuntimeError(
            "An active MCP session is required to register an API-key session."
        )
    expires_at = datetime.now(UTC) + timedelta(seconds=ttl_seconds)
    state = _SessionState(
        # ConfigMap records are cached globally. Give each client its own
        # copy so membership updates for one session cannot mutate the cache
        # or another session's record.
        user=deepcopy(user),
        expires_at=expires_at,
        ttl_seconds=ttl_seconds,
        session_id=session_id,
        default_driver_id=default_driver_id,
    )
    with _sessions_lock:
        _sessions_by_mcp_session[mcp_session_id] = state
    _prune_expired_sessions(exclude_session_id=mcp_session_id)
    _register_session_cleanup(active_context, mcp_session_id)
    return expires_at


def _prune_expired_sessions(exclude_session_id: str | None = None) -> None:
    """Opportunistically discard expired bindings for other MCP sessions."""
    now = datetime.now(UTC)
    with _sessions_lock:
        expired_ids = [
            session_id
            for session_id, state in _sessions_by_mcp_session.items()
            if session_id != exclude_session_id and now >= state.expires_at
        ]
        for session_id in expired_ids:
            _sessions_by_mcp_session.pop(session_id, None)


def _get_session_state(ctx: Any | None = None) -> _SessionState | None:
    mcp_session_id = _mcp_session_key(ctx)
    if mcp_session_id is None:
        return None
    _prune_expired_sessions(exclude_session_id=mcp_session_id)
    with _sessions_lock:
        return _sessions_by_mcp_session.get(mcp_session_id)


def _extend_session(state: _SessionState) -> None:
    """Reset the session expiry on activity."""
    with _sessions_lock:
        state.expires_at = datetime.now(UTC) + timedelta(seconds=state.ttl_seconds)


def refresh_session_metadata(ctx: Any | None = None) -> None:
    """Extend metadata for a session with a successfully authenticated request.

    JWT-authenticated clients do not bind ``state.user`` because each request
    carries its own verified identity. Their session ID and default driver ID
    still need the same inactivity renewal as API-key session state.
    """
    active_context = ctx if ctx is not None else _get_active_context()
    state = _get_session_state(active_context)
    if state is None or datetime.now(UTC) >= state.expires_at:
        return
    _extend_session(state)


def _extend_legacy_session() -> None:
    """Auto-extend the no-context compatibility session."""
    global _session_expires_at
    if _session_expires_at is not None:
        _session_expires_at = datetime.now(UTC) + timedelta(seconds=_session_ttl_seconds)


def is_session_expired(ctx: Any | None = None) -> bool:
    """Return True if the active MCP session has expired or is unregistered."""
    active_context = ctx if ctx is not None else _get_active_context()
    if active_context is None and ctx is None:
        return _session_expires_at is None or datetime.now(UTC) >= _session_expires_at
    state = _get_session_state(active_context)
    return state is None or datetime.now(UTC) >= state.expires_at


def get_session_expiry(ctx: Any | None = None) -> dict[str, Any] | None:
    """Return TTL info for the active API-key session, if registered."""
    active_context = ctx if ctx is not None else _get_active_context()
    if active_context is None and ctx is None:
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
    state = _get_session_state(active_context)
    if state is None or state.user is None:
        return None
    now = datetime.now(UTC)
    remaining = max(0, int((state.expires_at - now).total_seconds()))
    return {
        "expires_at": state.expires_at.isoformat(),
        "remaining_seconds": remaining,
        "ttl_seconds": state.ttl_seconds,
        "expired": remaining == 0,
    }


def get_current_user(ctx: Any | None = None) -> dict[str, Any] | None:
    """Return the authenticated user bound to the active MCP session."""
    active_context = ctx if ctx is not None else _get_active_context()
    if active_context is None and ctx is None:
        if _current_session is None or is_session_expired():
            return None
        if _session_expires_at is not None:
            _extend_legacy_session()
        return _current_session
    state = _get_session_state(active_context)
    if state is None or state.user is None or datetime.now(UTC) >= state.expires_at:
        return None
    _extend_session(state)
    return state.user


def require_auth(ctx: Any | None = None) -> dict[str, Any]:
    """Return the current session user or raise a descriptive error."""
    active_context = ctx if ctx is not None else _get_active_context()
    if active_context is None and ctx is None:
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
        _extend_legacy_session()
        return _current_session
    state = _get_session_state(active_context)
    if state is None or state.user is None:
        raise RuntimeError(
            "No session registered. Call register_session(api_key=...) "
            "at the start of every conversation to authenticate."
        )
    if datetime.now(UTC) >= state.expires_at:
        raise RuntimeError(
            "Session expired. Call register_session(api_key=...) to "
            "re-authenticate. Sessions auto-extend on activity but expire "
            f"after {state.ttl_seconds} seconds of inactivity."
        )
    _extend_session(state)
    return state.user


def has_scope(user: dict[str, Any], scope: str) -> bool:
    """Return True if the user has access to the given scope."""
    return scope in user.get("scopes", [])


def set_default_driver_id(driver_id: str | None, ctx: Any | None = None) -> None:
    """Store a session-level default driver_id for actor/driver plumbing.

    When an agent registers a session on behalf of a human user, the human's
    identity is set here so every subsequent write correctly attributes the
    upstream driver without requiring per-call driver_id parameters.
    """
    active_context = ctx if ctx is not None else _get_active_context()
    mcp_session_id = _mcp_session_key(active_context)
    if mcp_session_id is None:
        if active_context is None and ctx is None:
            _warn_legacy_fallback()
            global _default_driver_id
            _default_driver_id = driver_id
            return
        raise RuntimeError("An active MCP session is required to store session state.")
    with _sessions_lock:
        state = _sessions_by_mcp_session.get(mcp_session_id)
        if state is None:
            ttl = _configured_session_ttl_seconds()
            state = _SessionState(
                user=None,
                expires_at=datetime.now(UTC) + timedelta(seconds=ttl),
                ttl_seconds=ttl,
            )
            _sessions_by_mcp_session[mcp_session_id] = state
        state.default_driver_id = driver_id
    _register_session_cleanup(active_context, mcp_session_id)


def get_default_driver_id(ctx: Any | None = None) -> str | None:
    """Return the session-level default driver_id, or None if expired/unset."""
    active_context = ctx if ctx is not None else _get_active_context()
    if active_context is None and ctx is None:
        if _session_expires_at is not None and datetime.now(UTC) > _session_expires_at:
            return None
        return _default_driver_id
    state = _get_session_state(active_context)
    if state is None or datetime.now(UTC) >= state.expires_at:
        return None
    return state.default_driver_id


def clear_session(ctx: Any | None = None) -> None:
    """Clear the active MCP session, or all state when called out of band.

    The no-context form is intended for test/process teardown. Runtime cleanup
    should pass the owning context so another client's state cannot be cleared.
    """
    active_context = ctx if ctx is not None else _get_active_context()
    mcp_session_id = _mcp_session_key(active_context)
    with _sessions_lock:
        if mcp_session_id is None and active_context is None and ctx is None:
            _sessions_by_mcp_session.clear()
            global _current_session, _session_expires_at, _session_ttl_seconds
            global _session_id, _default_driver_id
            _current_session = None
            _session_expires_at = None
            _session_ttl_seconds = 3600
            _session_id = None
            _default_driver_id = None
        elif mcp_session_id is None:
            return
        else:
            _sessions_by_mcp_session.pop(mcp_session_id, None)
