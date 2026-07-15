"""Shared authorization module for MemoryHub MCP.

Supports dual-auth: FastMCP JWT tokens (OAuth 2.1) and legacy session-based
API key authentication. Both paths produce a normalized claims dict that the
authorize_read / authorize_write helpers consume uniformly.
"""

import os

from src.core.logging import get_logger
from src.tools.auth import DEFAULT_TENANT_ID, get_current_user

log = get_logger("authz")

ALL_TIERS = ("user", "project", "campaign", "role", "organizational", "enterprise")

# Feature flags for scope isolation (issue #167). Default: enabled.
# Set to "false" to revert to the pre-isolation behavior (open access)
# while debugging or during phased rollout.
PROJECT_ISOLATION_ENABLED = os.environ.get("MEMORYHUB_PROJECT_ISOLATION_ENABLED", "true").lower() == "true"
ROLE_ISOLATION_ENABLED = os.environ.get("MEMORYHUB_ROLE_ISOLATION_ENABLED", "true").lower() == "true"


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
        scopes.append(f"threads:read:{tier}")
        scopes.append(f"threads:write:{tier}")
    if all(t in access_tiers for t in ALL_TIERS):
        scopes.extend(["memory:read", "memory:write", "threads:read", "threads:write"])
    return scopes


def _extract_jwt_from_headers() -> dict | None:
    """Extract and decode JWT from the HTTP Authorization header.

    Returns decoded claims dict, or None if no JWT is available.
    Decodes without signature verification — the transport layer
    (JWTVerifier) already validated the token.
    """
    try:
        from fastmcp.server.dependencies import get_http_request

        request = get_http_request()
        auth_header = request.headers.get("authorization", "")
        if not auth_header.lower().startswith("bearer "):
            return None
        token = auth_header.split(" ", 1)[1].strip()
        import jwt as pyjwt

        return pyjwt.decode(token, options={"verify_signature": False})
    except Exception:
        return None


def get_claims_from_context() -> dict:
    """Resolve caller identity from JWT or session fallback.

    Returns a normalized claims dict with sub, identity_type, tenant_id,
    and scopes.
    """
    # 1. Try FastMCP JWT path (get_access_token populated by auth middleware)
    try:
        from fastmcp.server.dependencies import get_access_token

        token = get_access_token()
    except Exception:
        token = None

    if token is not None:
        claims = {
            "sub": token.claims.get("sub", token.client_id),
            "identity_type": token.claims.get("identity_type", "user"),
            "tenant_id": token.claims.get("tenant_id", DEFAULT_TENANT_ID),
            "scopes": list(token.scopes),
            "project_memberships": token.claims.get("project_memberships", []),
        }
        log.debug("Resolved JWT identity via get_access_token: sub=%s", claims["sub"])
        return claims

    # 2. Try extracting JWT directly from HTTP Authorization header.
    #    JWTVerifier validates tokens at transport level but may not populate
    #    get_access_token() in all transport modes. Decode without verification
    #    since the transport already validated the signature.
    jwt_claims = _extract_jwt_from_headers()
    if jwt_claims is not None:
        scopes = jwt_claims.get("scopes", [])
        if isinstance(scopes, str):
            scopes = scopes.split()
        claims = {
            "sub": jwt_claims.get("sub", "unknown"),
            "identity_type": jwt_claims.get("identity_type", "user"),
            "tenant_id": jwt_claims.get("tenant_id", DEFAULT_TENANT_ID),
            "scopes": scopes,
            "project_memberships": jwt_claims.get("project_memberships", []),
        }
        log.debug("Resolved JWT identity via Authorization header: sub=%s", claims["sub"])
        return claims

    # 3. Fall back to session
    user = get_current_user()
    if user is not None:
        raw_scopes = user.get("scopes", [])
        # Auth-service users already have OAuth-format scopes (contain ':').
        # ConfigMap users have tier names that need expansion.
        if raw_scopes and any(":" in s for s in raw_scopes):
            scopes = raw_scopes
        else:
            scopes = _normalize_session_scopes(raw_scopes)
        claims = {
            "sub": user["user_id"],
            "identity_type": user.get("identity_type", "user"),
            "tenant_id": user.get("tenant_id", DEFAULT_TENANT_ID),
            "scopes": scopes,
            "project_memberships": user.get("project_memberships", []),
            "authorized_tenants": user.get("authorized_tenants"),
        }
        log.debug("Resolved session identity: sub=%s", claims["sub"])
        return claims

    # 4. No identity
    log.warning("No JWT or session identity available")
    raise AuthenticationError("Authentication required. Provide a JWT or call register_session.")


def authorize_read(
    claims: dict,
    memory,
    campaign_ids: set[str] | None = None,
    project_ids: set[str] | None = None,
    role_names: set[str] | None = None,
) -> bool:
    """Can this identity read this memory?"""
    # Tenant isolation: reject cross-tenant reads before any other check.
    # This is the most fundamental boundary -- a cross-tenant caller should
    # not even learn that the memory exists. Run BEFORE scope/owner checks
    # so a tenant mismatch short-circuits everything else, including blanket
    # "memory:read" scopes.
    if memory.tenant_id != claims.get("tenant_id", DEFAULT_TENANT_ID):
        return False

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
        if not PROJECT_ISOLATION_ENABLED:
            return True
        if project_ids is None:
            return False
        return memory.scope_id in project_ids
    if tier == "campaign":
        # Campaign memories are accessible when the caller's project is
        # enrolled in the campaign. The memory's owner_id holds the
        # campaign UUID. campaign_ids is pre-resolved by the tool layer.
        if campaign_ids is None:
            return False
        return memory.owner_id in campaign_ids
    if tier == "role":
        if not ROLE_ISOLATION_ENABLED:
            return True
        if role_names is None:
            return False
        return memory.scope_id in role_names
    return False


def authorize_write(
    claims: dict,
    scope: str,
    owner_id: str,
    tenant_id: str,
    campaign_ids: set[str] | None = None,
    scope_id: str | None = None,
    project_ids: set[str] | None = None,
    role_names: set[str] | None = None,
) -> bool:
    """Can this identity write a memory at this scope for this owner in this tenant?"""
    # Tenant isolation: reject cross-tenant writes before any other check.
    # resolve_tenant() already validated cross-tenant access via
    # authorized_tenants; honour that decision here.
    own_tenant = claims.get("tenant_id", DEFAULT_TENANT_ID)
    if tenant_id != own_tenant:
        authorized = claims.get("authorized_tenants")
        if not authorized or tenant_id not in authorized:
            return False

    scopes = claims.get("scopes", [])
    if hasattr(scope, "value"):
        scope = scope.value

    if f"memory:write:{scope}" not in scopes and "memory:write" not in scopes:
        return False
    if scope == "user":
        if owner_id == claims["sub"]:
            return True
        # OBO: service agents can write to any user's scope (#284)
        return claims.get("identity_type") == "service"
    if scope == "enterprise":
        return False  # always rejected; HITL approval flow bypasses
    if scope == "organizational":
        return claims.get("identity_type") == "service"
    if scope == "role":
        if claims.get("identity_type") != "service":
            return False
        if not ROLE_ISOLATION_ENABLED:
            return True
        if role_names is None:
            return False
        return scope_id in role_names
    if scope == "project":
        if not PROJECT_ISOLATION_ENABLED:
            return True
        # OBO: service agents bypass project membership checks (#284)
        if claims.get("identity_type") == "service":
            return True
        if project_ids is None:
            return False
        if scope_id is None:
            return False
        return scope_id in project_ids
    if scope == "campaign":
        # Campaign writes are lower friction than org writes — no curator
        # review required. Access check: caller's project must be enrolled.
        if campaign_ids is None:
            return False
        return owner_id in campaign_ids
    return False


def build_authorized_scopes(claims: dict) -> dict[str, str | list[str] | None]:
    """Build scope visibility filter from claims for search queries.

    Returns a dict mapping scope names to required owner_id values:
      - ``str``: exact owner_id match (user tier)
      - ``list[str]``: set of allowed scope_ids (project tier, when
        project_memberships are present in claims)
      - ``None``: no owner filter (open read for that tier)

    For the project tier, when the caller has project read access and
    project_memberships are present in claims, the value is the list
    of project IDs the caller belongs to. When memberships are empty,
    the project tier is omitted entirely (no project memories visible).

    NOTE: This function does NOT include the tenant_id filter. Service-layer
    callers must combine the result of this function with `get_tenant_filter`
    to apply tenant isolation as a separate SQL predicate.
    """
    scopes = claims.get("scopes", [])
    caller_id = claims["sub"]
    result: dict[str, str | list[str] | None] = {}

    has_blanket_read = "memory:read" in scopes

    for tier in ALL_TIERS:
        if has_blanket_read or f"memory:read:{tier}" in scopes:
            if tier == "user":
                result[tier] = caller_id
            elif tier == "project" and PROJECT_ISOLATION_ENABLED:
                # When project isolation is on, use claims-based membership
                # to restrict project visibility. Empty membership = no
                # project memories visible (tier omitted from result).
                memberships = claims.get("project_memberships", [])
                if memberships:
                    result[tier] = list(memberships)
                # else: omit project tier entirely
            else:
                result[tier] = None

    return result


def get_tenant_filter(claims: dict) -> str:
    """Return the tenant_id that search/read queries must filter on.

    Returns the caller's tenant from claims, falling back to "default" for
    legacy session-based callers and tokens that predate the tenant_id claim.
    Service-layer callers should apply this as a SQL predicate alongside the
    scope filters from `build_authorized_scopes`:

        scope_filters = build_authorized_scopes(claims)
        tenant = get_tenant_filter(claims)
        # WHERE tenant_id = :tenant AND (<scope predicates>)

    Phase 2 introduces this helper; Phase 4 wires it into the read/search
    service paths.
    """
    return claims.get("tenant_id", DEFAULT_TENANT_ID)


def resolve_tenant(claims: dict, override: str | None = None) -> str:
    """Return the effective tenant for this request.

    When *override* is provided and the caller is authorized for that
    tenant, it takes precedence over the session/claims tenant. When
    omitted (or matches the caller's own tenant), falls back to the
    claims tenant.

    Phase 1: callers may only use their own tenant.
    Phase 2: ``authorized_tenants`` in claims enables cross-tenant access.
    """
    own_tenant = claims.get("tenant_id", DEFAULT_TENANT_ID)
    if override is None or override == own_tenant:
        return own_tenant
    authorized = claims.get("authorized_tenants")
    if authorized and override in authorized:
        return override
    from fastmcp.exceptions import ToolError
    raise ToolError(
        f"Not authorized for tenant '{override}'. "
        f"Your session is scoped to tenant '{own_tenant}'."
    )


def authorize_thread_read(
    claims: dict,
    thread,
    project_ids: set[str] | None = None,
) -> bool:
    """Can this identity read this conversation thread?

    Thread owner and listed participants always have read access.
    Scope-level threads:read permissions provide broader access.
    """
    # Tenant isolation first
    if thread.tenant_id != claims.get("tenant_id", DEFAULT_TENANT_ID):
        return False

    caller_id = claims["sub"]

    # Owner always has access
    if thread.owner_id == caller_id:
        return True

    # Participants have access
    participant_ids = thread.participant_ids or []
    if caller_id in participant_ids:
        return True

    # Scope-level permission check
    scopes = claims.get("scopes", [])
    tier = thread.scope
    if hasattr(tier, "value"):
        tier = tier.value

    if f"threads:read:{tier}" not in scopes and "threads:read" not in scopes:
        return False

    # For user-scoped threads, only owner (already checked above)
    if tier == "user":
        return False
    # For project-scoped, check project membership
    if tier == "project":
        if not PROJECT_ISOLATION_ENABLED:
            return True
        if project_ids is None:
            return False
        return thread.scope_id in project_ids
    # enterprise/organizational are open read
    return tier in ("enterprise", "organizational")


def authorize_thread_write(
    claims: dict,
    thread,
    project_ids: set[str] | None = None,
) -> bool:
    """Can this identity write (append) to this conversation thread?

    Thread owner always has write access. Listed participants have write
    access by default (can be narrowed by participant_access). Scope-level
    threads:write permissions provide broader access.
    """
    # Tenant isolation first
    if thread.tenant_id != claims.get("tenant_id", DEFAULT_TENANT_ID):
        return False

    caller_id = claims["sub"]

    # Owner always has access
    if thread.owner_id == caller_id:
        return True

    # Check participant_access for explicit access level
    participant_access = thread.participant_access or {}
    if caller_id in participant_access:
        level = participant_access[caller_id]
        return level in ("write", "admin")

    # Participants without explicit access level default to write
    participant_ids = thread.participant_ids or []
    if caller_id in participant_ids:
        return True

    # Scope-level permission check
    scopes = claims.get("scopes", [])
    tier = thread.scope
    if hasattr(tier, "value"):
        tier = tier.value

    if f"threads:write:{tier}" not in scopes and "threads:write" not in scopes:
        return False

    if tier == "user":
        return False
    if tier == "project":
        if not PROJECT_ISOLATION_ENABLED:
            return True
        if project_ids is None:
            return False
        return thread.scope_id in project_ids
    if tier in ("enterprise", "organizational"):
        return claims.get("identity_type") == "service"

    return False


def authorize_thread_admin(
    claims: dict,
    thread,
) -> bool:
    """Can this identity perform admin operations (archive, modify participants)?

    Only thread owner or holders of threads:admin scope permission.
    """
    if thread.tenant_id != claims.get("tenant_id", DEFAULT_TENANT_ID):
        return False

    caller_id = claims["sub"]

    # Owner always has admin
    if thread.owner_id == caller_id:
        return True

    # Check participant_access for admin grant
    participant_access = thread.participant_access or {}
    if caller_id in participant_access:
        return participant_access[caller_id] == "admin"

    # Scope-level admin check
    scopes = claims.get("scopes", [])
    tier = thread.scope
    if hasattr(tier, "value"):
        tier = tier.value

    return f"threads:admin:{tier}" in scopes or "threads:admin" in scopes
