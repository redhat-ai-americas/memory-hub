"""Reusable memory and relationship reads for services and human adapters."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from memoryhub_core.authorization.human import Access
from memoryhub_core.models.memory import MemoryNode, MemoryRelationship


def memory_by_id(memory_id: uuid.UUID, tenant_id: str | None, *, lock: bool = False, unscoped: bool = False):
    """One row, optionally locked; missing tenant fails closed by default.

    Only the legacy Core deletion service explicitly requests an unscoped
    seed lookup, before deriving its tenant and checking the affected set.
    """
    stmt = select(MemoryNode).where(MemoryNode.id == memory_id)
    if not unscoped:
        stmt = stmt.where(MemoryNode.tenant_id == tenant_id)
    return stmt.with_for_update() if lock else stmt


async def get_memory_row(
    db: AsyncSession,
    memory_id: uuid.UUID,
    tenant: str,
    *,
    lock: bool = False,
    live: bool = False,
    access: Access | None = None,
):
    stmt = memory_by_id(memory_id, tenant, lock=lock)
    if live:
        stmt = stmt.where(MemoryNode.deleted_at.is_(None))
    if access is not None:
        stmt = stmt.where(access.clause())
    return (await db.execute(stmt)).scalar_one_or_none()


async def memory_rows(
    db: AsyncSession,
    ids,
    tenant: str,
    *,
    live: bool = True,
    access: Access | None = None,
    content: bool = False,
    lock: bool = False,
):
    stmt = select(MemoryNode).where(MemoryNode.id.in_(ids), MemoryNode.tenant_id == tenant)
    if live:
        stmt = stmt.where(MemoryNode.deleted_at.is_(None))
    if access is not None:
        stmt = stmt.where(access.live_content_clause() if content else access.clause())
    if lock:
        stmt = stmt.with_for_update()
    return (await db.execute(stmt)).scalars().all()


async def current_children(
    db: AsyncSession, parents, tenant: str | None, *, access: Access | None = None, lock: bool = False
):
    stmt = select(MemoryNode).where(
        MemoryNode.parent_id.in_(parents),
        MemoryNode.is_current.is_(True),
        MemoryNode.deleted_at.is_(None),
    )
    if tenant is not None:
        stmt = stmt.where(MemoryNode.tenant_id == tenant)
    if access is not None:
        stmt = stmt.where(access.clause())
    if lock:
        stmt = stmt.with_for_update()
    return (await db.execute(stmt)).scalars().all()


async def visible_child_count(db: AsyncSession, memory_id, tenant: str, access: Access):
    return (
        await db.execute(
            select(func.count())
            .select_from(MemoryNode)
            .where(
                MemoryNode.parent_id == memory_id,
                MemoryNode.tenant_id == tenant,
                MemoryNode.deleted_at.is_(None),
                MemoryNode.is_current.is_(True),
                access.clause(),
            )
        )
    ).scalar_one()


async def visible_parent_id(db: AsyncSession, parent_id, access: Access):
    return (
        await db.execute(
            select(MemoryNode.id).where(
                MemoryNode.id == parent_id,
                MemoryNode.deleted_at.is_(None),
                access.clause(),
            )
        )
    ).scalar_one_or_none()


async def relationships_between(db: AsyncSession, ids, tenant: str, types=None):
    stmt = select(MemoryRelationship).where(
        MemoryRelationship.tenant_id == tenant,
        MemoryRelationship.valid_until.is_(None),
        MemoryRelationship.source_id.in_(ids),
        MemoryRelationship.target_id.in_(ids),
    )
    if types is not None:
        stmt = stmt.where(MemoryRelationship.relationship_type.in_(types))
    return (await db.execute(stmt)).scalars().all()


async def relationships_touching(db: AsyncSession, ids, tenant: str, *, types=None, lock: bool = False):
    stmt = select(MemoryRelationship).where(
        MemoryRelationship.tenant_id == tenant,
        MemoryRelationship.valid_until.is_(None),
        or_(MemoryRelationship.source_id.in_(ids), MemoryRelationship.target_id.in_(ids)),
    )
    if types is not None:
        stmt = stmt.where(MemoryRelationship.relationship_type.in_(types))
    if lock:
        stmt = stmt.with_for_update()
    return (await db.execute(stmt)).scalars().all()


async def visible_relationships(db: AsyncSession, memory_id, tenant: str, access: Access):
    source, target = aliased(MemoryNode), aliased(MemoryNode)
    return (
        (
            await db.execute(
                select(MemoryRelationship)
                .join(source, source.id == MemoryRelationship.source_id)
                .join(target, target.id == MemoryRelationship.target_id)
                .where(
                    MemoryRelationship.tenant_id == tenant,
                    MemoryRelationship.valid_until.is_(None),
                    access.clause(source),
                    access.clause(target),
                    source.deleted_at.is_(None),
                    target.deleted_at.is_(None),
                    or_(MemoryRelationship.source_id == memory_id, MemoryRelationship.target_id == memory_id),
                )
            )
        )
        .scalars()
        .all()
    )


async def mark_deleted(db: AsyncSession, ids, tenant: str, when: datetime):
    """Stage deletion in the caller's transaction; never commit or widen tenant."""
    return await db.execute(
        update(MemoryNode)
        .where(
            MemoryNode.tenant_id == tenant,
            MemoryNode.id.in_(ids),
        )
        .values(deleted_at=when, is_current=False)
    )
