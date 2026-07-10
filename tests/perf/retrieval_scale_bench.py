"""Retrieval-at-scale benchmark engine (#271).

Measures pgvector search latency and relevance as the tenant memory count
grows across 100, 1K, and 10K scale tiers. Generates synthetic corpora
with topic-labeled ground truth, seeds them into a real PostgreSQL+pgvector
database, runs search queries, and computes p50/p95/p99 latency plus
recall@10/precision@10/MRR relevance metrics.

Requires a running PostgreSQL+pgvector instance. Connection is configured
via environment variables (see DEFAULTS below).

Usage:
    from tests.perf.retrieval_scale_bench import run_scale_benchmark
    results = await run_scale_benchmark(scales=[100, 1000])
"""

from __future__ import annotations

import logging
import os
import random
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from statistics import median

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from memoryhub_core.models.memory import MemoryNode
from memoryhub_core.services.memory import search_memories, search_memories_with_focus
from tests.perf.metrics import mrr, precision_at_k, recall_at_k

logger = logging.getLogger(__name__)

DB_HOST = os.environ.get("MEMORYHUB_DB_HOST", "localhost")
DB_PORT = os.environ.get("MEMORYHUB_DB_PORT", "15433")
DB_NAME = os.environ.get("MEMORYHUB_DB_NAME", "memoryhub_bench")
DB_USER = os.environ.get("MEMORYHUB_DB_USER", "memoryhub")
DB_PASS = os.environ.get("MEMORYHUB_DB_PASS", "memoryhub")
EMBEDDING_DIM = 384

TOPICS = [
    "kubernetes-deployment",
    "python-testing",
    "react-frontend",
    "database-optimization",
    "authentication-security",
    "ci-cd-pipelines",
    "api-design",
    "monitoring-observability",
]

TOPIC_TEMPLATES: dict[str, list[str]] = {
    "kubernetes-deployment": [
        "Use kubectl apply -f {name}.yaml to deploy the {name} service",
        "Set resource limits: CPU {cpu}m, memory {mem}Mi for {name}",
        "The {name} deployment requires a PVC with {size}Gi storage",
        "Rolling update strategy: maxSurge=1, maxUnavailable=0 for {name}",
        "Configure liveness probe on /healthz for {name} with 30s timeout",
    ],
    "python-testing": [
        "Use pytest fixtures for {name} test setup and teardown",
        "Mock the {name} service with unittest.mock.AsyncMock",
        "Test coverage for {name} module should exceed 80%",
        "Use parametrize for {name} edge cases: empty, null, boundary",
        "Integration tests for {name} require the test database fixture",
    ],
    "react-frontend": [
        "The {name} component uses useState for local state management",
        "Apply CSS modules for {name} styling to avoid class collisions",
        "Use React.memo on {name} to prevent unnecessary re-renders",
        "The {name} form validates with react-hook-form and zod schema",
        "Lazy load the {name} route with React.lazy and Suspense",
    ],
    "database-optimization": [
        "Add a composite index on ({col1}, {col2}) for the {name} query",
        "Use EXPLAIN ANALYZE to check the {name} query plan",
        "Partition the {name} table by {col1} for better query performance",
        "Connection pool size for {name}: min=5, max=20 per replica",
        "Vacuum the {name} table weekly to reclaim dead tuple space",
    ],
    "authentication-security": [
        "JWT tokens for {name} expire after 15 minutes",
        "Use bcrypt with cost factor 12 for {name} password hashing",
        "RBAC policy: {name} requires the {role} role for access",
        "OAuth 2.1 client_credentials flow for {name} service-to-service auth",
        "Rotate the {name} signing key every 90 days via key ceremony",
    ],
    "ci-cd-pipelines": [
        "The {name} pipeline runs on every push to main branch",
        "Stage gate: {name} must pass unit tests before integration tests",
        "Build cache for {name}: use layer caching to speed up container builds",
        "Deploy {name} to staging first, then promote to production after soak",
        "Rollback strategy for {name}: keep last 3 revisions in OpenShift",
    ],
    "api-design": [
        "The {name} endpoint accepts JSON with Content-Type application/json",
        "Use pagination with cursor-based {name} list endpoint, limit=50",
        "Rate limit {name} API to 100 requests per minute per client",
        "Version the {name} API via URL prefix /v1/ for stability",
        "Return 422 Unprocessable Entity for {name} validation failures",
    ],
    "monitoring-observability": [
        "Export {name} metrics on /metrics in Prometheus format",
        "Set up alerting: {name} error rate > 5% triggers PagerDuty",
        "Trace {name} requests with OpenTelemetry span context propagation",
        "Dashboard for {name}: p50/p95/p99 latency, error rate, throughput",
        "Log {name} audit events as structured JSON to stdout",
    ],
}

FILLER_NAMES = [
    "user-service", "order-api", "auth-gateway", "payment-processor",
    "notification-hub", "inventory-manager", "search-engine", "cache-layer",
    "message-queue", "config-server", "api-gateway", "data-pipeline",
    "ml-inference", "file-storage", "scheduler", "webhook-relay",
]


def _generate_memory(topic: str, idx: int) -> dict:
    """Generate a synthetic memory for a topic with deterministic content."""
    rng = random.Random(f"{topic}-{idx}")
    templates = TOPIC_TEMPLATES[topic]
    template = templates[idx % len(templates)]
    name = FILLER_NAMES[idx % len(FILLER_NAMES)]
    content = template.format(
        name=name,
        cpu=rng.choice([100, 250, 500, 1000]),
        mem=rng.choice([128, 256, 512, 1024]),
        size=rng.choice([1, 5, 10, 50]),
        col1=rng.choice(["tenant_id", "created_at", "owner_id", "scope"]),
        col2=rng.choice(["status", "type", "priority", "category"]),
        role=rng.choice(["admin", "editor", "viewer", "operator"]),
    )
    weight = round(rng.uniform(0.3, 1.0), 2)
    return {
        "id": f"{topic}-{idx:05d}",
        "topic": topic,
        "content": content,
        "weight": weight,
    }


def generate_corpus(scale: int) -> list[dict]:
    """Generate a corpus of `scale` memories evenly distributed across topics."""
    per_topic = scale // len(TOPICS)
    remainder = scale % len(TOPICS)
    corpus = []
    for i, topic in enumerate(TOPICS):
        count = per_topic + (1 if i < remainder else 0)
        for idx in range(count):
            corpus.append(_generate_memory(topic, idx))
    return corpus


BENCHMARK_QUERIES = [
    {"query": "kubectl apply deployment", "relevant_topic": "kubernetes-deployment"},
    {"query": "resource limits CPU memory", "relevant_topic": "kubernetes-deployment"},
    {"query": "pytest fixtures test setup", "relevant_topic": "python-testing"},
    {"query": "test coverage module", "relevant_topic": "python-testing"},
    {"query": "React useState component state", "relevant_topic": "react-frontend"},
    {"query": "CSS modules styling", "relevant_topic": "react-frontend"},
    {"query": "composite index query optimization", "relevant_topic": "database-optimization"},
    {"query": "connection pool size", "relevant_topic": "database-optimization"},
    {"query": "JWT token expiration", "relevant_topic": "authentication-security"},
    {"query": "OAuth client_credentials", "relevant_topic": "authentication-security"},
    {"query": "pipeline runs on push", "relevant_topic": "ci-cd-pipelines"},
    {"query": "container build cache", "relevant_topic": "ci-cd-pipelines"},
    {"query": "pagination cursor-based endpoint", "relevant_topic": "api-design"},
    {"query": "rate limit API requests", "relevant_topic": "api-design"},
    {"query": "Prometheus metrics endpoint", "relevant_topic": "monitoring-observability"},
    {"query": "OpenTelemetry tracing spans", "relevant_topic": "monitoring-observability"},
]


class MockEmbeddingForBench:
    """Deterministic embedding service for benchmarks.

    Uses a hash-based approach to produce consistent 384-dim embeddings
    from text, so the same query always gets the same vector. Not
    semantically meaningful, but stable for latency measurement.
    """

    async def embed(self, text_input: str) -> list[float]:
        rng = random.Random(text_input)
        vec = [rng.gauss(0, 1) for _ in range(EMBEDDING_DIM)]
        norm = sum(x * x for x in vec) ** 0.5
        return [x / norm for x in vec]


@dataclass
class ScaleTierResult:
    """Results for a single scale tier (e.g., 100 memories)."""
    scale: int
    seed_time_s: float = 0.0
    queries: int = 0
    latency_p50_ms: float = 0.0
    latency_p95_ms: float = 0.0
    latency_p99_ms: float = 0.0
    recall_at_10: float = 0.0
    precision_at_10: float = 0.0
    mrr_score: float = 0.0
    keyword_recall_at_10: float = 0.0
    keyword_precision_at_10: float = 0.0
    keyword_mrr_score: float = 0.0


@dataclass
class BenchmarkResult:
    """Full benchmark output."""
    benchmark: str = "retrieval-scale"
    timestamp: str = ""
    config: dict = field(default_factory=dict)
    tiers: list[ScaleTierResult] = field(default_factory=list)
    total_seconds: float = 0.0


async def _seed_corpus(
    corpus: list[dict],
    session: AsyncSession,
    embedding_service: MockEmbeddingForBench,
    tenant_id: str,
) -> float:
    """Insert corpus into the database. Returns time in seconds."""
    t0 = time.perf_counter()
    for mem in corpus:
        embedding = await embedding_service.embed(mem["content"])
        node = MemoryNode(
            id=uuid.uuid5(uuid.NAMESPACE_DNS, f"{tenant_id}-{mem['id']}"),
            content=mem["content"],
            stub=mem["content"][:100],
            scope="user",
            owner_id="bench-user",
            tenant_id=tenant_id,
            weight=mem["weight"],
            embedding=embedding,
            content_type="experiential",
        )
        session.add(node)
    await session.flush()
    return time.perf_counter() - t0


async def _run_queries(
    queries: list[dict],
    corpus: list[dict],
    session: AsyncSession,
    embedding_service: MockEmbeddingForBench,
    tenant_id: str,
    use_keyword: bool = False,
) -> ScaleTierResult:
    """Run queries and collect latency + relevance metrics."""
    latencies: list[float] = []
    recalls: list[float] = []
    precisions: list[float] = []
    mrrs: list[float] = []

    for q in queries:
        relevant_ids = {
            str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{tenant_id}-{m['id']}"))
            for m in corpus
            if m["topic"] == q["relevant_topic"]
        }

        t0 = time.perf_counter()
        if use_keyword:
            result = await search_memories_with_focus(
                query=q["query"],
                session=session,
                embedding_service=embedding_service,
                tenant_id=tenant_id,
                focus_string=q["relevant_topic"].replace("-", " "),
                owner_id="bench-user",
                max_results=10,
                weight_threshold=0.0,
                keyword_boost_weight=0.15,
            )
            retrieved = [str(item.id) for item, _ in result.results]
        else:
            results = await search_memories(
                query=q["query"],
                session=session,
                embedding_service=embedding_service,
                tenant_id=tenant_id,
                owner_id="bench-user",
                max_results=10,
                weight_threshold=0.0,
            )
            retrieved = [str(item.id) for item, _ in results]
        elapsed_ms = (time.perf_counter() - t0) * 1000
        latencies.append(elapsed_ms)

        recalls.append(recall_at_k(retrieved, relevant_ids, 10))
        precisions.append(precision_at_k(retrieved, relevant_ids, 10))
        mrrs.append(mrr(retrieved, relevant_ids))

    latencies.sort()
    n = len(latencies)
    return ScaleTierResult(
        scale=0,  # caller sets this
        queries=len(queries),
        latency_p50_ms=latencies[n // 2] if n else 0,
        latency_p95_ms=latencies[int(n * 0.95)] if n else 0,
        latency_p99_ms=latencies[int(n * 0.99)] if n else 0,
        recall_at_10=sum(recalls) / len(recalls) if recalls else 0,
        precision_at_10=sum(precisions) / len(precisions) if precisions else 0,
        mrr_score=sum(mrrs) / len(mrrs) if mrrs else 0,
    )


async def run_scale_benchmark(
    scales: Sequence[int] = (100, 1000, 10000),
    runs_per_scale: int = 3,
    db_url: str | None = None,
) -> BenchmarkResult:
    """Run the full retrieval-at-scale benchmark.

    Creates a fresh tenant per scale tier, seeds the corpus, runs queries
    multiple times, and reports the median metrics across runs.
    """
    if db_url is None:
        db_url = (
            f"postgresql+asyncpg://{DB_USER}:{DB_PASS}"
            f"@{DB_HOST}:{DB_PORT}/{DB_NAME}"
        )

    engine = create_async_engine(db_url, pool_size=5, max_overflow=10)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    embedding_service = MockEmbeddingForBench()
    result = BenchmarkResult(
        timestamp=datetime.now(UTC).isoformat(),
        config={
            "scales": list(scales),
            "runs_per_scale": runs_per_scale,
            "queries": len(BENCHMARK_QUERIES),
            "topics": len(TOPICS),
            "db_host": DB_HOST,
            "db_port": DB_PORT,
        },
    )

    t_total = time.perf_counter()

    try:
        # Ensure pgvector extension and tables exist
        async with engine.begin() as conn:
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS \"uuid-ossp\""))
            await conn.run_sync(
                MemoryNode.metadata.create_all,
                tables=[MemoryNode.__table__],
            )

        for scale in scales:
            logger.info("Starting scale tier: %d memories", scale)
            tenant_id = f"bench-{scale}-{uuid.uuid4().hex[:8]}"
            corpus = generate_corpus(scale)

            async with session_factory() as session:
                seed_time = await _seed_corpus(corpus, session, embedding_service, tenant_id)
                await session.commit()

            # Run queries multiple times for stability
            tier_runs: list[ScaleTierResult] = []
            keyword_runs: list[ScaleTierResult] = []
            for run_idx in range(runs_per_scale):
                async with session_factory() as session:
                    tier = await _run_queries(
                        BENCHMARK_QUERIES, corpus, session, embedding_service, tenant_id,
                    )
                    tier.scale = scale
                    tier.seed_time_s = seed_time
                    tier_runs.append(tier)

                    kw_tier = await _run_queries(
                        BENCHMARK_QUERIES, corpus, session, embedding_service, tenant_id,
                        use_keyword=True,
                    )
                    keyword_runs.append(kw_tier)

            # Take median across runs
            best = ScaleTierResult(
                scale=scale,
                seed_time_s=seed_time,
                queries=len(BENCHMARK_QUERIES),
                latency_p50_ms=median(r.latency_p50_ms for r in tier_runs),
                latency_p95_ms=median(r.latency_p95_ms for r in tier_runs),
                latency_p99_ms=median(r.latency_p99_ms for r in tier_runs),
                recall_at_10=median(r.recall_at_10 for r in tier_runs),
                precision_at_10=median(r.precision_at_10 for r in tier_runs),
                mrr_score=median(r.mrr_score for r in tier_runs),
                keyword_recall_at_10=median(r.recall_at_10 for r in keyword_runs),
                keyword_precision_at_10=median(r.precision_at_10 for r in keyword_runs),
                keyword_mrr_score=median(r.mrr_score for r in keyword_runs),
            )
            result.tiers.append(best)
            logger.info(
                "Scale %d: p50=%.1fms, recall@10=%.3f, kw_recall@10=%.3f",
                scale, best.latency_p50_ms, best.recall_at_10, best.keyword_recall_at_10,
            )

        result.total_seconds = time.perf_counter() - t_total
    finally:
        await engine.dispose()

    return result
