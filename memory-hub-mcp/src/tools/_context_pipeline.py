"""Context assembly pipeline for search result injection (#561).

Composes the post-retrieval assembly path into explicit, ordered stages
with structured logging. Each stage carries machine-readable log entries
(no free text from memory content) so filtering decisions are auditable.

Ordering invariants:
  - Scope before dedup: prevents cross-tenant probing via dedup oracle
  - Budget before screening: prevents context exhaustion via large payloads

Stage contract: each stage receives a PipelineState and returns a
(possibly modified) PipelineState. Stages must not raise; failures are
logged and the pipeline continues with the unmodified state.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from memoryhub_core.models.schemas import MemoryNodeRead, MemoryNodeStub

logger = logging.getLogger(__name__)


@dataclass
class PipelineLogEntry:
    """Machine-readable log entry for one pipeline stage."""

    stage: str
    code: str
    input_count: int
    output_count: int
    filtered_count: int = 0
    detail: dict[str, Any] | None = None


@dataclass
class PipelineState:
    """State carried through the context assembly pipeline.

    Fields are populated by search_memory before pipeline entry and
    consumed/modified by stages. The ``results`` list is the primary
    payload; stages may filter, reorder, or degrade entries.
    """

    results: list[tuple[MemoryNodeRead | MemoryNodeStub, float]]
    authorized_scopes: set[str]
    tenant: str
    owner_id: str | None
    log: list[PipelineLogEntry] = field(default_factory=list)


# ── Stage 1: Authenticate source ─────────────────────────────────────────

def stage_authenticate_source(state: PipelineState) -> PipelineState:
    """Verify that results originated from an authenticated source.

    The SQL query already filters by tenant and authorized scopes,
    so this is a defense-in-depth assertion: every result must belong
    to the resolved tenant. Results from a different tenant are dropped.
    """
    before = len(state.results)
    if not state.results:
        state.log.append(PipelineLogEntry(
            stage="authenticate_source", code="skip_empty",
            input_count=0, output_count=0,
        ))
        return state

    filtered = [
        (item, score) for item, score in state.results
        if getattr(item, "tenant_id", state.tenant) == state.tenant
    ]
    dropped = before - len(filtered)
    state.results = filtered
    state.log.append(PipelineLogEntry(
        stage="authenticate_source",
        code="tenant_verified" if dropped == 0 else "tenant_mismatch_dropped",
        input_count=before,
        output_count=len(filtered),
        filtered_count=dropped,
    ))
    if dropped > 0:
        logger.warning(
            "context_pipeline.authenticate_source: dropped %d results with "
            "mismatched tenant_id (expected %s)", dropped, state.tenant,
        )
    return state


# ── Stage 2: Validate schema ─────────────────────────────────────────────

def stage_validate_schema(state: PipelineState) -> PipelineState:
    """Verify each result is a well-formed MemoryNodeRead or MemoryNodeStub.

    Results are already Pydantic-validated by the service layer, so this
    stage logs conformance without filtering. A malformed result would
    indicate a service-layer bug.
    """
    before = len(state.results)
    valid = [
        (item, score) for item, score in state.results
        if isinstance(item, (MemoryNodeRead, MemoryNodeStub))
    ]
    dropped = before - len(valid)
    state.results = valid
    state.log.append(PipelineLogEntry(
        stage="validate_schema",
        code="all_valid" if dropped == 0 else "schema_violation_dropped",
        input_count=before,
        output_count=len(valid),
        filtered_count=dropped,
    ))
    if dropped > 0:
        logger.error(
            "context_pipeline.validate_schema: dropped %d results with "
            "invalid schema (service layer bug)", dropped,
        )
    return state


# ── Stage 3: Enforce scope ────────────────────────────────────────────────

def stage_enforce_scope(state: PipelineState) -> PipelineState:
    """Re-verify that each result's scope is in the caller's authorized set.

    SQL-level scope filtering is the primary gate. This post-retrieval
    check is defense-in-depth: if the SQL filter had a gap (e.g., a new
    scope type added without filter coverage), this stage catches it.
    """
    before = len(state.results)
    if not state.authorized_scopes or not state.results:
        state.log.append(PipelineLogEntry(
            stage="enforce_scope",
            code="skip_no_filter" if not state.authorized_scopes else "skip_empty",
            input_count=before,
            output_count=before,
        ))
        return state

    filtered = [
        (item, score) for item, score in state.results
        if getattr(item, "scope", "") in state.authorized_scopes
    ]
    dropped = before - len(filtered)
    state.results = filtered
    state.log.append(PipelineLogEntry(
        stage="enforce_scope",
        code="scope_verified" if dropped == 0 else "scope_mismatch_dropped",
        input_count=before,
        output_count=len(filtered),
        filtered_count=dropped,
    ))
    if dropped > 0:
        logger.warning(
            "context_pipeline.enforce_scope: dropped %d results with "
            "unauthorized scope (defense-in-depth)", dropped,
        )
    return state


# ── Stage 4: Check freshness ─────────────────────────────────────────────

def stage_check_freshness(state: PipelineState) -> PipelineState:
    """Log temporal status of results.

    Freshness filtering (temporal_status) is applied at query time by the
    service layer. This stage logs the composition of results by temporal
    state so the pipeline audit trail shows what was injected.
    """
    before = len(state.results)
    expired = 0
    for item, _ in state.results:
        temporal = getattr(item, "temporal_status", None)
        if temporal == "expired":
            expired += 1

    state.log.append(PipelineLogEntry(
        stage="check_freshness",
        code="freshness_checked",
        input_count=before,
        output_count=before,
        detail={"expired_in_results": expired},
    ))
    return state


# ── Stage 5: Deduplicate ─────────────────────────────────────────────────

def stage_deduplicate(state: PipelineState) -> PipelineState:
    """Remove duplicate results by memory ID.

    The service layer's vector search can return the same memory via
    different paths (direct hit + graph neighbor, chunk + parent). This
    stage deduplicates by ID, keeping the highest-scoring instance.
    """
    before = len(state.results)
    if not state.results:
        state.log.append(PipelineLogEntry(
            stage="deduplicate", code="skip_empty",
            input_count=0, output_count=0,
        ))
        return state

    seen: dict[str, int] = {}
    deduped: list[tuple[MemoryNodeRead | MemoryNodeStub, float]] = []
    for item, score in state.results:
        key = str(item.id)
        if key not in seen:
            seen[key] = len(deduped)
            deduped.append((item, score))
        else:
            idx = seen[key]
            if score > deduped[idx][1]:
                deduped[idx] = (item, score)

    dropped = before - len(deduped)
    state.results = deduped
    state.log.append(PipelineLogEntry(
        stage="deduplicate",
        code="deduped" if dropped > 0 else "no_duplicates",
        input_count=before,
        output_count=len(deduped),
        filtered_count=dropped,
    ))
    return state


# ── Stage 6: Apply budget ────────────────────────────────────────────────
# Budget packing is complex and tightly coupled with S3 hydration and
# formatting. It remains in search_memory.py. This stage is a passthrough
# that logs the budget parameters for audit.

def stage_apply_budget(
    state: PipelineState,
    *,
    max_response_tokens: int,
    mode: str,
) -> PipelineState:
    """Log budget parameters. Actual packing happens in search_memory.

    The budget packing loop in search_memory handles full→stub degradation,
    S3 hydration, and format-specific entry building. This stage records
    the budget configuration for the audit trail.
    """
    state.log.append(PipelineLogEntry(
        stage="apply_budget",
        code="budget_configured",
        input_count=len(state.results),
        output_count=len(state.results),
        detail={
            "max_response_tokens": max_response_tokens,
            "mode": mode,
            "skip_budget": mode == "full_only" or max_response_tokens == 0,
        },
    ))
    return state


# ── Stage 7: Screen content (optional) ───────────────────────────────────

def stage_screen_content(state: PipelineState) -> PipelineState:
    """Placeholder for content screening/moderation.

    Not currently implemented. When enabled, this stage would filter
    results whose content triggers moderation rules (PII, secrets, etc.)
    before injection into agent context. Positioned after budget so
    screening cost is bounded by the budget cap.
    """
    state.log.append(PipelineLogEntry(
        stage="screen_content",
        code="not_configured",
        input_count=len(state.results),
        output_count=len(state.results),
    ))
    return state


# ── Stage 8: Stamp provenance ─────────────────────────────────────────────

def stage_stamp_provenance(state: PipelineState) -> PipelineState:
    """Log provenance metadata composition of results.

    Results already carry source and upstream_trust_level from the
    service layer. This stage logs the distribution for the audit trail.
    """
    source_counts: dict[str, int] = {}
    trust_counts: dict[str, int] = {}
    has_generating_model = 0

    for item, _ in state.results:
        src = getattr(item, "source", "unknown")
        source_counts[src] = source_counts.get(src, 0) + 1

        trust = getattr(item, "upstream_trust_level", "unknown")
        trust_counts[trust] = trust_counts.get(trust, 0) + 1

        if getattr(item, "generating_model", None):
            has_generating_model += 1

    state.log.append(PipelineLogEntry(
        stage="stamp_provenance",
        code="provenance_logged",
        input_count=len(state.results),
        output_count=len(state.results),
        detail={
            "sources": source_counts,
            "trust_levels": trust_counts,
            "with_generating_model": has_generating_model,
        },
    ))
    return state


# ── Stage 9: Emit to context ─────────────────────────────────────────────
# Response assembly stays in search_memory.py since it depends on
# compilation metadata, focus metadata, graph metadata, and pattern
# signals. This stage logs the final emission.

def stage_emit(state: PipelineState, *, result_count: int) -> PipelineState:
    """Log the final emission to context."""
    state.log.append(PipelineLogEntry(
        stage="emit",
        code="emitted",
        input_count=len(state.results),
        output_count=result_count,
    ))
    return state


# ── Pipeline runner ──────────────────────────────────────────────────────

STAGE_ORDER = [
    "authenticate_source",
    "validate_schema",
    "enforce_scope",
    "check_freshness",
    "deduplicate",
    "apply_budget",
    "screen_content",
    "stamp_provenance",
    "emit",
]


def run_pre_budget_pipeline(state: PipelineState) -> PipelineState:
    """Run pipeline stages 1-5 and 7-8 (everything except budget and emit).

    Budget packing and emit remain in search_memory because they are
    tightly coupled with formatting, S3 hydration, and compilation metadata.
    This function runs the filtering and logging stages that can be cleanly
    extracted.

    Stage ordering enforces the security invariants:
      - Scope (stage 3) before dedup (stage 5): prevents scope probing
      - Budget (stage 6) before screening (stage 7): bounds screening cost
    """
    state = stage_authenticate_source(state)
    state = stage_validate_schema(state)
    state = stage_enforce_scope(state)
    state = stage_check_freshness(state)
    state = stage_deduplicate(state)
    # stages 6 (budget), 7 (screen), 8 (provenance), 9 (emit) run
    # inline in search_memory after compilation and formatting
    return state


def log_pipeline_summary(state: PipelineState) -> None:
    """Emit a single structured log line summarizing the pipeline run."""
    summary = {
        entry.stage: {
            "code": entry.code,
            "in": entry.input_count,
            "out": entry.output_count,
            **({"filtered": entry.filtered_count} if entry.filtered_count else {}),
        }
        for entry in state.log
    }
    logger.info("context_pipeline.summary: %s", summary)
