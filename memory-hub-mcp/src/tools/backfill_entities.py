"""Admin action: backfill entity extraction on existing memories (#250)."""

import asyncio
import logging
from typing import Any

from src.tools._deps import get_db_session, get_embedding_service, release_db_session

logger = logging.getLogger(__name__)

_BACKFILL_CONCURRENCY = 2


async def backfill_entities(
    *,
    limit: int = 50,
    include_failed: bool = False,
) -> dict[str, Any]:
    """Run entity extraction on memories without extraction_status.

    Returns a summary dict with processing results.
    """
    from sqlalchemy import func, or_, select

    from memoryhub_core.models.memory import MemoryNode
    from memoryhub_core.services.extraction import extract_entities_from_memory

    session, gen = await get_db_session()
    try:
        # Count candidates
        status_conditions = [
            MemoryNode.metadata_.is_(None),
            MemoryNode.metadata_["extraction_status"].astext.is_(None),
        ]
        if include_failed:
            status_conditions.append(
                MemoryNode.metadata_["extraction_status"].astext == "failed",
            )

        base_where = [
            MemoryNode.deleted_at.is_(None),
            MemoryNode.is_current.is_(True),
            MemoryNode.scope != "entity",
            or_(*status_conditions),
        ]

        count_stmt = select(func.count()).select_from(MemoryNode).where(*base_where)
        total_candidates = (await session.execute(count_stmt)).scalar_one()

        if total_candidates == 0:
            return {
                "processed": 0,
                "succeeded": 0,
                "failed": 0,
                "entities_created": 0,
                "total_candidates": 0,
                "message": "No memories need extraction.",
            }

        # Fetch candidates
        stmt = (
            select(
                MemoryNode.id,
                MemoryNode.content,
                MemoryNode.owner_id,
                MemoryNode.tenant_id,
            )
            .where(*base_where)
            .order_by(MemoryNode.created_at.asc())
            .limit(limit)
        )
        rows = (await session.execute(stmt)).all()
    finally:
        await release_db_session(gen)

    embedding_service = get_embedding_service()
    semaphore = asyncio.Semaphore(_BACKFILL_CONCURRENCY)

    succeeded = 0
    failed = 0
    total_entities = 0

    async def process_one(row):
        nonlocal succeeded, failed, total_entities
        async with semaphore:
            sess, g = await get_db_session()
            try:
                result = await extract_entities_from_memory(
                    memory_id=row.id,
                    content=row.content,
                    session=sess,
                    embedding_service=embedding_service,
                    tenant_id=row.tenant_id,
                    owner_id=row.owner_id,
                )

                # Update status
                node_stmt = select(MemoryNode).where(MemoryNode.id == row.id)
                node = (await sess.execute(node_stmt)).scalar_one_or_none()
                if node:
                    meta = dict(node.metadata_ or {})
                    meta["extraction_status"] = "complete"
                    meta["extracted_entities"] = result.get("entities", [])
                    node.metadata_ = meta
                    await sess.commit()

                succeeded += 1
                total_entities += result["count"]
            except Exception:
                logger.warning(
                    "Backfill extraction failed for memory %s",
                    row.id, exc_info=True,
                )
                try:
                    node_stmt = select(MemoryNode).where(MemoryNode.id == row.id)
                    node = (await sess.execute(node_stmt)).scalar_one_or_none()
                    if node:
                        meta = dict(node.metadata_ or {})
                        meta["extraction_status"] = "failed"
                        node.metadata_ = meta
                        await sess.commit()
                except Exception:
                    pass
                failed += 1
            finally:
                await release_db_session(g)

    tasks = [process_one(row) for row in rows]
    await asyncio.gather(*tasks)

    return {
        "processed": len(rows),
        "succeeded": succeeded,
        "failed": failed,
        "entities_created": total_entities,
        "total_candidates": total_candidates,
        "message": (
            f"Processed {len(rows)} of {total_candidates} candidates. "
            f"{succeeded} succeeded, {failed} failed, "
            f"{total_entities} entities created."
        ),
    }
