"""PostgresBackend -- RecallBackend implementation for PostgreSQL with pgvector.

Uses pgvector's cosine distance operator (<=>) for vector operations and
PostgreSQL's tsvector/tsquery for keyword search. Requires a PostgreSQL
database with the pgvector extension and a schema that has Vector columns
and a generated search_vector TSVECTOR column.

No pgvector Python package import is needed -- the <=> operator is injected
via literal_column() and composes with standard SQLAlchemy ORM filters.
"""

from __future__ import annotations

import uuid

from sqlalchemy import and_, func, literal_column, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from memoryhub_local.models.memory import MemoryNode

_MAX_DEPTH_CAP = 3
_NEIGHBOR_ROW_LIMIT = 500


def _vec_literal(embedding: list[float]) -> str:
    """Format a list of floats as a pgvector vector literal."""
    return "[" + ",".join(str(x) for x in embedding) + "]"


class PostgresBackend:
    """RecallBackend implementation for PostgreSQL with pgvector.

    Satisfies the RecallBackend protocol with:
      - vector_recall: pgvector cosine distance (<=> operator)
      - keyword_recall: tsvector/tsquery with ts_rank
      - similarity_check: pgvector cosine distance with max_distance filter
      - graph_neighbors: recursive CTE with unnest seed initialization
    """

    async def vector_recall(
        self,
        query_embedding: list[float],
        filters: list,
        limit: int,
        session: AsyncSession,
    ) -> list[tuple[MemoryNode, float]]:
        """pgvector KNN: cosine distance via the <=> operator."""
        vec = _vec_literal(query_embedding)
        distance_expr = literal_column(f"(embedding <=> '{vec}'::vector)")

        stmt = (
            select(MemoryNode, distance_expr.label("distance"))
            .where(and_(*filters))
            .where(MemoryNode.embedding.isnot(None))
            .order_by(distance_expr)
            .limit(limit)
        )
        result = await session.execute(stmt)
        return [(row[0], row[1]) for row in result.all()]

    async def keyword_recall(
        self,
        query_text: str,
        filters: list,
        limit: int,
        session: AsyncSession,
    ) -> list[tuple[MemoryNode, float]]:
        """PostgreSQL tsvector/tsquery keyword search with ts_rank scoring."""
        tsquery = func.plainto_tsquery("english", query_text)
        search_vector = literal_column("search_vector")
        rank_expr = func.ts_rank(search_vector, tsquery)

        stmt = (
            select(MemoryNode, rank_expr.label("kw_rank"))
            .where(and_(*filters))
            .where(search_vector.op("@@")(tsquery))
            .order_by(rank_expr.desc())
            .limit(limit)
        )
        result = await session.execute(stmt)
        return [(row[0], row[1]) for row in result.all()]

    async def similarity_check(
        self,
        embedding: list[float],
        filters: list,
        max_distance: float,
        limit: int,
        session: AsyncSession,
    ) -> list[tuple[uuid.UUID, float]]:
        """pgvector near-duplicate check within max_distance threshold."""
        vec = _vec_literal(embedding)
        distance_expr = literal_column(f"(embedding <=> '{vec}'::vector)")

        stmt = (
            select(MemoryNode.id, distance_expr.label("distance"))
            .where(and_(*filters))
            .where(MemoryNode.embedding.isnot(None))
            .where(distance_expr <= max_distance)
            .order_by(distance_expr)
            .limit(limit)
        )
        result = await session.execute(stmt)
        return [(row[0], row[1]) for row in result.all()]

    async def graph_neighbors(
        self,
        seed_ids: list[uuid.UUID],
        max_depth: int,
        max_neighbors: int,
        session: AsyncSession,
    ) -> list[uuid.UUID]:
        """Recursive CTE graph traversal using PostgreSQL's unnest for seeds."""
        if not seed_ids:
            return []

        max_depth = min(max_depth, _MAX_DEPTH_CAP)

        sql = text(f"""
            WITH RECURSIVE neighbors AS (
                SELECT unnest(CAST(:seed_ids AS uuid[])) AS node_id, 0 AS depth

                UNION ALL

                SELECT
                    CASE
                        WHEN mr.source_id = n.node_id THEN mr.target_id
                        ELSE mr.source_id
                    END AS node_id,
                    n.depth + 1 AS depth
                FROM neighbors n
                JOIN memory_relationships mr
                    ON (mr.source_id = n.node_id OR mr.target_id = n.node_id)
                JOIN memory_nodes mn
                    ON mn.id = CASE
                        WHEN mr.source_id = n.node_id THEN mr.target_id
                        ELSE mr.source_id
                    END
                WHERE n.depth < :max_depth
                  AND mr.valid_until IS NULL
                  AND mn.deleted_at IS NULL
            )
            SELECT DISTINCT node_id
            FROM neighbors
            WHERE depth > 0
            LIMIT {_NEIGHBOR_ROW_LIMIT}
        """)

        result = await session.execute(
            sql,
            {
                "seed_ids": [str(sid) for sid in seed_ids],
                "max_depth": max_depth,
            },
        )
        rows = result.all()

        seed_set = {str(sid) for sid in seed_ids}
        neighbors = [
            uuid.UUID(str(row.node_id))
            for row in rows
            if str(row.node_id) not in seed_set
        ]
        return neighbors[:max_neighbors]
