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
) -> list[CuratorRule]:
    """Load and merge rules for a given trigger context.

    Loads all enabled rules matching the trigger, merges layers with
    user > org > system precedence, then returns them sorted by tier
    (regex first) then priority (lower number = higher priority).

    A higher-layer rule marked override=True cannot be replaced by a
    lower-layer rule with the same name.
    """
    stmt = (
        select(CuratorRule)
        .where(
            and_(
                CuratorRule.enabled.is_(True),
                CuratorRule.trigger == trigger,
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
        if rule.scope_filter is not None and scope is not None:
            if rule.scope_filter != scope:
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
) -> CuratorRule:
    """Create a new curation rule and persist it."""
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
        override=data.override,
        enabled=data.enabled,
        priority=data.priority,
    )
    session.add(rule)
    await session.commit()
    await session.refresh(rule)
    return rule


async def seed_default_rules(session: AsyncSession) -> int:
    """Seed default system rules if they have not been created yet.

    Returns the number of rules inserted, or 0 if already seeded.
    """
    stmt = select(CuratorRule).where(CuratorRule.layer == "system").limit(1)
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
            override=True,
            enabled=True,
            priority=1,
        ),
        CuratorRule(
            id=uuid.uuid4(),
            name="exact_duplicate",
            description="Reject near-exact duplicates (cosine similarity > 0.95)",
            trigger="on_write",
            tier="embedding",
            config={"threshold": 0.95},
            action="reject_with_pointer",
            scope_filter=None,
            layer="system",
            owner_id=None,
            override=False,
            enabled=True,
            priority=0,
        ),
        CuratorRule(
            id=uuid.uuid4(),
            name="near_duplicate",
            description="Flag possible duplicates (cosine similarity 0.80-0.95)",
            trigger="on_write",
            tier="embedding",
            config={"similarity_range": [0.80, 0.95]},
            action="flag",
            scope_filter=None,
            layer="system",
            owner_id=None,
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
            override=False,
            enabled=True,
            priority=0,
        ),
    ]

    session.add_all(defaults)
    await session.commit()
    return len(defaults)
