"""Unit tests for the curation rules engine and the inline pipeline.

Uses an in-memory SQLite database (same pattern as test_memory_service.py).
pgvector-specific similarity checks fall back to returning zero results on SQLite,
so pipeline tests with embeddings only verify the fallback path is clean.
"""

import pytest

import memoryhub_core.services.curation.pipeline as curation_pipeline
from memoryhub_core.models.schemas import (
    CuratorRuleCreate,
    RuleAction,
    RuleLayer,
    RuleTier,
    RuleTrigger,
)
from memoryhub_core.services.curation.pipeline import run_curation_pipeline as _svc_run_curation_pipeline
from memoryhub_core.services.curation.rules import (
    create_rule as _svc_create_rule,
)
from memoryhub_core.services.curation.rules import (
    load_rules as _svc_load_rules,
)
from memoryhub_core.services.curation.rules import (
    seed_default_rules as _svc_seed_default_rules,
)

# Phase 3 (#46): create_rule now requires a tenant_id kwarg. Most curation
# tests don't care which tenant owns the rule, so these wrappers supply a
# default. Phase 4 adds tenant_id to load_rules, seed_default_rules, and
# run_curation_pipeline; same pattern applies.
_TEST_TENANT_ID = "default"


async def create_rule(data, session, *, tenant_id=_TEST_TENANT_ID):
    """Test wrapper around the service create_rule with a default tenant."""
    return await _svc_create_rule(data, session, tenant_id=tenant_id)


async def load_rules(trigger, owner_id, scope, session, *, tenant_id=_TEST_TENANT_ID):
    """Test wrapper around load_rules with a default tenant."""
    return await _svc_load_rules(
        trigger=trigger,
        owner_id=owner_id,
        scope=scope,
        session=session,
        tenant_id=tenant_id,
    )


async def seed_default_rules(session, *, tenant_id=_TEST_TENANT_ID):
    """Test wrapper around seed_default_rules with a default tenant."""
    return await _svc_seed_default_rules(session, tenant_id=tenant_id)


async def run_curation_pipeline(
    content,
    embedding,
    owner_id,
    scope,
    session,
    *,
    tenant_id=_TEST_TENANT_ID,
    **kwargs,
):
    """Test wrapper around run_curation_pipeline with a default tenant."""
    return await _svc_run_curation_pipeline(
        content=content,
        embedding=embedding,
        owner_id=owner_id,
        scope=scope,
        session=session,
        tenant_id=tenant_id,
        **kwargs,
    )


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
    """Reset the module-level _seeded_tenants set before and after each test that uses it.

    Phase 4 (#46) replaced the Phase-0 boolean ``_rules_seeded`` with a
    per-tenant set so each tenant lazy-seeds independently. The fixture
    clears the set so tests can observe a fresh "no tenant seeded" state.
    """
    curation_pipeline._seeded_tenants = set()
    yield
    curation_pipeline._seeded_tenants = set()


def _is_tenant_seeded(tenant_id: str = _TEST_TENANT_ID) -> bool:
    """Backward-compat helper for tests that asserted on the old boolean."""
    return tenant_id in curation_pipeline._seeded_tenants


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
    assert _is_tenant_seeded() is True

    # Rules must now be present in the DB
    rules_after = await load_rules(
        trigger="on_write", owner_id="user-123", scope=None, session=async_session
    )
    assert len(rules_after) > 0, "Expected seeded rules after first pipeline call"


async def test_pipeline_sets_seeded_flag(async_session, reset_rules_seeded):
    """The default tenant is absent from _seeded_tenants before the call and present after."""
    assert _is_tenant_seeded() is False

    await run_curation_pipeline(
        content="Clean content with no issues.",
        embedding=None,
        owner_id="user-123",
        scope="user",
        session=async_session,
    )

    assert _is_tenant_seeded() is True


async def test_pipeline_skips_seed_on_second_call(async_session, reset_rules_seeded, monkeypatch):
    """seed_default_rules is called exactly once across multiple pipeline invocations."""
    call_count = 0

    async def _counting_seed(session, *, tenant_id="default"):
        nonlocal call_count
        call_count += 1
        return await _svc_seed_default_rules(session, tenant_id=tenant_id)

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
    """If rules already exist when the tenant is not yet in _seeded_tenants, seed_default_rules returns 0."""
    # Pre-seed manually to simulate a populated DB after a restart
    await seed_default_rules(async_session)

    # Flag is still clear (simulating a fresh process restart)
    assert _is_tenant_seeded() is False

    result = await run_curation_pipeline(
        content="Clean content.",
        embedding=None,
        owner_id="user-123",
        scope="user",
        session=async_session,
    )

    assert result["blocked"] is False
    assert _is_tenant_seeded() is True

    # Rule count must not have doubled
    rules = await load_rules(
        trigger="on_write", owner_id="user-123", scope=None, session=async_session
    )
    rule_names = [r.name for r in rules]
    assert rule_names.count("secrets_scan") == 1, "secrets_scan must not be duplicated"


# -- Phase 3 (#46) tenant plumbing tests --


async def test_create_rule_populates_tenant_from_param(async_session):
    """create_rule must stamp the passed tenant_id onto the persisted row."""
    from sqlalchemy import select

    from memoryhub_core.models.curation import CuratorRule

    data = _make_rule_create(name="tenant_a_rule")
    rule = await _svc_create_rule(data, async_session, tenant_id="tenant_a")
    assert rule.tenant_id == "tenant_a"

    stmt = select(CuratorRule).where(CuratorRule.id == rule.id)
    row = (await async_session.execute(stmt)).scalar_one()
    assert row.tenant_id == "tenant_a"


async def test_create_rule_tenant_id_is_keyword_only(async_session):
    """tenant_id must be a required keyword arg on create_rule so missing
    tenants are loud failures rather than silently-defaulted rows."""
    import inspect

    sig = inspect.signature(_svc_create_rule)
    tenant_param = sig.parameters["tenant_id"]
    assert tenant_param.kind == inspect.Parameter.KEYWORD_ONLY
    assert tenant_param.default is inspect.Parameter.empty


# -- Phase 4 (#46) read-path tenant isolation tests --


async def test_load_rules_excludes_cross_tenant_rules(async_session):
    """load_rules must only surface rules owned by the caller's tenant,
    including system and organizational layers. A rule seeded in tenant A
    must not appear when tenant B calls load_rules."""
    # Seed default system rules into both tenants.
    await _svc_seed_default_rules(async_session, tenant_id="tenant_a")
    await _svc_seed_default_rules(async_session, tenant_id="tenant_b")

    # Create a tenant-A-only user rule with a unique name.
    await _svc_create_rule(
        _make_rule_create(
            name="tenant_a_unique_rule",
            layer=RuleLayer.USER,
            owner_id="user-123",
            priority=50,
        ),
        async_session,
        tenant_id="tenant_a",
    )

    tenant_a_rules = await _svc_load_rules(
        trigger="on_write",
        owner_id="user-123",
        scope=None,
        session=async_session,
        tenant_id="tenant_a",
    )
    tenant_b_rules = await _svc_load_rules(
        trigger="on_write",
        owner_id="user-123",
        scope=None,
        session=async_session,
        tenant_id="tenant_b",
    )

    a_names = [r.name for r in tenant_a_rules]
    b_names = [r.name for r in tenant_b_rules]

    # Tenant A sees its unique rule; tenant B does not.
    assert "tenant_a_unique_rule" in a_names
    assert "tenant_a_unique_rule" not in b_names

    # Every rule tenant A sees is tagged with tenant_a.
    for rule in tenant_a_rules:
        assert rule.tenant_id == "tenant_a", (
            f"cross-tenant leak: rule {rule.name!r} has tenant_id={rule.tenant_id!r} "
            f"in tenant A's view"
        )
    for rule in tenant_b_rules:
        assert rule.tenant_id == "tenant_b", (
            f"cross-tenant leak: rule {rule.name!r} has tenant_id={rule.tenant_id!r} "
            f"in tenant B's view"
        )


async def test_run_curation_pipeline_only_evaluates_same_tenant_rules(
    async_session, reset_rules_seeded
):
    """The curation pipeline must only apply rules from the caller's tenant.
    A rule that would block a write when evaluated in its own tenant must
    NOT block the same content when the pipeline runs under a different
    tenant -- otherwise the rule engine leaks cross-tenant policy.
    """
    # Create a tenant_a-only "block_widget" user rule that flags any mention
    # of "widget" in on_write content. This rule does NOT exist in tenant_b.
    await _svc_create_rule(
        CuratorRuleCreate(
            name="block_widget",
            trigger=RuleTrigger.ON_WRITE,
            tier=RuleTier.REGEX,
            config={"pattern": r"widget"},
            action=RuleAction.BLOCK,
            layer=RuleLayer.USER,
            owner_id="user-123",
            priority=1,
        ),
        async_session,
        tenant_id="tenant_a",
    )

    # In tenant_a the block rule is active, so mentioning "widget" is blocked.
    blocked = await _svc_run_curation_pipeline(
        content="need to log this widget",
        embedding=None,
        owner_id="user-123",
        scope="user",
        session=async_session,
        tenant_id="tenant_a",
    )
    assert blocked["blocked"] is True
    assert blocked["reason"] == "block_widget"

    # In tenant_b the rule does not exist, so the same content passes
    # through -- not because the scanner was lenient, but because
    # load_rules filters by tenant and never sees the tenant_a rule.
    clean = await _svc_run_curation_pipeline(
        content="need to log this widget",
        embedding=None,
        owner_id="user-123",
        scope="user",
        session=async_session,
        tenant_id="tenant_b",
    )
    assert clean["blocked"] is False, (
        "tenant_b pipeline should not see tenant_a's block_widget rule; "
        f"got {clean!r}"
    )


async def test_seed_default_rules_is_per_tenant(async_session):
    """Each tenant gets its own idempotent seed; subsequent calls for the
    same tenant insert nothing but calls for new tenants still insert."""
    first_a = await _svc_seed_default_rules(async_session, tenant_id="tenant_a")
    second_a = await _svc_seed_default_rules(async_session, tenant_id="tenant_a")
    first_b = await _svc_seed_default_rules(async_session, tenant_id="tenant_b")

    assert first_a == 5
    assert second_a == 0  # already seeded for tenant_a
    assert first_b == 5  # tenant_b gets its own copy


# -- Cache-aware write gate tests --


async def test_pipeline_gates_near_duplicate(async_session, monkeypatch):
    """A similarity score in the gate range blocks with gated=True and returns existing memory info."""
    import uuid as _uuid
    from unittest.mock import AsyncMock

    from memoryhub_core.services.curation.similarity import SimilarityResult

    await seed_default_rules(async_session)

    nearest = _uuid.uuid4()
    mock_sim = SimilarityResult(similar_count=1, nearest_id=nearest, nearest_score=0.92)
    monkeypatch.setattr(
        "memoryhub_core.services.curation.pipeline.check_similarity",
        AsyncMock(return_value=mock_sim),
    )

    # Patch _gated to avoid a real DB stub lookup in the SQLite test env.
    from memoryhub_core.services.curation import pipeline as _pipeline

    async def _fake_gated(reason, nearest_id, nearest_score, similar_count, session):
        return {
            "blocked": True,
            "gated": True,
            "reason": reason,
            "detail": f"Memory is {nearest_score:.0%} similar to existing memory {nearest_id}",
            "similar_count": similar_count,
            "nearest_id": nearest_id,
            "nearest_score": nearest_score,
            "existing_memory_id": str(nearest_id),
            "existing_memory_stub": "stub text",
            "recommendation": "update_existing",
            "flags": [],
        }

    monkeypatch.setattr(_pipeline, "_gated", _fake_gated)

    result = await run_curation_pipeline(
        content="Some memory content",
        embedding=[0.1, 0.2, 0.3],
        owner_id="user-123",
        scope="user",
        session=async_session,
    )

    assert result["blocked"] is True, f"Expected blocked, got {result}"
    assert result["gated"] is True, f"Expected gated, got {result}"
    assert result["reason"] == "near_duplicate", f"Unexpected reason: {result['reason']}"
    assert result["existing_memory_id"] == str(nearest)


async def test_pipeline_gates_exact_duplicate(async_session, monkeypatch):
    """A similarity score above the reject threshold still uses the gated response path."""
    import uuid as _uuid
    from unittest.mock import AsyncMock

    from memoryhub_core.services.curation import pipeline as _pipeline
    from memoryhub_core.services.curation.similarity import SimilarityResult

    await seed_default_rules(async_session)

    nearest = _uuid.uuid4()
    mock_sim = SimilarityResult(similar_count=1, nearest_id=nearest, nearest_score=0.985)
    monkeypatch.setattr(
        "memoryhub_core.services.curation.pipeline.check_similarity",
        AsyncMock(return_value=mock_sim),
    )

    async def _fake_gated(reason, nearest_id, nearest_score, similar_count, session):
        return {
            "blocked": True,
            "gated": True,
            "reason": reason,
            "detail": f"Memory is {nearest_score:.0%} similar to existing memory {nearest_id}",
            "similar_count": similar_count,
            "nearest_id": nearest_id,
            "nearest_score": nearest_score,
            "existing_memory_id": str(nearest_id),
            "existing_memory_stub": None,
            "recommendation": "update_existing",
            "flags": [],
        }

    monkeypatch.setattr(_pipeline, "_gated", _fake_gated)

    result = await run_curation_pipeline(
        content="Some memory content",
        embedding=[0.1, 0.2, 0.3],
        owner_id="user-123",
        scope="user",
        session=async_session,
    )

    assert result["blocked"] is True
    assert result["gated"] is True
    assert result["reason"] == "exact_duplicate"


async def test_pipeline_force_bypasses_gate(async_session, monkeypatch):
    """force=True allows a near-duplicate write to proceed."""
    import uuid as _uuid
    from unittest.mock import AsyncMock

    from memoryhub_core.services.curation.similarity import SimilarityResult

    await seed_default_rules(async_session)

    nearest = _uuid.uuid4()
    mock_sim = SimilarityResult(similar_count=1, nearest_id=nearest, nearest_score=0.92)
    monkeypatch.setattr(
        "memoryhub_core.services.curation.pipeline.check_similarity",
        AsyncMock(return_value=mock_sim),
    )

    result = await run_curation_pipeline(
        content="Some memory content",
        embedding=[0.1, 0.2, 0.3],
        owner_id="user-123",
        scope="user",
        session=async_session,
        force=True,
    )

    assert result["blocked"] is False, f"Expected unblocked with force=True, got {result}"
    assert "possible_duplicate" in result["flags"]


async def test_pipeline_force_does_not_bypass_regex(async_session):
    """force=True never bypasses Tier 1 regex checks like secrets scanning."""
    await seed_default_rules(async_session)

    content = "My AWS key is AKIA1234567890ABCDEF — do not store!"
    result = await run_curation_pipeline(
        content=content,
        embedding=None,
        owner_id="user-123",
        scope="user",
        session=async_session,
        force=True,
    )

    assert result["blocked"] is True, "Secrets should still be blocked with force=True"
    assert result.get("gated") is not True, "Secrets block should not be a gate"
    assert result["reason"] == "secrets_scan"


async def test_pipeline_score_below_gate_writes(async_session, monkeypatch):
    """A similarity score below the gate threshold does not block; adds possible_duplicate flag."""
    import uuid as _uuid
    from unittest.mock import AsyncMock

    from memoryhub_core.services.curation.similarity import SimilarityResult

    await seed_default_rules(async_session)

    nearest = _uuid.uuid4()
    mock_sim = SimilarityResult(similar_count=1, nearest_id=nearest, nearest_score=0.85)
    monkeypatch.setattr(
        "memoryhub_core.services.curation.pipeline.check_similarity",
        AsyncMock(return_value=mock_sim),
    )

    result = await run_curation_pipeline(
        content="Some memory content",
        embedding=[0.1, 0.2, 0.3],
        owner_id="user-123",
        scope="user",
        session=async_session,
    )

    assert result["blocked"] is False, f"Score 0.85 should not be blocked, got {result}"
    assert "possible_duplicate" in result["flags"]


def test_resolve_embedding_thresholds_gate():
    """_resolve_embedding_thresholds returns a 3-tuple with gate_threshold from rule config."""
    from unittest.mock import MagicMock

    from memoryhub_core.services.curation.pipeline import _resolve_embedding_thresholds

    # Build minimal mock rules matching the seeded defaults.
    exact_rule = MagicMock()
    exact_rule.tier = "embedding"
    exact_rule.name = "exact_duplicate"
    exact_rule.config = {"threshold": 0.98}

    near_rule = MagicMock()
    near_rule.tier = "embedding"
    near_rule.name = "near_duplicate"
    near_rule.config = {"similarity_range": [0.80, 0.90], "gate_threshold": 0.90}

    reject, flag, gate = _resolve_embedding_thresholds(
        [exact_rule, near_rule],
        reject_threshold=0.95,
        flag_threshold=0.80,
        gate_threshold=0.85,
    )

    assert reject == 0.98, f"reject_threshold should be 0.98, got {reject}"
    assert flag == 0.80, f"flag_threshold should be 0.80, got {flag}"
    assert gate == 0.90, f"gate_threshold should be 0.90, got {gate}"
