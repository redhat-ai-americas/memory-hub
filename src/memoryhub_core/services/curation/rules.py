"""Curation rules — loading, layer merging, and evaluation."""

import uuid

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from memoryhub_core.models.curation import CuratorRule
from memoryhub_core.models.schemas import CuratorRuleCreate

# Layer precedence: higher index = higher layer (can protect with override=True)
_LAYER_ORDER = {"system": 0, "organizational": 1, "user": 2}
_TIER_ORDER = {"regex": 0, "embedding": 1}


async def load_rules(
    trigger: str,
    owner_id: str,
    scope: str | None,
    session: AsyncSession,
    *,
    tenant_id: str,
) -> list[CuratorRule]:
    """Load and merge rules for a given trigger context.

    Loads all enabled rules matching the trigger, merges layers with
    user > org > system precedence, then returns them sorted by tier
    (regex first) then priority (lower number = higher priority).

    A higher-layer rule marked override=True cannot be replaced by a
    lower-layer rule with the same name.

    Tenant isolation: ``tenant_id`` is a required keyword argument.
    Every rule -- including system and organizational layers -- is
    scoped to a single tenant, so each tenant effectively gets its own
    copy of the rule set. This means a tenant-A override of a system
    rule cannot affect tenant-B writes, and a staleness policy set by
    one organization cannot fire against another. ``seed_default_rules``
    now also takes a tenant_id so first-write-per-tenant seeds the
    system rules into the caller's tenant.
    """
    stmt = (
        select(CuratorRule)
        .where(
            and_(
                CuratorRule.enabled.is_(True),
                CuratorRule.trigger == trigger,
                CuratorRule.tenant_id == tenant_id,
                or_(
                    CuratorRule.layer.in_(["system", "organizational"]),
                    and_(
                        CuratorRule.layer == "user",
                        CuratorRule.owner_id == owner_id,
                    ),
                ),
            )
        )
        .order_by(CuratorRule.tier, CuratorRule.priority)
    )
    result = await session.execute(stmt)
    all_rules: list[CuratorRule] = list(result.scalars().all())

    system_rules: dict[str, CuratorRule] = {}
    org_rules: dict[str, CuratorRule] = {}
    user_rules: dict[str, CuratorRule] = {}

    for rule in all_rules:
        # Skip rules whose scope_filter doesn't match the write scope
        if rule.scope_filter is not None and scope is not None and rule.scope_filter != scope:
            continue

        if rule.layer == "system":
            system_rules[rule.name] = rule
        elif rule.layer == "organizational":
            org_rules[rule.name] = rule
        elif rule.layer == "user" and rule.owner_id == owner_id:
            user_rules[rule.name] = rule

    # Merge starting from system (lowest precedence), then org, then user.
    # A rule is protected if the incumbent has override=True.
    merged: dict[str, CuratorRule] = {}

    for name, rule in system_rules.items():
        merged[name] = rule

    for name, rule in org_rules.items():
        if name in merged and merged[name].override:
            continue  # System rule is protected — cannot be replaced
        merged[name] = rule

    for name, rule in user_rules.items():
        if name in merged and merged[name].override:
            continue  # Higher-layer rule is protected — cannot be replaced
        merged[name] = rule

    sorted_rules = sorted(
        merged.values(),
        key=lambda r: (_TIER_ORDER.get(r.tier, 99), r.priority),
    )
    return sorted_rules


async def create_rule(
    data: CuratorRuleCreate,
    session: AsyncSession,
    *,
    tenant_id: str,
) -> CuratorRule:
    """Create a new curation rule and persist it.

    ``tenant_id`` is a required keyword argument. Curation rules are
    per-tenant: a tenant A rule never affects tenant B writes. The tool
    layer must resolve the caller's tenant from JWT claims (via
    ``get_tenant_filter``) and pass it here.
    """
    rule = CuratorRule(
        id=uuid.uuid4(),
        name=data.name,
        description=data.description,
        trigger=data.trigger,
        tier=data.tier,
        config=data.config,
        action=data.action,
        scope_filter=data.scope_filter,
        layer=data.layer,
        owner_id=data.owner_id,
        tenant_id=tenant_id,
        override=data.override,
        enabled=data.enabled,
        priority=data.priority,
    )
    session.add(rule)
    await session.commit()
    await session.refresh(rule)
    return rule


async def seed_default_rules(
    session: AsyncSession,
    *,
    tenant_id: str = "default",
) -> int:
    """Seed default system rules for ``tenant_id`` if not already present.

    Returns the number of rules inserted, or 0 if this tenant is already
    seeded. Phase 4 (#46) makes rules tenant-scoped, so seeding is now
    per-tenant -- every tenant receives its own copy of the system rules
    on first write, and ``load_rules`` filters by tenant so cross-tenant
    rules never fire.

    The default value of ``tenant_id="default"`` preserves backwards
    compatibility with callers that predate the tenant parameter,
    including the integration harness that seeds rules before any
    per-tenant activity occurs.
    """
    stmt = (
        select(CuratorRule)
        .where(
            CuratorRule.layer == "system",
            CuratorRule.tenant_id == tenant_id,
        )
        .limit(1)
    )
    result = await session.execute(stmt)
    if result.scalar_one_or_none() is not None:
        return 0

    defaults = [
        CuratorRule(
            id=uuid.uuid4(),
            name="secrets_scan",
            description="Scan for API keys, tokens, private keys, and other secrets",
            trigger="on_write",
            tier="regex",
            config={"pattern_set": "secrets"},
            action="quarantine",
            scope_filter=None,
            layer="system",
            owner_id=None,
            tenant_id=tenant_id,
            override=True,
            enabled=True,
            priority=0,
        ),
        CuratorRule(
            id=uuid.uuid4(),
            name="pii_scan",
            description="Scan for personally identifiable information (SSN, email, phone)",
            trigger="on_write",
            tier="regex",
            config={"pattern_set": "pii"},
            action="flag",
            scope_filter=None,
            layer="system",
            owner_id=None,
            tenant_id=tenant_id,
            override=True,
            enabled=True,
            priority=1,
        ),
        CuratorRule(
            id=uuid.uuid4(),
            name="exact_duplicate",
            description="Reject near-exact duplicates (cosine similarity > 0.98)",
            trigger="on_write",
            tier="embedding",
            config={"threshold": 0.98},
            action="reject_with_pointer",
            scope_filter=None,
            layer="system",
            owner_id=None,
            tenant_id=tenant_id,
            override=False,
            enabled=True,
            priority=0,
        ),
        CuratorRule(
            id=uuid.uuid4(),
            name="near_duplicate",
            description="Flag possible duplicates (cosine similarity 0.80-0.90) and gate writes",
            trigger="on_write",
            tier="embedding",
            config={"similarity_range": [0.80, 0.90], "gate_threshold": 0.90},
            action="flag",
            scope_filter=None,
            layer="system",
            owner_id=None,
            tenant_id=tenant_id,
            override=False,
            enabled=True,
            priority=1,
        ),
        CuratorRule(
            id=uuid.uuid4(),
            name="staleness_trigger",
            description="Flag memories with high contradiction counts",
            trigger="on_contradiction_count",
            tier="regex",
            config={"threshold": 5},
            action="flag",
            scope_filter=None,
            layer="system",
            owner_id=None,
            tenant_id=tenant_id,
            override=False,
            enabled=True,
            priority=0,
        ),
    ]

    session.add_all(defaults)
    await session.commit()
    return len(defaults)
