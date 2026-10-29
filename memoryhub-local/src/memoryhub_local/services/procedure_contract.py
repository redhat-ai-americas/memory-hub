"""Procedural extraction contract shared by memoryhub-core and memoryhub-local (#554).

The model-independent part of procedural graph extraction: the trajectory
format the model sees, the strict proposal schema, the model call with its
one correction retry, and the deterministic validation (evidence and
corroboration rules, minimum bar, entry and reachability). Nothing here
touches a database or imports a service.

THIS FILE EXISTS TWICE, BYTE FOR BYTE:
  src/memoryhub_core/services/procedure_contract.py
  memoryhub-local/src/memoryhub_local/services/procedure_contract.py
memoryhub-local cannot depend on memoryhub-core (it is not published), so it
carries a copy. tests/test_services/test_procedure_contract_parity.py fails
when the two differ. Edit one, copy it to the other.

Design: planning/procedural-graph-extraction.md (D2, D3, review follow-ups).
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Annotated, Any, Literal, Protocol

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    field_validator,
)

logger = logging.getLogger(__name__)

# Transcript budget per message kind (characters).
_RESULT_HEAD, _RESULT_TAIL = 1500, 500
_CALL_HEAD, _CALL_TAIL = 800, 200
_TEXT_HEAD, _TEXT_TAIL = 3000, 1000

#: Root content cap (goal + summary). Keeps nodes far below chunking/S3 sizes.
_ROOT_CONTENT_MAX = 1500


class ValidationSettings(Protocol):
    """The thresholds validation reads (AppSettings in core, a dataclass in local)."""

    procedural_min_steps: int
    procedural_max_steps: int
    procedural_min_detection_confidence: float
    procedural_min_outcome_confidence: float


# ---------------------------------------------------------------------------
# Trajectory format (D2)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TrajectoryEvent:
    """One message as the procedural pass sees it. Never an ORM row.

    Hydrating S3 content into the ORM row would mark it dirty and write tool
    output into the inline content column on the next commit.
    """

    seq: int
    role: str
    content: str
    tool_call_id: str | None = None
    outcome_marker: str | None = None
    available: bool = True


_OUTCOME_MARKERS = frozenset({"success", "failure", "partial"})


def _clip(text: str, head: int, tail: int) -> str:
    if len(text) <= head + tail + 40:
        return text
    omitted = len(text) - head - tail
    return f"{text[:head]}\n[... {omitted} chars omitted ...]\n{text[-tail:]}"


_DELIMITER_RE = re.compile(r"<(/?)(transcript)", re.IGNORECASE)


def _neutralize_delimiters(text: str) -> str:
    """Stop message content from closing or reopening the transcript block."""
    return _DELIMITER_RE.sub(r"&lt;\1\2", text)


def wrap_transcript(text: str) -> str:
    return f"<transcript>\n{text}\n</transcript>"


def _render_event(event: TrajectoryEvent) -> str:
    event = TrajectoryEvent(
        seq=event.seq, role=event.role, content=_neutralize_delimiters(event.content),
        tool_call_id=event.tool_call_id, outcome_marker=event.outcome_marker,
        available=event.available,
    )
    if event.role == "tool_result":
        body = _clip(event.content, _RESULT_HEAD, _RESULT_TAIL)
    elif event.role == "tool_call":
        body = _clip(event.content, _CALL_HEAD, _CALL_TAIL)
    else:
        body = _clip(event.content, _TEXT_HEAD, _TEXT_TAIL)
    header = f"[seq={event.seq}] {event.role.upper()}"
    if event.tool_call_id:
        header += f" (tool_call_id={event.tool_call_id})"
    if event.outcome_marker:
        header += f" [outcome marker: {event.outcome_marker}]"
    return f"{header}\n{body}"


def format_trajectory(
    events: list[TrajectoryEvent], *, max_chars: int,
) -> tuple[str, set[int]]:
    """Render events within ``max_chars``. Returns (text, included sequence numbers).

    When the session does not fit, the first user message (the goal) and the
    most recent messages that fit are kept, with an explicit omission marker.
    Evidence may only cite included sequence numbers.
    """
    blocks = [(event.seq, _render_event(event)) for event in events]
    total = sum(len(block) + 2 for _, block in blocks)
    if total <= max_chars:
        return "\n\n".join(block for _, block in blocks), {seq for seq, _ in blocks}

    head: list[tuple[int, str]] = []
    first_user = next((i for i, event in enumerate(events) if event.role == "user"), None)
    budget = max_chars
    if first_user is not None:
        head = [blocks[first_user]]
        budget -= len(blocks[first_user][1]) + 2
    tail: list[tuple[int, str]] = []
    for index in range(len(blocks) - 1, -1, -1):
        if first_user is not None and index == first_user:
            break
        size = len(blocks[index][1]) + 2
        if size > budget - 80:
            break
        tail.append(blocks[index])
        budget -= size
    tail.reverse()
    kept = head + tail
    if not kept:  # one enormous message: keep a clipped version of the last
        seq, block = blocks[-1]
        kept = [(seq, block[: max(max_chars - 80, 200)])]
    included = {seq for seq, _ in kept}
    omitted = [seq for seq, _ in blocks if seq not in included]
    parts = [block for _, block in head]
    if omitted:
        parts.append(f"[messages {omitted[0]}-{omitted[-1]} omitted: {len(omitted)} messages]")
    parts.extend(block for _, block in tail)
    return "\n\n".join(parts), included


# ---------------------------------------------------------------------------
# Proposal schema (D3)
# ---------------------------------------------------------------------------

EvidenceKind = Literal["observed", "inferred"]


def _clip_str(limit: int) -> Callable[[Any], Any]:
    def _inner(value: Any) -> Any:
        if value is None:
            return value
        return str(value).strip()[:limit]

    return _inner


def _ints(value: Any) -> list[int]:
    if value is None:
        return []
    if not isinstance(value, list):
        value = [value]
    out: list[int] = []
    for item in value:
        try:
            out.append(int(item))
        except (TypeError, ValueError):
            continue
    return out


Text40 = Annotated[str, BeforeValidator(_clip_str(40)), StringConstraints(min_length=1)]
Text200 = Annotated[str, BeforeValidator(_clip_str(200)), StringConstraints(min_length=1)]
Text300 = Annotated[str, BeforeValidator(_clip_str(300)), StringConstraints(min_length=1)]
Text500 = Annotated[str, BeforeValidator(_clip_str(500)), StringConstraints(min_length=1)]
Text1000 = Annotated[str, BeforeValidator(_clip_str(1000)), StringConstraints(min_length=1)]
Seqs = Annotated[list[int], BeforeValidator(_ints)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class EvidencedText(_Strict):
    """A condition, pitfall or guidance item with its own evidence."""

    text: Text500
    evidence: EvidenceKind = "inferred"
    source_messages: Seqs = Field(default_factory=list)


def _coerce_evidenced(value: Any) -> Any:
    # A bare string is accepted but carries no evidence, so it is inferred.
    if isinstance(value, str):
        return {"text": value, "evidence": "inferred", "source_messages": []}
    return value


def _coerce_evidenced_list(value: Any) -> Any:
    if value is None:
        return []
    if not isinstance(value, list):
        value = [value]
    return [_coerce_evidenced(item) for item in value[:10]]


EvidencedItem = Annotated[EvidencedText, BeforeValidator(_coerce_evidenced)]
EvidencedList = Annotated[list[EvidencedText], BeforeValidator(_coerce_evidenced_list)]


class StepProposal(_Strict):
    key: Text40
    action: Text300
    tool_ref: Annotated[str | None, BeforeValidator(_clip_str(200))] = None
    preconditions: EvidencedList = Field(default_factory=list)
    postconditions: EvidencedList = Field(default_factory=list)
    pitfalls: EvidencedList = Field(default_factory=list)
    guidance: EvidencedItem | None = None
    status: Literal["succeeded", "failed", "skipped", "unknown"] = "unknown"
    evidence: EvidenceKind = "inferred"
    source_messages: Seqs = Field(default_factory=list)

    @field_validator("tool_ref")
    @classmethod
    def _blank_tool_ref(cls, value: str | None) -> str | None:
        return value or None


class EdgeProposal(_Strict):
    source: Text40
    target: Text40
    type: Literal["precedes", "requires", "alternative_to"]
    condition: EvidencedItem | None = None
    guidance: EvidencedItem | None = None
    pitfalls: EvidencedList = Field(default_factory=list)
    evidence: EvidenceKind = "inferred"
    source_messages: Seqs = Field(default_factory=list)


class EdgeRef(_Strict):
    source: Text40
    target: Text40


class FailureProposal(_Strict):
    step: Annotated[str | None, BeforeValidator(_clip_str(40))] = None
    edge: EdgeRef | None = None
    failure_class: Literal[
        "procedure", "tool_error", "environment", "precondition_unmet", "unknown",
    ] = Field(default="unknown", alias="class")
    evidence: EvidenceKind = "inferred"
    source_messages: Seqs = Field(default_factory=list)


class OutcomeProposal(_Strict):
    result: Literal["success", "failure", "partial", "unknown"] = "unknown"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence: EvidenceKind = "inferred"
    source_messages: Seqs = Field(default_factory=list)
    failure: FailureProposal | None = None


class ProceduralProposal(_Strict):
    procedure_detected: bool
    goal: Annotated[str | None, BeforeValidator(_clip_str(200))] = None
    summary: Annotated[str | None, BeforeValidator(_clip_str(1000))] = None
    steps: list[StepProposal] = Field(default_factory=list, max_length=60)
    edges: list[EdgeProposal] = Field(default_factory=list, max_length=200)
    entry_step: Annotated[str | None, BeforeValidator(_clip_str(40))] = None
    outcome: OutcomeProposal | None = None
    detection_confidence: float = Field(default=0.0, ge=0.0, le=1.0)


# ---------------------------------------------------------------------------
# Model call with one correction retry
# ---------------------------------------------------------------------------


class ProposalFormatError(ValueError):
    """The model's answer was not a usable proposal after one correction."""


def _parse_json(text: str) -> Any:
    cleaned = re.sub(r"^```(?:json)?\s*\n?", "", (text or "").strip())
    cleaned = re.sub(r"\n?```\s*$", "", cleaned)
    return json.loads(cleaned)


def _parse_proposal(content: str, finish_reason: str | None) -> ProceduralProposal:
    if finish_reason == "length":
        raise ProposalFormatError("response was truncated (finish_reason=length)")
    try:
        data = _parse_json(content)
    except json.JSONDecodeError as exc:
        raise ProposalFormatError(
            f"response is not valid JSON ({exc.msg} at char {exc.pos})"
        ) from exc
    except ValueError as exc:
        raise ProposalFormatError("response is not valid JSON") from exc
    if not isinstance(data, dict):
        raise ProposalFormatError("response is not a JSON object")
    try:
        return ProceduralProposal.model_validate(data)
    except ValidationError as exc:
        # Locations and messages only: the default text embeds input values,
        # which can carry tool output that has not been through curation.
        problems = "; ".join(
            f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}"
            for err in exc.errors(
                include_url=False, include_input=False, include_context=False
            )[:10]
        )
        raise ProposalFormatError(f"response does not match the schema: {problems}") from exc


async def detect_procedure(llm: Any, transcript: str, *, system_prompt: str) -> ProceduralProposal:
    """Ask the model for a proposal; one correction retry on a format error.

    ``llm`` has ``async complete(messages) -> (content, finish_reason)``.
    """
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": wrap_transcript(transcript)},
    ]
    content, finish = await llm.complete(messages)
    try:
        return _parse_proposal(content, finish)
    except ProposalFormatError as first:
        logger.warning("Procedural proposal format error, sending one correction: %s", first)
        messages = [
            *messages,
            {"role": "assistant", "content": content[:4000]},
            {
                "role": "user",
                "content": (
                    f"That response cannot be used: {str(first)[:1500]}. Return exactly one "
                    "JSON object that follows the schema in the system message and nothing "
                    "else. Report only steps visible in the transcript, cite only seq numbers "
                    "that appear in it, and do not invent intermediate reasoning."
                ),
            },
        ]
        content, finish = await llm.complete(messages)
        return _parse_proposal(content, finish)


# ---------------------------------------------------------------------------
# Deterministic validation (D3)
# ---------------------------------------------------------------------------


@dataclass
class EvText:
    text: str
    evidence: str
    source_messages: list[int]

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text, "evidence": self.evidence,
            "source_messages": self.source_messages,
        }


@dataclass
class VStep:
    key: str
    action: str
    tool_ref: str | None
    preconditions: list[EvText]
    postconditions: list[EvText]
    pitfalls: list[EvText]
    guidance: EvText | None
    status: str
    evidence: str
    source_messages: list[int]

    @property
    def first_seq(self) -> int:
        return min(self.source_messages) if self.source_messages else 10**9

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key, "action": self.action, "tool_ref": self.tool_ref,
            "preconditions": [t.to_dict() for t in self.preconditions],
            "postconditions": [t.to_dict() for t in self.postconditions],
            "pitfalls": [t.to_dict() for t in self.pitfalls],
            "guidance": self.guidance.to_dict() if self.guidance else None,
            "status": self.status, "evidence": self.evidence,
            "source_messages": self.source_messages,
        }


@dataclass
class VEdge:
    source: str
    target: str
    type: str
    condition: EvText | None
    guidance: EvText | None
    pitfalls: list[EvText]
    evidence: str
    source_messages: list[int]

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source, "target": self.target, "type": self.type,
            "condition": self.condition.to_dict() if self.condition else None,
            "guidance": self.guidance.to_dict() if self.guidance else None,
            "pitfalls": [t.to_dict() for t in self.pitfalls],
            "evidence": self.evidence, "source_messages": self.source_messages,
        }


@dataclass
class OutcomeInfo:
    """The session outcome as the gates see it (D-Outcome, D6a.5)."""

    result: str  # success | failure | partial | unknown
    source: str  # explicit_message | llm | none
    confidence: float
    strong: bool
    failure_class: str | None = None
    failure_step: str | None = None
    failure_edge: tuple[str, str] | None = None
    failure_observed: bool = False
    source_messages: list[int] = field(default_factory=list)

    @property
    def is_failure(self) -> bool:
        return self.result in ("failure", "partial")

    @property
    def strong_success(self) -> bool:
        return self.strong and self.result == "success"

    @property
    def attributable(self) -> bool:
        return (
            self.strong
            and self.is_failure
            and self.failure_class == "procedure"
            and self.failure_observed
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "result": self.result, "source": self.source, "confidence": self.confidence,
            "strong": self.strong, "failure_class": self.failure_class,
            "failure_step": self.failure_step,
            "failure_edge": list(self.failure_edge) if self.failure_edge else None,
            "failure_observed": self.failure_observed,
            "source_messages": self.source_messages,
        }


@dataclass
class ValidatedProcedure:
    goal: str
    summary: str
    steps: list[VStep]  # observed only, ordered by first cited sequence number
    edges: list[VEdge]  # observed only, between kept steps
    entry_key: str
    outcome: OutcomeInfo
    detection_confidence: float
    inferred_steps: list[VStep] = field(default_factory=list)
    inferred_edges: list[VEdge] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def description(self) -> str:
        return f"{self.goal}: {self.summary}".strip()[:_ROOT_CONTENT_MAX]

    @property
    def source_messages(self) -> list[int]:
        seqs: set[int] = set()
        for step in self.steps:
            seqs.update(step.source_messages)
        for edge in self.edges:
            seqs.update(edge.source_messages)
        seqs.update(self.outcome.source_messages)
        return sorted(seqs)

    def step(self, key: str) -> VStep | None:
        return next((s for s in self.steps if s.key == key), None)

    def all_text(self) -> list[str]:
        """Every string that may be written anywhere (for the curation pre-flight)."""
        texts = [self.goal, self.summary]
        for step in [*self.steps, *self.inferred_steps]:
            texts.extend([step.action, step.tool_ref or ""])
            for item in [*step.preconditions, *step.postconditions, *step.pitfalls]:
                texts.append(item.text)
            if step.guidance:
                texts.append(step.guidance.text)
        for edge in [*self.edges, *self.inferred_edges]:
            for item in [edge.condition, edge.guidance, *edge.pitfalls]:
                if item is not None:
                    texts.append(item.text)
        return [t for t in texts if t]

    def to_dict(self) -> dict[str, Any]:
        return {
            "goal": self.goal, "summary": self.summary, "entry_step": self.entry_key,
            "steps": [s.to_dict() for s in self.steps],
            "edges": [e.to_dict() for e in self.edges],
            "inferred_steps": [s.to_dict() for s in self.inferred_steps],
            "inferred_edges": [e.to_dict() for e in self.inferred_edges],
            "outcome": self.outcome.to_dict(),
            "detection_confidence": self.detection_confidence,
            "notes": self.notes,
        }


@dataclass
class Rejection:
    reason: str
    detail: str


def _corroborated(seqs: list[int], trusted: set[int]) -> bool:
    """True when at least one cited message was written by the agent or the user.

    Tool results are untrusted text (command output, fetched pages, files).
    Text that only a tool result shows is never ``observed``: otherwise a
    line in a tool's output could become a step or a pitfall that #553
    later injects into another agent's context (review of #554).
    """
    return bool(set(seqs) & trusted)


def _ev(item: EvidencedText | None, included: set[int], trusted: set[int]) -> EvText | None:
    if item is None:
        return None
    seqs = sorted({s for s in item.source_messages if s in included})
    evidence = item.evidence if _corroborated(seqs, trusted) else "inferred"
    return EvText(text=item.text, evidence=evidence, source_messages=seqs)


def _ev_list(items: list[EvidencedText], included: set[int], trusted: set[int]) -> list[EvText]:
    return [x for x in (_ev(item, included, trusted) for item in items) if x is not None]


def _resolve_outcome(
    proposal: ProceduralProposal,
    events: list[TrajectoryEvent],
    included: set[int],
    step_keys: set[str],
    edge_keys: set[tuple[str, str]],
    settings: ValidationSettings,
) -> OutcomeInfo:
    raw = proposal.outcome or OutcomeProposal()
    failure = raw.failure
    failure_class = failure.failure_class if failure else None
    failure_step = failure.step if failure and failure.step in step_keys else None
    failure_edge = None
    if failure and failure.edge and (failure.edge.source, failure.edge.target) in edge_keys:
        failure_edge = (failure.edge.source, failure.edge.target)
    trusted = {e.seq for e in events if e.role != "tool_result" and e.seq in included}
    failure_cited = failure.source_messages if failure else []
    failure_seqs = sorted({s for s in failure_cited if s in included})
    failure_observed = bool(
        failure and failure.evidence == "observed" and _corroborated(failure_seqs, trusted)
    )

    marker_event = next((e for e in reversed(events) if e.outcome_marker), None)
    if marker_event is not None:
        return OutcomeInfo(
            result=marker_event.outcome_marker or "unknown",
            source="explicit_message",
            confidence=1.0,
            strong=True,
            failure_class=failure_class,
            failure_step=failure_step,
            failure_edge=failure_edge,
            failure_observed=failure_observed,
            source_messages=[marker_event.seq],
        )

    seqs = sorted({s for s in raw.source_messages if s in included})
    strong = (
        raw.result in ("success", "failure", "partial")
        and raw.evidence == "observed"
        and _corroborated(seqs, trusted)
        and raw.confidence >= settings.procedural_min_outcome_confidence
    )
    return OutcomeInfo(
        result=raw.result,
        source="llm" if proposal.outcome is not None else "none",
        confidence=raw.confidence,
        strong=strong,
        failure_class=failure_class,
        failure_step=failure_step,
        failure_edge=failure_edge,
        failure_observed=failure_observed,
        source_messages=seqs,
    )


def validate_proposal(
    proposal: ProceduralProposal,
    events: list[TrajectoryEvent],
    included: set[int],
    settings: ValidationSettings,
) -> ValidatedProcedure | Rejection | None:
    """Apply the deterministic rules of D3. ``None`` means no procedure detected."""
    if not proposal.procedure_detected:
        return None
    roles = {e.seq: e.role for e in events}
    tool_seqs = {
        s for s, r in roles.items() if r in ("tool_call", "tool_result") and s in included
    }
    call_seqs = {s for s, r in roles.items() if r == "tool_call" and s in included}
    # Messages the agent or the user wrote. Tool results corroborate nothing on their own.
    trusted = {s for s, r in roles.items() if r != "tool_result" and s in included}
    notes: list[str] = []

    if not proposal.goal:
        return Rejection("below_confidence", "proposal has no goal")
    if len(proposal.steps) > settings.procedural_max_steps:
        return Rejection(
            "cap_reached",
            f"{len(proposal.steps)} steps exceeds "
            f"procedural_max_steps={settings.procedural_max_steps}",
        )

    # Steps: unique keys, citations restricted to the transcript, downgrades.
    steps: dict[str, VStep] = {}
    for raw in proposal.steps:
        if raw.key in steps:
            notes.append(f"duplicate step key {raw.key} dropped")
            continue
        seqs = sorted({s for s in raw.source_messages if s in included})
        evidence = raw.evidence if seqs else "inferred"
        if evidence == "observed" and not _corroborated(seqs, trusted):
            evidence = "inferred"
            notes.append(f"step {raw.key}: cited only tool output; downgraded")
        if evidence == "observed" and raw.tool_ref and not (set(seqs) & tool_seqs):
            evidence = "inferred"
            notes.append(f"step {raw.key}: tool_ref without a cited tool message; downgraded")
        steps[raw.key] = VStep(
            key=raw.key,
            action=raw.action,
            tool_ref=raw.tool_ref,
            preconditions=_ev_list(raw.preconditions, included, trusted),
            postconditions=_ev_list(raw.postconditions, included, trusted),
            pitfalls=_ev_list(raw.pitfalls, included, trusted),
            guidance=_ev(raw.guidance, included, trusted),
            status=raw.status,
            evidence=evidence,
            source_messages=seqs,
        )

    observed = {k: s for k, s in steps.items() if s.evidence == "observed"}
    inferred_steps = [s for s in steps.values() if s.evidence != "observed"]

    # Edges: known endpoints, no self/duplicate edges, ordering for precedes.
    edges: list[VEdge] = []
    inferred_edges: list[VEdge] = []
    seen: set[tuple[str, str, str]] = set()
    for raw in proposal.edges:
        triple = (raw.source, raw.target, raw.type)
        if raw.source == raw.target or triple in seen:
            continue
        if raw.source not in steps or raw.target not in steps:
            notes.append(f"edge {raw.source}->{raw.target} references an unknown step; dropped")
            continue
        seen.add(triple)
        seqs = sorted({s for s in raw.source_messages if s in included})
        evidence = raw.evidence if _corroborated(seqs, trusted) else "inferred"
        if raw.source not in observed or raw.target not in observed:
            evidence = "inferred"
        elif (
            raw.type == "precedes"
            and observed[raw.source].first_seq >= observed[raw.target].first_seq
        ):
            evidence = "inferred"
            notes.append(
                f"edge {raw.source}->{raw.target}: order contradicts citations; downgraded"
            )
        edge = VEdge(
            source=raw.source,
            target=raw.target,
            type=raw.type,
            condition=_ev(raw.condition, included, trusted),
            guidance=_ev(raw.guidance, included, trusted),
            pitfalls=_ev_list(raw.pitfalls, included, trusted),
            evidence=evidence,
            source_messages=seqs,
        )
        (edges if evidence == "observed" else inferred_edges).append(edge)

    # Entry: the proposal's entry when valid, otherwise the single candidate.
    incoming = {e.target for e in edges if e.type == "precedes"}
    entry = proposal.entry_step
    if entry not in observed or entry in incoming:
        candidates = sorted(k for k in observed if k not in incoming)
        if len(candidates) == 1:
            notes.append(f"entry_step {entry!r} invalid; using the only candidate {candidates[0]}")
            entry = candidates[0]
        else:
            return Rejection(
                "breaks_entry",
                f"no valid entry step (proposed {entry!r}, candidates {candidates})",
            )

    # Reachability from the entry: precedes directed, requires/alternative_to both ways.
    adjacency: dict[str, set[str]] = {k: set() for k in observed}
    for edge in edges:
        adjacency[edge.source].add(edge.target)
        if edge.type != "precedes":
            adjacency[edge.target].add(edge.source)
    reached = {entry}
    frontier = [entry]
    while frontier:
        node = frontier.pop()
        for nxt in adjacency.get(node, ()):
            if nxt not in reached:
                reached.add(nxt)
                frontier.append(nxt)
    unreachable = sorted(set(observed) - reached)
    if unreachable:
        notes.append(f"steps unreachable from the entry dropped: {unreachable}")
        for key in unreachable:
            inferred_steps.append(observed.pop(key))
        edges = [e for e in edges if e.source in observed and e.target in observed]

    ordered = sorted(observed.values(), key=lambda s: (s.first_seq, s.key))
    if len(ordered) < settings.procedural_min_steps:
        return Rejection(
            "insufficient_evidence",
            f"{len(ordered)} observed steps; procedural_min_steps={settings.procedural_min_steps}",
        )
    if not any(set(s.source_messages) & call_seqs for s in ordered):
        return Rejection("insufficient_evidence", "no observed step cites a tool_call message")
    if proposal.detection_confidence < settings.procedural_min_detection_confidence:
        return Rejection(
            "below_confidence",
            f"detection_confidence {proposal.detection_confidence:.2f} < "
            f"{settings.procedural_min_detection_confidence:.2f}",
        )

    outcome = _resolve_outcome(
        proposal, events, included,
        set(observed), {(e.source, e.target) for e in edges}, settings,
    )
    return ValidatedProcedure(
        goal=proposal.goal.strip(),
        summary=(proposal.summary or "").strip(),
        steps=ordered,
        edges=edges,
        entry_key=entry,
        outcome=outcome,
        detection_confidence=proposal.detection_confidence,
        inferred_steps=inferred_steps,
        inferred_edges=inferred_edges,
        notes=notes,
    )
