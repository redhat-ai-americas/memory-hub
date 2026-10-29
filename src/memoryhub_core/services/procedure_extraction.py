"""Procedural graph extraction from dreaming (#554).

Detects a multi-step procedure in one conversation session and writes it as a
procedural graph (#552 shape: a ``content_type="procedural"`` root, current
``procedure_step`` children, ``precedes``/``requires``/``alternative_to`` edges,
attributes in ``metadata_.procedure``). Later sessions that cover the same
procedure refine it through ``procedure_evolution`` instead of duplicating it.

Design and signed-off decisions: ``planning/procedural-graph-extraction.md``.

The pass is off by default (``AppSettings.procedural_extraction_mode``) and is
called from ``dreaming.extract_from_thread`` after the fact windows. It never
touches the fact cursor. All graph writes for one run, the provenance row, the
decision-log rows and the procedural cursor commit in one transaction.

Only observable evidence is reported as ``observed``: steps must be backed by
cited messages, and inferred items never reach the fields #553 renders into
guidance prose.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import logging
import ssl
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import yaml
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from memoryhub_core.config import AppSettings
from memoryhub_core.models.conversation import (
    ConversationExtraction,
    ConversationMessage,
    ConversationThread,
)
from memoryhub_core.models.memory import MemoryNode
from memoryhub_core.models.reconciliation import (
    ReconciliationDecision as ReconciliationDecisionRow,
)
from memoryhub_core.models.schemas import MemoryNodeCreate, RelationshipCreate
from memoryhub_core.services.curation.pipeline import run_curation_pipeline
from memoryhub_core.services.graph import create_relationship
from memoryhub_core.services.procedure_contract import (  # noqa: F401 -- re-exported
    _OUTCOME_MARKERS,
    EdgeProposal,
    EvidencedText,
    EvText,
    OutcomeInfo,
    OutcomeProposal,
    ProceduralProposal,
    ProposalFormatError,
    Rejection,
    StepProposal,
    TrajectoryEvent,
    ValidatedProcedure,
    VEdge,
    VStep,
    _parse_json,
    format_trajectory,
    validate_proposal,
    wrap_transcript,
)
from memoryhub_core.services.procedure_contract import (
    detect_procedure as _detect_with_prompt,
)

logger = logging.getLogger(__name__)

MODES: tuple[str, ...] = ("off", "propose", "apply")
_MODE_RANK = {mode: rank for rank, mode in enumerate(MODES)}

#: Thread scopes that may produce procedures. Never organizational,
#: enterprise or role (task constraint); campaign excluded conservatively.
ALLOWED_THREAD_SCOPES = frozenset({"user", "project"})

CREATED_BY = "dreaming:procedural"
EXTRACTED_BY = "procedural_extraction_pipeline"
CURSOR_KEY = "procedural_extraction"

# Decision-log actions (reconciliation_decisions.action is String(20)).
PROC_CREATE = "proc_create"
PROC_MATCH = "proc_match"
PROC_PROPOSE = "proc_propose"
PROC_EDIT = "proc_edit"
PROC_REJECT = "proc_reject"

# Rejection reasons (#555 seam; see record_procedural_decision).
REASONS = frozenset({
    "below_confidence",
    "insufficient_evidence",
    "breaks_entry",
    "hand_authored",
    "cap_reached",
    "duplicate",
    "inferred_only",
    "conflicting_evidence",
    "ambiguous_match",
    "invalid_proposal",
    "curation_blocked",
    "scope_not_allowed",
    "evidence_evicted",
    "propose_mode",
    "foreign_owner",
    # Optional validation gate (procedure_validation).
    "validation_rejected",
    "validation_unavailable",
    "validation_unseen",
})

_RETRY_DELAYS = [0.0, 30.0, 60.0, 120.0]
_MAX_SERVICE_ATTEMPTS = len(_RETRY_DELAYS)

# Text caps for what is written (keeps every node far below the chunking and
# S3 thresholds, which create_memory(commit=False) refuses).
_ATTR_PER_FIELD_MAX = 5


# ---------------------------------------------------------------------------
# Mode resolution (D1)
# ---------------------------------------------------------------------------


def _norm_mode(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip().lower()
    return value if value in _MODE_RANK else None


def resolve_mode(
    server_mode: Any,
    retention_policy: dict[str, Any] | None,
    *,
    caller_mode: str | None = None,
    procedures: bool | None = None,
) -> str:
    """Effective procedural mode for one run.

    The server setting is a ceiling. A thread's ``retention_policy`` override
    and the caller's ``procedure_mode`` can only lower it. ``procedures=False``
    turns the pass off for this call. An unknown server value is treated as
    ``off``; an unknown caller value raises ``ValueError``.
    """
    server = _norm_mode(server_mode)
    if server is None:
        if server_mode not in (None, ""):
            logger.warning("Unknown procedural_extraction_mode %r; treating as off", server_mode)
        server = "off"
    if caller_mode is not None and _norm_mode(caller_mode) is None:
        raise ValueError(
            f"procedure_mode must be one of {', '.join(MODES)}; got {caller_mode!r}"
        )
    if procedures is False:
        return "off"
    candidates = [server]
    if isinstance(retention_policy, dict):
        thread_mode = _norm_mode(retention_policy.get("procedural_extraction_mode"))
        if thread_mode is not None:
            candidates.append(thread_mode)
    if caller_mode is not None:
        candidates.append(_norm_mode(caller_mode))  # type: ignore[arg-type]
    return min(candidates, key=_MODE_RANK.__getitem__)


# ---------------------------------------------------------------------------
# Trajectory (D2)
# ---------------------------------------------------------------------------


async def load_trajectory(
    session: AsyncSession,
    *,
    thread_id: uuid.UUID,
    tenant_id: str,
    s3_adapter: Any | None = None,
    turn_range: tuple[int, int] | None = None,
) -> list[TrajectoryEvent]:
    """Load the session's messages as events, hydrating S3-backed content."""
    stmt = select(ConversationMessage).where(
        ConversationMessage.thread_id == thread_id,
        ConversationMessage.tenant_id == tenant_id,
    )
    if turn_range is not None:
        stmt = stmt.where(
            ConversationMessage.sequence_number >= turn_range[0],
            ConversationMessage.sequence_number <= turn_range[1],
        )
    stmt = stmt.order_by(ConversationMessage.sequence_number.asc())
    rows = list((await session.execute(stmt)).scalars().all())

    events: list[TrajectoryEvent] = []
    for msg in rows:
        content = msg.content
        available = content is not None
        if msg.storage_type == "s3" and msg.content_ref:
            available = False
            if s3_adapter is not None:
                try:
                    content = await s3_adapter.get_content(msg.content_ref)
                    available = content is not None
                except Exception as exc:  # pragma: no cover - logged and degraded
                    logger.warning(
                        "Could not hydrate S3 message seq=%s of thread %s: %s",
                        msg.sequence_number, thread_id, exc,
                    )
        marker = None
        metadata = msg.metadata_ if isinstance(msg.metadata_, dict) else {}
        raw_marker = metadata.get("outcome")
        if isinstance(raw_marker, str) and raw_marker.strip().lower() in _OUTCOME_MARKERS:
            marker = raw_marker.strip().lower()
        events.append(
            TrajectoryEvent(
                seq=msg.sequence_number,
                role=(msg.role or "").lower(),
                content=content if available and content is not None else "[content unavailable]",
                tool_call_id=msg.tool_call_id,
                outcome_marker=marker,
                available=available,
            )
        )
    return events


# ---------------------------------------------------------------------------
# Proposal schema (D3)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Prompt + LLM transport
# ---------------------------------------------------------------------------

_prompt_cache: dict[str, Any] = {}


def load_prompts() -> tuple[str, str, str]:
    """Return (system_prompt, tiebreaker_prompt, prompt_hash). Cached."""
    if "prompts" in _prompt_cache:
        return _prompt_cache["prompts"]
    path = Path(__file__).resolve().parents[3] / "prompts" / "procedural_extraction.yaml"
    data = yaml.safe_load(path.read_text())
    system_prompt = data["system_prompt"]
    tiebreaker = data["match_tiebreaker_prompt"]
    prompt_hash = hashlib.sha256(system_prompt.encode()).hexdigest()
    _prompt_cache["prompts"] = (system_prompt, tiebreaker, prompt_hash)
    return _prompt_cache["prompts"]


class ProceduralLLMError(RuntimeError):
    """The extraction endpoint could not be reached or kept failing."""


class ProceduralLLM:
    """OpenAI-compatible chat client for the procedural pass.

    Uses the ``conv_extraction_*`` endpoint (same URL convention as the fact
    path: ``{url}/chat/completions``). TLS verification stays on.
    """

    def __init__(
        self,
        *,
        model: str,
        url: str,
        api_key: str = "",
        timeout: float = 60,
        client: httpx.AsyncClient | None = None,
        ca_bundle: str | None = None,
    ) -> None:
        self.model = model
        self.url = url.rstrip("/")
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        # TODO(#604): replace with the shared outbound LLM client factory once
        # it exists. Default TLS verification on purpose: no verify=False here.
        # A private CA is configured with procedural_llm_ca_bundle (a path), never by
        # turning verification off.
        verify: Any = ssl.create_default_context(cafile=ca_bundle) if ca_bundle else True
        self._client = client or httpx.AsyncClient(timeout=timeout, headers=headers, verify=verify)
        self._owns_client = client is None

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def complete(self, messages: list[dict[str, Any]]) -> tuple[str, str | None]:
        last_error: Exception | None = None
        for attempt in range(_MAX_SERVICE_ATTEMPTS):
            try:
                response = await self._client.post(
                    f"{self.url}/chat/completions",
                    json={
                        "model": self.model,
                        "messages": messages,
                        "temperature": 0.0,
                        "max_tokens": 4000,
                        "response_format": {"type": "json_object"},
                    },
                )
                response.raise_for_status()
            except (httpx.ConnectError, httpx.TimeoutException) as exc:
                last_error = exc
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code not in (429, 502, 503, 504):
                    raise ProceduralLLMError(
                        f"Procedural extraction LLM returned {exc.response.status_code}"
                    ) from exc
                last_error = exc
            else:
                try:
                    choice = response.json()["choices"][0]
                    content = choice["message"].get("content") or ""
                    return str(content), choice.get("finish_reason")
                except (KeyError, IndexError, TypeError, ValueError) as exc:
                    raise ProceduralLLMError(f"Unexpected LLM response structure: {exc}") from exc
            if attempt < _MAX_SERVICE_ATTEMPTS - 1:
                delay = _RETRY_DELAYS[attempt + 1]
                logger.warning(
                    "Procedural extraction LLM error (attempt %d/%d): %s -- retrying in %.0fs",
                    attempt + 1, _MAX_SERVICE_ATTEMPTS, last_error, delay,
                )
                await _sleep(delay)
        raise ProceduralLLMError(f"Procedural extraction LLM failed after retries: {last_error}")


async def _sleep(delay: float) -> None:
    await asyncio.sleep(delay)


async def detect_procedure(llm: Any, transcript: str) -> ProceduralProposal:
    """Ask the model for a proposal with the repo prompt; one correction retry."""
    system_prompt, _, _ = load_prompts()
    return await _detect_with_prompt(llm, transcript, system_prompt=system_prompt)


def make_tiebreaker(llm: Any) -> Callable[[str, str], Awaitable[str]]:
    """Build the D5 tiebreaker on the same endpoint. Returns 'same' or 'different'."""

    async def _tiebreak(new_description: str, existing_description: str) -> str:
        _, tiebreaker_prompt, _ = load_prompts()
        content, _finish = await llm.complete([
            {"role": "system", "content": tiebreaker_prompt},
            {
                "role": "user",
                "content": f"Procedure A:\n{new_description}\n\nProcedure B:\n{existing_description}",
            },
        ])
        verdict = _parse_json(content).get("verdict")
        if verdict not in ("same", "different"):
            raise ValueError(f"tiebreaker returned {verdict!r}")
        return verdict

    return _tiebreak


# ---------------------------------------------------------------------------
# Deterministic validation (D3)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Thread snapshot, cursor, decision log (D9)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ThreadInfo:
    """Plain copy of the thread fields the pass needs (survives a rollback)."""

    id: uuid.UUID
    tenant_id: str
    owner_id: str
    scope: str
    scope_id: str | None
    actor_id: str | None

    @classmethod
    def of(cls, thread: ConversationThread) -> ThreadInfo:
        return cls(
            id=thread.id,
            tenant_id=thread.tenant_id,
            owner_id=thread.owner_id,
            scope=thread.scope,
            scope_id=thread.scope_id,
            actor_id=thread.actor_id,
        )


def cursor_state(thread: ConversationThread) -> dict[str, Any]:
    metadata = thread.metadata_ if isinstance(thread.metadata_, dict) else {}
    state = metadata.get(CURSOR_KEY)
    return dict(state) if isinstance(state, dict) else {}


def set_cursor_state(thread: ConversationThread, **updates: Any) -> None:
    metadata = copy.deepcopy(thread.metadata_) if isinstance(thread.metadata_, dict) else {}
    state = metadata.get(CURSOR_KEY) if isinstance(metadata.get(CURSOR_KEY), dict) else {}
    state = {**state, **updates}
    metadata[CURSOR_KEY] = state
    thread.metadata_ = metadata  # reassign: the JSON column is not mutation-tracked


def record_procedural_decision(
    session: AsyncSession,
    *,
    kind: str,
    reason: str | None,
    thread: ThreadInfo,
    run_id: str,
    payload: dict[str, Any],
    source_messages: list[int] | None = None,
    procedure_id: uuid.UUID | None = None,
    nearest_id: uuid.UUID | None = None,
    score: float | None = None,
    stub: str = "",
) -> None:
    """The single path for every procedural decision, accepted or rejected.

    Rejections (``kind=proc_reject`` or a proposal with a reason) carry the
    proposal, the reason, the source thread and messages and the run id. #555
    can back this function with a rejection store without changing callers.
    Rows land in ``reconciliation_decisions`` (no new table).
    """
    if reason is not None and reason not in REASONS:
        raise ValueError(f"unknown procedural decision reason {reason!r}")
    body = {
        "kind": kind,
        "thread_id": str(thread.id),
        "source_messages": source_messages or [],
        "run_id": run_id,
        **payload,
    }
    session.add(
        ReconciliationDecisionRow(
            id=uuid.uuid4(),
            extraction_run_id=run_id,
            candidate_content=json.dumps(body, default=str, sort_keys=True),
            candidate_stub=(stub or kind)[:200],
            nearest_match_id=nearest_id,
            similarity_score=score,
            action=kind,
            memory_id=procedure_id,
            reason=reason,
            owner_id=thread.owner_id,
            tenant_id=thread.tenant_id,
            scope=thread.scope,
            scope_id=thread.scope_id,
        )
    )


async def curation_preflight(
    session: AsyncSession, texts: list[str], *, thread: ThreadInfo,
) -> str | None:
    """Run the regex tier (secrets, PII) over all text that will be written.

    Returns a block detail, or ``None`` when the text may be written. Also
    seeds the tenant's default rules (which commits) before any write in the
    graph transaction, so that commit cannot split it.
    """
    if not texts:
        return None
    result = await run_curation_pipeline(
        content="\n".join(texts),
        embedding=None,
        owner_id=thread.owner_id,
        scope=thread.scope,
        session=session,
        tenant_id=thread.tenant_id,
    )
    if result.get("blocked"):
        return str(result.get("reason") or "blocked")
    return None


# ---------------------------------------------------------------------------
# Creation writer (D4)
# ---------------------------------------------------------------------------


@dataclass
class RunContext:
    run_id: str
    model: str
    prompt_hash: str
    mode: str
    settings: AppSettings
    now: datetime
    roles: dict[int, str]
    created_node_ids: list[uuid.UUID] = field(default_factory=list)
    created_node_contents: dict[uuid.UUID, str] = field(default_factory=dict)

    def extraction_source(self, thread: ThreadInfo, seqs: list[int]) -> dict[str, Any]:
        return {
            "thread_id": str(thread.id),
            "source_messages": sorted(set(seqs)),
            "model": self.model,
            "prompt_hash": self.prompt_hash,
            "run_id": self.run_id,
        }

    def trust_for(self, seqs: list[int]) -> str:
        return "mixed" if any(self.roles.get(s) == "tool_result" for s in seqs) else "trusted"

    @property
    def weight(self) -> float:
        return min(self.settings.procedural_auto_weight, self.settings.procedural_max_auto_weight)


def observed_texts(items: list[EvText]) -> list[str]:
    out: list[str] = []
    for item in items:
        if item.evidence == "observed" and item.text not in out:
            out.append(item.text)
    return out[:_ATTR_PER_FIELD_MAX]


def attribute_evidence_entry(item: EvText, thread_id: uuid.UUID) -> dict[str, Any]:
    return {
        "text": item.text,
        "evidence": item.evidence,
        "source_messages": item.source_messages,
        "threads": [str(thread_id)],
    }


def step_metadata(step: VStep, thread: ThreadInfo, ctx: RunContext) -> dict[str, Any]:
    """``metadata_`` for a new step. Render fields hold observed items only."""
    attr: dict[str, list[dict[str, Any]]] = {}
    for name in ("preconditions", "postconditions", "pitfalls"):
        items = getattr(step, name)
        if items:
            attr[name] = [attribute_evidence_entry(i, thread.id) for i in items]
    if step.guidance:
        attr["guidance"] = [attribute_evidence_entry(step.guidance, thread.id)]
    guidance = step.guidance.text if step.guidance and step.guidance.evidence == "observed" else None
    return {
        "extraction_source": ctx.extraction_source(thread, step.source_messages),
        "procedure": {
            "action": step.action,
            "tool_ref": step.tool_ref,
            "preconditions": observed_texts(step.preconditions),
            "postconditions": observed_texts(step.postconditions),
            "pitfalls": observed_texts(step.pitfalls),
            "guidance": guidance,
            "origin": "extracted",
            "step_key": step.key,
            "attribute_evidence": attr,
        },
    }


def edge_metadata(edge: VEdge, thread: ThreadInfo, ctx: RunContext) -> dict[str, Any]:
    attr: dict[str, list[dict[str, Any]]] = {}
    for name in ("condition", "guidance"):
        item = getattr(edge, name)
        if item is not None:
            attr[name] = [attribute_evidence_entry(item, thread.id)]
    if edge.pitfalls:
        attr["pitfalls"] = [attribute_evidence_entry(i, thread.id) for i in edge.pitfalls]
    condition = edge.condition.text if edge.condition and edge.condition.evidence == "observed" else None
    guidance = edge.guidance.text if edge.guidance and edge.guidance.evidence == "observed" else None
    return {
        "condition": condition,
        "guidance": guidance,
        "pitfalls": observed_texts(edge.pitfalls),
        "origin": "extracted",
        "attribute_evidence": attr,
        "extraction_source": ctx.extraction_source(thread, edge.source_messages),
    }


async def create_step_node(
    session: AsyncSession,
    embedding_service: Any,
    *,
    root_id: uuid.UUID,
    content: str,
    metadata: dict[str, Any],
    thread: ThreadInfo,
    ctx: RunContext,
    seqs: list[int],
) -> uuid.UUID:
    from memoryhub_core.services.memory import create_memory

    data = MemoryNodeCreate(
        content=content,
        scope=thread.scope,
        weight=ctx.weight,
        owner_id=thread.owner_id,
        scope_id=thread.scope_id,
        parent_id=root_id,
        branch_type="procedure_step",
        metadata=metadata,
        content_type="procedural",
        source="dreaming",
        upstream_trust_level=ctx.trust_for(seqs),
    )
    if thread.actor_id:
        data.actor_id = thread.actor_id
    node, _ = await create_memory(
        data, session, embedding_service,
        tenant_id=thread.tenant_id, skip_curation=True, commit=False,
    )
    assert node is not None  # skip_curation=True never blocks
    ctx.created_node_ids.append(node.id)
    ctx.created_node_contents[node.id] = content
    return node.id


async def create_procedural_edge(
    session: AsyncSession,
    *,
    source_id: uuid.UUID,
    target_id: uuid.UUID,
    rel_type: str,
    metadata: dict[str, Any],
) -> uuid.UUID:
    rel = await create_relationship(
        RelationshipCreate(
            source_id=source_id,
            target_id=target_id,
            relationship_type=rel_type,
            created_by=CREATED_BY,
            metadata=metadata,
        ),
        session,
        commit=False,
    )
    return rel.id


async def write_new_procedure(
    session: AsyncSession,
    embedding_service: Any,
    *,
    thread: ThreadInfo,
    vp: ValidatedProcedure,
    ctx: RunContext,
    max_seq: int,
) -> uuid.UUID:
    """Write root, steps, edges and the entry inside the caller's transaction.

    Nothing is committed here. The caller commits once (with the provenance
    row, the decision row and the cursor) or rolls everything back.
    """
    from memoryhub_core.services.memory import create_memory
    from memoryhub_core.services.procedure_evolution import (
        build_session_entry,
        refresh_derived_evidence,
    )

    root_seqs = vp.source_messages
    root_data = MemoryNodeCreate(
        content=vp.description,
        scope=thread.scope,
        weight=ctx.weight,
        owner_id=thread.owner_id,
        scope_id=thread.scope_id,
        metadata={
            "extraction_source": ctx.extraction_source(thread, root_seqs),
            "procedure": {
                "origin": "extracted",
                "schema_version": 1,
                "status": "candidate",
                "goal": vp.goal,
                "entry_step_id": None,
                "evidence": {"sessions": {}, "evicted": {}},
                "pending_edits": [],
                "contradictions": [],
            },
        },
        content_type="procedural",
        source="dreaming",
        upstream_trust_level=ctx.trust_for(root_seqs),
    )
    if thread.actor_id:
        root_data.actor_id = thread.actor_id
    root_read, _ = await create_memory(
        root_data, session, embedding_service,
        tenant_id=thread.tenant_id, skip_curation=True, commit=False,
    )
    assert root_read is not None
    root_id = root_read.id
    ctx.created_node_ids.append(root_id)
    ctx.created_node_contents[root_id] = vp.description

    ids: dict[str, uuid.UUID] = {}
    for step in vp.steps:
        ids[step.key] = await create_step_node(
            session, embedding_service,
            root_id=root_id,
            content=step.action,
            metadata=step_metadata(step, thread, ctx),
            thread=thread, ctx=ctx, seqs=step.source_messages,
        )
    active_edges: dict[tuple[str, str, str], str] = {}
    for edge in vp.edges:
        edge_id = await create_procedural_edge(
            session,
            source_id=ids[edge.source],
            target_id=ids[edge.target],
            rel_type=edge.type,
            metadata=edge_metadata(edge, thread, ctx),
        )
        active_edges[(str(ids[edge.source]), str(ids[edge.target]), edge.type)] = str(edge_id)

    root = await session.get(MemoryNode, root_id)
    assert root is not None
    metadata = copy.deepcopy(root.metadata_)
    procedure = metadata["procedure"]
    procedure["entry_step_id"] = str(ids[vp.entry_key])
    entry = build_session_entry(
        vp=vp, alignment=ids, active_edges=active_edges, run_id=ctx.run_id, max_seq=max_seq, now=ctx.now,
    )
    procedure["evidence"]["sessions"][str(thread.id)] = entry
    root.metadata_ = metadata

    session.add(
        ConversationExtraction(
            id=uuid.uuid4(),
            memory_node_id=root_id,
            thread_id=thread.id,
            source_messages=root_seqs,
            extracted_by=EXTRACTED_BY,
            extraction_model=ctx.model,
            extraction_prompt_hash=ctx.prompt_hash,
            tenant_id=thread.tenant_id,
        )
    )
    await session.flush()
    await refresh_derived_evidence(session, root_id=root_id, tenant_id=thread.tenant_id, settings=ctx.settings)
    return root_id


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def _proposal_texts(proposal: ProceduralProposal) -> list[str]:
    texts = [proposal.goal or "", proposal.summary or ""]
    for step in proposal.steps:
        texts.extend([step.action, step.tool_ref or ""])
        for item in [*step.preconditions, *step.postconditions, *step.pitfalls, step.guidance]:
            if item is not None:
                texts.append(item.text)
    for edge in proposal.edges:
        for item in [edge.condition, edge.guidance, *edge.pitfalls]:
            if item is not None:
                texts.append(item.text)
    return [t for t in texts if t]


def _empty_report(mode: str, run_id: str, cursor: int) -> dict[str, Any]:
    return {
        "mode": mode,
        "run_id": run_id,
        "detected": 0,
        "created": 0,
        "matched": 0,
        "edits_proposed": 0,
        "edits_applied": 0,
        "edits_rejected": 0,
        "procedure_ids": [],
        "cursor": cursor,
        "rejections": [],
        "overlapping_facts": [],
    }


async def _overlapping_facts(
    session: AsyncSession,
    embedding_service: Any,
    description: str,
    fact_ids: list[uuid.UUID],
    *,
    tenant_id: str,
) -> list[dict[str, Any]]:
    """D8: fact memories from the same run that restate the procedure."""
    if not fact_ids:
        return []
    from memoryhub_core.services.procedure_evolution import _cosine

    embedding = await embedding_service.embed(description)
    rows = (await session.execute(
        select(MemoryNode).where(MemoryNode.id.in_(fact_ids), MemoryNode.tenant_id == tenant_id)
    )).scalars().all()
    out = []
    for node in rows:
        score = _cosine(embedding, node.embedding)
        if score >= 0.85:
            out.append({"memory_id": str(node.id), "score": round(score, 4)})
    return out


async def release_transaction(session: AsyncSession) -> None:
    """End the session's implicit read transaction before a slow step (an LLM call).

    Holding a transaction open while waiting on a model leaves the pooled
    connection "idle in transaction" for minutes (review of #554, item 3).
    Only a transaction with nothing pending is ended; pending writes are a
    programming error here and are left for the caller.
    """
    if not session.in_transaction():
        return
    if session.new or session.dirty or session.deleted:
        logger.warning("release_transaction called with pending changes; leaving the transaction open")
        return
    await session.commit()


def _dialect(session: AsyncSession) -> str:
    try:
        return session.get_bind().dialect.name
    except Exception:  # pragma: no cover - unbound sessions in odd test setups
        return ""


async def lock_thread(session: AsyncSession, thread: ConversationThread) -> None:
    """``SELECT ... FOR UPDATE`` on the thread and refresh it (no-op lock on SQLite)."""
    await session.execute(
        select(ConversationThread)
        .where(ConversationThread.id == thread.id, ConversationThread.tenant_id == thread.tenant_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


async def lock_owner_scope(session: AsyncSession, thread: ThreadInfo) -> None:
    """Transaction-scoped advisory lock serializing procedure *creation* per owner scope.

    Two sessions of the same owner that detect the same new procedure
    concurrently would otherwise both create a root. PostgreSQL only.
    """
    if _dialect(session) != "postgresql":
        return
    from memoryhub_core.services.procedure_evolution import shares_procedures_across_members

    # In a project every member matches every member's procedures, so creation
    # is serialized per project, not per owner.
    owner = "*" if shares_procedures_across_members(thread) else thread.owner_id
    key = f"memoryhub:procedural:{thread.tenant_id}:{owner}:{thread.scope}:{thread.scope_id or ''}"
    await session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": key})


async def extract_procedures_from_thread(
    session: AsyncSession,
    *,
    thread: ConversationThread,
    embedding_service: Any,
    mode: str,
    model: str,
    url: str,
    api_key: str = "",
    timeout: float = 60,
    s3_adapter: Any | None = None,
    turn_range: tuple[int, int] | None = None,
    dry_run: bool = False,
    llm: Any | None = None,
    settings: AppSettings | None = None,
    fact_memory_ids: list[uuid.UUID] | None = None,
    validator: Any | None = None,
) -> dict[str, Any]:
    """Run the procedural pass over one thread and return the ``procedures`` report.

    Two phases. Phase A reads the trajectory, calls the model, validates,
    runs the curation pre-flight and matching, and holds no transaction
    while a model call is in flight. Phase B takes the locks (thread row,
    owner-scope advisory lock for a new root, ``FOR UPDATE`` on a matched
    root), re-checks the cursor and the ledger, and writes everything in one
    transaction.

    Never raises for model, validation or write failures: those are reported
    under ``error`` or ``rejections`` so the fact results are unaffected.
    """
    from memoryhub_core.services.procedure_evolution import (
        ProceduralInvariantError,
        check_invariants,
        evolve_procedure,
        find_matching_procedure,
    )

    if mode not in ("propose", "apply"):
        raise ValueError(f"extract_procedures_from_thread needs mode propose or apply, got {mode!r}")
    settings = settings or AppSettings()
    _, _, prompt_hash = load_prompts()
    now = datetime.now(UTC)
    run_id = f"dream-proc:{model}:{prompt_hash}:{now.isoformat()}"
    info = ThreadInfo.of(thread)

    cursor = int(cursor_state(thread).get("last_seq", 0) or 0)
    report = _empty_report(mode, run_id, cursor)
    if dry_run:
        report["dry_run"] = True
    max_seq = 0

    async def finish(*, advance: bool, error: str | None = None) -> None:
        """Write the cursor (re-read under the thread lock) and commit."""
        if dry_run:
            return
        await lock_thread(session, thread)
        current = int(cursor_state(thread).get("last_seq", 0) or 0)
        updates: dict[str, Any] = {"last_run_id": run_id, "last_attempt_at": now.isoformat(), "last_error": error}
        if advance and turn_range is None:
            updates["last_seq"] = max(current, max_seq)
            report["cursor"] = updates["last_seq"]
        set_cursor_state(thread, **updates)
        await session.commit()

    def reject(reason: str, detail: str, payload: dict[str, Any] | None = None, **kwargs: Any) -> None:
        report["rejections"].append({"reason": reason, "detail": detail})
        if not dry_run:
            record_procedural_decision(
                session, kind=PROC_REJECT, reason=reason, thread=info, run_id=run_id,
                payload={"detail": detail, **(payload or {})}, stub=detail, **kwargs,
            )

    async def rollback_and_reload() -> None:
        await session.rollback()
        await session.refresh(thread)
        ctx.created_node_ids.clear()

    if info.scope not in ALLOWED_THREAD_SCOPES:
        report["skipped"] = "scope_not_allowed"
        reject("scope_not_allowed", f"thread scope {info.scope!r} may not produce procedures")
        if not dry_run:
            await session.commit()
        return report

    # ---- Phase A: read, model, validate, pre-flight, match (no locks held) ----
    events = await load_trajectory(
        session, thread_id=info.id, tenant_id=info.tenant_id, s3_adapter=s3_adapter, turn_range=turn_range,
    )
    max_seq = max((e.seq for e in events), default=0)
    if turn_range is None and max_seq <= cursor:
        report["skipped"] = "no_new_messages"
        await release_transaction(session)
        return report
    if not any(e.role == "tool_call" for e in events):
        report["skipped"] = "no_tool_calls"
        await release_transaction(session)
        return report

    transcript, included = format_trajectory(events, max_chars=settings.procedural_max_transcript_chars)
    roles = {e.seq: e.role for e in events}
    owns_llm = llm is None
    if llm is None:
        llm = ProceduralLLM(
            model=model, url=url, api_key=api_key, timeout=timeout,
            ca_bundle=settings.procedural_llm_ca_bundle or None,
        )
    ctx = RunContext(
        run_id=run_id, model=model, prompt_hash=prompt_hash, mode=mode,
        settings=settings, now=now, roles=roles,
    )
    await release_transaction(session)

    try:
        try:
            proposal = await detect_procedure(llm, transcript)
        except ProposalFormatError as exc:
            reject("invalid_proposal", str(exc)[:500], source_messages=sorted(included))
            await finish(advance=True)
            return report
        except Exception as exc:
            logger.warning("Procedural extraction failed for thread %s: %s", info.id, exc)
            report["error"] = str(exc)[:500]
            await finish(advance=False, error=str(exc)[:500])
            return report

        if proposal.procedure_detected:
            report["detected"] = 1
        validated = validate_proposal(proposal, events, included, settings)
        if validated is None:
            await finish(advance=True)
            return report

        if isinstance(validated, Rejection):
            payload: dict[str, Any] = {}
            if dry_run:
                payload = {"proposal": proposal.model_dump(by_alias=True)}
                report["proposal"] = payload["proposal"]
            elif await curation_preflight(session, _proposal_texts(proposal), thread=info) is None:
                payload = {"proposal": proposal.model_dump(by_alias=True)}
            reject(validated.reason, validated.detail, payload, source_messages=sorted(included))
            await finish(advance=True)
            return report

        if dry_run:
            report["proposal"] = validated.to_dict()
            report["curation"] = "not_run_in_dry_run"
        else:
            # May seed the tenant's curation rules (a commit): done before any lock.
            blocked = await curation_preflight(session, validated.all_text(), thread=info)
            if blocked is not None:
                # The proposal text is withheld from the log on purpose.
                reject("curation_blocked", f"curation blocked the proposal: {blocked}",
                       source_messages=validated.source_messages)
                await finish(advance=True)
                return report

        match = await find_matching_procedure(
            session, thread=info, vp=validated, embedding_service=embedding_service,
            settings=settings, tiebreaker=make_tiebreaker(llm),
            before_tiebreak=lambda: release_transaction(session),
        )

        if dry_run:
            return await _dry_run_plan(
                session, embedding_service, report=report, info=info, validated=validated,
                match=match, ctx=ctx, max_seq=max_seq,
            )

        structural_verdicts = await _validate_planned_edits(
            session, embedding_service, settings=settings, validator=validator, report=report,
            info=info, validated=validated, match=match, ctx=ctx, max_seq=max_seq,
        )

        # ---- Phase B: lock, re-check, write, commit ----
        await release_transaction(session)
        await lock_thread(session, thread)
        locked_cursor = int(cursor_state(thread).get("last_seq", 0) or 0)
        if turn_range is None and locked_cursor >= max_seq:
            report["skipped"] = "processed_concurrently"
            report["cursor"] = locked_cursor
            await session.commit()
            return report

        if match.kind == "new":
            await lock_owner_scope(session, info)
            # Another run may have created the root while this one was in phase A.
            rematch = await find_matching_procedure(
                session, thread=info, vp=validated, embedding_service=embedding_service,
                settings=settings, tiebreaker=None, known_verdicts=match.verdicts(),
            )
            if rematch.kind != "new":
                rematch.candidates.append({"rematched_under_lock": True})
                match = rematch

        report["match"] = match.to_dict()
        proposal_payload = {"proposal": validated.to_dict(), "match": match.to_dict()}

        if match.kind == "ambiguous":
            reject("ambiguous_match", "procedure matches an existing one ambiguously; nothing created",
                   proposal_payload, source_messages=validated.source_messages)
            await finish(advance=True)
            return report

        if match.kind == "new":
            if validated.outcome.is_failure:
                reject("insufficient_evidence", "failed_session: a failed session does not create a procedure",
                       proposal_payload, source_messages=validated.source_messages)
                await finish(advance=True)
                return report
            try:
                root_id = await write_new_procedure(
                    session, embedding_service, thread=info, vp=validated, ctx=ctx, max_seq=max_seq,
                )
                await check_invariants(session, root_id=root_id, tenant_id=info.tenant_id, settings=settings)
                from memoryhub_core.services.procedure_evolution import graph_fingerprint

                record_procedural_decision(
                    session, kind=PROC_CREATE, reason=None, thread=info, run_id=run_id,
                    payload={
                        **proposal_payload,
                        "created_nodes": [str(n) for n in ctx.created_node_ids],
                        # The graph as this run left it; rollback refuses if it changed since.
                        "created_state": await graph_fingerprint(session, root_id=root_id, tenant_id=info.tenant_id),
                    },
                    source_messages=validated.source_messages, procedure_id=root_id,
                    stub=validated.description,
                )
                await finish(advance=True)
            except ProceduralInvariantError as exc:
                await rollback_and_reload()
                reject("breaks_entry", str(exc)[:500], proposal_payload,
                       source_messages=validated.source_messages)
                await finish(advance=True)
                return report
            except Exception as exc:
                logger.exception("Procedural graph write failed for thread %s", info.id)
                await rollback_and_reload()
                report["error"] = f"write failed: {str(exc)[:400]}"
                await finish(advance=False, error=report["error"])
                return report
            report["created"] = 1
            report["procedure_ids"] = [str(root_id)]
            await _trigger_entity_extraction(ctx, info, embedding_service)
            report["overlapping_facts"] = await _overlapping_facts(
                session, embedding_service, validated.description, fact_memory_ids or [], tenant_id=info.tenant_id,
            )
            await release_transaction(session)
            return report

        # match.kind == "match": evolve_procedure locks the root and re-reads its ledger.
        report["matched"] = 1
        report["procedure_ids"] = [str(match.root_id)]
        if match.foreign:
            return await _propose_to_foreign_procedure(
                session, embedding_service, report=report, info=info, validated=validated,
                match=match, ctx=ctx, max_seq=max_seq, finish=finish, proposal_payload=proposal_payload,
            )
        try:
            try:
                result = await evolve_procedure(
                    session, embedding_service, thread=info, vp=validated, match=match,
                    ctx=ctx, max_seq=max_seq, lock=True, structural_verdicts=structural_verdicts,
                )
            except ProceduralInvariantError as exc:
                logger.warning("Structural edits for %s broke an invariant; retrying without them: %s",
                               match.root_id, exc)
                await rollback_and_reload()
                report["structural_rollback"] = str(exc)[:500]
                await lock_thread(session, thread)
                result = await evolve_procedure(
                    session, embedding_service, thread=info, vp=validated, match=match,
                    ctx=ctx, max_seq=max_seq, lock=True, structural_allowed=False,
                    structural_verdicts=structural_verdicts,
                )
        except Exception as exc:
            logger.exception("Procedural refinement failed for %s", match.root_id)
            await rollback_and_reload()
            report["error"] = f"refinement failed: {str(exc)[:400]}"
            await finish(advance=False, error=report["error"])
            return report

        if result.status in ("duplicate", "evicted"):
            reason = "duplicate" if result.status == "duplicate" else "evidence_evicted"
            reject(reason, f"session already accounted for procedure {match.root_id}",
                   source_messages=validated.source_messages, procedure_id=match.root_id)
            await finish(advance=True)
            return report

        report["edits_proposed"] = len(result.edits)
        report["edits_applied"] = len(result.applied)
        report["edits_rejected"] = len(result.rejected)
        record_procedural_decision(
            session, kind=PROC_MATCH, reason=None, thread=info, run_id=run_id,
            payload={
                **proposal_payload,
                "applied": [e.to_dict() for e in result.applied],
                "snapshot": result.snapshot,
            },
            source_messages=validated.source_messages, procedure_id=match.root_id,
            nearest_id=match.root_id, score=match.score, stub=validated.description,
        )
        proposed = [p for p in result.pending if p.get("reason") == "propose_mode"]
        if proposed:
            record_procedural_decision(
                session, kind=PROC_PROPOSE, reason="propose_mode", thread=info, run_id=run_id,
                payload={"edits": proposed}, source_messages=validated.source_messages,
                procedure_id=match.root_id, stub=f"{len(proposed)} proposed edits",
            )
        if result.applied:
            record_procedural_decision(
                session, kind=PROC_EDIT, reason=None, thread=info, run_id=run_id,
                payload={"edits": [e.to_dict() for e in result.applied]},
                source_messages=validated.source_messages, procedure_id=match.root_id,
                stub=f"{len(result.applied)} applied edits",
            )
        for edit in result.rejected:
            reject(edit.gate or "insufficient_evidence", f"{edit.kind} on {edit.target}",
                   {"edit": edit.to_dict()}, source_messages=validated.source_messages,
                   procedure_id=match.root_id)
        await finish(advance=True)
        await _trigger_entity_extraction(ctx, info, embedding_service)
        report["overlapping_facts"] = await _overlapping_facts(
            session, embedding_service, validated.description, fact_memory_ids or [], tenant_id=info.tenant_id,
        )
        await release_transaction(session)
        return report
    finally:
        if owns_llm:
            await llm.aclose()


async def _validate_planned_edits(
    session: AsyncSession,
    embedding_service: Any,
    *,
    settings: AppSettings,
    validator: Any | None,
    report: dict[str, Any],
    info: ThreadInfo,
    validated: ValidatedProcedure,
    match: Any,
    ctx: RunContext,
    max_seq: int,
) -> dict[str, str] | None:
    """Phase A: ask the optional validation gate about planned structural edits.

    Returns None when the gate is off (or nothing could be applied anyway),
    else verdicts keyed by ``Edit.key()`` (possibly empty, which still gates:
    a structural edit that appears only under the lock is not applied).
    """
    from memoryhub_core.services.procedure_evolution import evolve_procedure
    from memoryhub_core.services.procedure_validation import (
        build_validator,
        validate_structural_edits,
    )

    if ctx.mode != "apply" or match.kind != "match" or match.foreign:
        return None
    owns = validator is None
    validator = validator or build_validator(settings)
    if validator is None:
        return None
    try:
        plan = await evolve_procedure(
            session, embedding_service, thread=info, vp=validated, match=match,
            ctx=ctx, max_seq=max_seq, dry_run=True,
        )
        root = (await session.execute(select(MemoryNode).where(
            MemoryNode.id == match.root_id, MemoryNode.tenant_id == info.tenant_id,
        ))).scalar_one_or_none()
        goal = ((root.metadata_ or {}).get("procedure") or {}).get("goal", "") if root else ""
        description = root.content if root else ""
        await release_transaction(session)  # no transaction while the validator runs
        verdicts = await validate_structural_edits(
            validator, edits=plan.applied, procedure_id=str(match.root_id), goal=goal,
            description=description, run_id=ctx.run_id,
        )
    finally:
        if owns:
            await validator.aclose()
    report["validation"] = {
        "asked": len(verdicts),
        "accepted": sum(1 for v in verdicts.values() if v == "accept"),
    }
    return verdicts


async def _propose_to_foreign_procedure(
    session: AsyncSession,
    embedding_service: Any,
    *,
    report: dict[str, Any],
    info: ThreadInfo,
    validated: ValidatedProcedure,
    match: Any,
    ctx: RunContext,
    max_seq: int,
    finish: Callable[..., Awaitable[None]],
    proposal_payload: dict[str, Any],
) -> dict[str, Any]:
    """Another project member's procedure matched: propose, never write to it.

    No duplicate is created and the other member's nodes, edges and ledger are
    not touched. The edits this session would support are derived as in a dry
    run and recorded in the decision log only (reason ``foreign_owner``).
    """
    from memoryhub_core.services.procedure_evolution import evolve_procedure

    result = await evolve_procedure(
        session, embedding_service, thread=info, vp=validated, match=match,
        ctx=ctx, max_seq=max_seq, dry_run=True,
    )
    edits = [e.to_dict() for e in result.edits] if result.status == "updated" else []
    report["foreign"] = True
    report["edits_proposed"] = len(edits)
    record_procedural_decision(
        session, kind=PROC_PROPOSE, reason="foreign_owner", thread=info, run_id=ctx.run_id,
        payload={**proposal_payload, "edits": edits, "session_outcome": validated.outcome.to_dict()},
        source_messages=validated.source_messages, procedure_id=match.root_id,
        nearest_id=match.root_id, score=match.score,
        stub=f"matches another member's procedure; {len(edits)} proposed edits",
    )
    await finish(advance=True)
    return report


async def _dry_run_plan(
    session: AsyncSession,
    embedding_service: Any,
    *,
    report: dict[str, Any],
    info: ThreadInfo,
    validated: ValidatedProcedure,
    match: Any,
    ctx: RunContext,
    max_seq: int,
) -> dict[str, Any]:
    """The dry-run tail: describe what would happen, write nothing, take no locks."""
    from memoryhub_core.services.procedure_evolution import evolve_procedure

    report["match"] = match.to_dict()
    if match.kind == "ambiguous":
        report["rejections"].append({"reason": "ambiguous_match", "detail": "nothing would be created"})
    elif match.kind == "new":
        if validated.outcome.is_failure:
            report["rejections"].append({"reason": "insufficient_evidence", "detail": "failed_session"})
        else:
            report["plan"] = {"action": "create", "status": "candidate"}
    else:
        report["matched"] = 1
        report["procedure_ids"] = [str(match.root_id)]
        if match.foreign:
            report["foreign"] = True
        result = await evolve_procedure(
            session, embedding_service, thread=info, vp=validated, match=match,
            ctx=ctx, max_seq=max_seq, dry_run=True,
        )
        if result.status in ("duplicate", "evicted"):
            report["rejections"].append({"reason": "duplicate" if result.status == "duplicate"
                                         else "evidence_evicted", "detail": "already accounted"})
        else:
            report["edits_proposed"] = len(result.edits)
            report["edits_applied"] = len(result.applied)
            report["edits_rejected"] = len(result.rejected)
            report["plan"] = {
                "action": "refine",
                "edits": [e.to_dict() for e in result.edits],
                "would_apply": [e.to_dict() for e in result.applied],
            }
    await release_transaction(session)
    return report


async def _trigger_entity_extraction(ctx: RunContext, thread: ThreadInfo, embedding_service: Any) -> None:
    """Fire entity extraction for every node the committed run created."""
    from memoryhub_core.services.extraction_runner import trigger_extraction

    for node_id in ctx.created_node_ids:
        await trigger_extraction(
            memory_id=node_id,
            content=ctx.created_node_contents.get(node_id, ""),
            tenant_id=thread.tenant_id,
            owner_id=thread.owner_id,
            embedding_service=embedding_service,
        )
