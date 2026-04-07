"""Pytest tests for the two-vector retrieval benchmark engine.

These tests validate the engine mechanically -- they exercise the math
helpers and pipeline logic with deterministic inputs, then run a small
real-network smoke test that confirms the deployed embedding and
reranker services are reachable.

The full benchmark (40 queries × 4 pipelines × 3 conditions × weight
sweep) is invoked via `scripts/bench-two-vector.py`, not via pytest --
keeping it out of the test suite avoids long network-bound runs in
local pytest invocations.

All tests in this directory are auto-marked `perf` (see conftest.py)
and excluded from the default CI suite. Run explicitly with:

    pytest tests/perf/ -m perf -v
"""

from __future__ import annotations

import math

import pytest

from tests.perf.fixtures.queries import QUERIES
from tests.perf.fixtures.topics import TOPICS, all_memories
from tests.perf.two_vector_bench import (
    EmbeddingClient,
    Memory,
    Query,
    RerankerClient,
    aggregate,
    cosine_sim,
    evaluate_query,
    load_dataset,
    mrr,
    pipeline_baseline,
    pipeline_new1_rrf_blend,
    pipeline_new2_augmented_query,
    pipeline_new3_rerank_only,
    precision_at_k,
    rank_dict,
    recall_at_k,
    reciprocal_rank_fusion,
    relevant_ids_for_query,
)


# ── Fixture sanity ───────────────────────────────────────────────────


def test_topic_fixtures_have_50_memories_each():
    memories = all_memories()
    assert len(memories) == 200
    counts: dict[str, int] = {}
    for m in memories:
        counts[m["topic"]] = counts.get(m["topic"], 0) + 1
    for topic in TOPICS:
        assert counts[topic] == 50, f"{topic} has {counts[topic]} memories, expected 50"


def test_query_fixture_has_40_entries_with_balanced_levels():
    assert len(QUERIES) == 40
    by_topic_level: dict[tuple[str, str], int] = {}
    for q in QUERIES:
        key = (q["topic"], q["level"])
        by_topic_level[key] = by_topic_level.get(key, 0) + 1
    expected = {"specific": 4, "ambiguous": 4, "cross_topic": 2}
    for topic in TOPICS:
        for level, n in expected.items():
            assert by_topic_level[(topic, level)] == n, (
                f"{topic}/{level} has {by_topic_level[(topic, level)]}, expected {n}"
            )


def test_memory_ids_are_unique():
    seen: set[str] = set()
    for m in all_memories():
        assert m["id"] not in seen, f"duplicate id {m['id']}"
        seen.add(m["id"])


# ── Math helpers ─────────────────────────────────────────────────────


def test_cosine_sim_orthogonal_is_zero():
    a = [1.0, 0.0, 0.0]
    b = [0.0, 1.0, 0.0]
    assert cosine_sim(a, b) == 0.0


def test_cosine_sim_identical_is_one():
    a = [0.6, 0.8, 0.0]
    assert math.isclose(cosine_sim(a, a), 1.0, abs_tol=1e-9)


def test_cosine_sim_opposite_is_minus_one():
    a = [1.0, 0.0]
    b = [-1.0, 0.0]
    assert math.isclose(cosine_sim(a, b), -1.0, abs_tol=1e-9)


def test_rank_dict_assigns_one_based_ranks():
    ranks = rank_dict(["a", "b", "c"])
    assert ranks == {"a": 1, "b": 2, "c": 3}


def test_rrf_collapses_to_rank_a_when_weight_zero():
    rank_a = {"x": 1, "y": 2, "z": 3}
    rank_b = {"x": 3, "y": 2, "z": 1}  # opposite order
    blended = reciprocal_rank_fusion(rank_a, rank_b, weight_b=0.0)
    assert blended == ["x", "y", "z"]


def test_rrf_collapses_to_rank_b_when_weight_one():
    rank_a = {"x": 1, "y": 2, "z": 3}
    rank_b = {"x": 3, "y": 2, "z": 1}
    blended = reciprocal_rank_fusion(rank_a, rank_b, weight_b=1.0)
    assert blended == ["z", "y", "x"]


def test_rrf_handles_disjoint_inputs():
    rank_a = {"only_a": 1}
    rank_b = {"only_b": 1}
    blended = reciprocal_rank_fusion(rank_a, rank_b, weight_b=0.5)
    assert set(blended) == {"only_a", "only_b"}


# ── Metric helpers ───────────────────────────────────────────────────


def test_recall_at_k_full_match():
    relevant = {"a", "b", "c"}
    retrieved = ["a", "b", "c", "d"]
    assert recall_at_k(retrieved, relevant, 4) == 1.0


def test_recall_at_k_partial_match():
    relevant = {"a", "b", "c", "d", "e"}
    retrieved = ["a", "b", "x"]
    assert recall_at_k(retrieved, relevant, 3) == 2 / 5


def test_precision_at_k_partial():
    relevant = {"a", "b"}
    retrieved = ["a", "x", "y", "b"]
    assert precision_at_k(retrieved, relevant, 4) == 0.5


def test_mrr_first_position():
    relevant = {"a"}
    retrieved = ["a", "b", "c"]
    assert mrr(retrieved, relevant) == 1.0


def test_mrr_third_position():
    relevant = {"c"}
    retrieved = ["a", "b", "c"]
    assert math.isclose(mrr(retrieved, relevant), 1 / 3)


def test_mrr_no_match():
    assert mrr(["x", "y"], {"a"}) == 0.0


# ── Pipelines on a synthetic in-memory dataset ───────────────────────


def _toy_dataset() -> tuple[list[Memory], dict[str, list[float]]]:
    """Tiny hand-built dataset for unit-testing the pipelines.

    4 memories with 3-dim embeddings that point in distinct directions
    so cosine similarity is exact and predictable. Used by the pipeline
    tests below; avoids touching the network.
    """
    memories = [
        Memory(id="d0", topic="deployment", content="podman build", weight=0.9,
               embedding=[1.0, 0.0, 0.0]),
        Memory(id="m0", topic="mcp_tools", content="fastmcp tool", weight=0.9,
               embedding=[0.0, 1.0, 0.0]),
        Memory(id="u0", topic="ui", content="patternfly label", weight=0.9,
               embedding=[0.0, 0.0, 1.0]),
        Memory(id="d1", topic="deployment", content="openshift route", weight=0.85,
               embedding=[0.9, 0.1, 0.0]),
    ]
    focus_embeddings = {
        "deployment": [1.0, 0.0, 0.0],
        "mcp_tools": [0.0, 1.0, 0.0],
        "ui": [0.0, 0.0, 1.0],
        "auth": [0.0, 0.0, 0.0],  # neutral
    }
    return memories, focus_embeddings


def test_pipeline_baseline_returns_query_top_matches():
    memories, focus_embeddings = _toy_dataset()
    dataset = type("DS", (), {})()
    dataset.memories = memories
    dataset.focus_embeddings = focus_embeddings
    query = Query(
        id="q0", topic="deployment", level="specific",
        text="container deployment",
        embedding=[1.0, 0.0, 0.0],
    )
    out = pipeline_baseline(query, dataset)
    # Both deployment memories should rank above the others.
    assert out[0] == "d0"
    assert out[1] == "d1"


def test_relevant_ids_for_query_picks_topic_matches():
    memories, focus_embeddings = _toy_dataset()
    dataset = type("DS", (), {})()
    dataset.memories = memories
    dataset.focus_embeddings = focus_embeddings
    query = Query(
        id="q0", topic="deployment", level="specific",
        text="container", embedding=[1.0, 0.0, 0.0],
    )
    relevant = relevant_ids_for_query(query, dataset)
    assert relevant == {"d0", "d1"}


# ── Live network smoke test ──────────────────────────────────────────
#
# These tests actually hit the deployed services. They are tagged
# perf (via conftest auto-mark) so they only run with `-m perf`.
# Each one is short and lightweight so the cluster impact is minimal,
# but they confirm the wiring end-to-end and would catch outages or
# response-shape regressions before the full benchmark runs.


def test_embedding_service_returns_384_dim_vector():
    client = EmbeddingClient()
    try:
        emb = client.embed("podman build platform linux/amd64")
    finally:
        client.close()
    assert isinstance(emb, list)
    assert len(emb) == 384
    assert all(isinstance(x, float) for x in emb)


def test_reranker_returns_index_and_score_pairs():
    client = RerankerClient()
    try:
        result = client.rerank(
            "container deployment",
            [
                "how to deploy with podman to openshift",
                "react component patterns",
                "openshift route configuration",
            ],
        )
    finally:
        client.close()
    assert isinstance(result, list)
    assert len(result) == 3
    assert all("index" in r and "score" in r for r in result)
    # Sorted by descending score per the API contract.
    scores = [r["score"] for r in result]
    assert scores == sorted(scores, reverse=True)


def test_pipelines_run_end_to_end_on_one_query():
    """Smoke-test all four pipelines against one real query.

    This is the smallest meaningful integration test: embed a fixture
    subset, fetch the deployed reranker, and confirm each pipeline
    returns N_FINAL=10 IDs without raising.
    """
    embedder = EmbeddingClient()
    try:
        dataset = load_dataset(embedder)
    finally:
        embedder.close()

    # Pick the first specific deployment query.
    query = next(q for q in dataset.queries if q.id == "deployment-s1")

    reranker = RerankerClient()
    try:
        baseline_ids = pipeline_baseline(query, dataset)
        new3_ids = pipeline_new3_rerank_only(query, dataset, reranker)
        new1_ids = pipeline_new1_rrf_blend(
            query,
            dataset,
            dataset.focus_embeddings["deployment"],
            weight=0.4,
            reranker=reranker,
        )
        new2_ids = pipeline_new2_augmented_query(
            query,
            dataset,
            "OpenShift deployment",
            reranker,
        )
    finally:
        reranker.close()

    for label, ids in [
        ("baseline", baseline_ids),
        ("new3", new3_ids),
        ("new1", new1_ids),
        ("new2", new2_ids),
    ]:
        assert len(ids) == 10, f"{label} returned {len(ids)} ids, expected 10"
        # Specific deployment queries should rank deployment memories at the top
        # for any sane pipeline. We don't require strict ordering, just that
        # the first result is on-topic.
        first = next(m for m in dataset.memories if m.id == ids[0])
        assert first.topic == "deployment", (
            f"{label} top hit is {first.topic}, expected deployment"
        )


def test_aggregate_groups_by_pipeline_condition_weight():
    """Aggregation produces one row per (pipeline, condition, weight) combo
    and averages metrics across the queries in each group.

    Uses evaluate_query on a small slice of the live dataset so the
    aggregation logic is exercised against realistic record shapes
    without re-running the full sweep.
    """
    embedder = EmbeddingClient()
    try:
        dataset = load_dataset(embedder)
    finally:
        embedder.close()

    # Just two queries to keep the smoke test cheap.
    sample_queries = [
        next(q for q in dataset.queries if q.id == "deployment-s1"),
        next(q for q in dataset.queries if q.id == "auth-s1"),
    ]

    reranker = RerankerClient()
    try:
        runs = []
        for q in sample_queries:
            runs.extend(evaluate_query(q, dataset, reranker))
    finally:
        reranker.close()

    rows = aggregate(runs)
    pipeline_set = {r.pipeline for r in rows}
    assert pipeline_set == {"baseline", "new1", "new2", "new3"}
    # NEW-1 should produce one row per (condition, weight) combination.
    new1_rows = [r for r in rows if r.pipeline == "new1"]
    new1_keys = {(r.condition, r.weight) for r in new1_rows}
    expected = {
        ("focus_match", 0.0), ("focus_match", 0.2), ("focus_match", 0.4),
        ("focus_match", 0.6), ("focus_match", 0.8),
        ("focus_cross", 0.0), ("focus_cross", 0.2), ("focus_cross", 0.4),
        ("focus_cross", 0.6), ("focus_cross", 0.8),
    }
    assert new1_keys == expected
    for r in rows:
        assert 0.0 <= r.mean_recall_at_10 <= 1.0
        assert 0.0 <= r.mean_precision_at_10 <= 1.0
        assert 0.0 <= r.mean_mrr <= 1.0
        assert r.n_queries > 0
