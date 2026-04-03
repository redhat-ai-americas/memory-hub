"""Session-based API key authentication for MemoryHub MCP.

Users call register_session(api_key=...) once at the start of a conversation.
The authenticated identity is stored in a module-level variable for that
process/session and used automatically by tools that need an owner identity.

User records are loaded from MEMORYHUB_USERS_FILE (path to JSON) or
MEMORYHUB_USERS_JSON (inline JSON string), falling back to
/config/users.json for OpenShift (mounted from the memoryhub-users ConfigMap).
"""

import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

# Module-level session state (one session per MCP process/connection).
_current_session: dict[str, Any] | None = None

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


def set_session(user: dict[str, Any]) -> None:
    """Store the authenticated user for this session."""
    global _current_session
    _current_session = user


def get_current_user() -> dict[str, Any] | None:
    """Return the currently authenticated user, or None if not registered."""
    return _current_session


def require_auth() -> dict[str, Any]:
    """Return the current user or raise a descriptive error.

    Raises:
        RuntimeError: If no session has been registered.
    """
    user = get_current_user()
    if user is None:
        raise RuntimeError(
            "No session registered. Call register_session(api_key=...) "
            "at the start of every conversation to authenticate."
        )
    return user


def has_scope(user: dict[str, Any], scope: str) -> bool:
    """Return True if the user has access to the given scope."""
    return scope in user.get("scopes", [])
