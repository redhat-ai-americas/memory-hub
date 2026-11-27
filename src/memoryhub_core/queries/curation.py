"""Tenant and layer-aware curation rule retrieval."""

from sqlalchemy import and_, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from memoryhub_core.authorization.human import Access
from memoryhub_core.models.curation import CuratorRule


def rule_visibility(tenant, owner):
    return and_(
        CuratorRule.tenant_id == tenant,
        or_(
            CuratorRule.layer.in_(("system", "organizational")),
            and_(CuratorRule.layer == "user", CuratorRule.owner_id == owner),
        ),
    )


async def rule_row(db: AsyncSession, rule_id, tenant, *, lock=False):
    stmt = select(CuratorRule).where(CuratorRule.id == rule_id, CuratorRule.tenant_id == tenant)
    if lock:
        stmt = stmt.with_for_update()
    return (await db.execute(stmt)).scalar_one_or_none()


async def visible_rules(db: AsyncSession, access: Access, *, tier=None, enabled=None, layer=None):
    tenant_id = access.principal.tenant_id
    stmt = (
        select(CuratorRule)
        .where(
            rule_visibility(tenant_id, access.principal.username),
            CuratorRule.is_current.is_(True),
        )
        .order_by(CuratorRule.priority)
    )
    if tier:
        stmt = stmt.where(CuratorRule.tier == tier)
    if enabled is not None:
        stmt = stmt.where(CuratorRule.enabled == enabled)
    if layer:
        stmt = stmt.where(CuratorRule.layer == layer)
    result = await db.execute(stmt)
    rules = result.scalars().all()
    return rules


async def history_rows(db: AsyncSession, parsed_id, tenant_id):
    # Single recursive CTE: walk backward to the oldest ancestor, then forward
    # through all descendants — replaces the previous O(N) per-version loop.
    chain_result = await db.execute(
        text("""
            WITH RECURSIVE
              ancestors(id, previous_version_id) AS (
                SELECT id, previous_version_id FROM curator_rules WHERE id = :seed_id AND tenant_id = :tenant_id
                UNION
                SELECT r.id, r.previous_version_id FROM curator_rules r
                JOIN ancestors a ON r.id = a.previous_version_id WHERE r.tenant_id = :tenant_id
              ),
              root AS (SELECT id FROM ancestors WHERE previous_version_id IS NULL),
              chain AS (
                SELECT r.id, r.version, r.is_current, r.name, r.edited_by, r.created_at,
                       r.tenant_id, r.layer, r.owner_id
                FROM curator_rules r JOIN root ON r.id = root.id WHERE r.tenant_id = :tenant_id
                UNION
                SELECT r.id, r.version, r.is_current, r.name, r.edited_by, r.created_at,
                       r.tenant_id, r.layer, r.owner_id
                FROM curator_rules r
                JOIN chain c ON r.previous_version_id = c.id WHERE r.tenant_id = :tenant_id
              )
            SELECT id, version, is_current, name, edited_by, created_at, tenant_id, layer, owner_id
            FROM chain
            ORDER BY version DESC
        """),
        {"seed_id": parsed_id, "tenant_id": tenant_id},
    )
    return chain_result.fetchall()
