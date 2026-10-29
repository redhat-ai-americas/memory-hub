"""Memory read/write authorization — the MCP server's rules, for the dashboard.

The source of truth is ``memory-hub-mcp/src/core/authz.py`` (``authorize_read``,
``authorize_write``). That module cannot be imported here: it depends on the MCP
server's request context. This file carries the same decision logic as pure
functions, and ``tests/test_authz_conformance.py`` loads the MCP module from the
monorepo and checks both agree on every scope / membership / identity
combination, so the two cannot drift silently.

One deliberate, documented extension: a dashboard *person* is the union of
their identities — their own username plus the agents linked to them (see
``ownership.py``). A memory is readable by the person when it is readable by
any of those identities under the MCP rules. Agents themselves are untouched:
they still get exactly what the MCP server decides.

Keep in sync with: upstream memory-hub-mcp/src/core/authz.py (checked at
4218eb5). Feature flags use the same environment variables.
"""

from __future__ import annotations

import os
from typing import Any

from sqlalchemy import and_, false, or_

ALL_TIERS = ("user", "project", "campaign", "role", "organizational", "enterprise")
DEFAULT_TENANT_ID = "default"


def project_isolation() -> bool:
    return os.environ.get("MEMORYHUB_PROJECT_ISOLATION_ENABLED", "true").lower() == "true"


def role_isolation() -> bool:
    return os.environ.get("MEMORYHUB_ROLE_ISOLATION_ENABLED", "true").lower() == "true"


def claims_for(identity: str, tenant_id: str, *, identity_type: str = "user") -> dict:
    """Claims for a dashboard identity: every tier readable and writable.

    Dashboard users are signed in through OpenShift or a local account, not an
    MCP API key, so they have no per-tier scope list; tier access is decided by
    ownership and memberships exactly as for an agent with full scopes.
    """
    return {
        "sub": identity,
        "identity_type": identity_type,
        "tenant_id": tenant_id,
        "scopes": ["memory:read", "memory:write"],
    }


def _tier(value: Any) -> str:
    return value.value if hasattr(value, "value") else value


def authorize_read(
    claims: dict,
    memory: Any,
    campaign_ids: set[str] | None = None,
    project_ids: set[str] | None = None,
    role_names: set[str] | None = None,
) -> bool:
    """Same decision as the MCP server's ``authorize_read``."""
    if memory.tenant_id != claims.get("tenant_id", DEFAULT_TENANT_ID):
        return False
    scopes = claims.get("scopes", [])
    tier = _tier(memory.scope)
    if f"memory:read:{tier}" not in scopes and "memory:read" not in scopes:
        return False
    if tier == "user":
        return memory.owner_id == claims["sub"]
    if tier in ("enterprise", "organizational"):
        return True
    if tier == "project":
        if not project_isolation():
            return True
        return project_ids is not None and memory.scope_id in project_ids
    if tier == "campaign":
        return campaign_ids is not None and memory.owner_id in campaign_ids
    if tier == "role":
        if not role_isolation():
            return True
        return role_names is not None and memory.scope_id in role_names
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
    """Same decision as the MCP server's ``authorize_write``."""
    own_tenant = claims.get("tenant_id", DEFAULT_TENANT_ID)
    if tenant_id != own_tenant:
        authorized = claims.get("authorized_tenants")
        if not authorized or tenant_id not in authorized:
            return False
    scopes = claims.get("scopes", [])
    scope = _tier(scope)
    if f"memory:write:{scope}" not in scopes and "memory:write" not in scopes:
        return False
    service = claims.get("identity_type") == "service"
    if scope == "user":
        return owner_id == claims["sub"] or service
    if scope == "enterprise":
        return False
    if scope == "organizational":
        return service
    if scope == "role":
        if not service:
            return False
        if not role_isolation():
            return True
        return role_names is not None and scope_id in role_names
    if scope == "project":
        if not project_isolation():
            return True
        if service:
            return True
        return project_ids is not None and scope_id is not None and scope_id in project_ids
    if scope == "campaign":
        return campaign_ids is not None and owner_id in campaign_ids
    return False


# ---------------------------------------------------------------------------
# A person = the union of their identities
# ---------------------------------------------------------------------------


def person_can_read(grants: Any, tenant_id: str, memory: Any) -> bool:
    return any(
        authorize_read(
            claims_for(identity, tenant_id),
            memory,
            campaign_ids=grants.campaigns,
            project_ids=grants.projects,
            role_names=grants.roles,
        )
        for identity in grants.identities
    )


def person_can_write(grants: Any, tenant_id: str, scope: str, owner_id: str, scope_id: str | None) -> bool:
    return any(
        authorize_write(
            claims_for(identity, tenant_id),
            scope,
            owner_id,
            tenant_id,
            campaign_ids=grants.campaigns,
            scope_id=scope_id,
            project_ids=grants.projects,
            role_names=grants.roles,
        )
        for identity in grants.identities
    )


def read_clause(grants: Any, tenant_id: str, node: Any):
    """SQL form of ``person_can_read`` (same rules, evaluated in the database)."""
    clauses = [
        node.scope.in_(("organizational", "enterprise")),
        and_(node.scope == "user", node.owner_id.in_(sorted(grants.identities))),
    ]
    if not project_isolation():
        clauses.append(node.scope == "project")
    elif grants.projects:
        clauses.append(and_(node.scope == "project", node.scope_id.in_(sorted(grants.projects))))
    if not role_isolation():
        clauses.append(node.scope == "role")
    elif grants.roles:
        clauses.append(and_(node.scope == "role", node.scope_id.in_(sorted(grants.roles))))
    if grants.campaigns:
        clauses.append(and_(node.scope == "campaign", node.owner_id.in_(sorted(grants.campaigns))))
    return and_(node.tenant_id == tenant_id, or_(*clauses)) if clauses else false()
