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


@pytest.mark.parametrize(
    "claims,memory_scope,memory_owner,expected",
    [
        ({"sub": "alice", "scopes": ["memory:read"]}, "user", "alice", True),
        ({"sub": "alice", "scopes": ["memory:read"]}, "user", "bob", False),
        ({"sub": "alice", "scopes": ["memory:read"]}, "organizational", "org-1", True),
        ({"sub": "alice", "scopes": ["memory:read"]}, "enterprise", "global", True),
        # Project/role without membership params → denied (fail closed)
        ({"sub": "alice", "scopes": ["memory:read"]}, "project", "proj-1", False),
        ({"sub": "alice", "scopes": ["memory:read"]}, "role", "admin", False),
        ({"sub": "alice", "scopes": []}, "user", "alice", False),
        ({"sub": "alice", "scopes": ["memory:read:user"]}, "user", "alice", True),
        (
            {"sub": "alice", "scopes": ["memory:read:user"]},
            "organizational",
            "org-1",
            False,
        ),
        (
            {"sub": "alice", "scopes": ["memory:read:organizational"]},
            "organizational",
            "org-1",
            True,
        ),
        ({"sub": "alice", "scopes": []}, "organizational", "org-1", False),
        ({"sub": "alice", "scopes": ["memory:write"]}, "user", "alice", False),
    ],
)
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


@pytest.mark.parametrize(
    "claims,scope,owner_id,expected",
    [
        ({"sub": "alice", "scopes": ["memory:write:user"]}, "user", "alice", True),
        ({"sub": "alice", "scopes": ["memory:write:user"]}, "user", "bob", False),
        ({"sub": "alice", "scopes": ["memory:write"]}, "user", "alice", True),
        ({"sub": "alice", "scopes": ["memory:write"]}, "enterprise", "alice", False),
        (
            {"sub": "curator", "identity_type": "service", "scopes": ["memory:write"]},
            "organizational",
            "org-1",
            True,
        ),
        (
            {"sub": "alice", "identity_type": "user", "scopes": ["memory:write"]},
            "organizational",
            "org-1",
            False,
        ),
        (
            {"sub": "alice", "scopes": ["memory:write"]},
            "organizational",
            "org-1",
            False,
        ),
        # Role/project without membership params → denied (fail closed)
        (
            {"sub": "curator", "identity_type": "service", "scopes": ["memory:write"]},
            "role",
            "admin",
            False,
        ),
        ({"sub": "alice", "scopes": ["memory:write"]}, "project", "proj-1", False),
        ({"sub": "alice", "scopes": []}, "user", "alice", False),
        (
            {
                "sub": "curator",
                "identity_type": "service",
                "scopes": ["memory:write:user"],
            },
            "organizational",
            "org-1",
            False,
        ),
    ],
)
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
    memory = SimpleNamespace(scope="user", owner_id="alice", tenant_id="tenant_a")
    claims = {
        "sub": "alice",
        "tenant_id": "tenant_b",
        "scopes": ["memory:read:user"],
    }
    assert authorize_read(claims, memory) is False


def test_authorize_read_allows_same_tenant():
    """Matching tenant_id plus a valid scope/owner combo passes."""
    memory = SimpleNamespace(scope="user", owner_id="alice", tenant_id="tenant_a")
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
    assert authorize_write(claims, "user", "alice", "tenant_b") is False


def test_authorize_write_allows_same_tenant():
    """Matching tenant plus valid scope/owner passes."""
    claims = {
        "sub": "alice",
        "tenant_id": "tenant_a",
        "scopes": ["memory:write:user"],
    }
    assert authorize_write(claims, "user", "alice", "tenant_a") is True


def test_authorize_write_rejects_cross_tenant_even_with_blanket_scope():
    """A blanket 'memory:write' scope cannot bypass tenant isolation, even
    for service identities writing to organizational scope."""
    claims = {
        "sub": "curator",
        "tenant_id": "tenant_a",
        "identity_type": "service",
        "scopes": ["memory:write"],
    }
    assert authorize_write(claims, "organizational", "org-1", "tenant_b") is False


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
    mock_token.claims = {
        "sub": "wjackson",
        "identity_type": "user",
        "tenant_id": "default",
    }
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
        {
            "sub": "curator",
            "identity_type": "service",
            "tenant_id": "default",
            "scopes": ["memory:read"],
        },
        "test-key-not-a-real-secret",
        algorithm="HS256",
    )
    mock_request = MagicMock()
    mock_request.headers = {"authorization": f"Bearer {test_token}"}

    with (
        patch("fastmcp.server.dependencies.get_access_token", return_value=None),
        patch(
            "fastmcp.server.dependencies.get_http_request", return_value=mock_request
        ),
    ):
        claims = get_claims_from_context()

    assert claims["sub"] == "curator"
    assert claims["identity_type"] == "service"
    assert "memory:read" in claims["scopes"]


def test_get_claims_session_fallback():
    """When no JWT via either path, fall back to session-based auth."""
    session_user = {
        "user_id": "wjackson",
        "name": "Wes Jackson",
        "scopes": [
            "user",
            "project",
            "campaign",
            "role",
            "organizational",
            "enterprise",
        ],
        "identity_type": "user",
    }

    with (
        patch("fastmcp.server.dependencies.get_access_token", return_value=None),
        patch("src.core.authz._extract_jwt_from_headers", return_value=None),
        patch("src.core.authz.get_current_user", return_value=session_user),
    ):
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

    with (
        patch("fastmcp.server.dependencies.get_access_token", return_value=None),
        patch("src.core.authz._extract_jwt_from_headers", return_value=None),
        patch("src.core.authz.get_current_user", return_value=session_user),
    ):
        claims = get_claims_from_context()

    assert "memory:read:user" in claims["scopes"]
    assert "memory:write:user" in claims["scopes"]
    assert "memory:read" not in claims["scopes"]
    assert "memory:write" not in claims["scopes"]
    assert "memory:read:organizational" not in claims["scopes"]


def test_get_claims_no_identity():
    """When neither JWT nor session exists, raise AuthenticationError."""
    with (
        patch("fastmcp.server.dependencies.get_access_token", return_value=None),
        patch("src.core.authz._extract_jwt_from_headers", return_value=None),
        patch("src.core.authz.get_current_user", return_value=None),
        pytest.raises(AuthenticationError),
    ):
        get_claims_from_context()


# -- Campaign scope (issue #157) ---------------------------------------------


@pytest.mark.parametrize(
    "claims,memory_owner,campaign_ids,expected",
    [
        # Caller enrolled in campaign → allowed
        (
            {"sub": "alice", "scopes": ["memory:read"]},
            "campaign-uuid-1",
            {"campaign-uuid-1", "campaign-uuid-2"},
            True,
        ),
        # Caller not enrolled in this campaign → denied
        (
            {"sub": "alice", "scopes": ["memory:read"]},
            "campaign-uuid-3",
            {"campaign-uuid-1", "campaign-uuid-2"},
            False,
        ),
        # No campaign_ids provided → denied
        (
            {"sub": "alice", "scopes": ["memory:read"]},
            "campaign-uuid-1",
            None,
            False,
        ),
        # Empty campaign_ids set → denied
        (
            {"sub": "alice", "scopes": ["memory:read"]},
            "campaign-uuid-1",
            set(),
            False,
        ),
        # Has campaign-specific read scope → allowed
        (
            {"sub": "alice", "scopes": ["memory:read:campaign"]},
            "campaign-uuid-1",
            {"campaign-uuid-1"},
            True,
        ),
        # No read scope at all → denied even if enrolled
        (
            {"sub": "alice", "scopes": []},
            "campaign-uuid-1",
            {"campaign-uuid-1"},
            False,
        ),
        # Has wrong tier scope → denied
        (
            {"sub": "alice", "scopes": ["memory:read:user"]},
            "campaign-uuid-1",
            {"campaign-uuid-1"},
            False,
        ),
    ],
)
def test_authorize_read_campaign(claims, memory_owner, campaign_ids, expected):
    memory = SimpleNamespace(
        scope="campaign", owner_id=memory_owner, tenant_id="default"
    )
    assert authorize_read(claims, memory, campaign_ids=campaign_ids) == expected


def test_authorize_read_campaign_cross_tenant_denied():
    """Campaign RBAC doesn't bypass tenant isolation."""
    memory = SimpleNamespace(
        scope="campaign", owner_id="campaign-uuid-1", tenant_id="tenant_a"
    )
    claims = {
        "sub": "alice",
        "tenant_id": "tenant_b",
        "scopes": ["memory:read"],
    }
    assert authorize_read(claims, memory, campaign_ids={"campaign-uuid-1"}) is False


@pytest.mark.parametrize(
    "claims,owner_id,campaign_ids,expected",
    [
        # Caller enrolled → allowed
        (
            {"sub": "alice", "scopes": ["memory:write"]},
            "campaign-uuid-1",
            {"campaign-uuid-1"},
            True,
        ),
        # Caller not enrolled → denied
        (
            {"sub": "alice", "scopes": ["memory:write"]},
            "campaign-uuid-2",
            {"campaign-uuid-1"},
            False,
        ),
        # No campaign_ids → denied
        (
            {"sub": "alice", "scopes": ["memory:write"]},
            "campaign-uuid-1",
            None,
            False,
        ),
        # Has campaign-specific write scope → allowed
        (
            {"sub": "alice", "scopes": ["memory:write:campaign"]},
            "campaign-uuid-1",
            {"campaign-uuid-1"},
            True,
        ),
        # Non-service user can write campaign (lower friction than org)
        (
            {"sub": "alice", "identity_type": "user", "scopes": ["memory:write"]},
            "campaign-uuid-1",
            {"campaign-uuid-1"},
            True,
        ),
    ],
)
def test_authorize_write_campaign(claims, owner_id, campaign_ids, expected):
    assert (
        authorize_write(
            claims, "campaign", owner_id, "default", campaign_ids=campaign_ids
        )
        == expected
    )


def test_authorize_write_campaign_cross_tenant_denied():
    """Campaign write RBAC doesn't bypass tenant isolation."""
    claims = {
        "sub": "alice",
        "tenant_id": "tenant_a",
        "scopes": ["memory:write"],
    }
    assert (
        authorize_write(
            claims,
            "campaign",
            "campaign-uuid-1",
            "tenant_b",
            campaign_ids={"campaign-uuid-1"},
        )
        is False
    )


# -- Project scope isolation (issue #167) --------------------------------------


@pytest.mark.parametrize(
    "claims,memory_scope_id,project_ids,expected",
    [
        # Caller is member of the project → allowed
        (
            {"sub": "alice", "scopes": ["memory:read"]},
            "memory-hub",
            {"memory-hub", "other-proj"},
            True,
        ),
        # Caller is not member of this project → denied
        (
            {"sub": "alice", "scopes": ["memory:read"]},
            "memory-hub",
            {"other-proj"},
            False,
        ),
        # No project_ids provided → denied
        (
            {"sub": "alice", "scopes": ["memory:read"]},
            "memory-hub",
            None,
            False,
        ),
        # Empty project_ids set → denied
        (
            {"sub": "alice", "scopes": ["memory:read"]},
            "memory-hub",
            set(),
            False,
        ),
        # Has project-specific read scope → allowed
        (
            {"sub": "alice", "scopes": ["memory:read:project"]},
            "memory-hub",
            {"memory-hub"},
            True,
        ),
        # No read scope at all → denied even if member
        (
            {"sub": "alice", "scopes": []},
            "memory-hub",
            {"memory-hub"},
            False,
        ),
    ],
)
def test_authorize_read_project(claims, memory_scope_id, project_ids, expected):
    memory = SimpleNamespace(
        scope="project",
        owner_id="alice",
        scope_id=memory_scope_id,
        tenant_id="default",
    )
    assert authorize_read(claims, memory, project_ids=project_ids) == expected


def test_authorize_read_project_cross_tenant_denied():
    """Project RBAC doesn't bypass tenant isolation."""
    memory = SimpleNamespace(
        scope="project",
        owner_id="alice",
        scope_id="memory-hub",
        tenant_id="tenant_a",
    )
    claims = {"sub": "alice", "tenant_id": "tenant_b", "scopes": ["memory:read"]}
    assert authorize_read(claims, memory, project_ids={"memory-hub"}) is False


@pytest.mark.parametrize(
    "claims,scope_id,project_ids,expected",
    [
        # Member writing to own project → allowed
        (
            {"sub": "alice", "scopes": ["memory:write"]},
            "memory-hub",
            {"memory-hub"},
            True,
        ),
        # Not a member → denied
        (
            {"sub": "alice", "scopes": ["memory:write"]},
            "memory-hub",
            {"other-proj"},
            False,
        ),
        # No project_ids → denied
        (
            {"sub": "alice", "scopes": ["memory:write"]},
            "memory-hub",
            None,
            False,
        ),
        # scope_id is None → denied
        (
            {"sub": "alice", "scopes": ["memory:write"]},
            None,
            {"memory-hub"},
            False,
        ),
    ],
)
def test_authorize_write_project(claims, scope_id, project_ids, expected):
    assert (
        authorize_write(
            claims,
            "project",
            "alice",
            "default",
            project_ids=project_ids,
            scope_id=scope_id,
        )
        == expected
    )


# -- Role scope isolation (issue #167) ----------------------------------------


@pytest.mark.parametrize(
    "claims,memory_scope_id,role_names,expected",
    [
        # Caller holds the role → allowed
        (
            {"sub": "alice", "scopes": ["memory:read"]},
            "sre",
            {"sre", "architect"},
            True,
        ),
        # Caller doesn't hold this role → denied
        (
            {"sub": "alice", "scopes": ["memory:read"]},
            "sre",
            {"architect"},
            False,
        ),
        # No role_names provided → denied
        (
            {"sub": "alice", "scopes": ["memory:read"]},
            "sre",
            None,
            False,
        ),
        # Has role-specific read scope → allowed
        (
            {"sub": "alice", "scopes": ["memory:read:role"]},
            "sre",
            {"sre"},
            True,
        ),
    ],
)
def test_authorize_read_role(claims, memory_scope_id, role_names, expected):
    memory = SimpleNamespace(
        scope="role",
        owner_id="curator-agent",
        scope_id=memory_scope_id,
        tenant_id="default",
    )
    assert authorize_read(claims, memory, role_names=role_names) == expected


@pytest.mark.parametrize(
    "claims,scope_id,role_names,expected",
    [
        # Service with role → allowed
        (
            {"sub": "curator", "identity_type": "service", "scopes": ["memory:write"]},
            "sre",
            {"sre"},
            True,
        ),
        # Service without the role → denied
        (
            {"sub": "curator", "identity_type": "service", "scopes": ["memory:write"]},
            "sre",
            {"architect"},
            False,
        ),
        # Non-service user with role → denied (curator-only writes)
        (
            {"sub": "alice", "identity_type": "user", "scopes": ["memory:write"]},
            "sre",
            {"sre"},
            False,
        ),
        # Service with no role_names → denied
        (
            {"sub": "curator", "identity_type": "service", "scopes": ["memory:write"]},
            "sre",
            None,
            False,
        ),
    ],
)
def test_authorize_write_role(claims, scope_id, role_names, expected):
    assert (
        authorize_write(
            claims,
            "role",
            "curator",
            "default",
            role_names=role_names,
            scope_id=scope_id,
        )
        == expected
    )


def test_build_authorized_scopes_includes_campaign():
    """build_authorized_scopes includes campaign when caller has read access."""
    claims = {"sub": "alice", "scopes": ["memory:read"]}
    result = build_authorized_scopes(claims)
    assert "campaign" in result
    assert result["campaign"] is None  # no owner filter; campaign_ids handles it


def test_build_authorized_scopes_campaign_specific_scope():
    """Only campaign scope when caller has campaign-specific read."""
    claims = {"sub": "alice", "scopes": ["memory:read:campaign"]}
    result = build_authorized_scopes(claims)
    assert result == {"campaign": None}
