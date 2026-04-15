"""Curation pipeline — orchestrates Tier 1 (regex) and Tier 2 (embedding) checks.

The pipeline is called inside write_memory before the memory is persisted. Every
check is deterministic and fast: regex in microseconds, one pgvector query in
milliseconds. No LLM calls happen on the write path.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from memoryhub_core.models.memory import MemoryNode
from memoryhub_core.services.curation.rules import load_rules, seed_default_rules
from memoryhub_core.services.curation.scanner import scan_content, scan_with_custom_patterns
from memoryhub_core.services.curation.similarity import check_similarity

# Actions that immediately halt the pipeline and block the write.
_TERMINAL_ACTIONS = {"block", "quarantine", "reject_with_pointer"}

# Set of tenant_ids that have had their default rules seeded in this
# process. Phase 4 made rules tenant-scoped, so each tenant gets its own
# lazy-seed on first write. Pre-Phase-4 this was a single boolean flag;
# the set form preserves the idempotency guarantee (each tenant seeds at
# most once in-process) while supporting an arbitrary number of tenants.
# Concurrent first-writes in the same tenant may both call
# seed_default_rules -- that's fine because the function is idempotent
# (it checks for existing system rules in the tenant before inserting).
_seeded_tenants: set[str] = set()


async def run_curation_pipeline(
    content: str,
    embedding: list[float] | None,
    owner_id: str,
    scope: str,
    session: AsyncSession,
    *,
    tenant_id: str,
    reject_threshold: float = 0.98,
    flag_threshold: float = 0.80,
    gate_threshold: float = 0.90,
    force: bool = False,
) -> dict:
    """Run the full inline curation pipeline on a pending memory write.

    Returns a dict that maps directly onto the CurationResult schema:
    {
        "blocked": bool,
        "reason": str | None,
        "detail": str | None,
        "similar_count": int,
        "nearest_id": uuid.UUID | None,
        "nearest_score": float | None,
        "flags": list[str],
    }

    When ``blocked=True`` and ``gated=True``, the caller should prompt the
    user to confirm or update the existing memory rather than writing a
    duplicate. The response includes ``existing_memory_id``,
    ``existing_memory_stub``, and ``recommendation="update_existing"`` to
    support this flow. When ``blocked=True`` and ``gated`` is absent (or
    False), the write is hard-blocked (regex match, policy, etc.).

    Pass ``force=True`` to bypass the gate (near-duplicate and exact-duplicate
    similarity checks). Tier 1 regex checks (secrets, PII, etc.) are never
    bypassed by ``force``.

    When blocked=True, the caller must not persist the memory.

    Tenant isolation: ``tenant_id`` is a required keyword argument.
    Curation rules, the seed step, and the similarity scan are all
    scoped to the caller's tenant -- a tenant-A write can never be
    blocked by a tenant-B rule, nor can it see a tenant-B near-duplicate
    in ``similar_count``/``nearest_id``. Phase 4 (#46).
    """
    if tenant_id not in _seeded_tenants:
        await seed_default_rules(session, tenant_id=tenant_id)
        _seeded_tenants.add(tenant_id)

    flags: list[str] = []
    rules = await load_rules(
        trigger="on_write",
        owner_id=owner_id,
        scope=scope,
        session=session,
        tenant_id=tenant_id,
    )

    # --- Tier 1: Regex scanning ---

    for rule in rules:
        if rule.tier != "regex":
            continue

        config = rule.config or {}
        pattern_set = config.get("pattern_set")
        blocked_result = _apply_regex_rule(rule, content, pattern_set, config, flags)
        if blocked_result is not None:
            return blocked_result

    # --- Tier 2: Embedding similarity ---

    similar_count = 0
    nearest_id: uuid.UUID | None = None
    nearest_score: float | None = None

    if embedding is not None:
        # Allow rule config to override the caller-supplied thresholds.
        reject_threshold, flag_threshold, gate_threshold = _resolve_embedding_thresholds(
            rules, reject_threshold, flag_threshold, gate_threshold
        )

        sim = await check_similarity(
            embedding=embedding,
            owner_id=owner_id,
            scope=scope,
            session=session,
            tenant_id=tenant_id,
            flag_threshold=flag_threshold,
        )

        similar_count = sim.similar_count
        nearest_id = sim.nearest_id
        nearest_score = sim.nearest_score

        if nearest_score is not None and not force:
            if nearest_score >= reject_threshold:
                return await _gated("exact_duplicate", nearest_id, nearest_score, similar_count, session)
            elif nearest_score >= gate_threshold:
                return await _gated("near_duplicate", nearest_id, nearest_score, similar_count, session)

        if similar_count > 0:
            flags.append("possible_duplicate")

    return {
        "blocked": False,
        "reason": None,
        "detail": None,
        "similar_count": similar_count,
        "nearest_id": nearest_id,
        "nearest_score": nearest_score,
        "flags": flags,
    }


# -- Helpers --


def _apply_regex_rule(rule, content: str, pattern_set: str | None, config: dict, flags: list[str]) -> dict | None:
    """Evaluate one regex-tier rule against content.

    Mutates flags in place for advisory (flag) actions.
    Returns a blocked result dict when the action is terminal, else None.
    """
    if pattern_set in ("secrets", "pii"):
        scan_results = scan_content(content, pattern_set=pattern_set)
        for scan_result in scan_results:
            if rule.action in _TERMINAL_ACTIONS:
                return _blocked(rule.name, scan_result.detail)
            elif rule.action == "flag":
                flags.append(f"{rule.name}:{scan_result.pattern_name}")

    elif "pattern" in config:
        custom_results = scan_with_custom_patterns(
            content, {rule.name: config["pattern"]}
        )
        for scan_result in custom_results:
            if rule.action in _TERMINAL_ACTIONS:
                return _blocked(rule.name, scan_result.detail)
            elif rule.action == "flag":
                flags.append(f"{rule.name}:{scan_result.pattern_name}")

    return None


def _resolve_embedding_thresholds(
    rules: list,
    reject_threshold: float,
    flag_threshold: float,
    gate_threshold: float,
) -> tuple[float, float, float]:
    """Extract threshold overrides from embedding-tier rules.

    Only the first matching config key wins (rules are already sorted by priority).
    Returns ``(reject_threshold, flag_threshold, gate_threshold)``.
    """
    for rule in rules:
        if rule.tier != "embedding":
            continue
        config = rule.config or {}
        if rule.name == "exact_duplicate" and "threshold" in config:
            reject_threshold = float(config["threshold"])
        elif rule.name == "near_duplicate" and "similarity_range" in config:
            flag_threshold = float(config["similarity_range"][0])
            if "gate_threshold" in config:
                gate_threshold = float(config["gate_threshold"])
    return reject_threshold, flag_threshold, gate_threshold


async def _gated(
    reason: str,
    nearest_id: uuid.UUID,
    nearest_score: float,
    similar_count: int,
    session: AsyncSession,
) -> dict:
    """Build a gated-write response that asks the caller to update an existing memory.

    Fetches the existing memory's stub text so the agent can present a
    meaningful "did you mean this?" prompt rather than a bare UUID.
    """
    stub: str | None = None
    try:
        result = await session.execute(
            select(MemoryNode.stub).where(MemoryNode.id == nearest_id)
        )
        row = result.scalar_one_or_none()
        if row is not None:
            stub = str(row)
    except Exception:
        pass  # Non-blocking; a missing stub is cosmetic, not fatal

    return {
        "blocked": True,
        "gated": True,
        "reason": reason,
        "detail": f"Memory is {nearest_score:.0%} similar to existing memory {nearest_id}",
        "similar_count": similar_count,
        "nearest_id": nearest_id,
        "nearest_score": nearest_score,
        "existing_memory_id": str(nearest_id),
        "existing_memory_stub": stub,
        "recommendation": "update_existing",
        "flags": [],
    }


def _blocked(reason: str, detail: str | None) -> dict:
    return {
        "blocked": True,
        "reason": reason,
        "detail": detail,
        "similar_count": 0,
        "nearest_id": None,
        "nearest_score": None,
        "flags": [],
    }
