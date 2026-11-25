"""Audit aggregates scoped to a known, authorized memory."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from memoryhub_core.models.audit import AuditLog


async def read_count(db: AsyncSession, memory_id, tenant: str):
    return (
        await db.execute(
            select(func.count())
            .select_from(AuditLog)
            .where(
                AuditLog.tenant_id == tenant,
                AuditLog.memory_id == memory_id,
                AuditLog.event_type == "memory.read",
                AuditLog.decision == "allowed",
            )
        )
    ).scalar_one()
