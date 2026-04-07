"""Curation pipeline — orchestrates Tier 1 (regex) and Tier 2 (embedding) checks.

The pipeline is called inside write_memory before the memory is persisted. Every
check is deterministic and fast: regex in microseconds, one pgvector query in
milliseconds. No LLM calls happen on the write path.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from memoryhub_core.services.curation.rules import load_rules, seed_default_rules
from memoryhub_core.services.curation.scanner import scan_content, scan_with_custom_patterns
from memoryhub_core.services.curation.similarity import check_similarity

# Actions that immediately halt the pipeline and block the write.
_TERMINAL_ACTIONS = {"block", "quarantine", "reject_with_pointer"}

# Set to True after the first successful seed so subsequent calls skip the DB check.
# Concurrent first-writes may both call seed_default_rules — that's fine because
# the function is idempotent (checks for existing system rules before inserting).
_rules_seeded = False


async def run_curation_pipeline(
    content: str,
    embedding: list[float] | None,
    owner_id: str,
    scope: str,
    session: AsyncSession,
    reject_threshold: float = 0.95,
    flag_threshold: float = 0.80,
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

    When blocked=True, the caller must not persist the memory.
    """
    global _rules_seeded
    if not _rules_seeded:
        await seed_default_rules(session)
        _rules_seeded = True

    flags: list[str] = []
    rules = await load_rules(
        trigger="on_write",
        owner_id=owner_id,
        scope=scope,
        session=session,
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
        reject_threshold, flag_threshold = _resolve_embedding_thresholds(
            rules, reject_threshold, flag_threshold
        )

        sim = await check_similarity(
            embedding=embedding,
            owner_id=owner_id,
            scope=scope,
            session=session,
            flag_threshold=flag_threshold,
        )

        similar_count = sim.similar_count
        nearest_id = sim.nearest_id
        nearest_score = sim.nearest_score

        if nearest_score is not None and nearest_score >= reject_threshold:
            return {
                "blocked": True,
                "reason": "exact_duplicate",
                "detail": (
                    f"Memory is {nearest_score:.0%} similar to existing memory {nearest_id}"
                ),
                "similar_count": similar_count,
                "nearest_id": nearest_id,
                "nearest_score": nearest_score,
                "flags": [],
            }

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
) -> tuple[float, float]:
    """Extract threshold overrides from embedding-tier rules.

    Only the first matching config key wins (rules are already sorted by priority).
    """
    for rule in rules:
        if rule.tier != "embedding":
            continue
        config = rule.config or {}
        if rule.name == "exact_duplicate" and "threshold" in config:
            reject_threshold = float(config["threshold"])
        elif rule.name == "near_duplicate" and "similarity_range" in config:
            flag_threshold = float(config["similarity_range"][0])
    return reject_threshold, flag_threshold


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
