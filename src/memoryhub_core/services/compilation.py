"""Compilation epoch logic for cache-optimized memory assembly (#175).

A compilation epoch is a point-in-time snapshot of the canonical memory
ordering. Between epochs, the ordering is stable — new memories are appended
at the end regardless of weight, preserving the KV cache prefix for all
existing memories. When the appendix grows past a threshold, a new epoch
is compiled (one-time cache invalidation, then stable again).

This module is pure logic — no I/O, no Valkey. Fully unit-testable.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class CompilationEpoch:
    """A frozen ordering of memory IDs that defines the cache-stable prefix."""

    epoch: int
    ordered_ids: list[str]
    compilation_hash: str
    compiled_at: str  # ISO 8601 timestamp

    def to_dict(self) -> dict[str, Any]:
        """Serialize for Valkey storage."""
        return {
            "epoch": str(self.epoch),
            "ordered_ids": "|".join(self.ordered_ids),
            "compilation_hash": self.compilation_hash,
            "compiled_at": self.compiled_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, str]) -> CompilationEpoch:
        """Deserialize from Valkey HGETALL."""
        ordered_ids = data["ordered_ids"].split("|") if data["ordered_ids"] else []
        return cls(
            epoch=int(data["epoch"]),
            ordered_ids=ordered_ids,
            compilation_hash=data["compilation_hash"],
            compiled_at=data["compiled_at"],
        )


def _canonical_sort_key(item: Any) -> tuple:
    """Return a sort tuple for canonical ordering.

    Sort order: weight DESC → created_at ASC → id ASC (string comparison).

    Weight is negated so that a single ascending sort yields descending weight.
    Items without a created_at (legacy stubs) use datetime.min as a fallback,
    which sorts them before any real timestamp at the same weight tier.
    """
    created = getattr(item, "created_at", None) or datetime.min
    # Make datetime timezone-aware if it isn't, so comparison with
    # datetime.min (which is naive) works without errors.
    if created != datetime.min and created.tzinfo is not None:
        # Convert to naive UTC for comparison with datetime.min.
        created = created.replace(tzinfo=None)
    return (-item.weight, created, str(item.id))


def compute_compilation_hash(ordered_ids: list[str]) -> str:
    """Compute a SHA-256 hash of the ordered ID list.

    Deterministic: the same ID list always produces the same hash.
    The empty list produces the hash of an empty string.
    """
    joined = "|".join(ordered_ids)
    return hashlib.sha256(joined.encode()).hexdigest()


def compile_memory_set(
    results: list[tuple[Any, float]],
    epoch: int = 1,
    now: datetime | None = None,
) -> CompilationEpoch:
    """Build a new CompilationEpoch from a set of scored memory results.

    Args:
        results: List of (item, score) tuples where item has .id, .weight,
                 and .created_at attributes. The score is ignored during
                 compilation — canonical order is driven by weight/created_at.
        epoch:   Epoch counter for this compilation.
        now:     Timestamp to record as compiled_at. Defaults to UTC now.

    Returns:
        A CompilationEpoch with a stable canonical ordering.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    sorted_items = sorted(
        (item for item, _score in results),
        key=_canonical_sort_key,
    )
    ordered_ids = [str(item.id) for item in sorted_items]
    return CompilationEpoch(
        epoch=epoch,
        ordered_ids=ordered_ids,
        compilation_hash=compute_compilation_hash(ordered_ids),
        compiled_at=now.isoformat(),
    )


def apply_compilation(
    results: list[tuple[Any, float]],
    epoch: CompilationEpoch,
) -> tuple[list[tuple[Any, float]], list[tuple[Any, float]]]:
    """Split results into epoch-ordered compiled section and new appendix.

    Walks epoch.ordered_ids in order, pulling matching items from results
    into `compiled`. Any result not referenced by the epoch goes into
    `appendix`, sorted by created_at ASC → id ASC (so the most stable
    items surface first within the appendix).

    IDs in the epoch that are absent from results are silently skipped
    (deleted memories).

    Args:
        results: List of (item, score) tuples to partition.
        epoch:   The current CompilationEpoch defining canonical order.

    Returns:
        (compiled, appendix) where compiled follows epoch ordering and
        appendix is sorted by created_at ASC → id ASC.
    """
    lookup: dict[str, tuple[Any, float]] = {
        str(item.id): (item, score) for item, score in results
    }

    compiled: list[tuple[Any, float]] = []
    seen_ids: set[str] = set()

    for mem_id in epoch.ordered_ids:
        if mem_id in lookup:
            compiled.append(lookup[mem_id])
            seen_ids.add(mem_id)

    appendix_pairs = [
        (item, score)
        for item, score in results
        if str(item.id) not in seen_ids
    ]

    def _appendix_key(pair: tuple[Any, float]) -> tuple:
        item = pair[0]
        created = getattr(item, "created_at", None) or datetime.min
        if created != datetime.min and created.tzinfo is not None:
            created = created.replace(tzinfo=None)
        return (created, str(item.id))

    appendix = sorted(appendix_pairs, key=_appendix_key)
    return compiled, appendix


def should_recompile(
    compiled_count: int,
    appendix_count: int,
    threshold: float = 0.3,
    min_appendix: int = 5,
) -> bool:
    """Decide whether the appendix has grown large enough to warrant recompilation.

    Rules (evaluated in order):
    - Empty epoch (compiled_count == 0): always True.
    - Absolute minimum reached (appendix_count >= min_appendix): True.
    - Small compiled corpus with high ratio: compiled_count < min_appendix
      AND appendix_count / compiled_count > threshold: True.
    - Otherwise: False.

    The default min_appendix=5 lets the appendix accumulate a few entries
    before triggering recompilation, avoiding unnecessary cache invalidation
    on every write. The compiled-entry backfill (#188) ensures displaced
    compiled entries are recovered regardless of appendix size.

    Args:
        compiled_count:  Number of memories in the current epoch (compiled section).
        appendix_count:  Number of new memories since the last compilation.
        threshold:       Fractional threshold; default 0.3 means 30%.
        min_appendix:    Absolute count that triggers recompilation regardless of ratio.
                         Default 5. Set higher to allow more appendix growth.

    Returns:
        True if a new compilation should be triggered.
    """
    if compiled_count == 0:
        return True
    if appendix_count >= min_appendix:
        return True
    # Ratio check: only applied to small compiled corpora (compiled_count <
    # min_appendix). For an established corpus, a few new memories at a high
    # ratio (e.g. 4/10 = 40%) is a normal cache-stable state — wait for the
    # absolute min_appendix count instead. For tiny corpora, proportional
    # growth is the right trigger.
    if compiled_count < min_appendix and appendix_count / compiled_count > threshold:
        return True
    return False
