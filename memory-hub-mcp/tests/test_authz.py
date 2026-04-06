"""Tests for the authorization module (src.core.authz)."""

import pytest
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

from src.core.authz import (
    authorize_read,
    authorize_write,
    build_authorized_scopes,
    get_claims_from_context,
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
    memory = SimpleNamespace(scope=memory_scope, owner_id=memory_owner)
    assert authorize_read(claims, memory) == expected


def test_authorize_read_with_enum_scope():
    """authorize_read should handle MemoryScope enum values."""
    from memoryhub.models.schemas import MemoryScope

    memory = SimpleNamespace(scope=MemoryScope.USER, owner_id="alice")
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
    assert authorize_write(claims, scope, owner_id) == expected


def test_authorize_write_with_enum_scope():
    """authorize_write should handle MemoryScope enum values."""
    from memoryhub.models.schemas import MemoryScope

    claims = {"sub": "alice", "scopes": ["memory:write:user"]}
    assert authorize_write(claims, MemoryScope.USER, "alice") is True


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
        "name": "William Jackson",
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
