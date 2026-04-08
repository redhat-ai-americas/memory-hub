"""Create or update a user-layer curation rule."""

from typing import Annotated, Any

from fastmcp import Context
from pydantic import Field
from sqlalchemy import and_, select

from src.core.app import mcp
from src.core.authz import (
    AuthenticationError,
    get_claims_from_context,
    get_tenant_filter,
)
from src.tools._deps import get_db_session, release_db_session

from memoryhub_core.models.curation import CuratorRule
from memoryhub_core.models.schemas import (
    CuratorRuleCreate,
    CuratorRuleRead,
    RuleAction,
    RuleLayer,
    RuleTier,
    RuleTrigger,
)
from memoryhub_core.services.curation.rules import create_rule

_VALID_TIERS = [t.value for t in RuleTier]
_VALID_ACTIONS = [a.value for a in RuleAction]


@mcp.tool(
    annotations={
        "readOnlyHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    }
)
async def set_curation_rule(
    name: Annotated[
        str,
        Field(description="Rule name. Used as the unique identifier within your rules."),
    ],
    tier: Annotated[
        str,
        Field(description="Rule tier: 'regex' or 'embedding'."),
    ] = "embedding",
    action: Annotated[
        str,
        Field(
            description=(
                "Action on match: 'flag', 'block', 'quarantine', "
                "'reject_with_pointer', 'decay_weight'."
            )
        ),
    ] = "flag",
    config: Annotated[
        dict[str, Any] | None,
        Field(
            description=(
                "Tier-specific config. "
                'For embedding: {"threshold": float}. '
                'For regex: {"pattern": string}.'
            )
        ),
    ] = None,
    scope_filter: Annotated[
        str | None,
        Field(description="Scope this rule applies to (user, project, etc). Null for all scopes."),
    ] = None,
    enabled: Annotated[
        bool,
        Field(description="Whether this rule is active."),
    ] = True,
    priority: Annotated[
        int,
        Field(description="Evaluation priority (lower = higher priority). Default: 10.", ge=0),
    ] = 10,
    ctx: Context = None,
) -> dict[str, Any]:
    """Create or update a user-layer curation rule.

    Use this to tune your curation preferences — for example, adjusting the
    duplicate detection threshold if you're getting false positives. Rules you
    create here only affect your own memories.

    Cannot override system rules marked as protected (like secrets scanning).
    """
    if ctx:
        await ctx.info(f"Setting curation rule {name!r} (tier={tier}, action={action})")

    try:
        claims = get_claims_from_context()
    except AuthenticationError as exc:
        return {"error": True, "message": str(exc)}

    # Admin operations require memory:admin scope or service identity
    caller_scopes = claims.get("scopes", [])
    is_admin = "memory:admin" in caller_scopes
    is_service = claims.get("identity_type") == "service"
    if not is_admin and not is_service:
        # Regular users can only manage their own user-layer rules
        pass  # allowed — user-layer rules are scoped to owner_id below

    if tier not in _VALID_TIERS:
        return {
            "error": True,
            "message": f"Invalid tier {tier!r}. Must be one of: {', '.join(_VALID_TIERS)}.",
        }

    if action not in _VALID_ACTIONS:
        return {
            "error": True,
            "message": f"Invalid action {action!r}. Must be one of: {', '.join(_VALID_ACTIONS)}.",
        }

    if not name.strip():
        return {"error": True, "message": "name cannot be empty."}

    owner_id = claims["sub"]
    tenant_id = get_tenant_filter(claims)
    resolved_config = config or {}

    gen = None
    try:
        session, gen = await get_db_session()

        # Check for protected system/org rule with this name in the caller's
        # tenant. System/org rules are still per-tenant -- a protected rule in
        # tenant A does not block user rules in tenant B.
        protected_stmt = select(CuratorRule).where(
            and_(
                CuratorRule.name == name,
                CuratorRule.layer.in_(["system", "organizational"]),
                CuratorRule.override.is_(True),
                CuratorRule.tenant_id == tenant_id,
            )
        )
        protected_result = await session.execute(protected_stmt)
        protected_rule = protected_result.scalar_one_or_none()
        if protected_rule is not None:
            return {
                "error": True,
                "message": (
                    f"Cannot override system rule {name!r} — it is protected "
                    "by the platform administrator."
                ),
            }

        # Check for existing user rule with this name (upsert). Scope by
        # tenant so tenant A's rule doesn't collide with tenant B's rule of
        # the same name.
        existing_stmt = select(CuratorRule).where(
            and_(
                CuratorRule.name == name,
                CuratorRule.layer == "user",
                CuratorRule.owner_id == owner_id,
                CuratorRule.tenant_id == tenant_id,
            )
        )
        existing_result = await session.execute(existing_stmt)
        existing = existing_result.scalar_one_or_none()

        if existing is not None:
            existing.tier = tier
            existing.action = action
            existing.config = resolved_config
            existing.scope_filter = scope_filter
            existing.enabled = enabled
            existing.priority = priority
            await session.commit()
            await session.refresh(existing)
            rule_read = CuratorRuleRead.model_validate(existing)
            return {
                "created": False,
                "updated": True,
                "rule": rule_read.model_dump(mode="json"),
            }

        # Create new user rule
        rule_data = CuratorRuleCreate(
            name=name,
            trigger=RuleTrigger.ON_WRITE,
            tier=RuleTier(tier),
            action=RuleAction(action),
            config=resolved_config,
            scope_filter=scope_filter,
            layer=RuleLayer.USER,
            owner_id=owner_id,
            override=False,
            enabled=enabled,
            priority=priority,
        )

        new_rule = await create_rule(rule_data, session, tenant_id=tenant_id)
        rule_read = CuratorRuleRead.model_validate(new_rule)
        return {
            "created": True,
            "updated": False,
            "rule": rule_read.model_dump(mode="json"),
        }

    except Exception as exc:
        return {"error": True, "message": f"Failed to set curation rule: {exc}"}
    finally:
        if gen is not None:
            await release_db_session(gen)
