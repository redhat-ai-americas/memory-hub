"""Matching and refinement of extracted procedural graphs (#554, D5-D7).

A detected procedure is matched against the thread owner's existing
procedural roots in the same tenant, scope and ``scope_id``. On a match the
session's evidence replaces that thread's previous contribution in a ledger on
the root, edits are derived from the whole ledger (never from the latest
session alone), gated deterministically, and either stored as pending
(``propose``) or applied (``apply``).

Nothing here calls ``update_memory``: re-versioning a procedure root
re-parents its steps under new ids and leaves the edges on the retired rows
(see the design doc inventory). Counters and attributes are updated in place
on ``metadata_``, and every change is captured as a before/after snapshot in
the decision log so ``rollback_extraction_run`` can undo it.

Design: ``planning/procedural-graph-extraction.md``.
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import re
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from memoryhub_core.config import AppSettings
from memoryhub_core.models.conversation import ConversationExtraction
from memoryhub_core.models.memory import MemoryNode, MemoryRelationship
from memoryhub_core.services.graph import (
    PROCEDURAL_RELATIONSHIP_TYPES,
    resolve_procedure_entry,
)
from memoryhub_core.services.reconciliation import SKIP_THRESHOLD, TIEBREAKER_THRESHOLD

logger = logging.getLogger(__name__)

_MATCH_SAME_OVERLAP = 0.6
_MATCH_DIFFERENT_OVERLAP = 0.2
_MAX_CANDIDATE_ROOTS = 200
_MAX_TIEBREAK_CANDIDATES = 3
_MAX_PENDING_EDITS = 50
_ATTR_PER_FIELD_MAX = 5
_SESSIONS_SHOWN = 10
_FINGERPRINT_IGNORED = frozenset({"extraction_status", "extraction_error", "extracted_entities"})

_STEP_LIST_FIELDS = ("pitfalls", "preconditions", "postconditions")
_EDGE_LIST_FIELDS = ("pitfalls",)
_SCALAR_FIELDS = ("guidance", "condition")
_FIELD_EDIT = {
    "pitfalls": "add_pitfall",
    "preconditions": "add_precondition",
    "postconditions": "add_postcondition",
    "guidance": "add_guidance",
    "condition": "add_condition",
}

Tiebreaker = Callable[[str, str], Awaitable[str]]


class ProceduralInvariantError(RuntimeError):
    """The edited graph would no longer resolve or would leave orphans."""


# ---------------------------------------------------------------------------
# Normalization helpers
# ---------------------------------------------------------------------------


def normalize_text(text: str | None) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def normalize_tool_ref(tool_ref: str | None) -> str:
    """Tool or command identity without arguments ("podman build -t x ." -> "podman build")."""
    tokens: list[str] = []
    for token in (tool_ref or "").strip().lower().split():
        if token.startswith("-") or "/" in token or "=" in token or not re.fullmatch(r"[a-z0-9_:.\-]+", token):
            break
        tokens.append(token)
        if len(tokens) == 2:
            break
    return " ".join(tokens)


def _cosine(a: Any, b: Any) -> float:
    if a is None or b is None:
        return 0.0
    from memoryhub_core.services.memory import _cosine_distance

    return 1.0 - _cosine_distance([float(x) for x in a], [float(x) for x in b])


def _sid(value: uuid.UUID | str) -> str:
    return str(value)


def _proc(node: MemoryNode) -> dict[str, Any]:
    metadata = node.metadata_ if isinstance(node.metadata_, dict) else {}
    procedure = metadata.get("procedure")
    return procedure if isinstance(procedure, dict) else {}


def is_extracted(node: MemoryNode) -> bool:
    return _proc(node).get("origin") == "extracted"


# ---------------------------------------------------------------------------
# Graph state
# ---------------------------------------------------------------------------


@dataclass
class GraphState:
    root: MemoryNode
    steps: dict[uuid.UUID, MemoryNode]
    edges: list[MemoryRelationship]

    @property
    def extracted(self) -> bool:
        return is_extracted(self.root)

    @property
    def entry_id(self) -> uuid.UUID | None:
        raw = _proc(self.root).get("entry_step_id")
        try:
            return uuid.UUID(str(raw)) if raw else None
        except ValueError:
            return None

    def edge(self, source: uuid.UUID, target: uuid.UUID, rel_type: str) -> MemoryRelationship | None:
        return next(
            (e for e in self.edges
             if e.source_id == source and e.target_id == target and e.relationship_type == rel_type),
            None,
        )

    def edge_by_id(self, edge_id: uuid.UUID) -> MemoryRelationship | None:
        return next((e for e in self.edges if e.id == edge_id), None)

    def active_edge_map(self) -> dict[tuple[str, str, str], str]:
        return {
            (_sid(e.source_id), _sid(e.target_id), e.relationship_type): _sid(e.id)
            for e in self.edges
        }

    def incoming_precedes(self, step_id: uuid.UUID) -> bool:
        return any(
            e.target_id == step_id and e.relationship_type == "precedes" and e.source_id in self.steps
            for e in self.edges
        )


async def load_graph(
    session: AsyncSession, *, root_id: uuid.UUID, tenant_id: str, lock: bool = False,
) -> GraphState:
    """Load a procedure. ``lock=True`` takes ``FOR UPDATE`` on the root and re-reads
    root, steps and edges from the database, so a writer always sees the ledger
    as the previous writer committed it (review of #554, item 2)."""
    root_stmt = select(MemoryNode).where(
        MemoryNode.id == root_id,
        MemoryNode.tenant_id == tenant_id,
        MemoryNode.deleted_at.is_(None),
    )
    if lock:
        root_stmt = root_stmt.with_for_update().execution_options(populate_existing=True)
    root = (await session.execute(root_stmt)).scalar_one()
    fresh = {"populate_existing": True} if lock else {}
    steps = list(
        (
            await session.execute(
                select(MemoryNode).where(
                    MemoryNode.parent_id == root_id,
                    MemoryNode.tenant_id == tenant_id,
                    MemoryNode.branch_type == "procedure_step",
                    MemoryNode.is_current.is_(True),
                    MemoryNode.deleted_at.is_(None),
                ).execution_options(**fresh)
            )
        ).scalars().all()
    )
    step_ids = [s.id for s in steps]
    edges: list[MemoryRelationship] = []
    if step_ids:
        edges = list(
            (
                await session.execute(
                    select(MemoryRelationship).where(
                        or_(
                            MemoryRelationship.source_id.in_(step_ids),
                            MemoryRelationship.target_id.in_(step_ids),
                        ),
                        MemoryRelationship.tenant_id == tenant_id,
                        MemoryRelationship.relationship_type.in_(PROCEDURAL_RELATIONSHIP_TYPES),
                        MemoryRelationship.valid_until.is_(None),
                    ).execution_options(**fresh)
                )
            ).scalars().all()
        )
        ids = set(step_ids)
        edges = [e for e in edges if e.source_id in ids and e.target_id in ids]
    edges.sort(key=lambda e: (e.relationship_type, str(e.id)))
    return GraphState(root=root, steps={s.id: s for s in steps}, edges=edges)


# ---------------------------------------------------------------------------
# Matching (D5)
# ---------------------------------------------------------------------------


@dataclass
class MatchResult:
    kind: str  # "new" | "match" | "ambiguous"
    root_id: uuid.UUID | None = None
    score: float | None = None
    overlap: float | None = None
    verdict: str | None = None
    alignment: dict[str, uuid.UUID] = field(default_factory=dict)
    candidates: list[dict[str, Any]] = field(default_factory=list)
    #: The matched root belongs to another member of the same project:
    #: proposal-only, nothing is written to it.
    foreign: bool = False

    def verdicts(self) -> dict[str, str]:
        return {c["id"]: c["tiebreaker"] for c in self.candidates if c.get("tiebreaker") and c.get("id")}

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "root_id": _sid(self.root_id) if self.root_id else None,
            "score": self.score,
            "overlap": self.overlap,
            "verdict": self.verdict,
            "alignment": {k: _sid(v) for k, v in self.alignment.items()},
            "foreign": self.foreign,
            "candidates": self.candidates,
        }


def shares_procedures_across_members(thread: Any) -> bool:
    """Project threads match every member's procedures in that project."""
    return thread.scope == "project" and thread.scope_id is not None


async def candidate_roots(session: AsyncSession, thread: Any) -> list[MemoryNode]:
    """Procedural roots the thread can match: same tenant, scope and ``scope_id``.

    In user scope only the owner's own procedures. In a project, also other
    members' procedures in the same project (#554 review), so two members
    following one runbook do not each build a copy. Those matches are
    proposal-only (``MatchResult.foreign``). Own procedures sort first.
    """
    scope_filter = (
        MemoryNode.scope_id.is_(None) if thread.scope_id is None else MemoryNode.scope_id == thread.scope_id
    )
    owner_filter = (
        MemoryNode.owner_id.isnot(None) if shares_procedures_across_members(thread)
        else MemoryNode.owner_id == thread.owner_id
    )
    stmt = (
        select(MemoryNode)
        .where(
            MemoryNode.tenant_id == thread.tenant_id,
            owner_filter,
            MemoryNode.scope == thread.scope,
            scope_filter,
            MemoryNode.content_type == "procedural",
            MemoryNode.parent_id.is_(None),
            MemoryNode.is_current.is_(True),
            MemoryNode.deleted_at.is_(None),
            MemoryNode.status == "active",
        )
        .order_by(MemoryNode.updated_at.desc())
        .limit(_MAX_CANDIDATE_ROOTS)
    )
    return list((await session.execute(stmt)).scalars().all())


def align_steps(
    new_steps: list[Any],
    new_embeddings: list[list[float]],
    existing: list[MemoryNode],
    threshold: float,
) -> dict[str, uuid.UUID]:
    """One-to-one greedy alignment: equal tool identity scores 1.0, else action cosine."""
    pairs: list[tuple[float, int, str, uuid.UUID]] = []
    for index, (step, emb) in enumerate(zip(new_steps, new_embeddings, strict=True)):
        new_tool = normalize_tool_ref(step.tool_ref)
        new_action = normalize_text(step.action)
        for node in existing:
            proc = _proc(node)
            old_tool = normalize_tool_ref(proc.get("tool_ref"))
            same_tool = bool(new_tool) and new_tool == old_tool
            same_action = bool(new_action) and new_action == normalize_text(proc.get("action") or node.content)
            if same_tool or same_action:
                score = 1.0
            else:
                score = _cosine(emb, node.embedding)
                if score < threshold:
                    continue
            pairs.append((score, index, step.key, node.id))
    pairs.sort(key=lambda p: (-p[0], p[1], str(p[3])))
    used_new: set[str] = set()
    used_old: set[uuid.UUID] = set()
    alignment: dict[str, uuid.UUID] = {}
    for _score, _index, key, node_id in pairs:
        if key in used_new or node_id in used_old:
            continue
        alignment[key] = node_id
        used_new.add(key)
        used_old.add(node_id)
    return alignment


async def find_matching_procedure(
    session: AsyncSession,
    *,
    thread: Any,
    vp: Any,
    embedding_service: Any,
    settings: AppSettings,
    tiebreaker: Tiebreaker | None = None,
    before_tiebreak: Callable[[], Awaitable[None]] | None = None,
    known_verdicts: dict[str, str] | None = None,
) -> MatchResult:
    """Match ``vp`` against the owner's procedures (D5).

    All database work happens first; ``before_tiebreak`` (used to end the
    read transaction) runs once before the first model call, so no
    transaction is open while the tiebreaker is in flight. ``known_verdicts``
    ({root id: "same" | "different"}) reuses tiebreaker answers from an
    earlier pass, so the re-match under the write lock needs no model call.
    """
    roots = await candidate_roots(session, thread)
    if not roots:
        return MatchResult(kind="new")
    embedding = await embedding_service.embed(vp.description)
    scored = sorted(
        ((root, _cosine(embedding, root.embedding)) for root in roots),
        key=lambda pair: (-round(pair[1], 4), pair[0].owner_id != thread.owner_id, str(pair[0].id)),
    )
    owners = {root.id: root.owner_id for root in roots}
    close = [(root, score) for root, score in scored if score >= TIEBREAKER_THRESHOLD][:_MAX_TIEBREAK_CANDIDATES]
    if not close:
        top = scored[0]
        return MatchResult(
            kind="new", score=round(top[1], 4),
            candidates=[{"id": _sid(top[0].id), "score": round(top[1], 4)}],
        )

    step_embeddings = await embedding_service.embed_batch([s.action for s in vp.steps])
    prepared: list[dict[str, Any]] = []
    for root, score in close:
        graph = await load_graph(session, root_id=root.id, tenant_id=thread.tenant_id)
        alignment = align_steps(
            vp.steps, step_embeddings, list(graph.steps.values()),
            settings.procedural_step_match_threshold,
        )
        denominator = max(len(vp.steps), len(graph.steps), 1)
        prepared.append({
            "root_id": root.id,
            "score": score,
            "overlap": round(len(alignment) / denominator, 4),
            "alignment": alignment,
            "existing_text": f"{root.content}\nSteps: " + "; ".join(
                (_proc(s).get("action") or s.content) for s in graph.steps.values()
            ),
        })

    new_text = f"{vp.description}\nSteps: " + "; ".join(s.action for s in vp.steps)
    ambiguous = False
    released = False
    candidates: list[dict[str, Any]] = []
    for item in prepared:
        info = {"id": _sid(item["root_id"]), "score": round(item["score"], 4), "overlap": item["overlap"]}
        candidates.append(info)
        verdict: str | None = None
        if item["score"] >= SKIP_THRESHOLD or item["overlap"] >= _MATCH_SAME_OVERLAP:
            verdict = "same"
        elif item["overlap"] <= _MATCH_DIFFERENT_OVERLAP:
            verdict = "different"
        elif known_verdicts and known_verdicts.get(info["id"]) in ("same", "different"):
            verdict = known_verdicts[info["id"]]
            info["tiebreaker"] = verdict
        elif tiebreaker is None:
            ambiguous = True
            continue
        else:
            if before_tiebreak is not None and not released:
                await before_tiebreak()
                released = True
            try:
                verdict = await tiebreaker(new_text, item["existing_text"])
            except Exception as exc:
                logger.warning("Procedural match tiebreaker failed for %s: %s", item["root_id"], exc)
                ambiguous = True
                continue
            info["tiebreaker"] = verdict
        if verdict == "same":
            return MatchResult(
                kind="match", root_id=item["root_id"], score=round(item["score"], 4),
                overlap=item["overlap"], verdict=verdict, alignment=item["alignment"],
                candidates=candidates, foreign=owners[item["root_id"]] != thread.owner_id,
            )
    if ambiguous:
        return MatchResult(kind="ambiguous", score=round(close[0][1], 4), candidates=candidates)
    return MatchResult(kind="new", score=round(close[0][1], 4), candidates=candidates)


# ---------------------------------------------------------------------------
# Evidence ledger (D6a)
# ---------------------------------------------------------------------------


def _verdict(outcome: Any, *, status: str, failed_here: bool) -> str:
    if outcome.strong_success and status in ("succeeded", "unknown"):
        return "success"
    if outcome.attributable and failed_here:
        return "attributable_failure"
    return "neutral"


def build_session_entry(
    *,
    vp: Any,
    alignment: dict[str, uuid.UUID],
    active_edges: dict[tuple[str, str, str], str],
    run_id: str,
    max_seq: int,
    now: datetime,
) -> dict[str, Any]:
    """One session's contribution, keyed to existing step and edge ids.

    A session contributes at most one verdict per step, edge and path.
    Re-processing replaces this entry; counters are derived from it.
    """
    outcome = vp.outcome
    aligned_steps = [s for s in vp.steps if s.key in alignment]
    path = [_sid(alignment[s.key]) for s in aligned_steps]
    items: dict[str, str] = {}
    observations: list[dict[str, Any]] = []
    failure_item: str | None = None
    failure_conditions: list[str] = []

    for step in aligned_steps:
        sid = _sid(alignment[step.key])
        failed_here = outcome.failure_step == step.key
        items[f"step:{sid}"] = _verdict(outcome, status=step.status, failed_here=failed_here)
        if failed_here:
            failure_item = f"step:{sid}"
            failure_conditions = [p.text for p in step.preconditions if p.evidence == "observed"]
        for name in _STEP_LIST_FIELDS:
            for item in getattr(step, name):
                observations.append({"item": f"step:{sid}", "field": name, **item.to_dict()})
        if step.guidance:
            observations.append({"item": f"step:{sid}", "field": "guidance", **step.guidance.to_dict()})

    novel_transitions: dict[tuple[str, str], dict[str, Any]] = {}
    for a, b in zip(path, path[1:], strict=False):
        if a != b and (a, b, "precedes") not in active_edges:
            novel_transitions[(a, b)] = {"source": a, "target": b, "condition": None}
    for edge in vp.edges:
        if edge.source not in alignment or edge.target not in alignment:
            continue
        src, tgt = _sid(alignment[edge.source]), _sid(alignment[edge.target])
        edge_id = active_edges.get((src, tgt, edge.type))
        if edge_id is None:
            if edge.type == "precedes" and (src, tgt) in novel_transitions and edge.condition:
                novel_transitions[(src, tgt)]["condition"] = edge.condition.to_dict()
            continue
        failed_here = outcome.failure_edge == (edge.source, edge.target)
        status = "unknown"
        items[f"edge:{edge_id}"] = _verdict(outcome, status=status, failed_here=failed_here)
        if failed_here:
            failure_item = f"edge:{edge_id}"
            failure_conditions = (
                [edge.condition.text] if edge.condition and edge.condition.evidence == "observed" else []
            )
        for name in ("condition", "guidance"):
            item = getattr(edge, name)
            if item is not None:
                observations.append({"item": f"edge:{edge_id}", "field": name, **item.to_dict()})
        for item in edge.pitfalls:
            observations.append({"item": f"edge:{edge_id}", "field": "pitfalls", **item.to_dict()})

    novel_steps: list[dict[str, Any]] = []
    for step in vp.steps:
        if step.key in alignment:
            continue
        before = [s for s in aligned_steps if s.first_seq < step.first_seq]
        after = [s for s in aligned_steps if s.first_seq > step.first_seq]
        novel_steps.append({
            "key": step.key,
            "action": step.action,
            "tool_ref": step.tool_ref,
            "identity": normalize_tool_ref(step.tool_ref) or normalize_text(step.action),
            "pred": _sid(alignment[before[-1].key]) if before else None,
            "succ": _sid(alignment[after[0].key]) if after else None,
            "status": step.status,
            "attributes": {
                name: [i.to_dict() for i in getattr(step, name) if i.evidence == "observed"]
                for name in _STEP_LIST_FIELDS
            },
            "guidance": step.guidance.to_dict() if step.guidance and step.guidance.evidence == "observed" else None,
            "source_messages": step.source_messages,
        })

    return {
        "run_id": run_id,
        "max_seq": max_seq,
        "recorded_at": now.isoformat(),
        "outcome": outcome.result,
        "outcome_source": outcome.source,
        "outcome_confidence": outcome.confidence,
        "strong": outcome.strong,
        "failure_class": outcome.failure_class if outcome.is_failure else None,
        "failure": {
            "item": failure_item,
            "attributable": bool(outcome.attributable and failure_item),
            "conditions": failure_conditions,
        } if outcome.is_failure else None,
        "items": items,
        "path": path,
        "novel_steps": novel_steps,
        "novel_transitions": list(novel_transitions.values()),
        "observations": observations,
    }


def ledger_of(root: MemoryNode) -> dict[str, Any]:
    evidence = _proc(root).get("evidence")
    if not isinstance(evidence, dict):
        evidence = {}
    sessions = evidence.get("sessions") if isinstance(evidence.get("sessions"), dict) else {}
    evicted = evidence.get("evicted") if isinstance(evidence.get("evicted"), dict) else {}
    return {"sessions": copy.deepcopy(sessions), "evicted": copy.deepcopy(evicted)}


def evict_old_sessions(ledger: dict[str, Any], limit: int) -> None:
    sessions: dict[str, Any] = ledger["sessions"]
    if len(sessions) <= limit:
        return
    ordered = sorted(sessions.items(), key=lambda kv: (kv[1].get("recorded_at", ""), kv[0]))
    evicted = ledger["evicted"]
    evicted_threads: list[str] = evicted.setdefault("threads", [])
    evicted_items: dict[str, dict[str, int]] = evicted.setdefault("items", {})
    for thread_id, entry in ordered[: len(sessions) - limit]:
        for item, verdict in (entry.get("items") or {}).items():
            bucket = evicted_items.setdefault(item, {})
            bucket[verdict] = bucket.get(verdict, 0) + 1
        evicted_threads.append(thread_id)
        del sessions[thread_id]


def derive_counts(ledger: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Per-item counters, derived (never incremented) from the ledger."""
    counts: dict[str, dict[str, Any]] = {}

    def bucket(item: str) -> dict[str, Any]:
        return counts.setdefault(
            item,
            {"success_count": 0, "failure_count": 0, "weak_count": 0, "sessions": [], "last_seen": None},
        )

    names = {"success": "success_count", "attributable_failure": "failure_count", "neutral": "weak_count"}
    for item, verdicts in (ledger["evicted"].get("items") or {}).items():
        for verdict, n in verdicts.items():
            bucket(item)[names.get(verdict, "weak_count")] += int(n)
    ordered = sorted(ledger["sessions"].items(), key=lambda kv: (kv[1].get("recorded_at", ""), kv[0]))
    for thread_id, entry in ordered:
        for item, verdict in (entry.get("items") or {}).items():
            b = bucket(item)
            b[names.get(verdict, "weak_count")] += 1
            b["sessions"].append(thread_id)
            b["last_seen"] = entry.get("recorded_at")
    for b in counts.values():
        b["session_total"] = b["success_count"] + b["failure_count"] + b["weak_count"]
        b["sessions"] = b["sessions"][-_SESSIONS_SHOWN:]
    return counts


# ---------------------------------------------------------------------------
# Snapshots (rollback unit)
# ---------------------------------------------------------------------------


def _jsonable(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str))


def _comparable(value: Any) -> Any:
    """Metadata without the keys async entity extraction rewrites after commit."""
    data = _jsonable(value)
    if isinstance(data, dict):
        return {k: v for k, v in data.items() if k not in _FINGERPRINT_IGNORED}
    return data


@dataclass
class SnapshotLog:
    node_meta: dict[str, Any] = field(default_factory=dict)
    edge_meta: dict[str, Any] = field(default_factory=dict)
    node_deleted: list[str] = field(default_factory=list)
    edge_invalidated: list[str] = field(default_factory=list)
    created_nodes: list[str] = field(default_factory=list)
    created_edges: list[str] = field(default_factory=list)
    created_extractions: list[str] = field(default_factory=list)

    def before_node(self, node: MemoryNode) -> None:
        self.node_meta.setdefault(_sid(node.id), _jsonable(node.metadata_))

    def before_edge(self, edge: MemoryRelationship) -> None:
        self.edge_meta.setdefault(_sid(edge.id), _jsonable(edge.metadata_))

    async def finalize(self, session: AsyncSession) -> dict[str, Any]:
        nodes = []
        for node_id, before in self.node_meta.items():
            node = await session.get(MemoryNode, uuid.UUID(node_id))
            after = _jsonable(node.metadata_) if node is not None else None
            if after != before:
                nodes.append({"id": node_id, "before": before, "after": after})
        edges = []
        for edge_id, before in self.edge_meta.items():
            edge = await session.get(MemoryRelationship, uuid.UUID(edge_id))
            after = _jsonable(edge.metadata_) if edge is not None else None
            if after != before:
                edges.append({"id": edge_id, "before": before, "after": after})
        return {
            "node_meta": nodes,
            "edge_meta": edges,
            "node_deleted": self.node_deleted,
            "edge_invalidated": self.edge_invalidated,
            "created_nodes": self.created_nodes,
            "created_edges": self.created_edges,
            "created_extractions": self.created_extractions,
        }

    def empty(self) -> bool:
        return not (
            self.node_meta or self.edge_meta or self.node_deleted or self.edge_invalidated
            or self.created_nodes or self.created_edges or self.created_extractions
        )


def set_node_metadata(node: MemoryNode, metadata: dict[str, Any], snaps: SnapshotLog | None) -> bool:
    if _jsonable(node.metadata_) == _jsonable(metadata):
        return False
    if snaps is not None:
        snaps.before_node(node)
    node.metadata_ = metadata
    return True


def set_edge_metadata(edge: MemoryRelationship, metadata: dict[str, Any], snaps: SnapshotLog | None) -> bool:
    if _jsonable(edge.metadata_) == _jsonable(metadata):
        return False
    if snaps is not None:
        snaps.before_edge(edge)
    edge.metadata_ = metadata
    return True


async def refresh_derived_evidence(
    session: AsyncSession,
    *,
    root_id: uuid.UUID,
    tenant_id: str,
    settings: AppSettings,
    snaps: SnapshotLog | None = None,
    promote: bool = True,
) -> GraphState:
    """Write counters derived from the root ledger onto extracted steps and edges.

    Writes only when a value changes, so re-processing a session leaves every
    row untouched. Hand-authored steps and edges are never written.
    """
    graph = await load_graph(session, root_id=root_id, tenant_id=tenant_id)
    ledger = ledger_of(graph.root)
    counts = derive_counts(ledger)
    empty = {"success_count": 0, "failure_count": 0, "weak_count": 0, "sessions": [],
             "last_seen": None, "session_total": 0}
    if graph.extracted:
        for step in graph.steps.values():
            if not is_extracted(step):
                continue
            metadata = copy.deepcopy(step.metadata_) or {}
            procedure = metadata.setdefault("procedure", {})
            procedure["evidence"] = counts.get(f"step:{step.id}", empty)
            set_node_metadata(step, metadata, snaps)
        for edge in graph.edges:
            metadata = copy.deepcopy(edge.metadata_) or {}
            if metadata.get("origin") != "extracted":
                continue
            metadata["evidence"] = counts.get(f"edge:{edge.id}", empty)
            set_edge_metadata(edge, metadata, snaps)
        strong_successes = sum(1 for e in ledger["sessions"].values() if _strong_success(e))
        root_meta = copy.deepcopy(graph.root.metadata_) or {}
        procedure = root_meta.setdefault("procedure", {})
        # candidate -> established is a structural decision (it makes the procedure
        # eligible for guidance), so it happens only in apply mode. It is sticky:
        # failures later deprecate steps and edges, they do not demote the root.
        if promote and procedure.get("status") == "candidate" \
                and strong_successes >= settings.procedural_min_supporting_sessions:
            procedure["status"] = "established"
            set_node_metadata(graph.root, root_meta, snaps)
    return graph


# ---------------------------------------------------------------------------
# Edit derivation and gates (D6, D7)
# ---------------------------------------------------------------------------


@dataclass
class Edit:
    kind: str
    target: str
    payload: dict[str, Any]
    support: list[str]
    structural: bool
    gate: str | None = None  # None = passes every gate; else a rejection reason

    def key(self) -> str:
        blob = json.dumps([self.kind, self.target, self.payload], sort_keys=True, default=str)
        return hashlib.sha1(blob.encode()).hexdigest()[:16]

    def to_dict(self) -> dict[str, Any]:
        return {
            "edit": self.kind, "target": self.target, "payload": self.payload,
            "support": self.support, "structural": self.structural, "gate": self.gate or "pass",
        }


def _current_values(graph: GraphState, item: str, field_name: str) -> list[str] | str | None:
    kind, raw_id = item.split(":", 1)
    if kind == "step":
        node = graph.steps.get(uuid.UUID(raw_id))
        if node is None:
            return None
        return _proc(node).get(field_name)
    edge = graph.edge_by_id(uuid.UUID(raw_id))
    if edge is None:
        return None
    return (edge.metadata_ or {}).get(field_name)


def _item_exists(graph: GraphState, item: str) -> bool:
    kind, raw_id = item.split(":", 1)
    if kind == "step":
        return uuid.UUID(raw_id) in graph.steps
    return graph.edge_by_id(uuid.UUID(raw_id)) is not None


def _strong_success(entry: dict[str, Any]) -> bool:
    return bool(entry.get("strong")) and entry.get("outcome") == "success"


def _strong_failure(entry: dict[str, Any]) -> bool:
    return bool(entry.get("strong")) and entry.get("outcome") in ("failure", "partial")


def derive_edits(graph: GraphState, ledger: dict[str, Any], settings: AppSettings) -> list[Edit]:
    """Derive the current edit set from the whole ledger.

    Edits already reflected in the graph are not produced again, so deriving
    and applying is idempotent.
    """
    sessions: dict[str, dict[str, Any]] = ledger["sessions"]
    ordered = sorted(sessions.items(), key=lambda kv: (kv[1].get("recorded_at", ""), kv[0]))
    min_support = settings.procedural_min_supporting_sessions
    edits: list[Edit] = []
    entry_id = graph.entry_id

    # 1. Non-structural: observed attributes on existing steps and edges.
    grouped: dict[tuple[str, str, str], dict[str, Any]] = {}
    for thread_id, entry in ordered:
        for obs in entry.get("observations") or []:
            if obs.get("evidence") != "observed" or not _item_exists(graph, obs["item"]):
                continue
            key = (obs["item"], obs["field"], normalize_text(obs["text"]))
            group = grouped.setdefault(key, {"text": obs["text"], "support": [], "sources": {}})
            if thread_id not in group["support"]:
                group["support"].append(thread_id)
            group["sources"].setdefault(thread_id, sorted(set(obs.get("source_messages") or [])))
    planned_counts: dict[tuple[str, str], int] = {}
    for (item, field_name, norm), group in grouped.items():
        current = _current_values(graph, item, field_name)
        if field_name in _SCALAR_FIELDS:
            if current:
                continue  # an existing value wins; the observation stays in the ledger
            if planned_counts.get((item, field_name)):
                continue
            planned_counts[(item, field_name)] = 1
            edits.append(Edit(_FIELD_EDIT[field_name], item,
                              {"field": field_name, "text": group["text"], "sources": group["sources"]},
                              group["support"], structural=False))
            continue
        values = current if isinstance(current, list) else []
        if norm in {normalize_text(v) for v in values}:
            continue
        planned = planned_counts.get((item, field_name), 0)
        gate = "cap_reached" if len(values) + planned >= _ATTR_PER_FIELD_MAX else None
        if gate is None:
            planned_counts[(item, field_name)] = planned + 1
        edits.append(Edit(_FIELD_EDIT[field_name], item,
                          {"field": field_name, "text": group["text"], "sources": group["sources"]},
                          group["support"], structural=False, gate=gate))

    # 2. Novel steps: alternatives or new main-path steps, never from failures alone.
    novel: dict[tuple[str, str | None, str | None], dict[str, Any]] = {}
    for thread_id, entry in ordered:
        for step in entry.get("novel_steps") or []:
            group = novel.setdefault(
                (step["identity"], step.get("pred"), step.get("succ")),
                {"step": step, "success": [], "weak": [], "failure": []},
            )
            if _strong_success(entry) and step.get("status") in ("succeeded", "unknown"):
                bucket = "success"
            elif _strong_failure(entry):
                bucket = "failure"
            else:
                bucket = "weak"
            if thread_id not in group[bucket]:
                group[bucket].append(thread_id)
    for (_identity, pred, succ), group in novel.items():
        step = group["step"]
        pred_id = uuid.UUID(pred) if pred else None
        succ_id = uuid.UUID(succ) if succ else None
        if not group["success"] and not group["weak"]:
            if pred_id in graph.steps:
                text = f"A failed session diverged here to: {step['action']}"
                current = _proc(graph.steps[pred_id]).get("pitfalls") or []
                if normalize_text(text) not in {normalize_text(v) for v in current}:
                    gate = "cap_reached" if len(current) >= _ATTR_PER_FIELD_MAX else None
                    edits.append(Edit("add_pitfall", f"step:{pred}", {"field": "pitfalls", "text": text},
                                      group["failure"], structural=False, gate=gate))
            continue
        if _already_has_step(graph, step):
            continue
        alternative_of = None
        if pred_id in graph.steps and succ_id in graph.steps:
            for candidate in graph.steps.values():
                if graph.edge(pred_id, candidate.id, "precedes") and graph.edge(candidate.id, succ_id, "precedes"):
                    alternative_of = _sid(candidate.id)
                    break
        if len(group["success"]) >= min_support:
            gate = None
        elif group["success"]:
            gate = "insufficient_evidence"
        else:
            gate = "inferred_only"
        if gate is None:
            unanchored = pred_id not in graph.steps and succ_id not in graph.steps
            if unanchored or (pred_id is None and succ_id == entry_id):
                gate = "breaks_entry"
            elif len(graph.steps) + 1 > settings.procedural_max_steps:
                gate = "cap_reached"
        edits.append(Edit(
            "add_step", f"root:{graph.root.id}",
            {"action": step["action"], "tool_ref": step.get("tool_ref"), "pred": pred, "succ": succ,
             "alternative_of": alternative_of, "attributes": step.get("attributes") or {},
             "guidance": step.get("guidance"), "source_messages": step.get("source_messages") or []},
            group["success"] or group["weak"], structural=True, gate=gate,
        ))

    # 3. Novel transitions between existing steps.
    transitions: dict[tuple[str, str], dict[str, Any]] = {}
    for thread_id, entry in ordered:
        for tr in entry.get("novel_transitions") or []:
            group = transitions.setdefault((tr["source"], tr["target"]), {"tr": tr, "success": [], "other": []})
            bucket = "success" if _strong_success(entry) else "other"
            if thread_id not in group[bucket]:
                group[bucket].append(thread_id)
    for (src, tgt), group in transitions.items():
        src_id, tgt_id = uuid.UUID(src), uuid.UUID(tgt)
        if src_id not in graph.steps or tgt_id not in graph.steps or graph.edge(src_id, tgt_id, "precedes"):
            continue
        if not group["success"]:
            gate = "inferred_only"
        elif len(group["success"]) < min_support:
            gate = "insufficient_evidence"
        elif tgt_id == entry_id:
            gate = "breaks_entry"
        else:
            gate = None
        edits.append(Edit("add_edge", f"step:{src}",
                          {"source": src, "target": tgt, "type": "precedes",
                           "condition": (group["tr"].get("condition") or {}).get("text")
                           if (group["tr"].get("condition") or {}).get("evidence") == "observed" else None},
                          group["success"] or group["other"], structural=True, gate=gate))

    # 4. Deprecation, conflicts and separating conditions.
    counts = derive_counts(ledger)
    for item, count in sorted(counts.items()):
        if count["failure_count"] == 0 or not _item_exists(graph, item):
            continue
        failing = [
            tid for tid, entry in ordered
            if (entry.get("items") or {}).get(item) == "attributable_failure"
        ]
        kind = "deprecate_step" if item.startswith("step:") else "deprecate_edge"
        if count["success_count"] == 0:
            enough = count["failure_count"] >= settings.procedural_deprecation_min_failures
            gate = None if enough else "insufficient_evidence"
            if gate is None and item == f"step:{entry_id}":
                gate = "breaks_entry"
            edits.append(Edit(kind, item, {}, failing, structural=True, gate=gate))
            continue
        conditions: dict[str, list[str]] = {}
        for tid in failing:
            for text in (sessions[tid].get("failure") or {}).get("conditions") or []:
                conditions.setdefault(text, []).append(tid)
        field_name = "preconditions" if item.startswith("step:") else "condition"
        separated = False
        for text, support in conditions.items():
            current = _current_values(graph, item, field_name)
            values = current if isinstance(current, list) else ([current] if current else [])
            if normalize_text(text) in {normalize_text(v) for v in values}:
                separated = True
                continue
            if field_name == "condition" and values:
                continue
            separated = True
            edits.append(Edit(_FIELD_EDIT[field_name], item, {"field": field_name, "text": text},
                              support, structural=False))
        if not separated:
            successes = [tid for tid, e in ordered if (e.get("items") or {}).get(item) == "success"]
            note = {"kind": "conflicts_with", "success_threads": successes, "failure_threads": failing}
            if not _has_contradiction(graph, item, note):
                edits.append(Edit("add_contradiction", item, note, failing, structural=False))
            edits.append(Edit(kind, item, {}, failing, structural=True, gate="conflicting_evidence"))

    # 5. Entry update.
    starts: dict[str, list[str]] = {}
    for thread_id, entry in ordered:
        path = entry.get("path") or []
        if _strong_success(entry) and path:
            starts.setdefault(path[0], []).append(thread_id)
    current_entry = _sid(entry_id) if entry_id else None
    current_count = len(starts.get(current_entry or "", []))
    for start, support in sorted(starts.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        if start == current_entry or len(support) <= current_count:
            continue
        start_id = uuid.UUID(start)
        if start_id not in graph.steps:
            continue
        gate = None if len(support) >= min_support else "insufficient_evidence"
        if gate is None and graph.incoming_precedes(start_id):
            gate = "breaks_entry"
        edits.append(Edit("update_entry", f"root:{graph.root.id}", {"entry_step_id": start},
                          support, structural=True, gate=gate))
        break

    return edits


def _already_has_step(graph: GraphState, step: dict[str, Any]) -> bool:
    identity = step.get("identity")
    for node in graph.steps.values():
        proc = _proc(node)
        if identity and identity in (
            normalize_tool_ref(proc.get("tool_ref")), normalize_text(proc.get("action") or node.content),
        ):
            return True
    return False


def _has_contradiction(graph: GraphState, item: str, note: dict[str, Any]) -> bool:
    kind, raw_id = item.split(":", 1)
    if kind == "step":
        node = graph.steps.get(uuid.UUID(raw_id))
        existing = _proc(node).get("contradictions") if node is not None else None
    else:
        edge = graph.edge_by_id(uuid.UUID(raw_id))
        existing = (edge.metadata_ or {}).get("contradictions") if edge is not None else None
    for prior in existing or []:
        if sorted(prior.get("failure_threads", [])) == sorted(note["failure_threads"]) and \
                sorted(prior.get("success_threads", [])) == sorted(note["success_threads"]):
            return True
    return False


# ---------------------------------------------------------------------------
# Applying edits
# ---------------------------------------------------------------------------


async def apply_edit(
    session: AsyncSession,
    embedding_service: Any,
    *,
    graph: GraphState,
    edit: Edit,
    thread: Any,
    ctx: Any,
    snaps: SnapshotLog,
) -> None:
    from memoryhub_core.services.graph import invalidate_relationship
    from memoryhub_core.services.procedure_extraction import (
        create_procedural_edge,
        create_step_node,
    )

    now = ctx.now
    if edit.kind in ("add_pitfall", "add_precondition", "add_postcondition", "add_guidance", "add_condition",
                     "add_contradiction"):
        kind, raw_id = edit.target.split(":", 1)
        if kind == "step":
            node = graph.steps[uuid.UUID(raw_id)]
            metadata = copy.deepcopy(node.metadata_) or {}
            container = metadata.setdefault("procedure", {})
        else:
            edge = graph.edge_by_id(uuid.UUID(raw_id))
            assert edge is not None
            metadata = copy.deepcopy(edge.metadata_) or {}
            container = metadata
        if edit.kind == "add_contradiction":
            container.setdefault("contradictions", []).append({**edit.payload, "run_id": ctx.run_id})
        else:
            field_name = edit.payload["field"]
            text = edit.payload["text"]
            if field_name in _SCALAR_FIELDS:
                container[field_name] = text
            else:
                container[field_name] = [*(container.get(field_name) or []), text]
            # Provenance per supporting thread: the messages each one cited.
            sources = edit.payload.get("sources") or {}
            attr = container.setdefault("attribute_evidence", {})
            attr.setdefault(field_name, []).append({
                "text": text,
                "evidence": "observed",
                "source_messages": sorted({s for seqs in sources.values() for s in seqs}),
                "sources": sources,
                "threads": edit.support,
                "run_id": ctx.run_id,
            })
        if kind == "step":
            set_node_metadata(node, metadata, snaps)
        else:
            set_edge_metadata(edge, metadata, snaps)
        return

    if edit.kind == "add_step":
        p = edit.payload
        attributes = p.get("attributes") or {}
        metadata = {
            "extraction_source": ctx.extraction_source(thread, p.get("source_messages") or []),
            "procedure": {
                "action": p["action"],
                "tool_ref": p.get("tool_ref"),
                "preconditions": [a["text"] for a in attributes.get("preconditions", [])][:_ATTR_PER_FIELD_MAX],
                "postconditions": [a["text"] for a in attributes.get("postconditions", [])][:_ATTR_PER_FIELD_MAX],
                "pitfalls": [a["text"] for a in attributes.get("pitfalls", [])][:_ATTR_PER_FIELD_MAX],
                "guidance": (p.get("guidance") or {}).get("text"),
                "origin": "extracted",
                "added_by_run": ctx.run_id,
                "support": edit.support,
            },
        }
        new_id = await create_step_node(
            session, embedding_service,
            root_id=graph.root.id, content=p["action"], metadata=metadata,
            thread=thread, ctx=ctx, seqs=p.get("source_messages") or [],
        )
        snaps.created_nodes.append(_sid(new_id))
        edge_meta = {"origin": "extracted", "condition": None, "guidance": None, "pitfalls": [],
                     "added_by_run": ctx.run_id, "support": edit.support}
        if p.get("pred") and uuid.UUID(p["pred"]) in graph.steps:
            eid = await create_procedural_edge(session, source_id=uuid.UUID(p["pred"]), target_id=new_id,
                                               rel_type="precedes", metadata=dict(edge_meta))
            snaps.created_edges.append(_sid(eid))
        if p.get("succ") and uuid.UUID(p["succ"]) in graph.steps:
            eid = await create_procedural_edge(session, source_id=new_id, target_id=uuid.UUID(p["succ"]),
                                               rel_type="precedes", metadata=dict(edge_meta))
            snaps.created_edges.append(_sid(eid))
        if p.get("alternative_of") and uuid.UUID(p["alternative_of"]) in graph.steps:
            eid = await create_procedural_edge(session, source_id=new_id,
                                               target_id=uuid.UUID(p["alternative_of"]),
                                               rel_type="alternative_to", metadata=dict(edge_meta))
            snaps.created_edges.append(_sid(eid))
        return

    if edit.kind == "add_edge":
        p = edit.payload
        eid = await create_procedural_edge(
            session, source_id=uuid.UUID(p["source"]), target_id=uuid.UUID(p["target"]),
            rel_type=p["type"],
            metadata={"origin": "extracted", "condition": p.get("condition"), "guidance": None,
                      "pitfalls": [], "added_by_run": ctx.run_id, "support": edit.support},
        )
        snaps.created_edges.append(_sid(eid))
        return

    if edit.kind == "deprecate_edge":
        edge_id = uuid.UUID(edit.target.split(":", 1)[1])
        await invalidate_relationship(edge_id, session, valid_until=now)
        snaps.edge_invalidated.append(_sid(edge_id))
        return

    if edit.kind == "deprecate_step":
        step_id = uuid.UUID(edit.target.split(":", 1)[1])
        node = graph.steps[step_id]
        preds = [e.source_id for e in graph.edges
                 if e.target_id == step_id and e.relationship_type == "precedes" and e.source_id != step_id]
        succs = [e.target_id for e in graph.edges
                 if e.source_id == step_id and e.relationship_type == "precedes" and e.target_id != step_id]
        node.deleted_at = now
        snaps.node_deleted.append(_sid(step_id))
        for edge in graph.edges:
            if edge.source_id == step_id or edge.target_id == step_id:
                await invalidate_relationship(edge.id, session, valid_until=now)
                snaps.edge_invalidated.append(_sid(edge.id))
        # Stitch the path back together so removing a middle step does not orphan
        # its neighbours (pred -> step -> succ becomes pred -> succ).
        for pred in preds:
            for succ in succs:
                if pred == succ or graph.edge(pred, succ, "precedes") is not None:
                    continue
                eid = await create_procedural_edge(
                    session, source_id=pred, target_id=succ, rel_type="precedes",
                    metadata={"origin": "extracted", "condition": None, "guidance": None, "pitfalls": [],
                              "added_by_run": ctx.run_id, "rewired_around": _sid(step_id),
                              "support": edit.support},
                )
                snaps.created_edges.append(_sid(eid))
        return

    if edit.kind == "update_entry":
        metadata = copy.deepcopy(graph.root.metadata_) or {}
        metadata.setdefault("procedure", {})["entry_step_id"] = edit.payload["entry_step_id"]
        set_node_metadata(graph.root, metadata, snaps)
        return

    raise ValueError(f"unknown procedural edit {edit.kind!r}")


async def check_invariants(
    session: AsyncSession, *, root_id: uuid.UUID, tenant_id: str, settings: AppSettings,
) -> None:
    """D7 graph invariants plus the #553 retrieval path, on flushed state."""
    from memoryhub_core.services.procedural_guidance import build_localized_subgraph

    await session.flush()
    graph = await load_graph(session, root_id=root_id, tenant_id=tenant_id)
    entry = graph.entry_id
    if entry is None or entry not in graph.steps:
        raise ProceduralInvariantError("entry_step_id does not name a current step of this procedure")
    if graph.incoming_precedes(entry):
        raise ProceduralInvariantError("entry step has an incoming precedes edge")
    if len(graph.steps) > settings.procedural_max_steps:
        raise ProceduralInvariantError("procedure exceeds procedural_max_steps")
    if len(graph.steps) > 1:
        touched = {e.source_id for e in graph.edges} | {e.target_id for e in graph.edges}
        orphans = sorted(str(s) for s in graph.steps if s not in touched)
        if orphans:
            raise ProceduralInvariantError(f"orphan steps: {orphans}")
    try:
        resolved = await resolve_procedure_entry(root_id, session, tenant_id=tenant_id)
        if resolved != entry:
            raise ProceduralInvariantError("resolve_procedure_entry disagrees with entry_step_id")
        await build_localized_subgraph(entry, session, tenant_id=tenant_id)
    except ProceduralInvariantError:
        raise
    except Exception as exc:
        raise ProceduralInvariantError(f"retrieval check failed: {exc}") from exc


# ---------------------------------------------------------------------------
# Evolution of a matched procedure
# ---------------------------------------------------------------------------


@dataclass
class EvolutionResult:
    status: str  # "updated" | "duplicate" | "evicted"
    edits: list[Edit] = field(default_factory=list)
    applied: list[Edit] = field(default_factory=list)
    pending: list[dict[str, Any]] = field(default_factory=list)
    rejected: list[Edit] = field(default_factory=list)
    snapshot: dict[str, Any] | None = None


async def evolve_procedure(
    session: AsyncSession,
    embedding_service: Any,
    *,
    thread: Any,
    vp: Any,
    match: MatchResult,
    ctx: Any,
    max_seq: int,
    dry_run: bool = False,
    structural_allowed: bool = True,
    lock: bool = False,
    structural_verdicts: dict[str, str] | None = None,
) -> EvolutionResult:
    """Account this session's evidence and derive, gate and (maybe) apply edits.

    No commit. In ``dry_run`` nothing is written to the session.

    ``structural_verdicts`` (from the optional validation gate, see
    ``procedure_validation``): when given, a structural edit is applied only
    if its key was accepted; otherwise it stays pending with the gate's reason.
    """
    from memoryhub_core.services.procedure_validation import gate_reason

    assert match.root_id is not None
    settings: AppSettings = ctx.settings
    # With lock=True the root is held FOR UPDATE and re-read, so the ledger
    # below is the one the previous writer committed.
    graph = await load_graph(session, root_id=match.root_id, tenant_id=thread.tenant_id, lock=lock and not dry_run)
    ledger = ledger_of(graph.root)
    thread_key = _sid(thread.id)

    existing = ledger["sessions"].get(thread_key)
    if existing is not None and int(existing.get("max_seq", -1)) >= max_seq:
        return EvolutionResult(status="duplicate")
    if thread_key in (ledger["evicted"].get("threads") or []):
        return EvolutionResult(status="evicted")

    # A concurrent run may have retired an aligned step since phase A.
    alignment = {key: step_id for key, step_id in match.alignment.items() if step_id in graph.steps}
    entry = build_session_entry(
        vp=vp, alignment=alignment, active_edges=graph.active_edge_map(),
        run_id=ctx.run_id, max_seq=max_seq, now=ctx.now,
    )
    ledger["sessions"][thread_key] = entry  # replaces this thread's earlier contribution
    evict_old_sessions(ledger, settings.procedural_evidence_session_limit)

    edits = derive_edits(graph, ledger, settings)
    result = EvolutionResult(status="updated", edits=edits)

    applied: list[Edit] = []
    pending: list[dict[str, Any]] = []
    for edit in edits:
        record = {**edit.to_dict(), "run_id": ctx.run_id}
        if not graph.extracted:
            pending.append({**record, "reason": "hand_authored"})
            result.rejected.append(Edit(**{**edit.__dict__, "gate": "hand_authored"}))
            continue
        if edit.gate is not None:
            pending.append({**record, "reason": edit.gate})
            result.rejected.append(edit)
            continue
        if ctx.mode != "apply":
            pending.append({**record, "reason": "propose_mode"})
            continue
        validation = gate_reason(structural_verdicts, edit)
        if validation is not None:
            pending.append({**record, "reason": validation})
            result.rejected.append(Edit(**{**edit.__dict__, "gate": validation}))
            continue
        if edit.structural and not structural_allowed:
            pending.append({**record, "reason": "breaks_entry"})
            result.rejected.append(Edit(**{**edit.__dict__, "gate": "breaks_entry"}))
            continue
        if len(applied) >= settings.procedural_max_edits_per_run:
            pending.append({**record, "reason": "cap_reached"})
            result.rejected.append(Edit(**{**edit.__dict__, "gate": "cap_reached"}))
            continue
        applied.append(edit)
    result.applied = applied
    result.pending = pending[-_MAX_PENDING_EDITS:]

    if dry_run:
        return result

    snaps = SnapshotLog()
    root_meta = copy.deepcopy(graph.root.metadata_) or {}
    procedure = root_meta.setdefault("procedure", {})
    procedure["evidence"] = ledger
    procedure["pending_edits"] = result.pending
    set_node_metadata(graph.root, root_meta, snaps)

    for edit in applied:
        await apply_edit(session, embedding_service, graph=graph, edit=edit, thread=thread, ctx=ctx, snaps=snaps)

    extraction_id = uuid.uuid4()
    session.add(
        ConversationExtraction(
            id=extraction_id,
            memory_node_id=graph.root.id,
            thread_id=thread.id,
            source_messages=vp.source_messages,
            extracted_by="procedural_extraction_pipeline",
            extraction_model=ctx.model,
            extraction_prompt_hash=ctx.prompt_hash,
            tenant_id=thread.tenant_id,
        )
    )
    snaps.created_extractions.append(_sid(extraction_id))
    await session.flush()
    await refresh_derived_evidence(
        session, root_id=graph.root.id, tenant_id=thread.tenant_id, settings=settings, snaps=snaps,
        promote=ctx.mode == "apply",
    )
    if any(e.structural for e in applied):
        await check_invariants(session, root_id=graph.root.id, tenant_id=thread.tenant_id, settings=settings)
    result.snapshot = await snaps.finalize(session)
    return result


# ---------------------------------------------------------------------------
# Rollback of procedural decisions
# ---------------------------------------------------------------------------


def _parse_ts(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


async def graph_fingerprint(session: AsyncSession, *, root_id: uuid.UUID, tenant_id: str) -> dict[str, Any]:
    """Root and step metadata plus the active edge ids, as plain JSON.

    Recorded by ``proc_create`` and compared on rollback: if a later session
    added evidence or edits (or a person changed the graph), the create is
    not rolled back.
    """
    await session.flush()
    graph = await load_graph(session, root_id=root_id, tenant_id=tenant_id)

    # Entity extraction updates extraction_status asynchronously; that is not an edit.
    return {
        "root": _comparable(graph.root.metadata_),
        "steps": {_sid(s.id): _comparable(s.metadata_) for s in graph.steps.values()},
        "edges": sorted(_sid(e.id) for e in graph.edges),
    }


async def _get_node(session: AsyncSession, node_id: str | uuid.UUID, tenant_id: str) -> MemoryNode | None:
    return (await session.execute(
        select(MemoryNode).where(MemoryNode.id == uuid.UUID(str(node_id)), MemoryNode.tenant_id == tenant_id)
    )).scalar_one_or_none()


async def _get_edge(session: AsyncSession, edge_id: str | uuid.UUID, tenant_id: str) -> MemoryRelationship | None:
    return (await session.execute(
        select(MemoryRelationship).where(
            MemoryRelationship.id == uuid.UUID(str(edge_id)), MemoryRelationship.tenant_id == tenant_id,
        )
    )).scalar_one_or_none()


async def rollback_procedural_decision(
    session: AsyncSession,
    *,
    action: str,
    content: str,
    memory_id: uuid.UUID | None,
    now: datetime,
    tenant_id: str,
) -> str:
    """Undo one procedural decision row, all or nothing.

    Returns ``rolled_back``, ``skipped_modified`` (something the run changed
    was changed again afterwards, so nothing is touched) or ``noop``.

    ``proc_create`` soft-deletes the root and its steps and closes their
    active edges. A row with a ``snapshot`` restores in-place metadata,
    reinstates deprecated steps and invalidated edges, and retires the
    nodes, edges and provenance rows the run added. Every lookup is
    tenant-scoped.
    """
    try:
        body = json.loads(content)
    except (TypeError, ValueError):
        return "noop"

    if action == "proc_create" and memory_id is not None:
        root = await _get_node(session, memory_id, tenant_id)
        if root is None or root.deleted_at is not None:
            return "noop"
        recorded = body.get("created_state")
        if isinstance(recorded, dict):
            current = await graph_fingerprint(session, root_id=memory_id, tenant_id=tenant_id)
            if current != recorded:
                # Later sessions added evidence or edits: undoing the create would
                # destroy their work and break their own rollbacks.
                return "skipped_modified"
        children = list((await session.execute(
            select(MemoryNode).where(
                MemoryNode.parent_id == memory_id,
                MemoryNode.tenant_id == tenant_id,
                MemoryNode.deleted_at.is_(None),
            )
        )).scalars().all())
        node_ids = [root.id, *(c.id for c in children)]
        edges = list((await session.execute(
            select(MemoryRelationship).where(
                or_(MemoryRelationship.source_id.in_(node_ids), MemoryRelationship.target_id.in_(node_ids)),
                MemoryRelationship.tenant_id == tenant_id,
                MemoryRelationship.valid_until.is_(None),
            )
        )).scalars().all())
        for node in [root, *children]:
            node.deleted_at = now
            node.is_current = False
        for edge in edges:
            edge.valid_until = now
        await session.execute(delete(ConversationExtraction).where(
            ConversationExtraction.memory_node_id == memory_id,
            ConversationExtraction.tenant_id == tenant_id,
        ))
        return "rolled_back"

    snapshot = body.get("snapshot")
    if not isinstance(snapshot, dict):
        return "noop"

    # Phase 1: verify every recorded change is still in the state the run left.
    node_meta = []
    for entry in snapshot.get("node_meta", []):
        node = await _get_node(session, entry["id"], tenant_id)
        if node is None or _comparable(node.metadata_) != _comparable(entry["after"]):
            return "skipped_modified"
        node_meta.append((node, entry["before"]))
    edge_meta = []
    for entry in snapshot.get("edge_meta", []):
        edge = await _get_edge(session, entry["id"], tenant_id)
        if edge is None or _comparable(edge.metadata_) != _comparable(entry["after"]):
            return "skipped_modified"
        edge_meta.append((edge, entry["before"]))
    deleted_nodes = []
    for node_id in snapshot.get("node_deleted", []):
        node = await _get_node(session, node_id, tenant_id)
        if node is None or node.deleted_at is None:
            return "skipped_modified"
        deleted_nodes.append(node)
    invalidated = []
    for edge_id in dict.fromkeys(snapshot.get("edge_invalidated", [])):
        edge = await _get_edge(session, edge_id, tenant_id)
        if edge is None or edge.valid_until is None:
            return "skipped_modified"
        invalidated.append(edge)
    created_nodes = []
    for node_id in snapshot.get("created_nodes", []):
        node = await _get_node(session, node_id, tenant_id)
        if node is None or node.deleted_at is not None:
            return "skipped_modified"
        created_nodes.append(node)
    created_edges = []
    for edge_id in snapshot.get("created_edges", []):
        edge = await _get_edge(session, edge_id, tenant_id)
        if edge is None or edge.valid_until is not None:
            return "skipped_modified"
        created_edges.append(edge)

    # Phase 2: apply all of it.
    for node, before in node_meta:
        node.metadata_ = before
    for edge, before in edge_meta:
        edge.metadata_ = before
    for edge in created_edges:
        edge.valid_until = now
    for node in created_nodes:
        node.deleted_at = now
        node.is_current = False
    await session.flush()  # retire added edges before reinstating the ones they replaced
    for node in deleted_nodes:
        node.deleted_at = None
    for edge in invalidated:
        edge.valid_until = None
    extraction_ids = [uuid.UUID(x) for x in snapshot.get("created_extractions", [])]
    if extraction_ids:
        await session.execute(delete(ConversationExtraction).where(
            ConversationExtraction.id.in_(extraction_ids),
            ConversationExtraction.tenant_id == tenant_id,
        ))
    return "rolled_back"


def utcnow() -> datetime:
    return datetime.now(UTC)
