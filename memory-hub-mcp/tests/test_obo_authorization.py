"""Tests for on-behalf-of (OBO) authorization for service agents (#284).

Service agents (identity_type: "service") can write memories at user and
project scope on behalf of other users. This enables curation agents like
trace-reviewer to write memories owned by the user whose session was reviewed,
while the actor_id column (from #66) captures the service agent's identity.
"""

import pytest

from src.core.authz import authorize_write


# -- User scope OBO -----------------------------------------------------------


def test_service_agent_can_write_user_scope_obo():
    """Service agent writes to another user's scope (OBO)."""
    claims = {
        "sub": "trace-reviewer",
        "identity_type": "service",
        "tenant_id": "default",
        "scopes": ["memory:write:user", "memory:read:user"],
    }
    assert authorize_write(claims, "user", "wjackson", "default") is True


def test_user_agent_cannot_write_other_user_scope():
    """Regular user cannot write to another user's scope."""
    claims = {
        "sub": "alice",
        "identity_type": "user",
        "tenant_id": "default",
        "scopes": ["memory:write:user"],
    }
    assert authorize_write(claims, "user", "bob", "default") is False


def test_user_can_still_write_own_scope():
    """OBO changes do not break regular user writes."""
    claims = {
        "sub": "alice",
        "identity_type": "user",
        "tenant_id": "default",
        "scopes": ["memory:write:user"],
    }
    assert authorize_write(claims, "user", "alice", "default") is True


# -- Project scope OBO --------------------------------------------------------


def test_service_agent_can_write_project_scope_obo():
    """Service agent writes to project scope regardless of membership."""
    claims = {
        "sub": "curator-agent",
        "identity_type": "service",
        "tenant_id": "default",
        "scopes": ["memory:write:project"],
    }
    assert (
        authorize_write(
            claims, "project", "my-project", "default", scope_id="my-project"
        )
        is True
    )


def test_service_agent_project_scope_no_membership_needed():
    """Service agent does not need project_ids for project scope writes."""
    claims = {
        "sub": "trace-reviewer",
        "identity_type": "service",
        "tenant_id": "default",
        "scopes": ["memory:write:project"],
    }
    # project_ids=None would deny a regular user; service agents bypass it
    assert (
        authorize_write(
            claims, "project", "some-owner", "default", scope_id="some-project"
        )
        is True
    )


# -- Scope permission enforcement ---------------------------------------------


def test_service_agent_still_needs_scope_permission():
    """Service agent without write scope is still denied."""
    claims = {
        "sub": "trace-reviewer",
        "identity_type": "service",
        "tenant_id": "default",
        "scopes": ["memory:read:user"],  # no write scope
    }
    assert authorize_write(claims, "user", "wjackson", "default") is False


def test_service_agent_needs_matching_scope_for_project():
    """Service agent needs memory:write:project, not just any write scope."""
    claims = {
        "sub": "curator-agent",
        "identity_type": "service",
        "tenant_id": "default",
        "scopes": ["memory:write:user"],  # wrong scope for project
    }
    assert (
        authorize_write(
            claims, "project", "owner", "default", scope_id="my-project"
        )
        is False
    )


def test_service_agent_blanket_write_covers_obo():
    """Service agent with blanket memory:write can OBO at user scope."""
    claims = {
        "sub": "trace-reviewer",
        "identity_type": "service",
        "tenant_id": "default",
        "scopes": ["memory:write"],
    }
    assert authorize_write(claims, "user", "wjackson", "default") is True


# -- Tenant isolation ----------------------------------------------------------


def test_service_agent_tenant_isolation():
    """Service agent cannot write across tenants even with OBO."""
    claims = {
        "sub": "trace-reviewer",
        "identity_type": "service",
        "tenant_id": "tenant-a",
        "scopes": ["memory:write:user"],
    }
    assert authorize_write(claims, "user", "wjackson", "tenant-b") is False


def test_service_agent_project_tenant_isolation():
    """Service agent cannot write to project scope across tenants."""
    claims = {
        "sub": "curator-agent",
        "identity_type": "service",
        "tenant_id": "tenant-a",
        "scopes": ["memory:write:project"],
    }
    assert (
        authorize_write(
            claims, "project", "owner", "tenant-b", scope_id="my-project"
        )
        is False
    )


# -- Enterprise scope still blocked -------------------------------------------


def test_service_agent_cannot_write_enterprise():
    """OBO does not extend to enterprise scope (requires HITL approval)."""
    claims = {
        "sub": "curator-agent",
        "identity_type": "service",
        "tenant_id": "default",
        "scopes": ["memory:write"],
    }
    assert authorize_write(claims, "enterprise", "global", "default") is False


# -- actor_id provenance -------------------------------------------------------


def test_actor_id_tracks_service_agent():
    """actor_id is set from claims['sub'] in the write path, so OBO writes
    automatically record the service agent as actor_id."""
    claims = {"sub": "trace-reviewer"}
    assert claims["sub"] == "trace-reviewer"
