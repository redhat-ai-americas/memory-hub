#!/usr/bin/env python3
"""Soft-delete test data from the MemoryHub database.

Identifies test data by:
  1. Content starting with "[test]" (SDK integration test convention)
  2. Owner IDs matching known test patterns

By default runs in dry-run mode (reports what would be deleted). Pass
--execute to perform the actual soft-delete.

Connection settings are read from MEMORYHUB_DB_* environment variables
(same as alembic and the MCP server).

Usage:
    # Dry run against local compose DB
    MEMORYHUB_DB_PORT=15433 python scripts/cleanup-test-data.py

    # Execute against cluster (port-forward first)
    oc port-forward svc/memoryhub-pg 5432:5432 -n memoryhub-db &
    MEMORYHUB_DB_PASSWORD=<secret> python scripts/cleanup-test-data.py --execute

    # Show what would be deleted, with full content
    python scripts/cleanup-test-data.py --verbose
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Add the project root to sys.path so memoryhub_core is importable.
sys.path.insert(0, ".")

from memoryhub_core.config import DatabaseSettings
from memoryhub_core.models.memory import MemoryNode

# ---------------------------------------------------------------------------
# Test data identification patterns
# ---------------------------------------------------------------------------

# Content prefix used by SDK integration tests (test_rbac_live.py etc.)
TEST_CONTENT_PREFIX = "[test]"

# Owner IDs created by integration test fixtures. These are patterns — any
# owner_id containing one of these substrings is considered test data.
TEST_OWNER_PATTERNS = [
    "test-user",
    "dup-test-user",
    "similarity-score-test",
    "seed-test-user",
    "rollback-test-user",
    "session-reuse-test",
    "domain-test-user",
    "near-dup-user",
    "similarity-direct-test",
    "seed-idempotency-user",
    "multi-domain-user",
    "e2e-test",
]


def _build_test_data_filter():
    """Build a SQLAlchemy WHERE clause matching test data patterns."""
    conditions = [
        # Content-based: SDK integration tests prefix with [test]
        MemoryNode.content.ilike(f"{TEST_CONTENT_PREFIX}%"),
        # Stub-based: stubs mirror content, catch truncated matches
        MemoryNode.stub.ilike(f"{TEST_CONTENT_PREFIX}%"),
    ]
    # Owner-based: exact match on known test owner_ids
    for pattern in TEST_OWNER_PATTERNS:
        conditions.append(MemoryNode.owner_id == pattern)

    return conditions


async def scan(session: AsyncSession, verbose: bool = False) -> list[dict]:
    """Find all test data rows that are not yet soft-deleted."""
    from sqlalchemy import or_

    conditions = _build_test_data_filter()
    stmt = (
        select(
            MemoryNode.id,
            MemoryNode.content,
            MemoryNode.stub,
            MemoryNode.owner_id,
            MemoryNode.tenant_id,
            MemoryNode.scope,
            MemoryNode.created_at,
        )
        .where(
            MemoryNode.deleted_at.is_(None),
            or_(*conditions),
        )
        .order_by(MemoryNode.created_at.desc())
    )
    result = await session.execute(stmt)
    rows = result.all()

    matches = []
    for row in rows:
        entry = {
            "id": str(row.id),
            "owner_id": row.owner_id,
            "tenant_id": row.tenant_id,
            "scope": row.scope,
            "created_at": row.created_at.isoformat() if row.created_at else "?",
            "stub": row.stub[:80] if row.stub else "(no stub)",
        }
        if verbose:
            entry["content"] = row.content[:200] if row.content else "(no content)"
        matches.append(entry)

    return matches


async def soft_delete(session: AsyncSession) -> int:
    """Soft-delete all matching test data. Returns count of affected rows."""
    from sqlalchemy import or_

    conditions = _build_test_data_filter()
    now = datetime.now(UTC)

    result = await session.execute(
        update(MemoryNode)
        .where(
            MemoryNode.deleted_at.is_(None),
            or_(*conditions),
        )
        .values(deleted_at=now, is_current=False)
    )
    await session.commit()
    return result.rowcount


async def count_total(session: AsyncSession) -> int:
    """Count all non-deleted memories for context."""
    result = await session.execute(
        select(func.count()).select_from(MemoryNode).where(MemoryNode.deleted_at.is_(None))
    )
    return result.scalar_one()


async def main(args: argparse.Namespace) -> int:
    settings = DatabaseSettings()
    engine = create_async_engine(settings.async_url, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as session:
        total = await count_total(session)
        matches = await scan(session, verbose=args.verbose)

        print(f"Database: {settings.host}:{settings.port}/{settings.name}")
        print(f"Total active memories: {total}")
        print(f"Test data found: {len(matches)}")
        print()

        if not matches:
            print("No test data to clean up.")
            await engine.dispose()
            return 0

        for entry in matches:
            owner = entry["owner_id"]
            stub = entry["stub"]
            created = entry["created_at"]
            print(f"  [{owner}] {stub}  ({created})")
            if args.verbose and "content" in entry:
                print(f"    content: {entry['content']}")

        print()

        if args.execute:
            count = await soft_delete(session)
            print(f"Soft-deleted {count} rows.")
        else:
            print("Dry run — no changes made. Pass --execute to delete.")

    await engine.dispose()
    return 0


def cli():
    parser = argparse.ArgumentParser(
        description="Soft-delete test data from the MemoryHub database.",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually perform the soft-delete (default is dry-run)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show full content of matched rows",
    )
    args = parser.parse_args()
    sys.exit(asyncio.run(main(args)))


if __name__ == "__main__":
    cli()
