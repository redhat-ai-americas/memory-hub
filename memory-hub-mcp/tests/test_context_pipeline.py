"""Tests for context assembly pipeline stages (#561).

Tests cover:
- Individual stage behavior (filtering, logging)
- Pipeline ordering invariants
- Machine-readable log entry structure
- Defense-in-depth filtering (tenant, scope)
- Deduplication (by ID, keep highest score)
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from src.tools._context_pipeline import (
    PipelineLogEntry,
    PipelineState,
    log_pipeline_summary,
    run_pre_budget_pipeline,
    stage_apply_budget,
    stage_authenticate_source,
    stage_check_freshness,
    stage_deduplicate,
    stage_emit,
    stage_enforce_scope,
    stage_screen_content,
    stage_stamp_provenance,
    stage_validate_schema,
)

from memoryhub_core.models.schemas import MemoryNodeRead, MemoryNodeStub


def _make_read(
    tenant_id: str = "default",
    scope: str = "user",
    source: str = "agent",
    upstream_trust_level: str = "trusted",
    generating_model: str | None = None,
    **overrides,
) -> MemoryNodeRead:
    """Build a minimal MemoryNodeRead for pipeline tests."""
    defaults = {
        "id": uuid.uuid4(),
        "parent_id": None,
        "content": "test memory",
        "stub": "test [scope=user, weight=0.7]",
        "storage_type": "inline",
        "content_ref": None,
        "weight": 0.7,
        "scope": scope,
        "branch_type": None,
        "owner_id": "user-1",
        "tenant_id": tenant_id,
        "is_current": True,
        "version": 1,
        "previous_version_id": None,
        "metadata": None,
        "created_at": datetime.now(tz=UTC),
        "updated_at": datetime.now(tz=UTC),
        "has_children": False,
        "has_rationale": False,
        "source": source,
        "upstream_trust_level": upstream_trust_level,
        "generating_model": generating_model,
    }
    defaults.update(overrides)
    return MemoryNodeRead(**defaults)


def _make_stub(scope: str = "user", **overrides) -> MemoryNodeStub:
    defaults = {
        "id": uuid.uuid4(),
        "stub": "stub text",
        "scope": scope,
        "weight": 0.5,
    }
    defaults.update(overrides)
    return MemoryNodeStub(**defaults)


_DEFAULT_SCOPES = {"user", "project", "organizational"}


def _make_state(
    results=None,
    authorized_scopes=None,
    tenant="default",
    owner_id="user-1",
) -> PipelineState:
    return PipelineState(
        results=results or [],
        authorized_scopes=authorized_scopes if authorized_scopes is not None else _DEFAULT_SCOPES,
        tenant=tenant,
        owner_id=owner_id,
    )


# ── Stage 1: Authenticate source ─────────────────────────────────────────


class TestAuthenticateSource:
    def test_passes_matching_tenant(self):
        results = [(_make_read(tenant_id="t1"), 0.9)]
        state = _make_state(results=results, tenant="t1")
        state = stage_authenticate_source(state)
        assert len(state.results) == 1
        assert state.log[-1].code == "tenant_verified"
        assert state.log[-1].filtered_count == 0

    def test_drops_mismatched_tenant(self):
        results = [
            (_make_read(tenant_id="t1"), 0.9),
            (_make_read(tenant_id="t2"), 0.8),
        ]
        state = _make_state(results=results, tenant="t1")
        state = stage_authenticate_source(state)
        assert len(state.results) == 1
        assert state.log[-1].code == "tenant_mismatch_dropped"
        assert state.log[-1].filtered_count == 1

    def test_empty_results(self):
        state = _make_state(results=[])
        state = stage_authenticate_source(state)
        assert state.log[-1].code == "skip_empty"


# ── Stage 2: Validate schema ─────────────────────────────────────────────


class TestValidateSchema:
    def test_all_valid(self):
        results = [
            (_make_read(), 0.9),
            (_make_stub(), 0.5),
        ]
        state = _make_state(results=results)
        state = stage_validate_schema(state)
        assert len(state.results) == 2
        assert state.log[-1].code == "all_valid"


# ── Stage 3: Enforce scope ────────────────────────────────────────────────


class TestEnforceScope:
    def test_passes_authorized_scope(self):
        results = [(_make_read(scope="user"), 0.9)]
        state = _make_state(results=results, authorized_scopes={"user"})
        state = stage_enforce_scope(state)
        assert len(state.results) == 1
        assert state.log[-1].code == "scope_verified"

    def test_drops_unauthorized_scope(self):
        results = [
            (_make_read(scope="user"), 0.9),
            (_make_read(scope="enterprise"), 0.8),
        ]
        state = _make_state(results=results, authorized_scopes={"user"})
        state = stage_enforce_scope(state)
        assert len(state.results) == 1
        assert state.log[-1].code == "scope_mismatch_dropped"
        assert state.log[-1].filtered_count == 1

    def test_empty_authorized_scopes_skips(self):
        """Empty authorized set skips scope enforcement (no filter to apply)."""
        results = [(_make_read(scope="user"), 0.9)]
        state = _make_state(results=results, authorized_scopes=set())
        state = stage_enforce_scope(state)
        assert len(state.results) == 1
        assert state.log[-1].code == "skip_no_filter"


# ── Stage 4: Check freshness ─────────────────────────────────────────────


class TestCheckFreshness:
    def test_logs_count(self):
        results = [(_make_read(), 0.9), (_make_read(), 0.8)]
        state = _make_state(results=results)
        state = stage_check_freshness(state)
        assert state.log[-1].code == "freshness_checked"
        assert state.log[-1].input_count == 2
        assert state.log[-1].output_count == 2


# ── Stage 5: Deduplicate ─────────────────────────────────────────────────


class TestDeduplicate:
    def test_removes_duplicate_ids(self):
        shared_id = uuid.uuid4()
        results = [
            (_make_read(id=shared_id), 0.9),
            (_make_read(id=shared_id), 0.7),
        ]
        state = _make_state(results=results)
        state = stage_deduplicate(state)
        assert len(state.results) == 1
        assert state.log[-1].code == "deduped"
        assert state.log[-1].filtered_count == 1

    def test_keeps_highest_score(self):
        shared_id = uuid.uuid4()
        low = _make_read(id=shared_id, content="low score")
        high = _make_read(id=shared_id, content="high score")
        results = [(low, 0.5), (high, 0.9)]
        state = _make_state(results=results)
        state = stage_deduplicate(state)
        assert state.results[0][1] == 0.9

    def test_no_duplicates(self):
        results = [(_make_read(), 0.9), (_make_read(), 0.8)]
        state = _make_state(results=results)
        state = stage_deduplicate(state)
        assert len(state.results) == 2
        assert state.log[-1].code == "no_duplicates"

    def test_empty_results(self):
        state = _make_state(results=[])
        state = stage_deduplicate(state)
        assert state.log[-1].code == "skip_empty"


# ── Stage 6-9: Budget, screen, provenance, emit ──────────────────────────


class TestApplyBudget:
    def test_logs_budget_config(self):
        state = _make_state(results=[(_make_read(), 0.9)])
        state = stage_apply_budget(state, max_response_tokens=4000, mode="full")
        assert state.log[-1].code == "budget_configured"
        assert state.log[-1].detail["max_response_tokens"] == 4000
        assert state.log[-1].detail["skip_budget"] is False

    def test_full_only_skips_budget(self):
        state = _make_state(results=[(_make_read(), 0.9)])
        state = stage_apply_budget(state, max_response_tokens=4000, mode="full_only")
        assert state.log[-1].detail["skip_budget"] is True


class TestScreenContent:
    def test_placeholder_logs_not_configured(self):
        state = _make_state(results=[(_make_read(), 0.9)])
        state = stage_screen_content(state)
        assert state.log[-1].code == "not_configured"


class TestStampProvenance:
    def test_logs_source_distribution(self):
        results = [
            (_make_read(source="agent"), 0.9),
            (_make_read(source="dreaming"), 0.8),
            (_make_read(source="dreaming", generating_model="gemini-2.5"), 0.7),
        ]
        state = _make_state(results=results)
        state = stage_stamp_provenance(state)
        detail = state.log[-1].detail
        assert detail["sources"] == {"agent": 1, "dreaming": 2}
        assert detail["with_generating_model"] == 1

    def test_logs_trust_levels(self):
        results = [
            (_make_read(upstream_trust_level="trusted"), 0.9),
            (_make_read(upstream_trust_level="untrusted"), 0.8),
        ]
        state = _make_state(results=results)
        state = stage_stamp_provenance(state)
        assert state.log[-1].detail["trust_levels"] == {
            "trusted": 1, "untrusted": 1,
        }


class TestEmit:
    def test_logs_result_count(self):
        state = _make_state(results=[(_make_read(), 0.9)])
        state = stage_emit(state, result_count=5)
        assert state.log[-1].code == "emitted"
        assert state.log[-1].output_count == 5


# ── Pipeline ordering invariants ──────────────────────────────────────────


class TestPipelineOrdering:
    def test_scope_before_dedup(self):
        """Scope enforcement runs before dedup to prevent cross-scope probing."""
        state = _make_state(
            results=[(_make_read(scope="user"), 0.9)],
            authorized_scopes={"user"},
        )
        state = run_pre_budget_pipeline(state)
        stage_names = [entry.stage for entry in state.log]
        scope_idx = stage_names.index("enforce_scope")
        dedup_idx = stage_names.index("deduplicate")
        assert scope_idx < dedup_idx

    def test_full_pipeline_runs_all_stages(self):
        state = _make_state(
            results=[(_make_read(), 0.9)],
            authorized_scopes={"user"},
        )
        state = run_pre_budget_pipeline(state)
        stage_names = [entry.stage for entry in state.log]
        assert stage_names == [
            "authenticate_source",
            "validate_schema",
            "enforce_scope",
            "check_freshness",
            "deduplicate",
        ]

    def test_pipeline_preserves_valid_results(self):
        """Pipeline doesn't filter results that pass all checks."""
        mem = _make_read(tenant_id="t1", scope="user")
        state = _make_state(
            results=[(mem, 0.9)],
            authorized_scopes={"user"},
            tenant="t1",
        )
        state = run_pre_budget_pipeline(state)
        assert len(state.results) == 1
        assert state.results[0][0].id == mem.id


class TestPipelineLogEntry:
    def test_log_entry_fields(self):
        entry = PipelineLogEntry(
            stage="test",
            code="test_code",
            input_count=5,
            output_count=3,
            filtered_count=2,
            detail={"key": "value"},
        )
        assert entry.stage == "test"
        assert entry.code == "test_code"
        assert entry.filtered_count == 2


class TestPipelineSummary:
    def test_summary_logging(self, caplog):
        """Pipeline summary is logged at INFO level."""
        import logging
        with caplog.at_level(logging.INFO, logger="src.tools._context_pipeline"):
            state = _make_state(results=[(_make_read(), 0.9)])
            state = run_pre_budget_pipeline(state)
            log_pipeline_summary(state)
        assert any("context_pipeline.summary" in r.message for r in caplog.records)
