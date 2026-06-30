"""Admin content moderation operations (issue #45).

Cross-owner search, quarantine, restore, and hard delete for incident
response workflows. All operations enforce tenant isolation and require
the caller to have already been verified as an admin (memory:admin scope).
Authorization is the responsibility of the calling layer (MCP tool or BFF
route); this module trusts that the caller has been checked.

Audit logging uses the structured JSON pattern from the MCP audit module.
A future phase will persist to the PostgreSQL audit table.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from memoryhub_core.models.memory import MemoryNode, MemoryRelationship
from memoryhub_core.services.exceptions import MemoryNotFoundError

logger = logging.getLogger(__name__)
audit_logger = logging.getLogger("memoryhub.audit")


def _audit_event(
    operation: str,
    actor_id: str,
    tenant_id: str,
    memory_id: str | None = None,
    decision: str = "permitted",
    state_before: dict | None = None,
    request_context: dict | None = None,
) -> None:
    """Emit a structured admin audit event."""
    event = {
        "timestamp": datetime.now(UTC).isoformat(),
        "operation": operation,
        "actor_id": actor_id,
        "actor_type": "service",
        "memory_id": memory_id,
        "tenant_id": tenant_id,
        "decision": decision,
        "state_before": state_before,
        "request_context": request_context,
    }
    audit_logger.info(json.dumps(event, sort_keys=True, default=str))


def _memory_to_dict(node: MemoryNode) -> dict:
    """Serialize a MemoryNode to a dict for search results and audit."""
    return {
        "id": str(node.id),
        "content": node.content,
        "stub": node.stub,
        "scope": node.scope,
        "owner_id": node.owner_id,
        "tenant_id": node.tenant_id,
        "status": node.status,
        "weight": node.weight,
        "is_current": node.is_current,
        "version": node.version,
        "created_at": node.created_at.isoformat() if node.created_at else None,
        "content_type": node.content_type,
        "domains": node.domains,
    }


async def search_memory_admin(
    session: AsyncSession,
    embedding_service,
    *,
    query: str,
    tenant_id: str,
    actor_id: str,
    regex: str | None = None,
    cross_tenant: bool = False,
    scope_filter: str | None = None,
    max_results: int = 50,
    include_statuses: list[str] | None = None,
) -> list[dict]:
    """Cross-owner search combining keyword/regex with semantic similarity.

    Ignores ownership boundaries within a tenant. By default searches
    active and quarantined memories; pass include_statuses to override.

    Returns results but does NOT persist them (spill response safety).
    """
    if include_statuses is None:
        include_statuses = ["active", "quarantined"]

    # Build base filters
    filters = [
        MemoryNode.deleted_at.is_(None),
        MemoryNode.is_current.is_(True),
        MemoryNode.status.in_(include_statuses),
    ]

    if not cross_tenant:
        filters.append(MemoryNode.tenant_id == tenant_id)

    if scope_filter:
        filters.append(MemoryNode.scope == scope_filter)

    # Semantic search via pgvector
    query_embedding = await embedding_service.embed(query)
    use_pgvector = True
    try:
        distance_expr = MemoryNode.embedding.cosine_distance(query_embedding)
        stmt = (
            select(MemoryNode, distance_expr.label("distance"))
            .where(*filters)
            .order_by(distance_expr)
            .limit(max_results * 2)  # over-fetch for regex post-filter
        )
    except Exception:
        use_pgvector = False
        stmt = (
            select(MemoryNode)
            .where(*filters)
            .order_by(MemoryNode.created_at.desc())
            .limit(max_results * 2)
        )

    result = await session.execute(stmt)

    if use_pgvector:
        rows = result.all()
        candidates = [(row[0], float(row[1])) for row in rows]
    else:
        nodes = result.scalars().all()
        candidates = [(node, 0.5) for node in nodes]

    # Post-filter with regex if provided
    if regex:
        try:
            pattern = re.compile(regex, re.IGNORECASE)
        except re.error as e:
            raise ValueError(f"Invalid regex pattern: {e}") from e

        filtered = []
        for node, dist in candidates:
            if pattern.search(node.content):
                filtered.append((node, dist))
        candidates = filtered

    # Deduplicate and limit
    seen: set[uuid.UUID] = set()
    results: list[dict] = []
    for node, distance in candidates:
        if node.id in seen:
            continue
        seen.add(node.id)
        entry = _memory_to_dict(node)
        entry["relevance_score"] = round(max(0.0, 1.0 - distance), 4)
        results.append(entry)
        if len(results) >= max_results:
            break

    # Audit the search (parameters only, not results)
    _audit_event(
        operation="admin_search",
        actor_id=actor_id,
        tenant_id=tenant_id,
        request_context={
            "query": query,
            "regex": regex,
            "cross_tenant": cross_tenant,
            "scope_filter": scope_filter,
            "result_count": len(results),
        },
    )

    return results


async def quarantine_memory(
    session: AsyncSession,
    *,
    memory_id: uuid.UUID,
    tenant_id: str,
    actor_id: str,
    reason: str,
    incident_reference: str | None = None,
) -> dict:
    """Set memory status to 'quarantined', hiding from non-admin queries.

    The memory still exists with full content and embeddings intact.
    Raises MemoryNotFoundError if the memory doesn't exist in this tenant.
    """
    stmt = select(MemoryNode).where(
        MemoryNode.id == memory_id,
        MemoryNode.deleted_at.is_(None),
        MemoryNode.tenant_id == tenant_id,
    )
    result = await session.execute(stmt)
    node = result.scalar_one_or_none()

    if node is None:
        raise MemoryNotFoundError(memory_id)

    previous_status = node.status

    # Audit before mutation
    _audit_event(
        operation="quarantine",
        actor_id=actor_id,
        tenant_id=tenant_id,
        memory_id=str(memory_id),
        state_before={"status": previous_status},
        request_context={
            "reason": reason,
            "incident_reference": incident_reference,
        },
    )

    node.status = "quarantined"
    await session.commit()

    return {
        "memory_id": str(memory_id),
        "previous_status": previous_status,
        "new_status": "quarantined",
        "reason": reason,
        "incident_reference": incident_reference,
    }


async def restore_memory(
    session: AsyncSession,
    *,
    memory_id: uuid.UUID,
    tenant_id: str,
    actor_id: str,
    reason: str,
) -> dict:
    """Restore a quarantined memory to active status.

    Raises MemoryNotFoundError if the memory doesn't exist in this tenant.
    """
    stmt = select(MemoryNode).where(
        MemoryNode.id == memory_id,
        MemoryNode.deleted_at.is_(None),
        MemoryNode.tenant_id == tenant_id,
    )
    result = await session.execute(stmt)
    node = result.scalar_one_or_none()

    if node is None:
        raise MemoryNotFoundError(memory_id)

    if node.status != "quarantined":
        return {
            "memory_id": str(memory_id),
            "error": f"Cannot restore: memory status is '{node.status}', not 'quarantined'",
            "current_status": node.status,
        }

    # Audit before mutation
    _audit_event(
        operation="restore",
        actor_id=actor_id,
        tenant_id=tenant_id,
        memory_id=str(memory_id),
        state_before={"status": node.status},
        request_context={"reason": reason},
    )

    node.status = "active"
    await session.commit()

    return {
        "memory_id": str(memory_id),
        "previous_status": "quarantined",
        "new_status": "active",
        "reason": reason,
    }


async def hard_delete_memory(
    session: AsyncSession,
    *,
    memory_id: uuid.UUID,
    tenant_id: str,
    actor_id: str,
    reason: str,
    incident_reference: str | None = None,
    sanitized_audit: bool = False,
) -> dict:
    """Physically remove a memory row from the database.

    This is irreversible. The deletion cascades to relationships and
    contradiction reports via FK ON DELETE CASCADE.

    When sanitized_audit=True, the audit entry contains only the memory
    ID and a SHA-256 content hash -- no content, no metadata. Use for
    classified data spill response.

    Raises MemoryNotFoundError if the memory doesn't exist in this tenant.
    """
    stmt = select(MemoryNode).where(
        MemoryNode.id == memory_id,
        MemoryNode.tenant_id == tenant_id,
    )
    result = await session.execute(stmt)
    node = result.scalar_one_or_none()

    if node is None:
        raise MemoryNotFoundError(memory_id)

    # Build audit entry BEFORE delete
    if sanitized_audit:
        content_hash = hashlib.sha256(
            node.content.encode("utf-8")
        ).hexdigest()
        state_before = None
        request_context = {
            "sanitized_audit": True,
            "content_hash": f"sha256:{content_hash}",
            "reason": reason,
            "incident_reference": incident_reference,
        }
    else:
        state_before = _memory_to_dict(node)
        request_context = {
            "reason": reason,
            "incident_reference": incident_reference,
        }

    _audit_event(
        operation="hard_delete",
        actor_id=actor_id,
        tenant_id=tenant_id,
        memory_id=str(memory_id),
        state_before=state_before,
        request_context=request_context,
    )

    # Delete relationships where this memory is source or target.
    # These have ON DELETE CASCADE on the FK, but we do it explicitly
    # to be safe across database configurations.
    await session.execute(
        delete(MemoryRelationship).where(
            (MemoryRelationship.source_id == memory_id)
            | (MemoryRelationship.target_id == memory_id)
        )
    )

    # Delete child branches (chunks, rationale, etc.)
    await session.execute(
        delete(MemoryNode).where(MemoryNode.parent_id == memory_id)
    )

    # Delete version chain predecessors if they exist
    # Walk backward to find and delete old versions
    version_ids = [memory_id]
    current = node
    while current.previous_version_id is not None:
        version_ids.append(current.previous_version_id)
        prev_stmt = select(MemoryNode).where(
            MemoryNode.id == current.previous_version_id
        )
        prev_result = await session.execute(prev_stmt)
        current = prev_result.scalar_one_or_none()
        if current is None:
            break

    # Delete children of all versions in the chain
    if len(version_ids) > 1:
        await session.execute(
            delete(MemoryNode).where(
                MemoryNode.parent_id.in_(version_ids),
                MemoryNode.id.notin_(version_ids),
            )
        )
        # Delete relationships for all versions
        await session.execute(
            delete(MemoryRelationship).where(
                (MemoryRelationship.source_id.in_(version_ids))
                | (MemoryRelationship.target_id.in_(version_ids))
            )
        )

    # Delete the memory node(s) themselves
    await session.execute(
        delete(MemoryNode).where(MemoryNode.id.in_(version_ids))
    )

    await session.commit()

    return {
        "memory_id": str(memory_id),
        "versions_deleted": len(version_ids),
        "reason": reason,
        "incident_reference": incident_reference,
        "sanitized_audit": sanitized_audit,
    }
