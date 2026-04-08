"""Tests for the authorization module (src.core.authz)."""

import pytest
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

from src.core.authz import (
    authorize_read,
    authorize_write,
    build_authorized_scopes,
    get_claims_from_context,
    get_tenant_filter,
    AuthenticationError,
)


# -- authorize_read ----------------------------------------------------------

@pytest.mark.parametrize("claims,memory_scope,memory_owner,expected", [
    ({"sub": "alice", "scopes": ["memory:read"]}, "user", "alice", True),
    ({"sub": "alice", "scopes": ["memory:read"]}, "user", "bob", False),
    ({"sub": "alice", "scopes": ["memory:read"]}, "organizational", "org-1", True),
    ({"sub": "alice", "scopes": ["memory:read"]}, "enterprise", "global", True),
    ({"sub": "alice", "scopes": ["memory:read"]}, "project", "proj-1", True),
    ({"sub": "alice", "scopes": ["memory:read"]}, "role", "admin", True),
    ({"sub": "alice", "scopes": []}, "user", "alice", False),
    ({"sub": "alice", "scopes": ["memory:read:user"]}, "user", "alice", True),
    ({"sub": "alice", "scopes": ["memory:read:user"]}, "organizational", "org-1", False),
    ({"sub": "alice", "scopes": ["memory:read:organizational"]}, "organizational", "org-1", True),
    ({"sub": "alice", "scopes": []}, "organizational", "org-1", False),
    ({"sub": "alice", "scopes": ["memory:write"]}, "user", "alice", False),
])
def test_authorize_read(claims, memory_scope, memory_owner, expected):
    # Existing pre-tenant tests assume default-tenant memories and
    # default-tenant claims (claims without tenant_id fall back to "default").
    memory = SimpleNamespace(
        scope=memory_scope, owner_id=memory_owner, tenant_id="default"
    )
    assert authorize_read(claims, memory) == expected


def test_authorize_read_with_enum_scope():
    """authorize_read should handle MemoryScope enum values."""
    from memoryhub_core.models.schemas import MemoryScope

    memory = SimpleNamespace(
        scope=MemoryScope.USER, owner_id="alice", tenant_id="default"
    )
    claims = {"sub": "alice", "scopes": ["memory:read"]}
    assert authorize_read(claims, memory) is True


# -- authorize_write ---------------------------------------------------------

@pytest.mark.parametrize("claims,scope,owner_id,expected", [
    ({"sub": "alice", "scopes": ["memory:write:user"]}, "user", "alice", True),
    ({"sub": "alice", "scopes": ["memory:write:user"]}, "user", "bob", False),
    ({"sub": "alice", "scopes": ["memory:write"]}, "user", "alice", True),
    ({"sub": "alice", "scopes": ["memory:write"]}, "enterprise", "alice", False),
    ({"sub": "curator", "identity_type": "service", "scopes": ["memory:write"]}, "organizational", "org-1", True),
    ({"sub": "alice", "identity_type": "user", "scopes": ["memory:write"]}, "organizational", "org-1", False),
    ({"sub": "alice", "scopes": ["memory:write"]}, "organizational", "org-1", False),
    ({"sub": "curator", "identity_type": "service", "scopes": ["memory:write"]}, "role", "admin", True),
    ({"sub": "alice", "scopes": ["memory:write"]}, "project", "proj-1", True),
    ({"sub": "alice", "scopes": []}, "user", "alice", False),
    ({"sub": "curator", "identity_type": "service", "scopes": ["memory:write:user"]}, "organizational", "org-1", False),
])
def test_authorize_write(claims, scope, owner_id, expected):
    # Existing pre-tenant tests assume the default tenant on both sides.
    assert authorize_write(claims, scope, owner_id, "default") == expected


def test_authorize_write_with_enum_scope():
    """authorize_write should handle MemoryScope enum values."""
    from memoryhub_core.models.schemas import MemoryScope

    claims = {"sub": "alice", "scopes": ["memory:write:user"]}
    assert authorize_write(claims, MemoryScope.USER, "alice", "default") is True


# -- Tenant isolation (issue #46, Phase 2) -----------------------------------

def test_authorize_read_rejects_cross_tenant():
    """A caller in tenant_b cannot read a memory in tenant_a, even if scope
    and owner would otherwise allow it."""
    memory = SimpleNamespace(
        scope="user", owner_id="alice", tenant_id="tenant_a"
    )
    claims = {
        "sub": "alice",
        "tenant_id": "tenant_b",
        "scopes": ["memory:read:user"],
    }
    assert authorize_read(claims, memory) is False


def test_authorize_read_allows_same_tenant():
    """Matching tenant_id plus a valid scope/owner combo passes."""
    memory = SimpleNamespace(
        scope="user", owner_id="alice", tenant_id="tenant_a"
    )
    claims = {
        "sub": "alice",
        "tenant_id": "tenant_a",
        "scopes": ["memory:read:user"],
    }
    assert authorize_read(claims, memory) is True


def test_authorize_read_rejects_cross_tenant_even_with_blanket_scope():
    """The tenant check runs BEFORE the scope check, so a blanket
    'memory:read' scope cannot bypass tenant isolation."""
    memory = SimpleNamespace(
        scope="organizational", owner_id="org-1", tenant_id="tenant_a"
    )
    claims = {
        "sub": "service-bot",
        "tenant_id": "tenant_b",
        "identity_type": "service",
        "scopes": ["memory:read"],
    }
    assert authorize_read(claims, memory) is False


def test_authorize_write_rejects_cross_tenant():
    """Writing to a tenant other than the caller's is rejected even when
    scope/owner are otherwise valid."""
    claims = {
        "sub": "alice",
        "tenant_id": "tenant_a",
        "scopes": ["memory:write:user"],
    }
    assert (
        authorize_write(claims, "user", "alice", "tenant_b") is False
    )


def test_authorize_write_allows_same_tenant():
    """Matching tenant plus valid scope/owner passes."""
    claims = {
        "sub": "alice",
        "tenant_id": "tenant_a",
        "scopes": ["memory:write:user"],
    }
    assert (
        authorize_write(claims, "user", "alice", "tenant_a") is True
    )


def test_authorize_write_rejects_cross_tenant_even_with_blanket_scope():
    """A blanket 'memory:write' scope cannot bypass tenant isolation, even
    for service identities writing to organizational scope."""
    claims = {
        "sub": "curator",
        "tenant_id": "tenant_a",
        "identity_type": "service",
        "scopes": ["memory:write"],
    }
    assert (
        authorize_write(claims, "organizational", "org-1", "tenant_b") is False
    )


def test_get_tenant_filter_reads_from_claims():
    """get_tenant_filter returns the caller's tenant_id when present."""
    claims = {"sub": "alice", "tenant_id": "tenant_a", "scopes": []}
    assert get_tenant_filter(claims) == "tenant_a"


def test_get_tenant_filter_falls_back_to_default():
    """Claims without tenant_id (legacy session callers) get the default tenant."""
    claims = {"sub": "alice", "scopes": []}
    assert get_tenant_filter(claims) == "default"


# -- build_authorized_scopes -------------------------------------------------

def test_build_authorized_scopes_blanket_read():
    claims = {"sub": "alice", "scopes": ["memory:read"]}
    result = build_authorized_scopes(claims)
    assert result["user"] == "alice"
    assert result["organizational"] is None
    assert result["enterprise"] is None
    assert result["project"] is None
    assert result["role"] is None


def test_build_authorized_scopes_user_only():
    claims = {"sub": "alice", "scopes": ["memory:read:user"]}
    result = build_authorized_scopes(claims)
    assert result == {"user": "alice"}


def test_build_authorized_scopes_no_read():
    claims = {"sub": "alice", "scopes": ["memory:write"]}
    result = build_authorized_scopes(claims)
    assert result == {}


# -- get_claims_from_context --------------------------------------------------

def test_get_claims_jwt_path():
    """When get_access_token returns a token, extract claims from it."""
    mock_token = MagicMock()
    mock_token.claims = {"sub": "wjackson", "identity_type": "user", "tenant_id": "default"}
    mock_token.scopes = ["memory:read", "memory:write:user"]
    mock_token.client_id = "wjackson"

    with patch("fastmcp.server.dependencies.get_access_token", return_value=mock_token):
        claims = get_claims_from_context()

    assert claims["sub"] == "wjackson"
    assert claims["identity_type"] == "user"
    assert "memory:read" in claims["scopes"]
    assert "memory:write:user" in claims["scopes"]


def test_get_claims_header_extraction():
    """When get_access_token returns None, extract JWT from Authorization header."""
    import jwt as pyjwt
    test_token = pyjwt.encode(
        {"sub": "curator", "identity_type": "service", "tenant_id": "default", "scopes": ["memory:read"]},
        "test-key-not-a-real-secret",
        algorithm="HS256",
    )
    mock_request = MagicMock()
    mock_request.headers = {"authorization": f"Bearer {test_token}"}

    with patch("fastmcp.server.dependencies.get_access_token", return_value=None), \
         patch("fastmcp.server.dependencies.get_http_request", return_value=mock_request):
        claims = get_claims_from_context()

    assert claims["sub"] == "curator"
    assert claims["identity_type"] == "service"
    assert "memory:read" in claims["scopes"]


def test_get_claims_session_fallback():
    """When no JWT via either path, fall back to session-based auth."""
    session_user = {
        "user_id": "wjackson",
        "name": "Wes Jackson",
        "scopes": ["user", "project", "role", "organizational", "enterprise"],
        "identity_type": "user",
    }

    with patch("fastmcp.server.dependencies.get_access_token", return_value=None), \
         patch("src.core.authz._extract_jwt_from_headers", return_value=None), \
         patch("src.core.authz.get_current_user", return_value=session_user):
        claims = get_claims_from_context()

    assert claims["sub"] == "wjackson"
    assert claims["identity_type"] == "user"
    assert claims["tenant_id"] == "default"
    assert "memory:read" in claims["scopes"]
    assert "memory:write" in claims["scopes"]
    assert "memory:read:user" in claims["scopes"]
    assert "memory:write:user" in claims["scopes"]


def test_get_claims_session_partial_scopes():
    """Session user with limited tiers gets limited operational scopes."""
    session_user = {
        "user_id": "limited",
        "name": "Limited User",
        "scopes": ["user"],
        "identity_type": "user",
    }

    with patch("fastmcp.server.dependencies.get_access_token", return_value=None), \
         patch("src.core.authz._extract_jwt_from_headers", return_value=None), \
         patch("src.core.authz.get_current_user", return_value=session_user):
        claims = get_claims_from_context()

    assert "memory:read:user" in claims["scopes"]
    assert "memory:write:user" in claims["scopes"]
    assert "memory:read" not in claims["scopes"]
    assert "memory:write" not in claims["scopes"]
    assert "memory:read:organizational" not in claims["scopes"]


def test_get_claims_no_identity():
    """When neither JWT nor session exists, raise AuthenticationError."""
    with patch("fastmcp.server.dependencies.get_access_token", return_value=None), \
         patch("src.core.authz._extract_jwt_from_headers", return_value=None), \
         patch("src.core.authz.get_current_user", return_value=None):
        with pytest.raises(AuthenticationError):
            get_claims_from_context()
