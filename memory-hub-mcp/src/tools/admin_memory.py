"""Admin content moderation tool (issue #45).

Action-dispatch tool for admin operations: search, quarantine, restore,
and hard_delete. All actions require memory:admin scope. Cross-tenant
search additionally requires memory:admin:cross_tenant.
"""

import logging
import uuid as uuid_module
from typing import Annotated, Any

from fastmcp import Context
from fastmcp.exceptions import ToolError
from pydantic import Field
from sqlalchemy import select, text

from src.core.app import mcp
from src.core.audit import record_event
from src.tools._audit_helpers import record_audit_event

logger = logging.getLogger(__name__)

_VALID_ACTIONS = frozenset({"search", "quarantine", "restore", "hard_delete"})

_SEARCH_OPTS = frozenset({
    "regex", "cross_tenant", "scope_filter", "incident_reference", "max_results",
    "include_statuses",
})
_QUARANTINE_OPTS = frozenset({"reason", "incident_reference"})
_RESTORE_OPTS = frozenset({"reason", "incident_reference"})
_HARD_DELETE_OPTS = frozenset({
    "reason", "incident_reference", "sanitized_audit",
})


def _check_admin_scope(scopes: list[str]) -> None:
    """Verify the caller has memory:admin scope."""
    if "memory:admin" not in scopes:
        raise ToolError(
            "Forbidden: admin_memory requires 'memory:admin' scope. "
            "Your current scopes do not include admin access."
        )


async def _require_active_incident_grant(session, *, tenant_id: str, driver_id: str, scopes: list[str], incident_reference: str | None) -> dict:
    """Require the elevated admin scope and a matching active UI break-glass grant."""
    if "memory:admin:super" not in scopes:
        raise ToolError("Forbidden: user-scope admin access requires 'memory:admin:super'.")
    if not isinstance(incident_reference, str) or not incident_reference.strip():
        raise ToolError("User-scope admin access requires an active break-glass grant and incident_reference.")
    try:
        row = (
            await session.execute(
                text(
                    "SELECT id, incident_ref, justification FROM memoryhub_ui_break_glass "
                    "WHERE tenant_id = :tenant_id AND username = :username AND incident_ref = :incident_ref "
                    "AND ended_at IS NULL AND expires_at > now() ORDER BY created_at DESC LIMIT 1"
                ),
                {
                    "tenant_id": tenant_id,
                    "username": driver_id,
                    "incident_ref": incident_reference.strip(),
                },
            )
        ).first()
    except Exception as exc:
        await session.rollback()
        raise ToolError("User-scope admin access is unavailable because incident grants could not be verified.") from exc
    if row is None:
        raise ToolError("No active break-glass grant matches this identity, tenant, and incident_reference.")
    return {"id": str(row.id), "incident_ref": row.incident_ref, "justification": row.justification}


async def _target_memory_scope(session, memory_id: str, tenant_id: str) -> tuple[str, str] | None:
    from memoryhub_core.models.memory import MemoryNode

    try:
        parsed_id = uuid_module.UUID(memory_id)
    except ValueError as exc:
        raise ToolError(f"Invalid memory_id '{memory_id}'. Expected a UUID.") from exc
    row = (
        await session.execute(
            select(MemoryNode.scope, MemoryNode.owner_id).where(
                MemoryNode.id == parsed_id,
                MemoryNode.tenant_id == tenant_id,
            )
        )
    ).first()
    return (row.scope, row.owner_id) if row else None


@mcp.tool(
    annotations={
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": False,
        "openWorldHint": False,
    }
)
async def admin_memory(
    action: Annotated[
        str,
        Field(description=(
            "Admin action: search, quarantine, restore, hard_delete"
        )),
    ],
    memory_id: Annotated[
        str | None,
        Field(description=(
            "Memory UUID (required for quarantine/restore/hard_delete)"
        )),
    ] = None,
    query: Annotated[
        str | None,
        Field(description="Search query (required for search)"),
    ] = None,
    options: Annotated[
        dict[str, Any] | None,
        Field(description=(
            "Action-specific options. "
            "search: regex, cross_tenant, scope_filter, incident_reference, max_results, include_statuses. "
            "quarantine: reason (required), incident_reference. "
            "restore: reason (required), incident_reference for user-scope memories. "
            "hard_delete: reason (required), incident_reference, sanitized_audit."
        )),
    ] = None,
    ctx: Context = None,
) -> dict[str, Any]:
    """Admin content moderation operations. Requires memory:admin scope.

    User-scope content additionally requires memory:admin:super and a matching
    active break-glass grant created through the dashboard.

    Actions:
      search(query, [options: regex, cross_tenant, scope_filter, max_results, include_statuses])
        Cross-owner search ignoring ownership boundaries within a tenant.
        Combines semantic similarity with optional regex matching.
        User-scope results require an active break-glass grant and are owner-audited.

      quarantine(memory_id, options: {reason}, [options: incident_reference])
        Hide memory from all non-admin queries immediately. Content and
        embeddings are preserved for admin review.

      restore(memory_id, options: {reason})
        Restore a quarantined memory to active status.

      hard_delete(memory_id, options: {reason}, [options: incident_reference, sanitized_audit])
        Physically remove memory from database. IRREVERSIBLE.
        Set sanitized_audit=true for classified data spill response --
        audit entry will contain only a SHA-256 content hash, no content.
    """
    if action not in _VALID_ACTIONS:
        raise ToolError(
            f"Invalid admin action '{action}'. Must be one of: "
            f"{', '.join(sorted(_VALID_ACTIONS))}."
        )

    # Resolve identity
    from src.core.authz import get_claims_from_context, get_tenant_filter

    claims = get_claims_from_context()
    scopes = claims.get("scopes", [])
    _check_admin_scope(scopes)

    tenant_id = get_tenant_filter(claims)
    actor_id = claims["sub"]
    from src.tools._deps import resolve_driver_id

    driver_id = resolve_driver_id(None, claims)
    opts = options or {}

    if action == "search":
        return await _dispatch_search(
            query, tenant_id, actor_id, driver_id, scopes, opts,
        )
    if action == "quarantine":
        return await _dispatch_quarantine(
            memory_id, tenant_id, actor_id, driver_id, scopes, opts,
        )
    if action == "restore":
        return await _dispatch_restore(
            memory_id, tenant_id, actor_id, driver_id, scopes, opts,
        )
    # hard_delete
    return await _dispatch_hard_delete(
        memory_id, tenant_id, actor_id, driver_id, scopes, opts,
    )


async def _dispatch_search(
    query: str | None,
    tenant_id: str,
    actor_id: str,
    driver_id: str,
    scopes: list[str],
    opts: dict,
) -> dict:
    """Dispatch admin search."""
    from memoryhub_core.services.admin import search_memory_admin
    from src.tools._deps import get_db_session, get_embedding_service, release_db_session

    if not query or (isinstance(query, str) and not query.strip()):
        raise ToolError(
            "action='search' requires 'query'. "
            "Example: admin_memory(action='search', query='API key')"
        )

    cross_tenant = opts.get("cross_tenant", False)
    if cross_tenant and "memory:admin:cross_tenant" not in scopes:
        raise ToolError(
            "Forbidden: cross-tenant admin search requires "
            "'memory:admin:cross_tenant' scope."
        )

    scope_filter = opts.get("scope_filter")
    if scope_filter not in (None, "user", "project", "campaign", "role", "organizational", "enterprise"):
        raise ToolError("Invalid scope_filter. Use user, project, campaign, role, organizational, or enterprise.")
    if scope_filter == "user" and cross_tenant:
        raise ToolError("User-scope break-glass searches cannot cross tenant boundaries.")

    session, gen = await get_db_session()
    try:
        grant = None
        if scope_filter == "user":
            grant = await _require_active_incident_grant(
                session,
                tenant_id=tenant_id,
                driver_id=driver_id,
                scopes=scopes,
                incident_reference=opts.get("incident_reference"),
            )
        embedding_service = get_embedding_service()

        kwargs: dict = {
            "query": query,
            "tenant_id": tenant_id,
            "actor_id": actor_id,
        }
        if "regex" in opts:
            kwargs["regex"] = opts["regex"]
        if cross_tenant:
            kwargs["cross_tenant"] = True
        if scope_filter is not None:
            kwargs["scope_filter"] = scope_filter
        else:
            kwargs["exclude_scopes"] = ["user"]
        if "max_results" in opts:
            kwargs["max_results"] = int(opts["max_results"])
        if "include_statuses" in opts:
            kwargs["include_statuses"] = opts["include_statuses"]

        try:
            results = await search_memory_admin(
                session, embedding_service, **kwargs,
            )
        except ValueError as e:
            raise ToolError(str(e)) from e

        private_results = [item for item in results if item.get("scope") == "user"]
        if private_results:
            # Persist an owner-visible high-severity audit for every private
            # record revealed through the admin search response.
            for item in private_results:
                await record_audit_event(
                    event_type="memory.read",
                    actor_id=actor_id,
                    driver_id=driver_id,
                    scope="user",
                    owner_id=item["owner_id"],
                    memory_id=item["id"],
                    decision="allowed",
                    tenant_id=tenant_id,
                    metadata={
                        "via": "mcp.admin_memory.search",
                        "break_glass": True,
                        "privacy_invasive": True,
                        "severity": "HIGH",
                        "grant_id": grant["id"],
                        "incident_ref": grant["incident_ref"],
                        "justification": grant["justification"],
                    },
                    session=session,
                )
            await session.commit()
        else:
            await record_audit_event(
                event_type="admin.search",
                actor_id=actor_id,
                driver_id=driver_id,
                scope=scope_filter or "admin",
                owner_id=driver_id,
                memory_id=None,
                decision="allowed",
                tenant_id=tenant_id,
                metadata={"result_ids": [item["id"] for item in results], "result_count": len(results)},
                session=session,
            )
            await session.commit()

        return {
            "results": results,
            "total": len(results),
            "query": query,
            "regex": opts.get("regex"),
        }
    finally:
        await release_db_session(gen)


async def _dispatch_quarantine(
    memory_id: str | None,
    tenant_id: str,
    actor_id: str,
    driver_id: str,
    scopes: list[str],
    opts: dict,
) -> dict:
    """Dispatch quarantine operation."""
    from memoryhub_core.services.admin import quarantine_memory
    from src.tools._deps import get_db_session, release_db_session

    if not memory_id:
        raise ToolError(
            "action='quarantine' requires 'memory_id'. "
            "Example: admin_memory(action='quarantine', memory_id='...')"
        )
    reason = opts.get("reason")
    if not reason or (isinstance(reason, str) and not reason.strip()):
        raise ToolError(
            "action='quarantine' requires 'reason' in options. "
            "Example: admin_memory(action='quarantine', memory_id='...', "
            "options={'reason': 'Suspected PII leak'})"
        )

    session, gen = await get_db_session()
    try:
        target = await _target_memory_scope(session, memory_id, tenant_id)
        if target and target[0] == "user":
            grant = await _require_active_incident_grant(
                session,
                tenant_id=tenant_id,
                driver_id=driver_id,
                scopes=scopes,
                incident_reference=opts.get("incident_reference"),
            )
        else:
            grant = None
        result = await quarantine_memory(
            session,
            memory_id=uuid_module.UUID(memory_id),
            tenant_id=tenant_id,
            actor_id=actor_id,
            reason=reason,
            incident_reference=opts.get("incident_reference"),
        )

        # MCP-layer audit
        record_event(
            event_type="admin.quarantine",
            actor_id=actor_id,
            driver_id=actor_id,
            scope="admin",
            owner_id=actor_id,
            memory_id=memory_id,
            decision="allowed",
            metadata={"reason": reason, "incident_reference": grant["incident_ref"] if grant else None},
        )
        await record_audit_event(
            event_type="admin.quarantine",
            actor_id=actor_id,
            driver_id=driver_id,
            scope=target[0] if target else "admin",
            owner_id=target[1] if target else actor_id,
            memory_id=memory_id,
            decision="allowed",
            tenant_id=tenant_id,
            metadata={
                "reason": reason,
                "break_glass": bool(grant),
                "privacy_invasive": bool(grant),
                "severity": "HIGH" if grant else None,
                "grant_id": grant["id"] if grant else None,
                "incident_ref": grant["incident_ref"] if grant else None,
                "justification": grant["justification"] if grant else None,
            },
            session=session,
        )
        await session.commit()

        return result
    except Exception as e:
        if "not found" in str(e).lower():
            raise ToolError(f"Memory {memory_id} not found") from e
        raise
    finally:
        await release_db_session(gen)


async def _dispatch_restore(
    memory_id: str | None,
    tenant_id: str,
    actor_id: str,
    driver_id: str,
    scopes: list[str],
    opts: dict,
) -> dict:
    """Dispatch restore operation."""
    from memoryhub_core.services.admin import restore_memory
    from src.tools._deps import get_db_session, release_db_session

    if not memory_id:
        raise ToolError(
            "action='restore' requires 'memory_id'. "
            "Example: admin_memory(action='restore', memory_id='...')"
        )
    reason = opts.get("reason")
    if not reason or (isinstance(reason, str) and not reason.strip()):
        raise ToolError(
            "action='restore' requires 'reason' in options. "
            "Example: admin_memory(action='restore', memory_id='...', "
            "options={'reason': 'Content reviewed, no issues found'})"
        )

    session, gen = await get_db_session()
    try:
        target = await _target_memory_scope(session, memory_id, tenant_id)
        if target and target[0] == "user":
            grant = await _require_active_incident_grant(
                session,
                tenant_id=tenant_id,
                driver_id=driver_id,
                scopes=scopes,
                incident_reference=opts.get("incident_reference"),
            )
        else:
            grant = None
        result = await restore_memory(
            session,
            memory_id=uuid_module.UUID(memory_id),
            tenant_id=tenant_id,
            actor_id=actor_id,
            reason=reason,
        )

        record_event(
            event_type="admin.restore",
            actor_id=actor_id,
            driver_id=actor_id,
            scope="admin",
            owner_id=actor_id,
            memory_id=memory_id,
            decision="allowed",
            metadata={"reason": reason, "incident_reference": grant["incident_ref"] if grant else None},
        )
        await record_audit_event(
            event_type="admin.restore",
            actor_id=actor_id,
            driver_id=driver_id,
            scope=target[0] if target else "admin",
            owner_id=target[1] if target else actor_id,
            memory_id=memory_id,
            decision="allowed",
            tenant_id=tenant_id,
            metadata={
                "reason": reason,
                "break_glass": bool(grant),
                "privacy_invasive": bool(grant),
                "severity": "HIGH" if grant else None,
                "grant_id": grant["id"] if grant else None,
                "incident_ref": grant["incident_ref"] if grant else None,
                "justification": grant["justification"] if grant else None,
            },
            session=session,
        )
        await session.commit()

        return result
    except Exception as e:
        if "not found" in str(e).lower():
            raise ToolError(f"Memory {memory_id} not found") from e
        raise
    finally:
        await release_db_session(gen)


async def _dispatch_hard_delete(
    memory_id: str | None,
    tenant_id: str,
    actor_id: str,
    driver_id: str,
    scopes: list[str],
    opts: dict,
) -> dict:
    """Dispatch hard delete operation."""
    from memoryhub_core.services.admin import hard_delete_memory
    from src.tools._deps import get_db_session, release_db_session

    if not memory_id:
        raise ToolError(
            "action='hard_delete' requires 'memory_id'. "
            "Example: admin_memory(action='hard_delete', memory_id='...')"
        )
    reason = opts.get("reason")
    if not reason or (isinstance(reason, str) and not reason.strip()):
        raise ToolError(
            "action='hard_delete' requires 'reason' in options. "
            "Example: admin_memory(action='hard_delete', memory_id='...', "
            "options={'reason': 'Classified data spill cleanup'})"
        )

    sanitized = opts.get("sanitized_audit", False)
    if sanitized and "memory:admin:sanitized_audit" not in scopes:
        raise ToolError(
            "Forbidden: sanitized_audit mode requires "
            "'memory:admin:sanitized_audit' scope."
        )

    session, gen = await get_db_session()
    try:
        target = await _target_memory_scope(session, memory_id, tenant_id)
        if target and target[0] == "user":
            grant = await _require_active_incident_grant(
                session,
                tenant_id=tenant_id,
                driver_id=driver_id,
                scopes=scopes,
                incident_reference=opts.get("incident_reference"),
            )
        else:
            grant = None
        result = await hard_delete_memory(
            session,
            memory_id=uuid_module.UUID(memory_id),
            tenant_id=tenant_id,
            actor_id=actor_id,
            reason=reason,
            incident_reference=opts.get("incident_reference"),
            sanitized_audit=sanitized,
        )

        record_event(
            event_type="admin.hard_delete",
            actor_id=actor_id,
            driver_id=actor_id,
            scope="admin",
            owner_id=actor_id,
            memory_id=memory_id,
            decision="allowed",
            metadata={
                "reason": reason,
                "sanitized_audit": sanitized,
                "versions_deleted": result.get("versions_deleted", 0),
                "incident_reference": grant["incident_ref"] if grant else None,
            },
        )
        await record_audit_event(
            event_type="admin.hard_delete",
            actor_id=actor_id,
            driver_id=driver_id,
            scope=target[0] if target else "admin",
            owner_id=target[1] if target else actor_id,
            memory_id=memory_id,
            decision="allowed",
            tenant_id=tenant_id,
            metadata={
                "reason": reason,
                "sanitized_audit": sanitized,
                "versions_deleted": result.get("versions_deleted", 0),
                "break_glass": bool(grant),
                "privacy_invasive": bool(grant),
                "severity": "HIGH" if grant else None,
                "grant_id": grant["id"] if grant else None,
                "incident_ref": grant["incident_ref"] if grant else None,
                "justification": grant["justification"] if grant else None,
            },
            session=session,
        )
        await session.commit()

        return result
    except Exception as e:
        if "not found" in str(e).lower():
            raise ToolError(f"Memory {memory_id} not found") from e
        raise
    finally:
        await release_db_session(gen)
