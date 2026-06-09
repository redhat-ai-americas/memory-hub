#!/usr/bin/env python3
"""Backfill entity extraction on existing memories (#250).

Runs the full 3-stage extraction cascade (spaCy + GLiNER + LLM) on
memories that have no extraction_status or whose extraction failed.
Dry-run by default; pass --execute to process.

Connection settings are read from MEMORYHUB_DB_* environment variables.
LLM settings come from MEMORYHUB_LLM_EXTRACTION_URL and
MEMORYHUB_LLM_EXTRACTION_MODEL (same as the extraction pipeline).

Usage:
    # Dry run -- show candidates
    python scripts/backfill-entities.py

    # Execute with port-forwarded DB and LLM
    oc port-forward svc/memoryhub-pg 5432:5432 -n memoryhub-db --context mcp-rhoai &
    oc port-forward svc/gpt-oss-20b 8000:80 -n gpt-oss-model --context mcp-rhoai &

    MEMORYHUB_LLM_EXTRACTION_URL=http://localhost:8000 \\
    MEMORYHUB_LLM_EXTRACTION_MODEL=RedHatAI/gpt-oss-20b \\
    python scripts/backfill-entities.py --execute --concurrency 2

    # Test with a small batch first
    python scripts/backfill-entities.py --execute --limit 5 --verbose
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

sys.path.insert(0, ".")

from memoryhub_core.config import DatabaseSettings
from memoryhub_core.models.memory import MemoryNode
from memoryhub_core.services.embeddings import MockEmbeddingService
from memoryhub_core.services.extraction import extract_entities_from_memory


def _candidate_filter(include_failed: bool):
    """Build WHERE clauses for backfill candidates."""
    conditions = [
        MemoryNode.deleted_at.is_(None),
        MemoryNode.is_current.is_(True),
        MemoryNode.scope != "entity",
    ]

    status_conditions = [
        MemoryNode.metadata_.is_(None),
        MemoryNode.metadata_["extraction_status"].astext.is_(None),
    ]
    if include_failed:
        status_conditions.append(
            MemoryNode.metadata_["extraction_status"].astext == "failed",
        )

    conditions.append(or_(*status_conditions))
    return conditions


async def count_candidates(
    session: AsyncSession, include_failed: bool,
) -> int:
    """Count memories eligible for backfill."""
    conditions = _candidate_filter(include_failed)
    stmt = select(func.count()).select_from(MemoryNode).where(*conditions)
    result = await session.execute(stmt)
    return result.scalar_one()


async def count_total(session: AsyncSession) -> int:
    """Count all non-deleted memories."""
    result = await session.execute(
        select(func.count())
        .select_from(MemoryNode)
        .where(MemoryNode.deleted_at.is_(None)),
    )
    return result.scalar_one()


async def count_already_extracted(session: AsyncSession) -> int:
    """Count memories with extraction_status = 'complete'."""
    result = await session.execute(
        select(func.count())
        .select_from(MemoryNode)
        .where(
            MemoryNode.deleted_at.is_(None),
            MemoryNode.metadata_["extraction_status"].astext == "complete",
        ),
    )
    return result.scalar_one()


async def scan(
    session: AsyncSession,
    include_failed: bool,
    limit: int | None = None,
) -> list[dict]:
    """Fetch backfill candidate rows."""
    conditions = _candidate_filter(include_failed)
    stmt = (
        select(
            MemoryNode.id,
            MemoryNode.content,
            MemoryNode.stub,
            MemoryNode.owner_id,
            MemoryNode.tenant_id,
            MemoryNode.scope,
            MemoryNode.created_at,
            MemoryNode.metadata_,
        )
        .where(*conditions)
        .order_by(MemoryNode.created_at.asc())
    )
    if limit:
        stmt = stmt.limit(limit)

    result = await session.execute(stmt)
    return [
        {
            "id": row.id,
            "content": row.content,
            "stub": row.stub,
            "owner_id": row.owner_id,
            "tenant_id": row.tenant_id,
            "scope": row.scope,
            "created_at": row.created_at,
            "metadata": row.metadata_,
        }
        for row in result.all()
    ]


async def update_extraction_status(
    session: AsyncSession,
    memory_id,
    status: str,
    entities: list[dict] | None = None,
) -> None:
    """Update extraction_status in a memory's metadata."""
    stmt = select(MemoryNode).where(MemoryNode.id == memory_id)
    result = await session.execute(stmt)
    node = result.scalar_one_or_none()
    if node is None:
        return

    meta = dict(node.metadata_ or {})
    meta["extraction_status"] = status
    if entities is not None:
        meta["extracted_entities"] = entities
    node.metadata_ = meta
    await session.commit()


async def process_one(
    row: dict,
    session_factory: async_sessionmaker,
    embedding_service,
    semaphore: asyncio.Semaphore,
    index: int,
    total: int,
    verbose: bool,
) -> dict:
    """Extract entities from a single memory. Returns result summary."""
    async with semaphore:
        memory_id = row["id"]
        short_id = str(memory_id)[:8]

        async with session_factory() as session:
            await update_extraction_status(session, memory_id, "pending")

        try:
            async with session_factory() as session:
                result = await extract_entities_from_memory(
                    memory_id=memory_id,
                    content=row["content"],
                    session=session,
                    embedding_service=embedding_service,
                    tenant_id=row["tenant_id"],
                    owner_id=row["owner_id"],
                )

            async with session_factory() as session:
                await update_extraction_status(
                    session, memory_id, "complete",
                    result.get("entities", []),
                )

            count = result["count"]
            extractors = {e["extractor"] for e in result.get("entities", [])}
            extractor_str = "+".join(sorted(extractors)) if extractors else "none"

            stub = (row["stub"] or row["content"][:50] or "(empty)")[:60]
            print(f"  [{index}/{total}] {short_id}... {count} entities ({extractor_str}) -- {stub}")

            if verbose and result.get("entities"):
                for e in result["entities"]:
                    print(f"         {e['type']:12s} {e['name']} ({e['extractor']})")

            return {"status": "ok", "count": count}

        except Exception as exc:
            print(f"  [{index}/{total}] {short_id}... FAILED: {exc}")
            try:
                async with session_factory() as session:
                    await update_extraction_status(session, memory_id, "failed")
            except Exception:
                pass
            return {"status": "failed", "count": 0}


async def main(args: argparse.Namespace) -> int:
    settings = DatabaseSettings()
    engine = create_async_engine(settings.async_url, echo=False)
    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False,
    )

    llm_url = os.environ.get("MEMORYHUB_LLM_EXTRACTION_URL", "")
    llm_model = os.environ.get("MEMORYHUB_LLM_EXTRACTION_MODEL", "")

    async with session_factory() as session:
        total = await count_total(session)
        already = await count_already_extracted(session)
        candidates = await count_candidates(session, args.include_failed)

    print(f"Database: {settings.host}:{settings.port}/{settings.name}")
    print(f"Total active memories: {total}")
    print(f"Already extracted: {already}")
    print(f"Backfill candidates: {candidates}")
    if llm_url:
        print(f"LLM endpoint: {llm_url} ({llm_model})")
    else:
        print("LLM endpoint: not configured (Stage 3 will be skipped)")
    print()

    if candidates == 0:
        print("Nothing to backfill.")
        await engine.dispose()
        return 0

    async with session_factory() as session:
        rows = await scan(session, args.include_failed, args.limit)

    if not args.execute:
        print(f"Candidates (showing {len(rows)}):")
        for row in rows:
            stub = (row["stub"] or "(no stub)")[:70]
            created = row["created_at"].isoformat() if row["created_at"] else "?"
            print(f"  [{row['owner_id']}] {stub}  ({created})")
        print()
        print("Dry run -- no changes made. Pass --execute to process.")
        await engine.dispose()
        return 0

    print(f"Processing {len(rows)} memories (concurrency={args.concurrency})...")
    print()

    embedding_service = MockEmbeddingService()
    semaphore = asyncio.Semaphore(args.concurrency)
    start = time.monotonic()

    tasks = [
        process_one(
            row, session_factory, embedding_service, semaphore,
            i + 1, len(rows), args.verbose,
        )
        for i, row in enumerate(rows)
    ]
    results = await asyncio.gather(*tasks)

    elapsed = time.monotonic() - start
    succeeded = sum(1 for r in results if r["status"] == "ok")
    failed = sum(1 for r in results if r["status"] == "failed")
    total_entities = sum(r["count"] for r in results)

    print()
    print(f"Done in {elapsed:.1f}s")
    print(f"  Processed: {len(results)}")
    print(f"  Succeeded: {succeeded}")
    print(f"  Failed:    {failed}")
    print(f"  Entities:  {total_entities}")

    await engine.dispose()
    return 1 if failed > 0 else 0


def cli():
    parser = argparse.ArgumentParser(
        description="Backfill entity extraction on existing memories.",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually run extraction (default is dry-run)",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=2,
        help="Max concurrent extractions (default: 2)",
    )
    parser.add_argument(
        "--include-failed",
        action="store_true",
        help="Re-process memories with extraction_status='failed'",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print entity details for each memory",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Process at most N memories",
    )
    args = parser.parse_args()
    sys.exit(asyncio.run(main(args)))


if __name__ == "__main__":
    cli()
