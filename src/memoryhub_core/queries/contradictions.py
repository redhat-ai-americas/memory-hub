"""Shared contradiction retrieval; every path uses the same live-memory boundary."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import contains_eager

from memoryhub_core.authorization.human import Access
from memoryhub_core.models.contradiction import ContradictionReport
from memoryhub_core.models.memory import MemoryNode


def live_reports(tenant_id, access: Access):
    stmt = (
        select(ContradictionReport)
        .join(MemoryNode, ContradictionReport.memory_id == MemoryNode.id)
        .where(
            ContradictionReport.tenant_id == tenant_id,
            MemoryNode.tenant_id == tenant_id,
            MemoryNode.deleted_at.is_(None),
            access.content_clause(),
        )
    )
    if access.principal.role == "admin":
        stmt = stmt.where(MemoryNode.scope.in_(access.moderation_scopes))
    return stmt


def live_count(tenant_id, access: Access):
    return live_reports(tenant_id, access).with_only_columns(func.count())


async def for_memory(db: AsyncSession, memory_id, tenant):
    return (
        (
            await db.execute(
                select(ContradictionReport)
                .where(
                    ContradictionReport.memory_id == memory_id,
                    ContradictionReport.tenant_id == tenant,
                )
                .order_by(ContradictionReport.created_at.desc())
            )
        )
        .scalars()
        .all()
    )


async def review_row(db: AsyncSession, report_id, tenant):
    return (
        await db.execute(
            select(ContradictionReport, MemoryNode)
            .join(
                MemoryNode,
                ContradictionReport.memory_id == MemoryNode.id,
            )
            .where(
                ContradictionReport.id == report_id,
                ContradictionReport.tenant_id == tenant,
                MemoryNode.tenant_id == tenant,
                MemoryNode.deleted_at.is_(None),
            )
            .with_for_update()
        )
    ).one_or_none()


async def list_reports(db: AsyncSession, access: Access, *, resolved=None, min_confidence=None, max_confidence=None):
    tenant_id = access.principal.tenant_id
    stmt = (
        live_reports(tenant_id, access)
        .options(contains_eager(ContradictionReport.memory))
        .order_by(ContradictionReport.created_at.desc())
    )
    if resolved is not None:
        stmt = stmt.where(ContradictionReport.resolved == resolved)
    if min_confidence is not None:
        stmt = stmt.where(ContradictionReport.confidence >= min_confidence)
    if max_confidence is not None:
        stmt = stmt.where(ContradictionReport.confidence <= max_confidence)
    result = await db.execute(stmt)
    reports = result.scalars().all()
    return reports


async def statistics(db: AsyncSession, access: Access):
    tenant_id = access.principal.tenant_id
    total_result = await db.execute(live_count(tenant_id, access))
    total = total_result.scalar_one()

    unresolved_result = await db.execute(live_count(tenant_id, access).where(ContradictionReport.resolved.is_(False)))
    unresolved = unresolved_result.scalar_one()

    high_result = await db.execute(live_count(tenant_id, access).where(ContradictionReport.confidence > 0.8))
    high = high_result.scalar_one()

    medium_result = await db.execute(
        live_count(tenant_id, access).where(ContradictionReport.confidence.between(0.5, 0.8))
    )
    medium = medium_result.scalar_one()

    low_result = await db.execute(live_count(tenant_id, access).where(ContradictionReport.confidence < 0.5))
    low = low_result.scalar_one()

    return total, unresolved, high, medium, low
