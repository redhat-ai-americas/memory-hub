#!/usr/bin/env python3
"""Pool size sweep benchmark for reranker pool optimization.

Sweeps RERANK_POOL_SIZE values to measure the latency vs quality tradeoff.
Uses the same production database and services as bench-cluster-retrieval.py.

Prerequisites:
- Port-forward to memoryhub-pg: oc port-forward statefulset/memoryhub-pg 25432:5432 --context mcp-rhoai -n memoryhub-db
- Embedding service accessible at the cluster route
- Reranker service accessible at the cluster route

Usage:
    python scripts/bench-pool-sweep.py
    python scripts/bench-pool-sweep.py --pool-sizes 16,24,32,48,64
"""

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from statistics import median

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from memoryhub_core.services.memory import search_memories_with_focus
from memoryhub_core.services.embeddings import HttpEmbeddingService
from memoryhub_core.services.rerank import HttpRerankerService
import memoryhub_core.services.rerank as rerank_module
import memoryhub_core.services.memory as memory_module

logger = logging.getLogger(__name__)

DB_HOST = os.environ.get("MEMORYHUB_DB_HOST", "localhost")
DB_PORT = os.environ.get("MEMORYHUB_DB_PORT", "25432")
DB_USER = os.environ.get("MEMORYHUB_DB_USER", "memoryhub")
DB_PASS = os.environ.get("MEMORYHUB_DB_PASS", "d64c86093e57f4e94aa4740974e70ad3")
DB_NAME = os.environ.get("MEMORYHUB_DB_NAME", "memoryhub")

EMBEDDING_URL = os.environ.get(
    "MEMORYHUB_EMBEDDING_URL",
    "https://all-minilm-l6-v2-embedding-model.apps.cluster-n7pd5.n7pd5.sandbox5167.opentlc.com/embed",
)
RERANKER_URL = os.environ.get(
    "MEMORYHUB_RERANKER_URL",
    "https://ms-marco-minilm-l12-v2-reranker-model.apps.cluster-n7pd5.n7pd5.sandbox5167.opentlc.com",
)

# Diverse query set covering different retrieval patterns
SWEEP_QUERIES = [
    {"query": "FIPS compliance requirements", "description": "short factual"},
    {"query": "what authentication approach did we decide on for the MCP server", "description": "long natural"},
    {"query": "MEMORYHUB_RERANKER_URL environment variable", "description": "code/config"},
    {"query": "deployment issues", "description": "vague/broad"},
    {"query": "parmesan cheese", "description": "exact preference recall"},
    {"query": "how does the reranker work", "description": "semantic technical"},
    {"query": "memory graph relationships", "description": "semantic graph"},
    {"query": "alembic migration upgrade", "description": "CLI command"},
    {"query": "conversation thread persistence and storage", "description": "semantic threads"},
    {"query": "user preferences and behavioral memory", "description": "semantic preferences"},
]


@dataclass
class PoolSizeResult:
    pool_size: int
    query_latencies: list[float] = field(default_factory=list)
    query_top5s: list[list[str]] = field(default_factory=list)
    query_top10s: list[list[str]] = field(default_factory=list)
    avg_latency_ms: float = 0.0
    p50_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    top5_overlap: float = 0.0
    top10_overlap: float = 0.0


@dataclass
class PoolSweepResult:
    benchmark: str = "pool-sweep"
    timestamp: str = ""
    pool_sizes: list[int] = field(default_factory=list)
    config: dict = field(default_factory=dict)
    memory_count: int = 0
    results: list[PoolSizeResult] = field(default_factory=list)
    total_seconds: float = 0.0


async def run_queries_for_pool_size(
    pool_size: int,
    query_list: list[dict],
    session_factory: async_sessionmaker,
    embedding_service: HttpEmbeddingService,
    reranker: HttpRerankerService,
) -> PoolSizeResult:
    """Run all queries with a specific pool size."""
    orig_rerank = rerank_module.RERANK_POOL_SIZE
    orig_memory = memory_module.RERANK_POOL_SIZE

    rerank_module.RERANK_POOL_SIZE = pool_size
    memory_module.RERANK_POOL_SIZE = pool_size
    logger.info("Running queries with RERANK_POOL_SIZE=%d", pool_size)

    result = PoolSizeResult(pool_size=pool_size)

    try:
        for q in query_list:
            async with session_factory() as session:
                t0 = time.perf_counter()
                bundle = await search_memories_with_focus(
                    query=q["query"], session=session, embedding_service=embedding_service,
                    tenant_id="default", focus_string=q["query"], reranker=reranker,
                    max_results=10, weight_threshold=0.0, keyword_boost_weight=0.15,
                )
                latency_ms = (time.perf_counter() - t0) * 1000

            result_ids = [str(item.id) for item, _ in bundle.results]
            result.query_latencies.append(round(latency_ms, 1))
            result.query_top5s.append(result_ids[:5])
            result.query_top10s.append(result_ids[:10])

        # Aggregate stats
        lats = result.query_latencies
        result.avg_latency_ms = round(sum(lats) / len(lats), 1)
        result.p50_latency_ms = round(median(lats), 1)
        result.p95_latency_ms = round(sorted(lats)[int(len(lats) * 0.95)], 1)

    finally:
        rerank_module.RERANK_POOL_SIZE = orig_rerank
        memory_module.RERANK_POOL_SIZE = orig_memory

    return result


def compute_overlap(baseline_ids: list[str], candidate_ids: list[str]) -> float:
    """Compute overlap as fraction of baseline IDs found in candidate."""
    if not baseline_ids:
        return 1.0
    baseline_set = set(baseline_ids)
    candidate_set = set(candidate_ids)
    overlap_count = len(baseline_set & candidate_set)
    return overlap_count / len(baseline_set)


async def run_pool_sweep(pool_sizes: list[int], query_list: list[dict] | None = None) -> PoolSweepResult:
    """Run the full pool size sweep benchmark."""
    query_list = query_list or SWEEP_QUERIES
    db_url = f"postgresql+asyncpg://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

    engine = create_async_engine(db_url, pool_size=5, max_overflow=10)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    embedding_service = HttpEmbeddingService(url=EMBEDDING_URL)
    reranker = HttpRerankerService(url=RERANKER_URL)

    result = PoolSweepResult(
        timestamp=datetime.now(UTC).isoformat(), pool_sizes=pool_sizes,
        config={"embedding_url": EMBEDDING_URL, "reranker_url": RERANKER_URL, "db_host": DB_HOST, "queries": len(query_list)},
    )

    t_total = time.perf_counter()

    try:
        from sqlalchemy import text
        async with session_factory() as session:
            row = await session.execute(text("SELECT count(*) FROM memory_nodes WHERE is_current = true AND deleted_at IS NULL"))
            result.memory_count = row.scalar()

        logger.info("Running pool sweep against %d memories, pool sizes: %s", result.memory_count, pool_sizes)

        for pool_size in pool_sizes:
            pool_result = await run_queries_for_pool_size(pool_size, query_list, session_factory, embedding_service, reranker)
            result.results.append(pool_result)

        # Compute overlap with baseline (largest pool size)
        baseline = result.results[-1]
        for pool_result in result.results[:-1]:
            top5_overlaps = [compute_overlap(baseline.query_top5s[i], pool_result.query_top5s[i]) for i in range(len(query_list))]
            top10_overlaps = [compute_overlap(baseline.query_top10s[i], pool_result.query_top10s[i]) for i in range(len(query_list))]
            pool_result.top5_overlap = round(sum(top5_overlaps) / len(top5_overlaps), 3)
            pool_result.top10_overlap = round(sum(top10_overlaps) / len(top10_overlaps), 3)

        baseline.top5_overlap = 1.0
        baseline.top10_overlap = 1.0
        result.total_seconds = time.perf_counter() - t_total

    finally:
        await engine.dispose()

    return result


def main():
    parser = argparse.ArgumentParser(description="Pool size sweep benchmark")
    parser.add_argument(
        "--pool-sizes",
        type=str,
        default="16,24,32,48,64",
        help="Comma-separated pool sizes to test (default: 16,24,32,48,64)",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    pool_sizes = [int(x.strip()) for x in args.pool_sizes.split(",")]
    pool_sizes.sort()  # Ensure ascending order for baseline logic

    result = asyncio.run(run_pool_sweep(pool_sizes=pool_sizes))

    print("\n" + "=" * 100)
    print("POOL SIZE SWEEP BENCHMARK")
    print(f"Memories: {result.memory_count} | Baseline: pool={max(result.pool_sizes)}")
    print("=" * 100)
    print(f"{'Pool':>5} {'Avg ms':>8} {'p50 ms':>8} {'p95 ms':>8} "
          f"{'Top5 overlap':>13} {'Top10 overlap':>14}")
    print("-" * 100)

    for pr in result.results:
        print(f"{pr.pool_size:>5} {pr.avg_latency_ms:>8.0f} {pr.p50_latency_ms:>8.0f} "
              f"{pr.p95_latency_ms:>8.0f} {pr.top5_overlap:>13.3f} {pr.top10_overlap:>14.3f}")

    print("-" * 100)
    print(f"Total time: {result.total_seconds:.1f}s")

    # Write results
    benchmarks_dir = Path(__file__).resolve().parent.parent / "benchmarks"
    benchmarks_dir.mkdir(exist_ok=True)
    date_str = datetime.now().strftime("%Y%m%dT%H%M%SZ")
    out_path = benchmarks_dir / f"pool-sweep-{date_str}.json"
    with open(out_path, "w") as f:
        json.dump(asdict(result), f, indent=2)
    print(f"\nResults written to: {out_path}")


if __name__ == "__main__":
    main()
