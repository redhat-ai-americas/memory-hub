"""Benchmark preflight: probe deployment, emit manifest, enforce expectations.

Standalone:
    python -m memoryhub_evalhub.preflight

From adapter:
    from memoryhub_evalhub.preflight import run_preflight, enforce_manifest
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import sys
from datetime import UTC, datetime

import asyncpg
import httpx

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Signal checks
# ---------------------------------------------------------------------------


async def check_signal_vector(
    conn: asyncpg.Connection, tenant_id: str
) -> dict:
    """Check whether vector embeddings are populated for the tenant."""
    count = await conn.fetchval(
        "SELECT COUNT(*) FROM memory_nodes "
        "WHERE embedding IS NOT NULL AND tenant_id = $1",
        tenant_id,
    )
    return {"active": bool(count > 0), "node_count": count}


async def check_signal_reranker(reranker_url: str | None) -> dict:
    """Probe the reranker endpoint for availability."""
    if not reranker_url:
        return {"active": False, "reason": "MEMORYHUB_RERANKER_URL not set"}

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{reranker_url.rstrip('/')}/info", timeout=5
            )
        if resp.status_code == 200:
            return {"active": True, "url": reranker_url}
        return {
            "active": False,
            "url": reranker_url,
            "reason": f"HTTP {resp.status_code}",
        }
    except Exception as err:
        return {"active": False, "url": reranker_url, "reason": str(err)}


async def check_signal_keyword(
    conn: asyncpg.Connection, tenant_id: str
) -> dict:
    """Check search_vector column, index, and populated row count."""
    col_exists = bool(
        await conn.fetchval(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = 'memory_nodes' "
            "AND column_name = 'search_vector'"
        )
    )
    idx_exists = bool(
        await conn.fetchval(
            "SELECT 1 FROM pg_indexes "
            "WHERE tablename = 'memory_nodes' "
            "AND indexname = 'ix_memory_nodes_search_vector'"
        )
    )
    count = await conn.fetchval(
        "SELECT COUNT(*) FROM memory_nodes "
        "WHERE search_vector IS NOT NULL AND tenant_id = $1",
        tenant_id,
    )
    return {
        "active": bool(col_exists and idx_exists and count > 0),
        "column_exists": col_exists,
        "index_exists": idx_exists,
        "populated_count": count,
    }


def check_signal_focus() -> dict:
    """Focus signal -- always inactive in benchmark mode.

    The benchmark harness never calls set_focus, so there is no Valkey
    state to inspect.
    """
    return {"active": False, "reason": "benchmark does not call set_focus"}


async def check_signal_domain(
    conn: asyncpg.Connection, tenant_id: str
) -> dict:
    """Check whether any memory nodes have domain tags."""
    count = await conn.fetchval(
        "SELECT COUNT(*) FROM memory_nodes "
        "WHERE domains IS NOT NULL "
        "AND array_length(domains, 1) > 0 "
        "AND tenant_id = $1",
        tenant_id,
    )
    return {"active": bool(count > 0), "tagged_count": count}


async def check_signal_graph(
    conn: asyncpg.Connection, tenant_id: str
) -> dict:
    """Check whether graph edges exist for the tenant's nodes."""
    count = await conn.fetchval(
        "SELECT COUNT(*) FROM memory_relationships mr "
        "JOIN memory_nodes mn ON mr.source_id = mn.id "
        "WHERE mn.tenant_id = $1",
        tenant_id,
    )
    return {"active": bool(count > 0), "edge_count": count}


# ---------------------------------------------------------------------------
# Corpus snapshot
# ---------------------------------------------------------------------------


async def check_corpus(conn: asyncpg.Connection, tenant_id: str) -> dict:
    """Return a corpus size breakdown for the tenant."""
    row = await conn.fetchrow(
        "SELECT "
        "  COUNT(*) AS total, "
        "  COUNT(*) FILTER (WHERE branch_type = 'chunk') AS chunks, "
        "  COUNT(*) FILTER (WHERE branch_type IS NULL "
        "    OR branch_type != 'chunk') AS parents "
        "FROM memory_nodes WHERE tenant_id = $1",
        tenant_id,
    )
    return {
        "tenant_id": tenant_id,
        "total_nodes": row["total"],
        "parent_nodes": row["parents"],
        "chunk_nodes": row["chunks"],
    }


# ---------------------------------------------------------------------------
# Version info
# ---------------------------------------------------------------------------


def get_version_shas() -> dict:
    """Return the pipeline git SHA (or 'unknown' if git is unavailable)."""
    try:
        sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=os.path.dirname(os.path.abspath(__file__)),
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        sha = "unknown"
    return {"pipeline_sha": sha}


# ---------------------------------------------------------------------------
# Run all checks
# ---------------------------------------------------------------------------


async def run_preflight(
    db_url: str,
    tenant_id: str = "amb-benchmark",
    reranker_url: str | None = None,
) -> dict:
    """Execute all preflight checks and return the manifest dict."""
    conn = await asyncpg.connect(db_url)
    try:
        manifest = {
            "signals": {
                "vector": await check_signal_vector(conn, tenant_id),
                "reranker": await check_signal_reranker(reranker_url),
                "keyword": await check_signal_keyword(conn, tenant_id),
                "focus": check_signal_focus(),
                "domain": await check_signal_domain(conn, tenant_id),
                "graph": await check_signal_graph(conn, tenant_id),
            },
            "corpus": await check_corpus(conn, tenant_id),
            "versions": get_version_shas(),
            "timestamp": datetime.now(UTC).isoformat(),
        }
    finally:
        await conn.close()
    return manifest


# ---------------------------------------------------------------------------
# Manifest enforcement
# ---------------------------------------------------------------------------


def _compare(
    actual: object,
    expected: object,
    path: str,
    mismatches: list[str],
) -> None:
    """Recursively compare *expected* as a subset of *actual*."""
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            mismatches.append(
                f"{path}: expected dict, got {type(actual).__name__}"
            )
            return
        for key, exp_val in expected.items():
            child_path = f"{path}.{key}" if path else key
            if key not in actual:
                mismatches.append(f"{child_path}: key missing in actual")
            else:
                _compare(actual[key], exp_val, child_path, mismatches)
    else:
        if actual != expected:
            mismatches.append(
                f"{path}: expected {expected!r}, got {actual!r}"
            )


def enforce_manifest(
    actual: dict, expected: dict
) -> tuple[bool, str]:
    """Check that *actual* is a superset of *expected*.

    Returns ``(True, "")`` on success, or ``(False, diff_string)`` listing
    every mismatch.
    """
    mismatches: list[str] = []
    _compare(actual, expected, "", mismatches)
    if mismatches:
        return False, "\n".join(mismatches)
    return True, ""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_db_url() -> str:
    """Assemble a raw asyncpg-compatible DSN from environment variables."""
    host = os.environ.get("MEMORYHUB_DB_HOST", "localhost")
    port = os.environ.get("MEMORYHUB_DB_PORT", "25432")
    user = os.environ.get("MEMORYHUB_DB_USER", "memoryhub")
    password = os.environ.get("MEMORYHUB_DB_PASS", "")
    dbname = os.environ.get("MEMORYHUB_DB_NAME", "memoryhub")
    return f"postgresql://{user}:{password}@{host}:{port}/{dbname}"


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Run preflight from the command line."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Run MemoryHub benchmark preflight checks"
    )
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="Path to a YAML config file with expected_manifest",
    )
    args = parser.parse_args()

    db_url = _build_db_url()
    reranker_url = os.environ.get("MEMORYHUB_RERANKER_URL")
    tenant_id = os.environ.get("MEMORYHUB_TENANT_ID", "amb-benchmark")

    manifest = asyncio.run(
        run_preflight(db_url, tenant_id=tenant_id, reranker_url=reranker_url)
    )
    print(json.dumps(manifest, indent=2))

    if args.config:
        import yaml  # noqa: F811 -- lazy import keeps module light

        with open(args.config) as fh:
            cfg = yaml.safe_load(fh)

        expected = cfg.get("parameters", {}).get("expected_manifest")
        if expected is None:
            benchmarks = cfg.get("benchmarks", [])
            if benchmarks:
                expected = benchmarks[0].get("parameters", {}).get(
                    "expected_manifest"
                )

        if expected is None:
            print(
                "warning: --config provided but no expected_manifest found",
                file=sys.stderr,
            )
            return

        ok, diff = enforce_manifest(manifest, expected)
        if ok:
            print("preflight: manifest matches expected", file=sys.stderr)
        else:
            print(
                f"preflight: manifest mismatch\n{diff}", file=sys.stderr
            )
            sys.exit(1)


if __name__ == "__main__":
    main()
