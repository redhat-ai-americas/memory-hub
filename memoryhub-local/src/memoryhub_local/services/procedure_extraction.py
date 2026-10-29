"""Procedural graph extraction for the personal edition (#554).

Detects a multi-step procedure in one thread with the same contract as the
server (``procedure_contract``: transcript format, strict schema,
observed/inferred evidence with the corroboration rule, minimum bar, entry
and reachability) and writes it as a procedural graph: a
``content_type="procedural"`` root, ``procedure_step`` children and
``precedes``/``requires``/``alternative_to`` edges, all in one transaction.

What the personal edition does NOT do (server only, see
planning/procedural-graph-extraction.md): structural refinement of an
existing graph (``apply`` mode), deprecation, cross-member matching,
candidate gating of guidance. A later session that matches an existing
procedure adds its evidence to the root's ledger (idempotent per thread)
and nothing else.

Off unless asked for: ``memoryhub dream --procedures``.
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from memoryhub_local.identity import TENANT_ID
from memoryhub_local.models.conversation import (
    ConversationExtraction,
    ConversationMessage,
    ConversationThread,
)
from memoryhub_local.models.memory import MemoryNode, MemoryRelationship
from memoryhub_local.models.reconciliation import ReconciliationDecision
from memoryhub_local.models.utils import generate_stub
from memoryhub_local.services.procedure_contract import (
    ProposalFormatError,
    Rejection,
    TrajectoryEvent,
    ValidatedProcedure,
    detect_procedure,
    format_trajectory,
    validate_proposal,
)
from memoryhub_local.services.procedure_prompt import SYSTEM_PROMPT

if TYPE_CHECKING:
    from memoryhub_local.embeddings.base import EmbeddingService
    from memoryhub_local.storage.recall import RecallBackend

logger = logging.getLogger(__name__)

CURSOR_KEY = "procedural_extraction"
_OUTCOMES = frozenset({"success", "failure", "partial"})
#: Procedures are written in the thread's own scope, never a shared tier.
_WRITABLE_SCOPES = frozenset({"user", "project"})

CompleteFn = Callable[[list[dict[str, Any]]], Awaitable[tuple[str, str | None]]]


@dataclass
class LocalProceduralSettings:
    """Thresholds (names match the server's AppSettings fields)."""

    procedural_min_steps: int = 3
    procedural_max_steps: int = 30
    procedural_min_detection_confidence: float = 0.7
    procedural_min_outcome_confidence: float = 0.7
    procedural_max_transcript_chars: int = 60000
    #: Cosine similarity of goal+summary at or above which a detection is the
    #: same procedure as an existing one (no tiebreaker locally).
    match_similarity: float = 0.90
    weight: float = 0.6


def _observed(items: list[Any]) -> list[str]:
    """Render fields hold observed items only (inferred stay in the decision log)."""
    return [i.text for i in items if i.evidence == "observed"]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _cursor(thread: ConversationThread) -> int:
    meta = thread.metadata_ if isinstance(thread.metadata_, dict) else {}
    state = meta.get(CURSOR_KEY) if isinstance(meta.get(CURSOR_KEY), dict) else {}
    return int(state.get("last_seq", 0) or 0)


def _set_cursor(thread: ConversationThread, last_seq: int, run_id: str) -> None:
    meta = copy.deepcopy(thread.metadata_) if isinstance(thread.metadata_, dict) else {}
    meta[CURSOR_KEY] = {"last_seq": last_seq, "last_run_id": run_id,
                        "last_attempt_at": _now().isoformat()}
    thread.metadata_ = meta


async def get_procedural_pending_threads(session: AsyncSession) -> list[dict[str, Any]]:
    """Active threads with messages after their procedural cursor."""
    rows = (await session.execute(
        select(
            ConversationThread,
            func.max(ConversationMessage.sequence_number).label("max_seq"),
        )
        .join(ConversationMessage, ConversationMessage.thread_id == ConversationThread.id)
        .where(ConversationThread.tenant_id == TENANT_ID, ConversationThread.status == "active")
        .group_by(ConversationThread.id)
    )).all()
    return [
        {"id": str(thread.id), "title": thread.title}
        for thread, max_seq in rows
        if max_seq is not None and max_seq > _cursor(thread)
    ]


def _event(msg: ConversationMessage) -> TrajectoryEvent:
    meta = msg.metadata_ if isinstance(msg.metadata_, dict) else {}
    marker = meta.get("outcome")
    marker = marker.strip().lower() if isinstance(marker, str) else None
    return TrajectoryEvent(
        seq=msg.sequence_number,
        role=(msg.role or "").lower(),
        content=msg.content if msg.content is not None else "[content unavailable]",
        tool_call_id=msg.tool_call_id,
        outcome_marker=marker if marker in _OUTCOMES else None,
        available=msg.content is not None,
    )


def _node(
    content: str,
    embedding: list[float],
    *,
    weight: float,
    metadata: dict[str, Any],
    thread: ConversationThread,
    parent_id: uuid.UUID | None = None,
    branch_type: str | None = None,
) -> MemoryNode:
    owner = thread.owner_id
    node_id = uuid.uuid4()
    return MemoryNode(
        id=node_id,
        logical_id=node_id,
        content=content,
        stub=generate_stub(content, thread.scope, weight, 0, False),
        storage_type="inline",
        weight=weight,
        scope=thread.scope,
        scope_id=thread.scope_id,
        parent_id=parent_id,
        branch_type=branch_type,
        owner_id=owner,
        actor_id=owner,
        tenant_id=TENANT_ID,
        domains=[],
        content_type="procedural",
        status="active",
        source="dreaming",
        content_hash=hashlib.sha256(content.encode()).hexdigest(),
        is_current=True,
        version=1,
        embedding=embedding,
        metadata_=metadata,
    )


def _session_entry(vp: ValidatedProcedure, run_id: str, max_seq: int) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "max_seq": max_seq,
        "recorded_at": _now().isoformat(),
        "outcome": vp.outcome.result,
        "outcome_source": vp.outcome.source,
        "strong": vp.outcome.strong,
        "steps": [s.action for s in vp.steps],
    }


def _decision(kind: str, reason: str | None, run_id: str, body: dict[str, Any],
              thread: ConversationThread, memory_id: uuid.UUID | None = None,
              stub: str = "") -> ReconciliationDecision:
    return ReconciliationDecision(
        extraction_run_id=run_id,
        candidate_content=json.dumps(body, default=str, sort_keys=True),
        candidate_stub=(stub or kind)[:100],
        action=kind,
        memory_id=memory_id,
        nearest_match_id=memory_id,
        reason=reason,
        owner_id=thread.owner_id,
        tenant_id=TENANT_ID,
        scope=thread.scope,
        scope_id=thread.scope_id,
    )


async def _find_match(
    session: AsyncSession,
    thread: ConversationThread,
    description_embedding: list[float],
    recall_backend: RecallBackend,
    settings: LocalProceduralSettings,
) -> uuid.UUID | None:
    filters = [
        MemoryNode.tenant_id == TENANT_ID,
        MemoryNode.owner_id == thread.owner_id,
        MemoryNode.scope == thread.scope,
        (MemoryNode.scope_id == thread.scope_id) if thread.scope_id is not None
        else MemoryNode.scope_id.is_(None),
        MemoryNode.content_type == "procedural",
        MemoryNode.parent_id.is_(None),
        MemoryNode.is_current.is_(True),
        MemoryNode.deleted_at.is_(None),
        MemoryNode.status == "active",
    ]
    pairs = await recall_backend.similarity_check(
        description_embedding, filters, 1.0 - settings.match_similarity, 1, session,
    )
    return pairs[0][0] if pairs else None


async def extract_procedures_from_thread(
    session: AsyncSession,
    thread_id: str,
    *,
    complete_fn: CompleteFn,
    embedding_service: EmbeddingService,
    recall_backend: RecallBackend,
    extraction_model: str = "local",
    settings: LocalProceduralSettings | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Run the procedural pass over one thread. Returns a ``procedures`` report.

    Model and validation failures are reported, not raised. Writes (root,
    steps, edges, provenance, decision rows, cursor) commit together.
    """
    settings = settings or LocalProceduralSettings()
    run_id = f"dream-proc:{extraction_model}:local:{_now().isoformat()}"
    report: dict[str, Any] = {"run_id": run_id, "detected": 0, "created": 0, "matched": 0,
                              "procedure_ids": [], "rejections": []}
    thread = (await session.execute(
        select(ConversationThread).where(
            ConversationThread.id == uuid.UUID(thread_id),
            ConversationThread.tenant_id == TENANT_ID,
        )
    )).scalar_one_or_none()
    if thread is None:
        raise ValueError(f"Thread {thread_id} not found")

    cursor = _cursor(thread)
    messages = list((await session.execute(
        select(ConversationMessage)
        .where(ConversationMessage.thread_id == thread.id)
        .order_by(ConversationMessage.sequence_number)
    )).scalars().all())
    events = [_event(m) for m in messages]
    max_seq = max((e.seq for e in events), default=0)
    if max_seq <= cursor:
        report["skipped"] = "no_new_messages"
        return report
    if thread.scope not in _WRITABLE_SCOPES:
        report["skipped"] = "scope_not_writable"
        return report
    if not any(e.role == "tool_call" for e in events):
        report["skipped"] = "no_tool_calls"
        return report

    def finish() -> None:
        if not dry_run:
            _set_cursor(thread, max_seq, run_id)

    def reject(reason: str, detail: str, body: dict[str, Any] | None = None) -> None:
        report["rejections"].append({"reason": reason, "detail": detail})
        if not dry_run:
            session.add(_decision("proc_reject", reason, run_id,
                                  {"detail": detail, "thread_id": thread_id, **(body or {})},
                                  thread))

    transcript, included = format_trajectory(
        events, max_chars=settings.procedural_max_transcript_chars,
    )
    try:
        proposal = await detect_procedure(complete_fn_adapter(complete_fn), transcript,
                                          system_prompt=SYSTEM_PROMPT)
    except ProposalFormatError as exc:
        reject("invalid_proposal", str(exc)[:500])
        finish()
        await _commit(session, dry_run)
        return report
    except Exception as exc:
        logger.warning("Procedural extraction failed for thread %s: %s", thread_id, exc)
        report["error"] = str(exc)[:500]
        return report

    report["detected"] = 1 if proposal.procedure_detected else 0
    validated = validate_proposal(proposal, events, included, settings)
    if validated is None:
        finish()
        await _commit(session, dry_run)
        return report
    if isinstance(validated, Rejection):
        reject(validated.reason, validated.detail)
        finish()
        await _commit(session, dry_run)
        return report

    report["proposal"] = validated.to_dict() if dry_run else None
    description_embedding = await embedding_service.embed(validated.description)
    match_id = await _find_match(session, thread, description_embedding, recall_backend,
                                 settings)

    try:
        if match_id is not None:
            report["matched"] = 1
            report["procedure_ids"] = [str(match_id)]
            if not dry_run:
                root = await session.get(MemoryNode, match_id)
                meta = copy.deepcopy(root.metadata_) if isinstance(root.metadata_, dict) else {}
                proc = meta.setdefault("procedure", {})
                sessions = proc.setdefault("evidence", {}).setdefault("sessions", {})
                previous = sessions.get(thread_id)
                if previous is not None and int(previous.get("max_seq", -1)) >= max_seq:
                    reject("duplicate", "session already accounted for")
                else:
                    sessions[thread_id] = _session_entry(validated, run_id, max_seq)
                    root.metadata_ = meta
                    session.add(_decision("proc_match", None, run_id,
                                          {"thread_id": thread_id,
                                           "proposal": validated.to_dict()},
                                          thread, memory_id=match_id,
                                          stub=validated.description))
        elif validated.outcome.is_failure:
            reject("insufficient_evidence",
                   "failed_session: a failed session does not create a procedure")
        elif dry_run:
            report["plan"] = {"action": "create", "status": "candidate"}
        else:
            root_id = await _write_graph(session, validated, thread, run_id, max_seq,
                                         extraction_model, description_embedding,
                                         embedding_service, settings)
            report["created"] = 1
            report["procedure_ids"] = [str(root_id)]
        finish()
        await _commit(session, dry_run)
    except Exception as exc:
        logger.exception("Procedural graph write failed for thread %s", thread_id)
        await session.rollback()
        report["created"] = 0
        report["error"] = f"write failed: {str(exc)[:400]}"
    return report


async def _commit(session: AsyncSession, dry_run: bool) -> None:
    if not dry_run:
        await session.commit()


def complete_fn_adapter(complete_fn: CompleteFn) -> Any:
    """Wrap a ``complete(messages)`` callable in the object the contract expects."""

    class _Adapter:
        async def complete(self, messages: list[dict[str, Any]]) -> tuple[str, str | None]:
            return await complete_fn(messages)

    return _Adapter()


async def _write_graph(
    session: AsyncSession,
    vp: ValidatedProcedure,
    thread: ConversationThread,
    run_id: str,
    max_seq: int,
    model: str,
    description_embedding: list[float],
    embedding_service: EmbeddingService,
    settings: LocalProceduralSettings,
) -> uuid.UUID:
    """Root, steps, edges and provenance in the caller's transaction (no commit)."""
    source = {"thread_id": str(thread.id), "model": model, "run_id": run_id}
    root = _node(
        vp.description, description_embedding, weight=settings.weight, thread=thread,
        metadata={
            "extraction_source": {**source, "source_messages": vp.source_messages},
            "procedure": {
                "origin": "extracted", "schema_version": 1, "status": "candidate",
                "goal": vp.goal, "entry_step_id": None,
                "evidence": {
                    "sessions": {str(thread.id): _session_entry(vp, run_id, max_seq)},
                    "evicted": {},
                },
                "pending_edits": [],
                "contradictions": [],
            },
        },
    )
    session.add(root)
    ids: dict[str, uuid.UUID] = {}
    embeddings = await embedding_service.embed_batch([s.action for s in vp.steps])
    for step, emb in zip(vp.steps, embeddings, strict=True):
        node = _node(
            step.action, emb, weight=settings.weight, thread=thread, parent_id=root.id,
            branch_type="procedure_step",
            metadata={
                "extraction_source": {**source, "source_messages": step.source_messages},
                "procedure": {
                    "action": step.action,
                    "tool_ref": step.tool_ref,
                    "preconditions": _observed(step.preconditions),
                    "postconditions": _observed(step.postconditions),
                    "pitfalls": _observed(step.pitfalls),
                    "guidance": step.guidance.text
                    if step.guidance and step.guidance.evidence == "observed" else None,
                    "origin": "extracted",
                    "step_key": step.key,
                },
            },
        )
        session.add(node)
        ids[step.key] = node.id
    await session.flush()
    for edge in vp.edges:
        session.add(MemoryRelationship(
            source_id=ids[edge.source],
            target_id=ids[edge.target],
            relationship_type=edge.type,
            created_by="dreaming:procedural",
            tenant_id=TENANT_ID,
            metadata_={
                "condition": edge.condition.text
                if edge.condition and edge.condition.evidence == "observed" else None,
                "guidance": edge.guidance.text
                if edge.guidance and edge.guidance.evidence == "observed" else None,
                "pitfalls": _observed(edge.pitfalls),
                "origin": "extracted",
            },
        ))
    meta = copy.deepcopy(root.metadata_)
    meta["procedure"]["entry_step_id"] = str(ids[vp.entry_key])
    root.metadata_ = meta
    session.add(ConversationExtraction(
        memory_node_id=root.id,
        thread_id=thread.id,
        source_messages=vp.source_messages,
        extracted_by="procedural_extraction_pipeline",
        extraction_model=model,
        extraction_prompt_hash=hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest(),
        tenant_id=TENANT_ID,
    ))
    session.add(_decision("proc_create", None, run_id,
                          {"thread_id": str(thread.id), "proposal": vp.to_dict()},
                          thread, memory_id=root.id, stub=vp.description))
    await session.flush()
    return root.id


def make_http_complete_fn(model: str, url: str, api_key: str | None = None) -> CompleteFn:
    """``complete(messages)`` against an OpenAI-compatible endpoint (TLS verification on)."""

    async def _complete(messages: list[dict[str, Any]]) -> tuple[str, str | None]:
        import httpx

        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                f"{url.rstrip('/')}/chat/completions",
                json={"model": model, "messages": messages, "temperature": 0.0,
                      "max_tokens": 4000, "response_format": {"type": "json_object"}},
                headers=headers,
            )
            resp.raise_for_status()
            choice = resp.json()["choices"][0]
            return choice["message"].get("content") or "", choice.get("finish_reason")

    return _complete
