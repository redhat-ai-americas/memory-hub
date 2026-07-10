#!/usr/bin/env python3
"""LongMemEval benchmark for MemoryHub (#304).

Adapts the LongMemEval dataset (ICLR 2025) to evaluate MemoryHub's
retrieval quality. Each chat session is ingested as a memory node,
then questions are used as search queries. We measure whether the
relevant evidence sessions appear in the top-k results.

Metrics: Recall@k (k=5,10), MRR at the session level.

Requires:
- LongMemEval dataset: download from HuggingFace
- Running PostgreSQL+pgvector instance

Usage:
    # Download dataset first
    mkdir -p data/longmemeval
    wget -P data/longmemeval https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/resolve/main/longmemeval_oracle.json

    # Run benchmark (oracle variant is fastest)
    python scripts/bench-longmemeval.py --variant oracle
    python scripts/bench-longmemeval.py --variant s --max-questions 50
"""

import argparse
import asyncio
import dataclasses
import json
import logging
import os
import random
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from statistics import median

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from memoryhub_core.models.memory import MemoryNode
from memoryhub_core.services.memory import search_memories, search_memories_with_focus
from tests.perf.metrics import mrr, recall_at_k

logger = logging.getLogger(__name__)

DB_HOST = os.environ.get("MEMORYHUB_DB_HOST", "localhost")
DB_PORT = os.environ.get("MEMORYHUB_DB_PORT", "15433")
DB_NAME = os.environ.get("MEMORYHUB_DB_NAME", "memoryhub_bench")
DB_USER = os.environ.get("MEMORYHUB_DB_USER", "memoryhub")
DB_PASS = os.environ.get("MEMORYHUB_DB_PASS", "memoryhub")
EMBEDDING_DIM = 384

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "longmemeval"

VARIANT_FILES = {
    "oracle": "longmemeval_oracle.json",
    "s": "longmemeval_s_cleaned.json",
    "m": "longmemeval_m_cleaned.json",
}


class MockEmbeddingForBench:
    """Deterministic embedding from text hash (same as retrieval_scale_bench)."""

    async def embed(self, text_input: str) -> list[float]:
        rng = random.Random(text_input)
        vec = [rng.gauss(0, 1) for _ in range(EMBEDDING_DIM)]
        norm = sum(x * x for x in vec) ** 0.5
        return [x / norm for x in vec]


def _session_to_text(session_turns: list[dict]) -> str:
    """Flatten a chat session's turns into a single text block."""
    parts = []
    for turn in session_turns:
        role = turn.get("role", "unknown")
        content = turn.get("content", "")
        parts.append(f"{role}: {content}")
    return "\n".join(parts)


@dataclass
class QuestionResult:
    question_id: str
    question_type: str
    recall_at_5: float
    recall_at_10: float
    mrr_score: float
    latency_ms: float


@dataclass
class LongMemEvalResult:
    benchmark: str = "longmemeval"
    variant: str = ""
    timestamp: str = ""
    config: dict = field(default_factory=dict)
    total_questions: int = 0
    avg_recall_at_5: float = 0.0
    avg_recall_at_10: float = 0.0
    avg_mrr: float = 0.0
    avg_latency_ms: float = 0.0
    by_type: dict = field(default_factory=dict)
    total_seconds: float = 0.0


async def run_longmemeval_benchmark(
    variant: str = "oracle",
    max_questions: int | None = None,
    db_url: str | None = None,
    use_keyword: bool = True,
) -> LongMemEvalResult:
    """Run LongMemEval against MemoryHub retrieval."""
    data_file = DATA_DIR / VARIANT_FILES[variant]
    if not data_file.exists():
        raise FileNotFoundError(
            f"Dataset not found at {data_file}. Download from "
            "https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned"
        )

    with open(data_file) as f:
        dataset = json.load(f)

    if max_questions:
        dataset = dataset[:max_questions]

    if db_url is None:
        db_url = (
            f"postgresql+asyncpg://{DB_USER}:{DB_PASS}"
            f"@{DB_HOST}:{DB_PORT}/{DB_NAME}"
        )

    engine = create_async_engine(db_url, pool_size=5, max_overflow=10)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    embedding_service = MockEmbeddingForBench()

    t_total = time.perf_counter()

    try:
        async with engine.begin() as conn:
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            await conn.execute(text('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"'))
            await conn.run_sync(
                MemoryNode.metadata.create_all,
                tables=[MemoryNode.__table__],
            )

        question_results: list[QuestionResult] = []

        for q_idx, entry in enumerate(dataset):
            question_id = entry["question_id"]
            question = entry["question"]
            question_type = entry["question_type"]
            answer_session_ids = set(entry.get("answer_session_ids", []))
            sessions = entry.get("haystack_sessions", [])
            session_ids = entry.get("haystack_session_ids", [])

            tenant_id = f"lme-{question_id}"

            # Ingest each session as a memory node
            async with session_factory() as db_session:
                session_id_to_node: dict[str, str] = {}
                for sid, turns in zip(session_ids, sessions):
                    content = _session_to_text(turns)
                    if not content.strip():
                        continue
                    node_id = uuid.uuid5(uuid.NAMESPACE_DNS, f"{tenant_id}-{sid}")
                    embedding = await embedding_service.embed(content[:2000])
                    node = MemoryNode(
                        id=node_id,
                        content=content[:10000],
                        stub=content[:200],
                        scope="user",
                        owner_id="lme-user",
                        tenant_id=tenant_id,
                        weight=0.7,
                        embedding=embedding,
                        content_type="experiential",
                    )
                    db_session.add(node)
                    session_id_to_node[str(sid)] = str(node_id)
                await db_session.commit()

            # Search for the question
            relevant_node_ids = {
                session_id_to_node[str(sid)]
                for sid in answer_session_ids
                if str(sid) in session_id_to_node
            }

            async with session_factory() as db_session:
                t0 = time.perf_counter()
                if use_keyword:
                    result = await search_memories_with_focus(
                        query=question,
                        session=db_session,
                        embedding_service=embedding_service,
                        tenant_id=tenant_id,
                        focus_string="chat history recall",
                        owner_id="lme-user",
                        max_results=10,
                        weight_threshold=0.0,
                        keyword_boost_weight=0.15,
                    )
                    retrieved = [str(item.id) for item, _ in result.results]
                else:
                    results = await search_memories(
                        query=question,
                        session=db_session,
                        embedding_service=embedding_service,
                        tenant_id=tenant_id,
                        owner_id="lme-user",
                        max_results=10,
                        weight_threshold=0.0,
                    )
                    retrieved = [str(item.id) for item, _ in results]
                latency_ms = (time.perf_counter() - t0) * 1000

            qr = QuestionResult(
                question_id=question_id,
                question_type=question_type,
                recall_at_5=recall_at_k(retrieved, relevant_node_ids, 5),
                recall_at_10=recall_at_k(retrieved, relevant_node_ids, 10),
                mrr_score=mrr(retrieved, relevant_node_ids),
                latency_ms=latency_ms,
            )
            question_results.append(qr)

            if (q_idx + 1) % 25 == 0:
                logger.info("Processed %d/%d questions", q_idx + 1, len(dataset))

        # Aggregate results
        by_type: dict[str, dict] = {}
        for qr in question_results:
            if qr.question_type not in by_type:
                by_type[qr.question_type] = {
                    "count": 0, "recall_at_5": [], "recall_at_10": [], "mrr": [],
                }
            bt = by_type[qr.question_type]
            bt["count"] += 1
            bt["recall_at_5"].append(qr.recall_at_5)
            bt["recall_at_10"].append(qr.recall_at_10)
            bt["mrr"].append(qr.mrr_score)

        for bt in by_type.values():
            n = bt["count"]
            bt["avg_recall_at_5"] = sum(bt["recall_at_5"]) / n
            bt["avg_recall_at_10"] = sum(bt["recall_at_10"]) / n
            bt["avg_mrr"] = sum(bt["mrr"]) / n
            del bt["recall_at_5"], bt["recall_at_10"], bt["mrr"]

        all_r5 = [qr.recall_at_5 for qr in question_results]
        all_r10 = [qr.recall_at_10 for qr in question_results]
        all_mrr = [qr.mrr_score for qr in question_results]
        all_lat = [qr.latency_ms for qr in question_results]
        n = len(question_results)

        return LongMemEvalResult(
            variant=variant,
            timestamp=datetime.now(UTC).isoformat(),
            config={
                "variant": variant,
                "max_questions": max_questions,
                "use_keyword": use_keyword,
                "total_sessions_ingested": sum(
                    len(e.get("haystack_sessions", [])) for e in dataset
                ),
            },
            total_questions=n,
            avg_recall_at_5=sum(all_r5) / n if n else 0,
            avg_recall_at_10=sum(all_r10) / n if n else 0,
            avg_mrr=sum(all_mrr) / n if n else 0,
            avg_latency_ms=sum(all_lat) / n if n else 0,
            by_type=by_type,
            total_seconds=time.perf_counter() - t_total,
        )
    finally:
        await engine.dispose()


def main():
    parser = argparse.ArgumentParser(description="LongMemEval benchmark for MemoryHub (#304)")
    parser.add_argument(
        "--variant", choices=["oracle", "s", "m"], default="oracle",
        help="Dataset variant (default: oracle)",
    )
    parser.add_argument("--max-questions", type=int, default=None)
    parser.add_argument("--db-url", type=str, default=None)
    parser.add_argument("--no-keyword", action="store_true", help="Disable keyword search")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    result = asyncio.run(
        run_longmemeval_benchmark(
            variant=args.variant,
            max_questions=args.max_questions,
            db_url=args.db_url,
            use_keyword=not args.no_keyword,
        )
    )

    print("\n" + "=" * 70)
    print(f"LONGMEMEVAL BENCHMARK ({result.variant.upper()})")
    print("=" * 70)
    print(f"Questions: {result.total_questions}")
    print(f"Recall@5:  {result.avg_recall_at_5:.3f}")
    print(f"Recall@10: {result.avg_recall_at_10:.3f}")
    print(f"MRR:       {result.avg_mrr:.3f}")
    print(f"Avg latency: {result.avg_latency_ms:.1f}ms")
    print(f"\nBy question type:")
    for qt, stats in sorted(result.by_type.items()):
        print(f"  {qt:30s} n={stats['count']:3d}  R@5={stats['avg_recall_at_5']:.3f}  "
              f"R@10={stats['avg_recall_at_10']:.3f}  MRR={stats['avg_mrr']:.3f}")
    print(f"\nTotal time: {result.total_seconds:.1f}s")

    benchmarks_dir = Path(__file__).resolve().parent.parent / "benchmarks"
    benchmarks_dir.mkdir(exist_ok=True)
    date_str = datetime.now().strftime("%Y%m%dT%H%M%SZ")
    out_path = benchmarks_dir / f"longmemeval-{result.variant}-{date_str}.json"

    with open(out_path, "w") as f:
        json.dump(dataclasses.asdict(result), f, indent=2)
    print(f"\nResults written to: {out_path}")


if __name__ == "__main__":
    main()
