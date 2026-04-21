"""Consolidated curation management tool.

Replaces report_contradiction and set_curation_rule with a single action-
dispatch interface, and adds resolve_contradiction for closing out reports.
"""

import logging
import uuid
from typing import Annotated, Any

from fastmcp import Context
from fastmcp.exceptions import ToolError
from pydantic import Field
from sqlalchemy import and_, select

from src.core.app import mcp
from src.core.authz import (
    AuthenticationError,
    authorize_read,
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
from memoryhub_core.services.campaign import get_campaigns_for_project
from memoryhub_core.services.curation.rules import create_rule
from memoryhub_core.services.exceptions import (
    ContradictionNotFoundError,
    MemoryNotFoundError,
)
from memoryhub_core.services.memory import (
    read_memory as _read_memory,
    report_contradiction as _report_contradiction,
    resolve_contradiction as _resolve_contradiction,
    VALID_RESOLUTION_ACTIONS,
)
from memoryhub_core.services.project import get_projects_for_user
from memoryhub_core.services.role import get_roles_for_user

logger = logging.getLogger(__name__)

CONTRADICTION_THRESHOLD = 5

_VALID_TIERS = [t.value for t in RuleTier]
_VALID_ACTIONS_RULE = [a.value for a in RuleAction]

_VALID_ACTIONS = {"report_contradiction", "resolve_contradiction", "set_rule"}


@mcp.tool(
    annotations={
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    }
)
async def manage_curation(
    action: Annotated[
        str,
        Field(
            description=(
                "The curation operation to perform. One of: "
                "'report_contradiction' (signal that observed behavior conflicts "
                "with a stored memory), "
                "'resolve_contradiction' (close out a contradiction report with "
                "a disposition), "
                "'set_rule' (create or update a user-layer curation rule)."
            ),
        ),
    ],
    # --- report_contradiction params ---
    memory_id: Annotated[
        str | None,
        Field(
            description=(
                "action='report_contradiction': The ID of the memory that "
                "appears to be contradicted."
            ),
        ),
    ] = None,
    observed_behavior: Annotated[
        str | None,
        Field(
            description=(
                "action='report_contradiction': Description of what was "
                "observed that conflicts with the memory. Be specific: "
                "'User created a Docker Compose project with 12 services' "
                "not just 'used Docker'."
            ),
        ),
    ] = None,
    confidence: Annotated[
        float,
        Field(
            ge=0.0,
            le=1.0,
            description=(
                "action='report_contradiction': How confident the agent is "
                "that this is a real contradiction (0.0-1.0). Temporary "
                "exceptions warrant lower confidence. Repeated, consistent "
                "contradictions warrant higher."
            ),
        ),
    ] = 0.7,
    project_id: Annotated[
        str | None,
        Field(
            description=(
                "action='report_contradiction': Your project identifier. "
                "Required when the target memory has campaign scope — used to "
                "verify your project is enrolled in the campaign."
            ),
        ),
    ] = None,
    # --- resolve_contradiction params ---
    contradiction_id: Annotated[
        str | None,
        Field(
            description=(
                "action='resolve_contradiction': UUID of the contradiction "
                "report to resolve."
            ),
        ),
    ] = None,
    resolution_action: Annotated[
        str | None,
        Field(
            description=(
                "action='resolve_contradiction': Disposition for the report. "
                "One of: 'accept_new' (the new observation supersedes the "
                "memory), 'keep_old' (the memory stands; observation was an "
                "exception), 'mark_both_invalid' (neither is authoritative), "
                "'manual_merge' (a human will reconcile manually)."
            ),
        ),
    ] = None,
    resolution_note: Annotated[
        str | None,
        Field(
            description=(
                "action='resolve_contradiction': Optional rationale for the "
                "resolution, for audit purposes."
            ),
        ),
    ] = None,
    # --- set_rule params ---
    name: Annotated[
        str | None,
        Field(
            description=(
                "action='set_rule': Rule name, used as the unique identifier "
                "within your rules."
            ),
        ),
    ] = None,
    tier: Annotated[
        str,
        Field(description="action='set_rule': Rule tier: 'regex' or 'embedding'."),
    ] = "embedding",
    action_type: Annotated[
        str,
        Field(
            description=(
                "action='set_rule': Action on match: 'flag', 'block', "
                "'quarantine', 'reject_with_pointer', 'decay_weight'."
            ),
        ),
    ] = "flag",
    config: Annotated[
        dict[str, Any] | None,
        Field(
            description=(
                "action='set_rule': Tier-specific config. "
                'For embedding: {"threshold": float}. '
                'For regex: {"pattern": string}.'
            ),
        ),
    ] = None,
    scope_filter: Annotated[
        str | None,
        Field(
            description=(
                "action='set_rule': Scope this rule applies to "
                "(user, project, etc). Null for all scopes."
            ),
        ),
    ] = None,
    enabled: Annotated[
        bool,
        Field(description="action='set_rule': Whether this rule is active."),
    ] = True,
    priority: Annotated[
        int,
        Field(
            ge=0,
            description=(
                "action='set_rule': Evaluation priority (lower = higher "
                "priority). Default: 10."
            ),
        ),
    ] = 10,
    ctx: Context = None,
) -> dict[str, Any]:
    """Manage memory curation: report contradictions, resolve them, or tune rules.

    Three actions in one tool:

    report_contradiction — When an agent notices the user doing something that
    conflicts with a stored preference (e.g., using Docker when the memory says
    "prefers Podman"), report the contradiction. After enough reports accumulate,
    the curator triggers a revision prompt asking the user to review the memory.

    resolve_contradiction — Close out a contradiction report with a disposition:
    accept_new (observation supersedes memory), keep_old (memory stands),
    mark_both_invalid, or manual_merge. Requires the contradiction UUID from a
    prior report_contradiction response.

    set_rule — Create or update a user-layer curation rule to tune duplicate
    detection thresholds or other curation behaviors. Rules you create only
    affect your own memories and cannot override protected system rules.
    """
    if action not in _VALID_ACTIONS:
        raise ToolError(
            f"Invalid action '{action}'. Must be one of: "
            f"{', '.join(sorted(_VALID_ACTIONS))}."
        )

    try:
        claims = get_claims_from_context()
    except AuthenticationError as exc:
        raise ToolError(str(exc)) from exc

    if action == "report_contradiction":
        return await _handle_report_contradiction(
            claims=claims,
            memory_id=memory_id,
            observed_behavior=observed_behavior,
            confidence=confidence,
            project_id=project_id,
            ctx=ctx,
        )

    if action == "resolve_contradiction":
        return await _handle_resolve_contradiction(
            claims=claims,
            contradiction_id=contradiction_id,
            resolution_action=resolution_action,
            resolution_note=resolution_note,
            ctx=ctx,
        )

    # set_rule
    return await _handle_set_rule(
        claims=claims,
        name=name,
        tier=tier,
        action_type=action_type,
        config=config,
        scope_filter=scope_filter,
        enabled=enabled,
        priority=priority,
        ctx=ctx,
    )


async def _handle_report_contradiction(
    claims: dict[str, Any],
    memory_id: str | None,
    observed_behavior: str | None,
    confidence: float,
    project_id: str | None,
    ctx: Context | None,
) -> dict[str, Any]:
    if not memory_id or not memory_id.strip():
        raise ToolError(
            "action='report_contradiction' requires memory_id. "
            "Provide the UUID of the memory being contradicted."
        )
    if not observed_behavior or not observed_behavior.strip():
        raise ToolError(
            "observed_behavior cannot be empty. Describe what was observed "
            "that conflicts with the memory."
        )

    try:
        parsed_memory_id = uuid.UUID(memory_id)
    except ValueError:
        raise ToolError(
            f"Invalid memory_id format: '{memory_id}'. "
            "Provide a valid UUID (e.g., '550e8400-e29b-41d4-a716-446655440000')."
        )

    if ctx:
        await ctx.info(
            f"Reporting contradiction against memory {memory_id} "
            f"(confidence: {confidence})"
        )

    reporter = claims["sub"]
    tenant = get_tenant_filter(claims)

    session, gen = await get_db_session()
    try:
        target_memory = await _read_memory(parsed_memory_id, session, tenant_id=tenant)

        campaign_ids: set[str] | None = None
        if target_memory.scope == "campaign":
            if not project_id:
                raise ToolError(
                    "project_id is required when reporting a contradiction against a "
                    "campaign-scoped memory. Set it to your project identifier "
                    "so enrollment can be verified."
                )
            campaign_ids = await get_campaigns_for_project(session, project_id, tenant)

        project_ids: set[str] | None = None
        if target_memory.scope == "project":
            project_ids = await get_projects_for_user(session, claims["sub"])

        role_names: set[str] | None = None
        if target_memory.scope == "role":
            role_names = await get_roles_for_user(
                session, claims["sub"], tenant, claims=claims,
            )

        if not authorize_read(
            claims, target_memory,
            campaign_ids=campaign_ids,
            project_ids=project_ids,
            role_names=role_names,
        ):
            raise ToolError(f"Not authorized to access memory {memory_id}.")

        contradiction_count = await _report_contradiction(
            memory_id=parsed_memory_id,
            observed_behavior=observed_behavior,
            confidence=confidence,
            reporter=reporter,
            session=session,
        )

        revision_triggered = contradiction_count >= CONTRADICTION_THRESHOLD

        if revision_triggered:
            message = (
                f"Contradiction recorded ({contradiction_count} of "
                f"{CONTRADICTION_THRESHOLD} threshold). A revision prompt "
                "will be triggered — the user will be asked to review this memory."
            )
        else:
            message = (
                f"Contradiction recorded ({contradiction_count} of "
                f"{CONTRADICTION_THRESHOLD} threshold). "
                f"{CONTRADICTION_THRESHOLD - contradiction_count} more "
                "before a revision prompt is triggered."
            )

        return {
            "memory_id": memory_id,
            "contradiction_count": contradiction_count,
            "threshold": CONTRADICTION_THRESHOLD,
            "revision_triggered": revision_triggered,
            "message": message,
        }

    except ToolError:
        raise
    except MemoryNotFoundError:
        raise ToolError(
            f"Memory {memory_id} not found. "
            "It may have been deleted, or you may not have access to this "
            "memory's scope."
        )
    finally:
        await release_db_session(gen)


async def _handle_resolve_contradiction(
    claims: dict[str, Any],
    contradiction_id: str | None,
    resolution_action: str | None,
    resolution_note: str | None,
    ctx: Context | None,
) -> dict[str, Any]:
    if not contradiction_id or not contradiction_id.strip():
        raise ToolError(
            "action='resolve_contradiction' requires contradiction_id. "
            "Provide the UUID of the contradiction report to resolve."
        )
    if not resolution_action or not resolution_action.strip():
        raise ToolError(
            "action='resolve_contradiction' requires resolution_action. "
            f"Must be one of: {', '.join(sorted(VALID_RESOLUTION_ACTIONS))}."
        )

    try:
        parsed_id = uuid.UUID(contradiction_id)
    except ValueError:
        raise ToolError(
            f"Invalid contradiction_id format: '{contradiction_id}'. "
            "Provide a valid UUID."
        )

    if resolution_action not in VALID_RESOLUTION_ACTIONS:
        raise ToolError(
            f"Invalid resolution_action '{resolution_action}'. "
            f"Must be one of: {', '.join(sorted(VALID_RESOLUTION_ACTIONS))}."
        )

    user_id = claims["sub"]

    if ctx:
        await ctx.info(
            f"Resolving contradiction {contradiction_id} "
            f"(resolution_action={resolution_action})"
        )

    session, gen = await get_db_session()
    try:
        report = await _resolve_contradiction(
            parsed_id,
            session,
            resolution_action=resolution_action,
            actor_id=user_id,
        )

        return {
            "contradiction_id": str(report.id),
            "resolved": True,
            "resolved_at": report.resolved_at.isoformat() if report.resolved_at else None,
            "resolution_action": report.resolution_action,
            "resolved_by": report.resolved_by,
            "message": (
                f"Contradiction resolved with disposition '{resolution_action}'."
                + (f" Note: {resolution_note}" if resolution_note else "")
            ),
        }

    except ContradictionNotFoundError:
        raise ToolError(f"Contradiction {contradiction_id} not found.")
    except ValueError as exc:
        raise ToolError(str(exc)) from exc
    finally:
        await release_db_session(gen)


async def _handle_set_rule(
    claims: dict[str, Any],
    name: str | None,
    tier: str,
    action_type: str,
    config: dict[str, Any] | None,
    scope_filter: str | None,
    enabled: bool,
    priority: int,
    ctx: Context | None,
) -> dict[str, Any]:
    if not name or not name.strip():
        raise ToolError(
            "action='set_rule' requires name. "
            "Provide a unique rule name."
        )

    if tier not in _VALID_TIERS:
        raise ToolError(
            f"Invalid tier {tier!r}. Must be one of: {', '.join(_VALID_TIERS)}."
        )

    if action_type not in _VALID_ACTIONS_RULE:
        raise ToolError(
            f"Invalid action_type {action_type!r}. "
            f"Must be one of: {', '.join(_VALID_ACTIONS_RULE)}."
        )

    if ctx:
        await ctx.info(
            f"Setting curation rule {name!r} (tier={tier}, action_type={action_type})"
        )

    owner_id = claims["sub"]
    tenant_id = get_tenant_filter(claims)
    resolved_config = config or {}

    gen = None
    try:
        session, gen = await get_db_session()

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
            raise ToolError(
                f"Cannot override system rule {name!r} — it is protected "
                "by the platform administrator."
            )

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
            existing.action = action_type
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

        rule_data = CuratorRuleCreate(
            name=name,
            trigger=RuleTrigger.ON_WRITE,
            tier=RuleTier(tier),
            action=RuleAction(action_type),
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

    except ToolError:
        raise
    except Exception as exc:
        logger.error("Failed to set curation rule %r: %s", name, exc, exc_info=True)
        raise ToolError(
            f"Failed to set curation rule {name!r}. See server logs for details."
        ) from exc
    finally:
        if gen is not None:
            await release_db_session(gen)
