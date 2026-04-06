"""Shared authorization module for MemoryHub MCP.

Supports dual-auth: FastMCP JWT tokens (OAuth 2.1) and legacy session-based
API key authentication. Both paths produce a normalized claims dict that the
authorize_read / authorize_write helpers consume uniformly.
"""

from src.core.logging import get_logger
from src.tools.auth import get_current_user

log = get_logger("authz")

ALL_TIERS = ("user", "project", "role", "organizational", "enterprise")


class AuthenticationError(Exception):
    """No identity available (neither JWT nor session)."""


class AuthorizationError(Exception):
    """Identity exists but lacks permission."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _normalize_session_scopes(access_tiers: list[str]) -> list[str]:
    """Convert access-tier names to operational scopes."""
    scopes: list[str] = []
    for tier in access_tiers:
        scopes.append(f"memory:read:{tier}")
        scopes.append(f"memory:write:{tier}")
    if all(t in access_tiers for t in ALL_TIERS):
        scopes.extend(["memory:read", "memory:write"])
    return scopes


def get_claims_from_context() -> dict:
    """Resolve caller identity from JWT or session fallback.

    Returns a normalized claims dict with sub, identity_type, tenant_id,
    and scopes.
    """
    # 1. Try FastMCP JWT path
    try:
        from fastmcp.server.dependencies import get_access_token
        token = get_access_token()
    except Exception:
        token = None

    if token is not None:
        claims = {
            "sub": token.claims.get("sub", token.client_id),
            "identity_type": token.claims.get("identity_type", "user"),
            "tenant_id": token.claims.get("tenant_id", "default"),
            "scopes": list(token.scopes),
        }
        log.debug("Resolved JWT identity: sub=%s", claims["sub"])
        return claims

    # 2. Fall back to session
    user = get_current_user()
    if user is not None:
        access_tiers = user.get("scopes", [])
        claims = {
            "sub": user["user_id"],
            "identity_type": user.get("identity_type", "user"),
            "tenant_id": "default",
            "scopes": _normalize_session_scopes(access_tiers),
        }
        log.debug("Resolved session identity: sub=%s", claims["sub"])
        return claims

    # 3. No identity
    log.warning("No JWT or session identity available")
    raise AuthenticationError(
        "Authentication required. Provide a JWT or call register_session."
    )


def authorize_read(claims: dict, memory) -> bool:
    """Can this identity read this memory?"""
    scopes = claims.get("scopes", [])
    tier = memory.scope
    if hasattr(tier, "value"):
        tier = tier.value

    if f"memory:read:{tier}" not in scopes and "memory:read" not in scopes:
        return False

    if tier == "user":
        return memory.owner_id == claims["sub"]
    if tier in ("enterprise", "organizational"):
        return True
    if tier == "project":
        return True  # project membership check TBD
    if tier == "role":
        return True  # role matching TBD
    return False


def authorize_write(claims: dict, scope: str, owner_id: str) -> bool:
    """Can this identity write a memory at this scope for this owner?"""
    scopes = claims.get("scopes", [])
    if hasattr(scope, "value"):
        scope = scope.value

    if f"memory:write:{scope}" not in scopes and "memory:write" not in scopes:
        return False
    if scope == "user":
        return owner_id == claims["sub"]
    if scope == "enterprise":
        return False  # always rejected; HITL approval flow bypasses
    if scope in ("organizational", "role"):
        return claims.get("identity_type") == "service"
    if scope == "project":
        return True  # project membership check TBD
    return False


def build_authorized_scopes(claims: dict) -> dict[str, str | None]:
    """Build scope visibility filter from claims for search queries.

    Returns a dict mapping scope names to required owner_id values.
    None means no owner filter (open read for that tier).
    """
    scopes = claims.get("scopes", [])
    caller_id = claims["sub"]
    result: dict[str, str | None] = {}

    has_blanket_read = "memory:read" in scopes

    for tier in ALL_TIERS:
        if has_blanket_read or f"memory:read:{tier}" in scopes:
            if tier == "user":
                result[tier] = caller_id
            else:
                result[tier] = None

    return result
