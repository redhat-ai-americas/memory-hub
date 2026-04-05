"""Unit tests for the curation rules engine and the inline pipeline.

Uses an in-memory SQLite database (same pattern as test_memory_service.py).
pgvector-specific similarity checks fall back to returning zero results on SQLite,
so pipeline tests with embeddings only verify the fallback path is clean.
"""

import pytest

from memoryhub.models.schemas import (
    CuratorRuleCreate,
    RuleAction,
    RuleLayer,
    RuleTier,
    RuleTrigger,
)
import memoryhub.services.curation.pipeline as curation_pipeline
from memoryhub.services.curation.pipeline import run_curation_pipeline
from memoryhub.services.curation.rules import create_rule, load_rules, seed_default_rules


# -- Helper --


def _make_rule_create(**overrides) -> CuratorRuleCreate:
    """Build a CuratorRuleCreate with sensible defaults for user-layer rules."""
    defaults = {
        "name": "test_rule",
        "trigger": RuleTrigger.ON_WRITE,
        "tier": RuleTier.REGEX,
        "config": {},
        "action": RuleAction.FLAG,
        "layer": RuleLayer.USER,
        "owner_id": "user-123",
        "priority": 10,
    }
    defaults.update(overrides)
    return CuratorRuleCreate(**defaults)


# -- seed_default_rules --


async def test_seed_default_rules(async_session):
    count = await seed_default_rules(async_session)
    assert count == 5


async def test_seed_default_rules_idempotent(async_session):
    first = await seed_default_rules(async_session)
    second = await seed_default_rules(async_session)
    assert first == 5
    assert second == 0  # Already seeded — nothing inserted


# -- load_rules --


async def test_load_rules_filters_by_trigger(async_session):
    await seed_default_rules(async_session)

    rules = await load_rules(
        trigger="on_write",
        owner_id="user-123",
        scope=None,
        session=async_session,
    )

    names = [r.name for r in rules]
    assert "secrets_scan" in names
    assert "pii_scan" in names
    # staleness_trigger fires on a different trigger — must not appear
    assert "staleness_trigger" not in names


async def test_load_rules_user_overrides_system(async_session):
    """A user rule with the same name as a system rule wins when system override=False."""
    await seed_default_rules(async_session)

    # exact_duplicate is a system rule with override=False — user can override it
    user_rule = _make_rule_create(
        name="exact_duplicate",
        tier=RuleTier.EMBEDDING,
        action=RuleAction.FLAG,
        config={"threshold": 0.98},
        layer=RuleLayer.USER,
        owner_id="user-123",
        priority=5,
    )
    await create_rule(user_rule, async_session)

    rules = await load_rules(
        trigger="on_write",
        owner_id="user-123",
        scope=None,
        session=async_session,
    )

    exact = next((r for r in rules if r.name == "exact_duplicate"), None)
    assert exact is not None
    assert exact.layer == "user"
    assert exact.config["threshold"] == 0.98


async def test_load_rules_override_protects_system(async_session):
    """A system rule with override=True blocks a user rule with the same name."""
    await seed_default_rules(async_session)

    # secrets_scan is a system rule with override=True — user cannot replace it
    user_rule = _make_rule_create(
        name="secrets_scan",
        tier=RuleTier.REGEX,
        action=RuleAction.FLAG,  # weaker action than system's quarantine
        config={"pattern_set": "secrets"},
        layer=RuleLayer.USER,
        owner_id="user-123",
        priority=5,
    )
    await create_rule(user_rule, async_session)

    rules = await load_rules(
        trigger="on_write",
        owner_id="user-123",
        scope=None,
        session=async_session,
    )

    secrets = next((r for r in rules if r.name == "secrets_scan"), None)
    assert secrets is not None
    # System rule must win — action should still be quarantine, not flag
    assert secrets.layer == "system"
    assert secrets.action == "quarantine"


# -- create_rule --


async def test_create_rule(async_session):
    data = _make_rule_create(
        name="my_custom_rule",
        description="Catch internal ticket references",
        config={"pattern": r"JIRA-\d+"},
        priority=20,
    )
    rule = await create_rule(data, async_session)

    assert rule.id is not None
    assert rule.name == "my_custom_rule"
    assert rule.description == "Catch internal ticket references"
    assert rule.layer == "user"
    assert rule.owner_id == "user-123"
    assert rule.priority == 20
    assert rule.enabled is True


# -- pipeline integration --


async def test_pipeline_blocks_secrets(async_session):
    await seed_default_rules(async_session)

    content = "My AWS key is AKIA1234567890ABCDEF — keep it secret!"
    result = await run_curation_pipeline(
        content=content,
        embedding=None,
        owner_id="user-123",
        scope="user",
        session=async_session,
    )

    assert result["blocked"] is True
    assert result["reason"] == "secrets_scan"
    assert result["detail"] is not None
    assert "aws_access_key" in result["detail"]


async def test_pipeline_flags_pii(async_session):
    await seed_default_rules(async_session)

    content = "Contact me at user@example.com for details."
    result = await run_curation_pipeline(
        content=content,
        embedding=None,
        owner_id="user-123",
        scope="user",
        session=async_session,
    )

    assert result["blocked"] is False
    assert "pii_scan:email" in result["flags"]


async def test_pipeline_clean_content(async_session):
    await seed_default_rules(async_session)

    content = "I prefer Podman over Docker for all container workloads."
    result = await run_curation_pipeline(
        content=content,
        embedding=None,
        owner_id="user-123",
        scope="user",
        session=async_session,
    )

    assert result["blocked"] is False
    assert result["reason"] is None
    assert result["flags"] == []
    assert result["similar_count"] == 0


async def test_pipeline_passes_without_embedding(async_session):
    """When embedding is None and content is clean, pipeline returns a clean zero-similarity result."""
    await seed_default_rules(async_session)

    result = await run_curation_pipeline(
        content="Uses FastAPI for REST APIs.",
        embedding=None,
        owner_id="user-456",
        scope="project",
        session=async_session,
    )

    assert result["blocked"] is False
    assert result["similar_count"] == 0
    assert result["nearest_id"] is None
    assert result["nearest_score"] is None
    assert result["flags"] == []


# -- lazy seeding via pipeline --


@pytest.fixture(autouse=False)
def reset_rules_seeded():
    """Reset the module-level _rules_seeded flag before and after each test that uses it."""
    curation_pipeline._rules_seeded = False
    yield
    curation_pipeline._rules_seeded = False


async def test_pipeline_seeds_rules_on_first_call(async_session, reset_rules_seeded):
    """run_curation_pipeline seeds default rules automatically when the DB is empty."""
    # DB is empty — no manual seed call
    rules_before = await load_rules(
        trigger="on_write", owner_id="user-123", scope=None, session=async_session
    )
    assert rules_before == [], f"Expected empty rules table, got {rules_before}"

    result = await run_curation_pipeline(
        content="I prefer Podman over Docker.",
        embedding=None,
        owner_id="user-123",
        scope="user",
        session=async_session,
    )

    assert result["blocked"] is False, f"Unexpected block: {result}"
    assert curation_pipeline._rules_seeded is True

    # Rules must now be present in the DB
    rules_after = await load_rules(
        trigger="on_write", owner_id="user-123", scope=None, session=async_session
    )
    assert len(rules_after) > 0, "Expected seeded rules after first pipeline call"


async def test_pipeline_sets_seeded_flag(async_session, reset_rules_seeded):
    """_rules_seeded is False before the call and True after."""
    assert curation_pipeline._rules_seeded is False

    await run_curation_pipeline(
        content="Clean content with no issues.",
        embedding=None,
        owner_id="user-123",
        scope="user",
        session=async_session,
    )

    assert curation_pipeline._rules_seeded is True


async def test_pipeline_skips_seed_on_second_call(async_session, reset_rules_seeded, monkeypatch):
    """seed_default_rules is called exactly once across multiple pipeline invocations."""
    call_count = 0

    async def _counting_seed(session):
        nonlocal call_count
        call_count += 1
        return await seed_default_rules(session)

    monkeypatch.setattr(curation_pipeline, "seed_default_rules", _counting_seed)

    await run_curation_pipeline(
        content="First write.",
        embedding=None,
        owner_id="user-123",
        scope="user",
        session=async_session,
    )
    await run_curation_pipeline(
        content="Second write.",
        embedding=None,
        owner_id="user-123",
        scope="user",
        session=async_session,
    )

    assert call_count == 1, (
        f"seed_default_rules should be called once, was called {call_count} time(s)"
    )


async def test_pipeline_seed_idempotent_when_rules_exist(async_session, reset_rules_seeded):
    """If rules already exist when the flag is False, seed_default_rules returns 0 and doesn't duplicate."""
    # Pre-seed manually to simulate a populated DB after a restart
    await seed_default_rules(async_session)

    # Flag is still False (simulating a fresh process restart)
    assert curation_pipeline._rules_seeded is False

    result = await run_curation_pipeline(
        content="Clean content.",
        embedding=None,
        owner_id="user-123",
        scope="user",
        session=async_session,
    )

    assert result["blocked"] is False
    assert curation_pipeline._rules_seeded is True

    # Rule count must not have doubled
    rules = await load_rules(
        trigger="on_write", owner_id="user-123", scope=None, session=async_session
    )
    rule_names = [r.name for r in rules]
    assert rule_names.count("secrets_scan") == 1, "secrets_scan must not be duplicated"
