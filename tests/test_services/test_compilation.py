"""Unit tests for the compilation epoch pure logic module (#175).

All tests are synchronous — compilation.py has no I/O, no async.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from memoryhub_core.services.compilation import (
    CompilationEpoch,
    apply_compilation,
    compile_memory_set,
    compute_compilation_hash,
    should_recompile,
)

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

_BASE_DATE = datetime(2026, 4, 1, tzinfo=UTC)


@dataclass
class FakeMemory:
    id: uuid.UUID
    weight: float
    created_at: datetime | None


def _mem(
    weight: float,
    days_ago: int = 0,
    id_override: str | None = None,
) -> FakeMemory:
    """Create a FakeMemory with deterministic attributes.

    Pass days_ago=-1 to get created_at=None (legacy stub).
    """
    created = (
        _BASE_DATE + timedelta(days=-days_ago)
        if days_ago >= 0
        else None
    )
    return FakeMemory(
        id=uuid.UUID(id_override) if id_override else uuid.uuid4(),
        weight=weight,
        created_at=created,
    )


def _results(*memories: FakeMemory) -> list[tuple[FakeMemory, float]]:
    """Wrap FakeMemory objects into (item, score) tuples with a dummy score."""
    return [(m, 1.0) for m in memories]


# ---------------------------------------------------------------------------
# compile_memory_set
# ---------------------------------------------------------------------------


def test_compile_produces_deterministic_order():
    """Compiling the same set twice must yield identical ordered_ids and hash."""
    a = _mem(0.9, days_ago=3)
    b = _mem(0.7, days_ago=1)
    c = _mem(0.5, days_ago=2)

    epoch1 = compile_memory_set(_results(a, b, c))
    epoch2 = compile_memory_set(_results(c, a, b))  # different input order

    assert epoch1.ordered_ids == epoch2.ordered_ids
    assert epoch1.compilation_hash == epoch2.compilation_hash


def test_canonical_sort_weight_desc():
    """Higher weight memories must appear first."""
    lo = _mem(0.3, days_ago=0)
    hi = _mem(0.9, days_ago=0)
    mid = _mem(0.6, days_ago=0)

    epoch = compile_memory_set(_results(lo, hi, mid))

    ids = epoch.ordered_ids
    assert ids.index(str(hi.id)) < ids.index(str(mid.id))
    assert ids.index(str(mid.id)) < ids.index(str(lo.id))


def test_canonical_sort_created_at_asc_within_weight():
    """Same weight: earlier created_at must sort first."""
    newer = _mem(0.8, days_ago=0)   # today
    older = _mem(0.8, days_ago=5)   # 5 days ago → earlier

    epoch = compile_memory_set(_results(newer, older))

    ids = epoch.ordered_ids
    assert ids.index(str(older.id)) < ids.index(str(newer.id))


def test_canonical_sort_id_tiebreaker():
    """Same weight and created_at: lexicographically smaller UUID string sorts first."""
    same_date = _BASE_DATE
    # Construct two UUIDs where we know the string ordering.
    id_a = "00000000-0000-0000-0000-000000000001"
    id_b = "00000000-0000-0000-0000-000000000002"

    a = FakeMemory(id=uuid.UUID(id_a), weight=0.5, created_at=same_date)
    b = FakeMemory(id=uuid.UUID(id_b), weight=0.5, created_at=same_date)

    epoch = compile_memory_set(_results(b, a))  # reversed input

    assert epoch.ordered_ids[0] == id_a
    assert epoch.ordered_ids[1] == id_b


def test_empty_results():
    """Empty input produces an epoch with empty ordered_ids list."""
    epoch = compile_memory_set([])

    assert epoch.ordered_ids == []
    assert epoch.compilation_hash == compute_compilation_hash([])
    assert epoch.epoch == 1


# ---------------------------------------------------------------------------
# compute_compilation_hash
# ---------------------------------------------------------------------------


def test_compilation_hash_stability():
    """Same ID list → same hash; different ID list → different hash."""
    ids1 = ["aaa", "bbb", "ccc"]
    ids2 = ["aaa", "bbb", "ddd"]

    assert compute_compilation_hash(ids1) == compute_compilation_hash(ids1)
    assert compute_compilation_hash(ids1) != compute_compilation_hash(ids2)


# ---------------------------------------------------------------------------
# apply_compilation
# ---------------------------------------------------------------------------


def test_apply_compilation_preserves_epoch_order():
    """Items must come back in epoch-defined order, regardless of input order."""
    a = _mem(0.9, days_ago=2)
    b = _mem(0.7, days_ago=1)
    c = _mem(0.5, days_ago=0)

    # Compile to get a stable epoch.
    epoch = compile_memory_set(_results(a, b, c))

    # Pass results in a different order.
    compiled, appendix = apply_compilation(_results(c, a, b), epoch)

    compiled_ids = [str(item.id) for item, _score in compiled]
    assert compiled_ids == epoch.ordered_ids
    assert appendix == []


def test_appendix_contains_only_new_memories():
    """Memories not in the epoch must end up in the appendix."""
    a = _mem(0.9, days_ago=2)
    b = _mem(0.7, days_ago=1)
    c = _mem(0.5, days_ago=0)  # new — not part of original epoch

    epoch = compile_memory_set(_results(a, b))

    compiled, appendix = apply_compilation(_results(a, b, c), epoch)

    compiled_ids = {str(item.id) for item, _ in compiled}
    appendix_ids = {str(item.id) for item, _ in appendix}

    assert compiled_ids == {str(a.id), str(b.id)}
    assert appendix_ids == {str(c.id)}


def test_appendix_sorted_by_created_at():
    """Multiple new memories in the appendix must be sorted by created_at ASC."""
    a = _mem(0.9, days_ago=5)  # in epoch
    # New memories (not in epoch) with different creation times.
    new_late = _mem(0.4, days_ago=0)   # today
    new_early = _mem(0.6, days_ago=3)  # 3 days ago

    epoch = compile_memory_set(_results(a))

    _compiled, appendix = apply_compilation(_results(a, new_late, new_early), epoch)

    appendix_ids = [str(item.id) for item, _ in appendix]
    # new_early was created before new_late → should be first.
    assert appendix_ids.index(str(new_early.id)) < appendix_ids.index(str(new_late.id))


def test_deleted_memories_silently_skipped():
    """Epoch IDs absent from results must be skipped without error."""
    a = _mem(0.9, days_ago=2)
    b = _mem(0.7, days_ago=1)
    c = _mem(0.5, days_ago=0)

    epoch = compile_memory_set(_results(a, b, c))

    # Results only contain a and c — b was deleted.
    compiled, appendix = apply_compilation(_results(a, c), epoch)

    compiled_ids = [str(item.id) for item, _ in compiled]
    assert str(b.id) not in compiled_ids
    assert str(a.id) in compiled_ids
    assert str(c.id) in compiled_ids
    assert appendix == []


# ---------------------------------------------------------------------------
# should_recompile
# ---------------------------------------------------------------------------


def test_should_recompile_default_threshold():
    """Default min_appendix=5 allows appendix growth before recompilation."""
    assert should_recompile(10, 0) is False
    assert should_recompile(10, 1) is False  # below min_appendix=5
    assert should_recompile(10, 4) is False  # still below
    assert should_recompile(10, 5) is True   # hits min_appendix
    assert should_recompile(100, 5) is True  # hits min_appendix


def test_should_recompile_boundary_conditions():
    """Verify boundary conditions around the default min_appendix=5."""
    # 10 compiled + 4 appendix → below min_appendix and below ratio threshold.
    assert should_recompile(10, 4) is False

    # 10 compiled + 5 appendix → hits min_appendix.
    assert should_recompile(10, 5) is True

    # 10 compiled + 3 appendix → 3/10 = 0.3, not strictly greater than 0.3.
    assert should_recompile(10, 3) is False

    # 3 compiled + 1 appendix → 1/3 ≈ 0.333 > 0.3 → True (ratio check).
    assert should_recompile(3, 1) is True


def test_should_recompile_empty_epoch():
    """An empty epoch always triggers recompilation."""
    assert should_recompile(0, 0) is True
    assert should_recompile(0, 100) is True


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_created_at_none_sorts_to_front():
    """Items without created_at sort before items that have a created_at at the
    same weight tier (datetime.min < any real timestamp)."""
    with_date = _mem(0.5, days_ago=10)
    without_date = _mem(0.5, days_ago=-1)  # created_at=None

    epoch = compile_memory_set(_results(with_date, without_date))

    assert epoch.ordered_ids[0] == str(without_date.id)
    assert epoch.ordered_ids[1] == str(with_date.id)


def test_epoch_serialization_roundtrip():
    """to_dict() → from_dict() must produce an identical CompilationEpoch."""
    a = _mem(0.9, days_ago=2)
    b = _mem(0.5, days_ago=1)
    now = datetime(2026, 4, 13, 12, 0, 0, tzinfo=UTC)

    original = compile_memory_set(_results(a, b), epoch=3, now=now)
    restored = CompilationEpoch.from_dict(original.to_dict())

    assert restored.epoch == original.epoch
    assert restored.ordered_ids == original.ordered_ids
    assert restored.compilation_hash == original.compilation_hash
    assert restored.compiled_at == original.compiled_at
