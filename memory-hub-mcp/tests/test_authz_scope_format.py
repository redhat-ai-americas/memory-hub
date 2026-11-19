"""Tests for scope format detection in get_claims_from_context session fallback.

Auth-service users have OAuth-format scopes (e.g. "memory:read") and should
not be run through _normalize_session_scopes.  ConfigMap users have tier
names (e.g. "user", "project") that need expansion.
"""

from unittest.mock import patch
from contextlib import nullcontext

import pytest

from src.core.authz import _normalize_session_scopes, get_claims_from_context


def _patch_no_jwt():
    """Context manager that disables the verified JWT resolution path."""
    return (
        patch("fastmcp.server.dependencies.get_access_token", return_value=None),
        nullcontext(),
    )


def test_oauth_scopes_not_normalized():
    """User with OAuth-format scopes (containing ':') should NOT be normalized."""
    session_user = {
        "user_id": "remote-bob",
        "name": "Bob Remote",
        "identity_type": "user",
        "tenant_id": "acme",
        "scopes": ["memory:read", "memory:write:user"],
    }

    p1, p2 = _patch_no_jwt()
    with p1, p2, patch("src.core.authz.get_current_user", return_value=session_user):
        claims = get_claims_from_context()

    # Scopes should be passed through verbatim
    assert claims["scopes"] == ["memory:read", "memory:write:user"]
    # Should NOT contain expanded tier scopes
    assert "memory:read:user" not in claims["scopes"]
    assert "memory:write:project" not in claims["scopes"]


def test_configmap_scopes_normalized():
    """User with tier-name scopes (no ':') should be expanded via _normalize_session_scopes."""
    session_user = {
        "user_id": "local-alice",
        "name": "Alice Local",
        "identity_type": "user",
        "scopes": ["user", "project"],
    }

    p1, p2 = _patch_no_jwt()
    with p1, p2, patch("src.core.authz.get_current_user", return_value=session_user):
        claims = get_claims_from_context()

    # Should be expanded
    assert "memory:read:user" in claims["scopes"]
    assert "memory:write:user" in claims["scopes"]
    assert "memory:read:project" in claims["scopes"]
    assert "memory:write:project" in claims["scopes"]
    # Should NOT have blanket scopes (only 2 tiers, not all 6)
    assert "memory:read" not in claims["scopes"]


def test_tenant_from_user_dict():
    """tenant_id should come from the user dict, not be hardcoded to 'default'."""
    session_user = {
        "user_id": "tenant-user",
        "name": "Tenant User",
        "identity_type": "user",
        "tenant_id": "acme-corp",
        "scopes": ["memory:read", "memory:write:user"],
    }

    p1, p2 = _patch_no_jwt()
    with p1, p2, patch("src.core.authz.get_current_user", return_value=session_user):
        claims = get_claims_from_context()

    assert claims["tenant_id"] == "acme-corp"


def test_tenant_defaults_when_missing():
    """ConfigMap users without tenant_id should get 'default'."""
    session_user = {
        "user_id": "legacy-user",
        "name": "Legacy",
        "identity_type": "user",
        "scopes": ["user"],
    }

    p1, p2 = _patch_no_jwt()
    with p1, p2, patch("src.core.authz.get_current_user", return_value=session_user):
        claims = get_claims_from_context()

    assert claims["tenant_id"] == "default"


def test_empty_scopes_not_treated_as_oauth():
    """Empty scopes list should go through normalization (no-op), not be treated as OAuth."""
    session_user = {
        "user_id": "empty-scopes",
        "name": "No Scopes",
        "identity_type": "user",
        "scopes": [],
    }

    p1, p2 = _patch_no_jwt()
    with p1, p2, patch("src.core.authz.get_current_user", return_value=session_user):
        claims = get_claims_from_context()

    # Empty input -> empty output from _normalize_session_scopes
    assert claims["scopes"] == []
