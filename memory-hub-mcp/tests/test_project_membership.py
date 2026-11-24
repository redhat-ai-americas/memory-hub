"""Tests for project membership claims pipeline (issue #64).

Verifies that project_memberships flows through the claims pipeline:
  ConfigMap/DB -> session user dict -> get_claims_from_context() ->
  build_authorized_scopes() -> _build_search_filters()
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.core.authz import (
    AuthenticationError,
    authorize_read,
    authorize_write,
    build_authorized_scopes,
    get_claims_from_context,
)


# -- build_authorized_scopes with project memberships -----------------------


class TestBuildAuthorizedScopesProjectMembership:
    """build_authorized_scopes uses claims-based project_memberships."""

    def test_includes_project_ids_from_claims(self):
        """Project tier carries the membership list when present."""
        claims = {
            "sub": "alice",
            "scopes": ["memory:read"],
            "project_memberships": ["proj-1", "proj-2"],
        }
        result = build_authorized_scopes(claims)
        assert "project" in result
        assert sorted(result["project"]) == ["proj-1", "proj-2"]

    def test_empty_membership_omits_project_tier(self):
        """Empty project_memberships means no project memories visible."""
        claims = {
            "sub": "alice",
            "scopes": ["memory:read"],
            "project_memberships": [],
        }
        result = build_authorized_scopes(claims)
        assert "project" not in result

    def test_missing_membership_key_omits_project_tier(self):
        """Missing project_memberships key treated as empty."""
        claims = {
            "sub": "alice",
            "scopes": ["memory:read"],
        }
        result = build_authorized_scopes(claims)
        # With PROJECT_ISOLATION_ENABLED=True (default), no memberships
        # means no project tier. This test verifies the key-missing case.
        assert "project" not in result

    def test_project_specific_scope_with_memberships(self):
        """memory:read:project scope respects membership filtering."""
        claims = {
            "sub": "alice",
            "scopes": ["memory:read:project"],
            "project_memberships": ["my-proj"],
        }
        result = build_authorized_scopes(claims)
        assert result == {"project": ["my-proj"]}

    def test_project_with_isolation_disabled(self):
        """When isolation is off, project tier returns None (no filter)."""
        claims = {
            "sub": "alice",
            "scopes": ["memory:read"],
            "project_memberships": ["proj-1"],
        }
        with patch("src.core.authz.PROJECT_ISOLATION_ENABLED", False):
            result = build_authorized_scopes(claims)
        assert result["project"] is None

    def test_other_tiers_unaffected(self):
        """Non-project tiers are unaffected by project_memberships."""
        claims = {
            "sub": "alice",
            "scopes": ["memory:read"],
            "project_memberships": ["proj-1"],
        }
        result = build_authorized_scopes(claims)
        assert result["user"] == "alice"
        assert result["organizational"] is None
        assert result["enterprise"] is None

    def test_blanket_read_includes_project_with_memberships(self):
        """Blanket memory:read includes project tier when memberships exist."""
        claims = {
            "sub": "alice",
            "scopes": ["memory:read"],
            "project_memberships": ["proj-a", "proj-b", "proj-c"],
        }
        result = build_authorized_scopes(claims)
        assert "project" in result
        assert sorted(result["project"]) == ["proj-a", "proj-b", "proj-c"]

    def test_no_read_scope_excludes_project(self):
        """No read scope means no project tier regardless of memberships."""
        claims = {
            "sub": "alice",
            "scopes": ["memory:write"],
            "project_memberships": ["proj-1"],
        }
        result = build_authorized_scopes(claims)
        assert "project" not in result


# -- get_claims_from_context extracts project_memberships -------------------


class TestClaimsIncludeProjectMemberships:
    """get_claims_from_context populates project_memberships from session."""

    def test_session_fallback_includes_memberships(self):
        """Session user dict with project_memberships flows into claims."""
        user = {
            "user_id": "alice",
            "name": "Alice",
            "scopes": ["user", "project"],
            "project_memberships": ["proj-1", "proj-2"],
        }
        with (
            patch("fastmcp.server.dependencies.get_access_token", return_value=None),
            patch("src.core.authz.get_current_user", return_value=user),
        ):
            claims = get_claims_from_context()

        assert claims["project_memberships"] == ["proj-1", "proj-2"]
        assert claims["sub"] == "alice"

    def test_session_fallback_empty_memberships(self):
        """Session user without project_memberships defaults to empty list."""
        user = {
            "user_id": "bob",
            "name": "Bob",
            "scopes": ["user"],
        }
        with (
            patch("fastmcp.server.dependencies.get_access_token", return_value=None),
            patch("src.core.authz.get_current_user", return_value=user),
        ):
            claims = get_claims_from_context()

        assert claims["project_memberships"] == []

    def test_jwt_path_includes_memberships(self):
        """JWT token with project_memberships flows into claims."""
        token = MagicMock()
        token.claims = {
            "sub": "alice",
            "tenant_id": "default",
            "project_memberships": ["jwt-proj-1"],
        }
        token.client_id = "alice"
        token.scopes = ["memory:read"]

        with patch("fastmcp.server.dependencies.get_access_token", return_value=token):
            claims = get_claims_from_context()

        assert claims["project_memberships"] == ["jwt-proj-1"]

    def test_jwt_path_missing_memberships(self):
        """JWT token without project_memberships defaults to empty list."""
        token = MagicMock()
        token.claims = {"sub": "alice", "tenant_id": "default"}
        token.client_id = "alice"
        token.scopes = ["memory:read"]

        with patch("fastmcp.server.dependencies.get_access_token", return_value=token):
            claims = get_claims_from_context()

        assert claims["project_memberships"] == []

    def test_header_jwt_without_verifier_is_ignored(self):
        """An unverified header cannot supply project memberships."""
        with (
            patch("fastmcp.server.dependencies.get_access_token", return_value=None),
            patch("src.core.authz.get_current_user", return_value=None),
            pytest.raises(AuthenticationError),
        ):
            get_claims_from_context()


# -- authorize_read/write with project memberships -------------------------


class TestAuthorizeWithMemberships:
    """authorize_read/write project checks work with membership-aware claims."""

    def test_read_project_member_allowed(self):
        """Member of the project can read its memories."""
        memory = SimpleNamespace(
            scope="project",
            owner_id="alice",
            scope_id="proj-1",
            tenant_id="default",
        )
        claims = {
            "sub": "alice",
            "scopes": ["memory:read"],
            "project_memberships": ["proj-1", "proj-2"],
        }
        assert authorize_read(claims, memory, project_ids={"proj-1", "proj-2"}) is True

    def test_read_project_non_member_denied(self):
        """Non-member cannot read project memories."""
        memory = SimpleNamespace(
            scope="project",
            owner_id="alice",
            scope_id="proj-secret",
            tenant_id="default",
        )
        claims = {
            "sub": "alice",
            "scopes": ["memory:read"],
            "project_memberships": ["proj-1"],
        }
        assert authorize_read(claims, memory, project_ids={"proj-1"}) is False

    def test_write_project_member_allowed(self):
        """Member can write to their project."""
        claims = {
            "sub": "alice",
            "scopes": ["memory:write"],
            "project_memberships": ["proj-1"],
        }
        assert authorize_write(
            claims, "project", "alice", "default",
            project_ids={"proj-1"}, scope_id="proj-1",
        ) is True

    def test_write_project_non_member_denied(self):
        """Non-member cannot write to a project."""
        claims = {
            "sub": "alice",
            "scopes": ["memory:write"],
            "project_memberships": ["proj-1"],
        }
        assert authorize_write(
            claims, "project", "alice", "default",
            project_ids={"proj-1"}, scope_id="proj-other",
        ) is False


# -- End-to-end: claims -> build_authorized_scopes --------------------------


class TestClaimsToBuildAuthorizedScopes:
    """Integration: session claims flow through to build_authorized_scopes."""

    def test_session_with_memberships_produces_scoped_project(self):
        """Session user with memberships -> claims -> authorized_scopes with project list."""
        user = {
            "user_id": "alice",
            "name": "Alice",
            "scopes": ["user", "project"],
            "project_memberships": ["my-proj"],
        }
        with (
            patch("fastmcp.server.dependencies.get_access_token", return_value=None),
            patch("src.core.authz.get_current_user", return_value=user),
        ):
            claims = get_claims_from_context()

        scopes = build_authorized_scopes(claims)
        assert "project" in scopes
        assert scopes["project"] == ["my-proj"]

    def test_session_without_memberships_omits_project(self):
        """Session user without memberships -> claims -> no project tier."""
        user = {
            "user_id": "alice",
            "name": "Alice",
            "scopes": ["user", "project"],
            "project_memberships": [],
        }
        with (
            patch("fastmcp.server.dependencies.get_access_token", return_value=None),
            patch("src.core.authz.get_current_user", return_value=user),
        ):
            claims = get_claims_from_context()

        scopes = build_authorized_scopes(claims)
        assert "project" not in scopes
        # But user tier is present
        assert scopes["user"] == "alice"
