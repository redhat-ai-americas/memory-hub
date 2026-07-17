"""Extraction reconciliation: search-before-write with guardrailed thresholds.

Sits between the dreaming extraction pipeline (Step 1) and memory creation.
Each candidate memory is compared against existing memories by embedding
similarity, and an LLM tiebreaker resolves ambiguous matches. Every
decision is logged for threshold tuning and rollback.

Design reference: planning/memory-extraction-pipeline.md, Layer 2 Step 2.
Part of #347.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any, Callable, Awaitable

from pydantic import BaseModel
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from memoryhub_core.models.conversation import ConversationExtraction
from memoryhub_core.models.memory import MemoryNode
from memoryhub_core.models.reconciliation import (
    ReconciliationDecision as ReconciliationDecisionRow,
)
from memoryhub_core.models.schemas import MemoryNodeCreate, MemoryNodeUpdate
from memoryhub_core.services.curation.similarity import check_similarity
from memoryhub_core.services.memory import create_memory, update_memory

logger = logging.getLogger(__name__)

SKIP_THRESHOLD = 0.98
TIEBREAKER_THRESHOLD = 0.80

TiebreakerFn = Callable[[str, str], Awaitable[str]]


# ---------------------------------------------------------------------------
# Stage contracts
# ---------------------------------------------------------------------------

class ExtractionCandidate(BaseModel):
    """Output of the extraction stage, input to reconciliation."""

    content: str
    weight: float = 0.7
    content_type: str = "experiential"
    domains: list[str] | None = None
    metadata: dict[str, Any] | None = None

    thread_id: uuid.UUID | None = None
    source_messages: list[int] | None = None
    extraction_model: str | None = None
    extraction_prompt_hash: str | None = None


class ReconciliationResult(BaseModel):
    """Output of the reconciliation stage."""

    candidate_stub: str
    action: str = ""  # "create" | "update" | "skip" -- always set before return
    nearest_match_id: uuid.UUID | None = None
    similarity_score: float | None = None
    tiebreaker_verdict: str | None = None  # "same" | "different"
    content_type_match: bool | None = None
    domain_match: bool | None = None
    memory_id: uuid.UUID | None = None
    reason: str | None = None


# ---------------------------------------------------------------------------
# Core reconciliation
# ---------------------------------------------------------------------------

async def reconcile_candidate(
    candidate: ExtractionCandidate,
    owner_id: str,
    scope: str,
    scope_id: str | None,
    session: AsyncSession,
    embedding_service: Any,
    *,
    tenant_id: str,
    extraction_run_id: str,
    actor_id: str | None = None,
    s3_adapter: Any | None = None,
    tiebreaker_fn: TiebreakerFn | None = None,
    dry_run: bool = False,
) -> ReconciliationResult:
    """Reconcile a single extraction candidate against existing memories.

    Threshold bands:
      >= 0.98  skip (exact duplicate)
      >= 0.80  LLM tiebreaker; if "same" AND content_type+domain match -> update
      <  0.80  create new memory

    When dry_run=True, computes the full decision but skips memory writes
    and decision logging. Returns ReconciliationResult with memory_id=None.
    """
    stub = candidate.content[:200]
    embedding = await embedding_service.embed(candidate.content)

    sim = await check_similarity(
        embedding,
        owner_id,
        scope,
        session,
        tenant_id=tenant_id,
        flag_threshold=TIEBREAKER_THRESHOLD,
    )

    result = ReconciliationResult(candidate_stub=stub)

    if sim.nearest_id is None or sim.nearest_score is None:
        result.action = "create"
        result.reason = "no_similar_memory"
    elif sim.nearest_score >= SKIP_THRESHOLD:
        result.action = "skip"
        result.reason = "exact_duplicate"
        result.nearest_match_id = sim.nearest_id
        result.similarity_score = sim.nearest_score
    elif sim.nearest_score >= TIEBREAKER_THRESHOLD:
        existing = await _fetch_memory(sim.nearest_id, session)
        if existing is None:
            result.action = "create"
            result.reason = "nearest_match_disappeared"
        else:
            ct_match = existing.content_type == candidate.content_type
            dm_match = _domains_overlap(existing.domains, candidate.domains)
            result.content_type_match = ct_match
            result.domain_match = dm_match
            result.nearest_match_id = sim.nearest_id
            result.similarity_score = sim.nearest_score

            verdict = None
            if tiebreaker_fn is not None:
                existing_text = existing.stub or existing.content[:500]
                verdict = await tiebreaker_fn(candidate.content, existing_text)
                result.tiebreaker_verdict = verdict

            if verdict == "same" and ct_match:
                result.action = "update"
                result.reason = "tiebreaker_same"
            elif verdict == "same" and not ct_match:
                result.action = "create"
                result.reason = "content_type_mismatch"
            else:
                result.action = "create"
                result.reason = "tiebreaker_different"
    else:
        result.action = "create"
        result.reason = "below_threshold"

    if not dry_run:
        # Execute the decided action
        if result.action == "create":
            data = MemoryNodeCreate(
                content=candidate.content,
                scope=scope,
                weight=candidate.weight,
                owner_id=owner_id,
                scope_id=scope_id,
                metadata=candidate.metadata,
                domains=candidate.domains,
                content_type=candidate.content_type,
            )
            if actor_id:
                data.actor_id = actor_id
            memory_node, _ = await create_memory(
                data, session, embedding_service,
                tenant_id=tenant_id,
                force=True,
                s3_adapter=s3_adapter,
            )
            if memory_node:
                result.memory_id = memory_node.id

        elif result.action == "update":
            update_data = MemoryNodeUpdate(content=candidate.content)
            if candidate.domains is not None:
                update_data.domains = candidate.domains
            updated = await update_memory(
                result.nearest_match_id,
                update_data,
                session,
                embedding_service,
                s3_adapter=s3_adapter,
                actor_id=actor_id,
            )
            result.memory_id = updated.id

        # Log the decision
        await _log_decision(
            session,
            result=result,
            candidate=candidate,
            owner_id=owner_id,
            tenant_id=tenant_id,
            scope=scope,
            scope_id=scope_id,
            extraction_run_id=extraction_run_id,
        )

    return result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _fetch_memory(
    memory_id: uuid.UUID, session: AsyncSession,
) -> MemoryNode | None:
    """Fetch a current, active memory by ID."""
    stmt = select(MemoryNode).where(
        MemoryNode.id == memory_id,
        MemoryNode.is_current.is_(True),
        MemoryNode.deleted_at.is_(None),
        MemoryNode.status == "active",
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


def _domains_overlap(
    existing: list[str] | None, candidate: list[str] | None,
) -> bool:
    """Check if domain lists have any overlap (or both are empty/None)."""
    if not existing and not candidate:
        return True
    if not existing or not candidate:
        return False
    return bool(set(existing) & set(candidate))


async def _log_decision(
    session: AsyncSession,
    *,
    result: ReconciliationResult,
    candidate: ExtractionCandidate,
    owner_id: str,
    tenant_id: str,
    scope: str,
    scope_id: str | None,
    extraction_run_id: str,
) -> None:
    """Persist a reconciliation decision to the audit log."""
    row = ReconciliationDecisionRow(
        id=uuid.uuid4(),
        extraction_run_id=extraction_run_id,
        candidate_content=candidate.content,
        candidate_stub=result.candidate_stub,
        nearest_match_id=result.nearest_match_id,
        similarity_score=result.similarity_score,
        action=result.action,
        tiebreaker_verdict=result.tiebreaker_verdict,
        content_type_match=result.content_type_match,
        domain_match=result.domain_match,
        memory_id=result.memory_id,
        reason=result.reason,
        owner_id=owner_id,
        tenant_id=tenant_id,
        scope=scope,
        scope_id=scope_id,
    )
    session.add(row)


# ---------------------------------------------------------------------------
# Rollback
# ---------------------------------------------------------------------------

async def rollback_extraction_run(
    extraction_run_id: str,
    session: AsyncSession,
) -> dict[str, Any]:
    """Rollback all creates and updates from an extraction run.

    For creates: soft-delete the created memory and its children.
    For updates: soft-delete the new version and restore the prior version.
    Skips decisions where post-run modifications have occurred.
    """
    stmt = (
        select(ReconciliationDecisionRow)
        .where(ReconciliationDecisionRow.extraction_run_id == extraction_run_id)
        .order_by(ReconciliationDecisionRow.created_at.desc())
    )
    result = await session.execute(stmt)
    decisions = list(result.scalars().all())

    if not decisions:
        return {
            "extraction_run_id": extraction_run_id,
            "total_decisions": 0,
            "rolled_back": {"creates": 0, "updates": 0, "skips": 0},
            "skipped": {"post_run_modifications": 0, "already_deleted": 0},
        }

    now = datetime.now(UTC)
    rolled_creates = 0
    rolled_updates = 0
    rolled_skips = 0
    skipped_modified = 0
    skipped_deleted = 0

    for decision in decisions:
        if decision.action == "skip":
            rolled_skips += 1
            continue

        if decision.memory_id is None:
            continue

        memory = await session.get(MemoryNode, decision.memory_id)
        if memory is None:
            skipped_deleted += 1
            continue

        if memory.deleted_at is not None:
            skipped_deleted += 1
            continue

        # Safety: check for post-run modifications (a newer version exists)
        successor_stmt = select(MemoryNode.id).where(
            MemoryNode.previous_version_id == decision.memory_id,
        )
        successor = await session.execute(successor_stmt)
        if successor.scalar_one_or_none() is not None:
            skipped_modified += 1
            logger.warning(
                "Skipping rollback of %s (action=%s): post-run modification exists",
                decision.memory_id, decision.action,
            )
            continue

        if decision.action == "create":
            # Soft-delete the created memory and its children
            memory.deleted_at = now
            memory.is_current = False

            children_stmt = select(MemoryNode).where(
                MemoryNode.parent_id == decision.memory_id,
                MemoryNode.deleted_at.is_(None),
            )
            children_result = await session.execute(children_stmt)
            for child in children_result.scalars().all():
                child.deleted_at = now
                child.is_current = False

            # Remove provenance records
            await session.execute(
                delete(ConversationExtraction).where(
                    ConversationExtraction.memory_node_id == decision.memory_id,
                )
            )
            rolled_creates += 1

        elif decision.action == "update":
            if decision.nearest_match_id is None:
                skipped_modified += 1
                continue

            # Soft-delete the new version and its children
            memory.deleted_at = now
            memory.is_current = False

            new_children_stmt = select(MemoryNode).where(
                MemoryNode.parent_id == decision.memory_id,
                MemoryNode.deleted_at.is_(None),
            )
            new_children_result = await session.execute(new_children_stmt)
            for child in new_children_result.scalars().all():
                child.deleted_at = now
                child.is_current = False

            # Restore the prior version
            old_memory = await session.get(MemoryNode, decision.nearest_match_id)
            if old_memory is not None:
                old_memory.is_current = True
                old_memory.expires_at = None

                # Restore old version's children
                old_children_stmt = select(MemoryNode).where(
                    MemoryNode.parent_id == decision.nearest_match_id,
                    MemoryNode.deleted_at.is_(None),
                )
                old_children_result = await session.execute(old_children_stmt)
                for child in old_children_result.scalars().all():
                    child.is_current = True
                    child.expires_at = None

            # Remove provenance records for the new version
            await session.execute(
                delete(ConversationExtraction).where(
                    ConversationExtraction.memory_node_id == decision.memory_id,
                )
            )
            rolled_updates += 1

    await session.commit()

    return {
        "extraction_run_id": extraction_run_id,
        "total_decisions": len(decisions),
        "rolled_back": {
            "creates": rolled_creates,
            "updates": rolled_updates,
            "skips": rolled_skips,
        },
        "skipped": {
            "post_run_modifications": skipped_modified,
            "already_deleted": skipped_deleted,
        },
    }
