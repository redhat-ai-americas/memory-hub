"""One human-memory selection for browse, graph and export.

Filters narrow an already authorized set. Content predicates cannot inspect
redacted rows, and relationship predicates inherit tenant and row visibility.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import String, and_, cast, func, or_, select
from sqlalchemy.orm import aliased

from memoryhub_core.authorization.human import Access
from memoryhub_core.models.contradiction import ContradictionReport
from memoryhub_core.models.memory import MemoryNode, MemoryRelationship


class QueryValidationError(ValueError):
    """An unsupported or inconsistent query filter."""


class QueryAccessError(PermissionError):
    """A filter would inspect a category the caller cannot query."""


@dataclass(frozen=True)
class MemoryFilters:
    tab: str = "current"
    q: str | None = None
    mode: str = "semantic"
    scope: list[str] | None = None
    actor: list[str] | None = None
    project: str | None = None
    domain: list[str] | None = None
    min_weight: float | None = None
    max_weight: float | None = None
    created_from: date | None = None
    created_to: date | None = None
    branch_type: str | None = None
    flag: list[str] | None = None
    entity: uuid.UUID | None = None


def base_conditions(access: Access) -> list:
    return [
        MemoryNode.tenant_id == access.principal.tenant_id,
        access.live_content_clause() if access.principal.role == "user" else access.clause(),
    ]


def state_conditions(tab: str) -> tuple:
    if tab == "current":
        return MemoryNode.deleted_at.is_(None), MemoryNode.is_current.is_(True), MemoryNode.status == "active"
    if tab == "all":
        return (MemoryNode.deleted_at.is_(None),)
    if tab == "quarantined":
        return MemoryNode.deleted_at.is_(None), MemoryNode.status == "quarantined"
    if tab == "deleted":
        return (MemoryNode.deleted_at.is_not(None),)
    raise QueryValidationError("Invalid memory tab")


def has_children(access: Access, branch_type: str | None = None):
    child = aliased(MemoryNode)
    stmt = select(child.id).where(
        child.parent_id == MemoryNode.id,
        child.tenant_id == access.principal.tenant_id,
        child.deleted_at.is_(None),
        child.is_current.is_(True),
        access.clause(child),
    )
    if branch_type:
        stmt = stmt.where(child.branch_type == branch_type)
    return stmt.exists()


def has_contradictions(tenant: str):
    return (
        select(ContradictionReport.id)
        .where(
            ContradictionReport.memory_id == MemoryNode.id,
            ContradictionReport.tenant_id == tenant,
            ContradictionReport.resolved.is_(False),
        )
        .exists()
    )


def memory_writer(node=MemoryNode):
    """The actual writer, falling back to the owner on legacy rows."""
    return func.coalesce(node.actor_id, node.owner_id)


def memory_conditions(access: Access, filters: MemoryFilters) -> list:
    if filters.min_weight is not None and filters.max_weight is not None and filters.min_weight > filters.max_weight:
        raise QueryValidationError("Invalid weight range")
    if filters.flag and set(filters.flag) - {"contradicted", "has_branches"}:
        raise QueryValidationError("Unsupported flag filter")
    if access.principal.role == "user" and filters.tab in {"quarantined", "deleted"}:
        raise QueryAccessError("Memory state forbidden")
    if not access.sees_individual_activity and filters.actor:
        raise QueryAccessError("Per-person filters are not available to admins")
    tenant = access.principal.tenant_id
    where = [*base_conditions(access), *state_conditions(filters.tab)]
    if filters.scope:
        where.append(MemoryNode.scope.in_(filters.scope))
    if filters.actor:
        where.append(memory_writer().in_(filters.actor))
    if filters.project:
        where += [MemoryNode.scope == "project", MemoryNode.scope_id == filters.project]
    if filters.domain:
        where += [access.live_content_clause(), MemoryNode.domains.overlap(filters.domain)]
    if filters.min_weight is not None:
        where.append(MemoryNode.weight >= filters.min_weight)
    if filters.max_weight is not None:
        where.append(MemoryNode.weight <= filters.max_weight)
    if filters.created_from:
        where.append(MemoryNode.created_at >= filters.created_from)
    if filters.created_to:
        where.append(MemoryNode.created_at < filters.created_to + timedelta(days=1))
    if filters.branch_type:
        where.append(has_children(access, filters.branch_type))
    if filters.flag:
        if "contradicted" in filters.flag:
            where += [access.live_content_clause(), has_contradictions(tenant)]
        if "has_branches" in filters.flag:
            where.append(has_children(access))
    if filters.entity:
        where += [
            access.live_content_clause(),
            select(MemoryRelationship.id)
            .where(
                MemoryRelationship.source_id == MemoryNode.id,
                MemoryRelationship.target_id == filters.entity,
                MemoryRelationship.tenant_id == tenant,
                MemoryRelationship.relationship_type == "mentions",
                MemoryRelationship.valid_until.is_(None),
            )
            .exists(),
        ]
    if filters.q:
        pattern = f"%{filters.q.strip()}%"
        metadata = cast(MemoryNode.id, String).ilike(pattern)
        if access.sees_individual_activity:
            metadata = or_(metadata, MemoryNode.owner_id.ilike(pattern))
        if filters.mode == "metadata":
            where.append(metadata)
        elif filters.mode in {"semantic", "text"}:
            where.append(
                or_(
                    metadata,
                    and_(
                        access.live_content_clause(),
                        or_(MemoryNode.content.ilike(pattern), MemoryNode.stub.ilike(pattern)),
                    ),
                )
            )
        else:
            raise QueryValidationError("Invalid search mode")
    return where
