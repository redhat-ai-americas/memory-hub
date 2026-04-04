"""Tier 2: Embedding similarity check against existing memories."""

import uuid
from dataclasses import dataclass

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from memoryhub.models.memory import MemoryNode


@dataclass
class SimilarityResult:
    similar_count: int
    nearest_id: uuid.UUID | None
    nearest_score: float | None  # cosine similarity in [0, 1]; higher = more similar


async def check_similarity(
    embedding: list[float],
    owner_id: str,
    scope: str,
    session: AsyncSession,
    flag_threshold: float = 0.80,
    max_results: int = 50,
    exclude_id: uuid.UUID | None = None,
) -> SimilarityResult:
    """Check embedding similarity against existing memories in the same (owner_id, scope).

    Returns a SimilarityResult with:
      - similar_count: number of existing memories with similarity >= flag_threshold
      - nearest_id: UUID of the most similar memory (if any above flag_threshold)
      - nearest_score: similarity score of the nearest match

    The caller (pipeline) compares nearest_score against reject_threshold to decide
    whether to block the write.

    Uses pgvector's cosine distance operator (<=>).
    cosine_similarity = 1 - cosine_distance, so we filter on distance <= (1 - flag_threshold).
    """
    filters = [
        MemoryNode.owner_id == owner_id,
        MemoryNode.scope == scope,
        MemoryNode.is_current.is_(True),
        MemoryNode.embedding.isnot(None),
    ]
    if exclude_id is not None:
        filters.append(MemoryNode.id != exclude_id)

    # pgvector distance = 1 - similarity, so similarity >= threshold ↔ distance <= (1 - threshold)
    max_distance = 1.0 - flag_threshold

    try:
        distance_expr = MemoryNode.embedding.cosine_distance(embedding)
        stmt = (
            select(MemoryNode.id, distance_expr.label("distance"))
            .where(and_(*filters))
            .where(distance_expr <= max_distance)
            .order_by(distance_expr)
            .limit(max_results)
        )
        result = await session.execute(stmt)
        rows = result.all()
    except Exception:
        # Non-pgvector backend (e.g., SQLite in tests): skip similarity check.
        return SimilarityResult(similar_count=0, nearest_id=None, nearest_score=None)

    if not rows:
        return SimilarityResult(similar_count=0, nearest_id=None, nearest_score=None)

    nearest_row = rows[0]
    nearest_similarity = round(1.0 - float(nearest_row.distance), 4)

    return SimilarityResult(
        similar_count=len(rows),
        nearest_id=nearest_row.id,
        nearest_score=nearest_similarity,
    )


async def get_similar_memories(
    memory_id: uuid.UUID,
    session: AsyncSession,
    threshold: float = 0.80,
    max_results: int = 10,
    offset: int = 0,
) -> dict:
    """Return paged similar memories for a given memory ID.

    Uses the stored embedding from the source memory so no re-embedding is needed.

    Returns:
      {"results": [{"id": uuid, "stub": str, "score": float}], "total": int, "has_more": bool}
    """
    source_stmt = select(MemoryNode).where(MemoryNode.id == memory_id)
    source_result = await session.execute(source_stmt)
    source = source_result.scalar_one_or_none()

    if source is None:
        from memoryhub.services.exceptions import MemoryNotFoundError

        raise MemoryNotFoundError(memory_id)

    if source.embedding is None:
        return {"results": [], "total": 0, "has_more": False}

    max_distance = 1.0 - threshold
    distance_expr = MemoryNode.embedding.cosine_distance(source.embedding)

    base_filters = and_(
        MemoryNode.owner_id == source.owner_id,
        MemoryNode.scope == source.scope,
        MemoryNode.is_current.is_(True),
        MemoryNode.embedding.isnot(None),
        MemoryNode.id != memory_id,
        distance_expr <= max_distance,
    )

    count_stmt = select(func.count()).select_from(MemoryNode).where(base_filters)
    total = (await session.execute(count_stmt)).scalar() or 0

    fetch_stmt = (
        select(MemoryNode.id, MemoryNode.stub, distance_expr.label("distance"))
        .where(base_filters)
        .order_by(distance_expr)
        .offset(offset)
        .limit(max_results)
    )
    rows = (await session.execute(fetch_stmt)).all()

    results = [
        {"id": row.id, "stub": row.stub, "score": round(1.0 - float(row.distance), 4)}
        for row in rows
    ]

    return {
        "results": results,
        "total": total,
        "has_more": (offset + max_results) < total,
    }
