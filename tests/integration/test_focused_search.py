"""Integration tests for search_memories_with_focus and domain-boosted search.

These tests exercise the two-vector retrieval pipeline (NEW-1) and domain
ARRAY/GIN column interactions against real PostgreSQL + pgvector. They cover
the numpy.float32 class of bug where unit tests pass but real pgvector
returns unexpected types.

Run with the compose stack active:
    podman-compose -f tests/integration/compose.yaml up -d
    pytest tests/integration/test_focused_search.py
"""

import json

import pydantic_core
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from memoryhub_core.models.schemas import MemoryNodeCreate, MemoryScope
from memoryhub_core.services.embeddings import MockEmbeddingService
from memoryhub_core.services.memory import (
    FocusedSearchResult,
)
from memoryhub_core.services.memory import (
    create_memory as _svc_create_memory,
)
from memoryhub_core.services.memory import (
    search_memories as _svc_search_memories,
)
from memoryhub_core.services.memory import (
    search_memories_with_focus as _svc_search_memories_with_focus,
)

pytestmark = pytest.mark.integration

_TEST_TENANT_ID = "default"


# -- Wrapper functions with default tenant_id --------------------------------


async def create_memory(
    data, session, embedding_service, skip_curation=False, *, tenant_id=_TEST_TENANT_ID
):
    """Test wrapper around the service create_memory with a default tenant."""
    return await _svc_create_memory(
        data, session, embedding_service, tenant_id=tenant_id, skip_curation=skip_curation,
    )


async def search_memories(
    query, session, embedding_service, *, tenant_id=_TEST_TENANT_ID, **kwargs
):
    """Test wrapper around search_memories with a default tenant."""
    return await _svc_search_memories(
        query, session, embedding_service, tenant_id=tenant_id, **kwargs,
    )


async def search_with_focus(
    query, session, embedding_service, *, tenant_id=_TEST_TENANT_ID, **kwargs
):
    """Test wrapper around search_memories_with_focus with a default tenant."""
    return await _svc_search_memories_with_focus(
        query, session, embedding_service, tenant_id=tenant_id, **kwargs,
    )


# -- Helpers -----------------------------------------------------------------


def _make(
    content: str,
    *,
    owner_id: str = "test-user",
    scope: MemoryScope = MemoryScope.USER,
    weight: float = 0.9,
    domains: list[str] | None = None,
) -> MemoryNodeCreate:
    return MemoryNodeCreate(
        content=content,
        scope=scope,
        weight=weight,
        owner_id=owner_id,
        domains=domains,
    )


def _content_set(results: list) -> set[str]:
    """Extract the set of content strings from a results list."""
    return {node.content if hasattr(node, "content") else node.stub for node, _ in results}


def _rank_of(results: list, substring: str) -> int | None:
    """Return 0-based rank of the first result whose content contains *substring*."""
    for idx, (node, _) in enumerate(results):
        text = node.content if hasattr(node, "content") else (node.stub or "")
        if substring.lower() in text.lower():
            return idx
    return None


# ---------------------------------------------------------------------------
# 1. Two-vector retrieval (search_memories_with_focus)
# ---------------------------------------------------------------------------


async def test_focus_biases_results_toward_focus_topic(
    async_session: AsyncSession,
    embedding_service: MockEmbeddingService,
) -> None:
    """Focus vector should boost memories that are close to the focus topic.

    Creates 4 memories across 2 topics and verifies that the Python-testing
    memories rank higher when the focus is set to "Python development" compared
    to a zero-focus baseline.
    """
    await create_memory(
        _make("python unit testing with pytest fixtures"), async_session, embedding_service, skip_curation=True,
    )
    await create_memory(
        _make("python test coverage measurement and reporting"), async_session, embedding_service, skip_curation=True,
    )
    await create_memory(
        _make("kubernetes deployment rolling update strategy"), async_session, embedding_service, skip_curation=True,
    )
    await create_memory(
        _make("kubernetes pod autoscaling horizontal vertical"), async_session, embedding_service, skip_curation=True,
    )

    query = "testing best practices"

    # Baseline: no focus bias.
    baseline: FocusedSearchResult = await search_with_focus(
        query, async_session, embedding_service,
        focus_string="Python development",
        session_focus_weight=0.0,
    )

    # With focus bias toward Python.
    focused: FocusedSearchResult = await search_with_focus(
        query, async_session, embedding_service,
        focus_string="Python development",
        session_focus_weight=0.4,
    )

    assert len(focused.results) > 0, "Focused search returned no results"
    assert len(baseline.results) > 0, "Baseline search returned no results"

    # Both should return the same set of memories (just reordered).
    assert _content_set(focused.results) == _content_set(baseline.results)

    # With focus on "Python development", the Python-testing memories should
    # appear in the top 2.
    for rank, (node, _) in enumerate(focused.results[:2]):
        text = node.content if hasattr(node, "content") else (node.stub or "")
        assert "python" in text.lower(), (
            f"Expected top-2 to be Python memories with focus bias, "
            f"but rank {rank} is: {text!r}"
        )


async def test_focus_zero_weight_matches_plain_search(
    async_session: AsyncSession,
    embedding_service: MockEmbeddingService,
) -> None:
    """session_focus_weight=0.0 should short-circuit to plain search_memories.

    The function explicitly falls through to search_memories when the weight
    is zero, so results and ordering must be identical.
    """
    await create_memory(
        _make("react component lifecycle hooks"), async_session, embedding_service, skip_curation=True,
    )
    await create_memory(
        _make("angular dependency injection service"), async_session, embedding_service, skip_curation=True,
    )

    query = "frontend component lifecycle"

    plain_results = await search_memories(
        query, async_session, embedding_service, max_results=10,
    )
    focused_result: FocusedSearchResult = await search_with_focus(
        query, async_session, embedding_service,
        focus_string="anything irrelevant",
        session_focus_weight=0.0,
    )

    assert len(plain_results) == len(focused_result.results), (
        f"Result count mismatch: plain={len(plain_results)}, "
        f"focused={len(focused_result.results)}"
    )

    # Content and scores should match exactly.
    for (plain_node, plain_score), (focused_node, focused_score) in zip(
        plain_results, focused_result.results, strict=True,
    ):
        plain_text = plain_node.content if hasattr(plain_node, "content") else plain_node.stub
        focused_text = focused_node.content if hasattr(focused_node, "content") else focused_node.stub
        assert plain_text == focused_text, (
            f"Ordering mismatch: plain={plain_text!r} vs focused={focused_text!r}"
        )
        assert plain_score == pytest.approx(focused_score), (
            f"Score mismatch for {plain_text!r}: plain={plain_score} vs focused={focused_score}"
        )

    # Pivot fields should not be set when focus was inactive.
    assert focused_result.pivot_suggested is False
    assert focused_result.pivot_distance is None


async def test_pivot_detection_fires_on_off_topic_query(
    async_session: AsyncSession,
    embedding_service: MockEmbeddingService,
) -> None:
    """Pivot should be suggested when the query is far from the focus topic.

    MockEmbeddingService uses word-level hashing: completely disjoint word sets
    produce near-orthogonal vectors (high cosine distance), which should exceed
    the pivot threshold.
    """
    await create_memory(
        _make("python flask web application routing"), async_session, embedding_service, skip_curation=True,
    )
    await create_memory(
        _make("python django orm database models"), async_session, embedding_service, skip_curation=True,
    )

    # Focus is about Python web frameworks; query is about something unrelated.
    result: FocusedSearchResult = await search_with_focus(
        "quantum computing qubit entanglement superposition",
        async_session, embedding_service,
        focus_string="python web framework development",
        session_focus_weight=0.4,
        # Use a low threshold so the test is robust even if mock vectors
        # aren't perfectly orthogonal.
        pivot_threshold=0.3,
    )

    assert result.pivot_suggested is True, (
        f"Expected pivot_suggested=True for off-topic query, "
        f"but got pivot_distance={result.pivot_distance}"
    )
    assert result.pivot_reason is not None
    assert result.pivot_distance is not None
    assert result.pivot_distance > 0.3


async def test_pivot_not_suggested_for_on_topic_query(
    async_session: AsyncSession,
    embedding_service: MockEmbeddingService,
) -> None:
    """Pivot should not be suggested when the query aligns with the focus.

    When the query and focus share most words, cosine distance is small and
    the pivot flag stays False.
    """
    await create_memory(
        _make("python pytest unit testing fixtures"), async_session, embedding_service, skip_curation=True,
    )

    result: FocusedSearchResult = await search_with_focus(
        "python pytest testing",
        async_session, embedding_service,
        focus_string="python pytest unit testing",
        session_focus_weight=0.4,
    )

    assert result.pivot_suggested is False, (
        f"Expected pivot_suggested=False for on-topic query, "
        f"but got pivot_distance={result.pivot_distance}"
    )


async def test_result_scores_are_real_floats(
    async_session: AsyncSession,
    embedding_service: MockEmbeddingService,
) -> None:
    """Scores must be Python float, not numpy.float32 or None.

    pgvector can return numpy scalars; the service layer must coerce them
    to native Python floats to avoid serialization failures downstream.
    """
    await create_memory(
        _make("machine learning gradient descent optimization"), async_session, embedding_service, skip_curation=True,
    )
    await create_memory(
        _make("neural network backpropagation training"), async_session, embedding_service, skip_curation=True,
    )

    result: FocusedSearchResult = await search_with_focus(
        "machine learning training",
        async_session, embedding_service,
        focus_string="deep learning neural networks",
        session_focus_weight=0.4,
    )

    assert len(result.results) > 0, "Expected at least one result"

    for idx, (_node, score) in enumerate(result.results):
        # Must be a Python float, not numpy.float32 or similar.
        assert isinstance(score, float), (
            f"Score at index {idx} is {type(score).__name__}, expected float"
        )
        assert type(score).__module__ != "numpy", (
            f"Score at index {idx} is a numpy scalar ({type(score).__name__}), "
            f"not a native Python float"
        )
        # The relevance_score in the output is 1-cosine_dist, so it's in [0,1].
        assert score >= 0.0, f"Score at index {idx} is negative: {score}"
        assert score is not None


# ---------------------------------------------------------------------------
# 2. Domain-boosted focused search
# ---------------------------------------------------------------------------


async def test_domain_boost_lifts_matching_memories(
    async_session: AsyncSession,
    embedding_service: MockEmbeddingService,
) -> None:
    """Memories tagged with a requested domain should rank higher.

    Creates frontend memories with different domain tags and verifies that
    the React-tagged memory gets boosted when domains=["React"] is passed.
    """
    # React-tagged memory.
    await create_memory(
        _make(
            "frontend component state management patterns",
            domains=["React"],
        ),
        async_session, embedding_service, skip_curation=True,
    )
    # Vue-tagged memory with overlapping content.
    await create_memory(
        _make(
            "frontend component composition and reuse patterns",
            domains=["Vue"],
        ),
        async_session, embedding_service, skip_curation=True,
    )
    # Untagged memory, also about frontend.
    await create_memory(
        _make("frontend component rendering performance optimization"),
        async_session, embedding_service, skip_curation=True,
    )

    query = "frontend component patterns"
    focus = "frontend web development"

    # Without domain boost.
    no_boost: FocusedSearchResult = await search_with_focus(
        query, async_session, embedding_service,
        focus_string=focus,
        session_focus_weight=0.4,
    )

    # With React domain boost.
    with_boost: FocusedSearchResult = await search_with_focus(
        query, async_session, embedding_service,
        focus_string=focus,
        session_focus_weight=0.4,
        domains=["React"],
        domain_boost_weight=0.3,
    )

    assert len(with_boost.results) > 0, "Domain-boosted search returned no results"

    # The React-tagged memory should be at the top when boosted.
    top_node = with_boost.results[0][0]
    top_text = top_node.content if hasattr(top_node, "content") else (top_node.stub or "")
    assert "state management" in top_text.lower(), (
        f"Expected React-tagged 'state management' memory at rank 0 with "
        f"domain boost, got: {top_text!r}"
    )

    # Verify the boost actually changed the ranking. The React memory's rank
    # in the boosted results should be <= its rank in the unboosted results.
    react_rank_boosted = _rank_of(with_boost.results, "state management")
    react_rank_plain = _rank_of(no_boost.results, "state management")
    assert react_rank_boosted is not None
    assert react_rank_plain is not None
    assert react_rank_boosted <= react_rank_plain, (
        f"Domain boost did not improve React memory rank: "
        f"boosted={react_rank_boosted}, plain={react_rank_plain}"
    )


async def test_domain_boost_zero_weight_has_no_effect(
    async_session: AsyncSession,
    embedding_service: MockEmbeddingService,
) -> None:
    """domain_boost_weight=0.0 should produce the same ranking as no domains.

    The RRF blend disables the domain signal when weight is zero, so results
    should be identical to a call without the domains parameter.
    """
    await create_memory(
        _make("backend api authentication token validation", domains=["Spring"]),
        async_session, embedding_service, skip_curation=True,
    )
    await create_memory(
        _make("backend api rate limiting middleware", domains=["Express"]),
        async_session, embedding_service, skip_curation=True,
    )

    query = "backend api security"
    focus = "backend development"

    no_domains: FocusedSearchResult = await search_with_focus(
        query, async_session, embedding_service,
        focus_string=focus,
        session_focus_weight=0.4,
    )

    zero_weight: FocusedSearchResult = await search_with_focus(
        query, async_session, embedding_service,
        focus_string=focus,
        session_focus_weight=0.4,
        domains=["Spring"],
        domain_boost_weight=0.0,
    )

    assert len(no_domains.results) == len(zero_weight.results), (
        f"Result count mismatch: no_domains={len(no_domains.results)}, "
        f"zero_weight={len(zero_weight.results)}"
    )

    for (nd_node, nd_score), (zw_node, zw_score) in zip(
        no_domains.results, zero_weight.results, strict=True,
    ):
        nd_text = nd_node.content if hasattr(nd_node, "content") else nd_node.stub
        zw_text = zw_node.content if hasattr(zw_node, "content") else zw_node.stub
        assert nd_text == zw_text, (
            f"Ordering mismatch: no_domains={nd_text!r} vs zero_weight={zw_text!r}"
        )
        assert nd_score == pytest.approx(zw_score), (
            f"Score mismatch for {nd_text!r}: "
            f"no_domains={nd_score} vs zero_weight={zw_score}"
        )


# ---------------------------------------------------------------------------
# 3. Pydantic serialization roundtrip (numpy.float32 regression guard)
# ---------------------------------------------------------------------------


async def test_focused_results_survive_pydantic_serialization(
    async_session: AsyncSession,
    embedding_service: MockEmbeddingService,
) -> None:
    """FocusedSearchResult must survive pydantic_core serialization without error.

    Regression guard for the numpy.float32 class of bug: pgvector can return
    numpy scalars that pydantic_core.to_jsonable_python cannot serialize, causing
    a downstream crash in the MCP tool layer. The service must coerce all scores
    to native Python types before returning.
    """
    await create_memory(
        _make("distributed tracing opentelemetry instrumentation"),
        async_session, embedding_service, skip_curation=True,
    )
    await create_memory(
        _make("observability metrics prometheus grafana dashboards"),
        async_session, embedding_service, skip_curation=True,
    )

    result: FocusedSearchResult = await search_with_focus(
        "distributed systems observability",
        async_session, embedding_service,
        focus_string="cloud native monitoring",
        session_focus_weight=0.4,
    )

    assert len(result.results) > 0, "Expected at least one result for serialization test"

    # Build the response dict that mimics what the MCP tool returns.
    response = {
        "results": [
            {
                "content": node.content if hasattr(node, "content") else node.stub,
                "relevance_score": score,
                "id": str(node.id),
                "scope": node.scope,
                "weight": node.weight,
            }
            for node, score in result.results
        ],
        "pivot_suggested": result.pivot_suggested,
        "pivot_distance": result.pivot_distance,
        "pivot_threshold": result.pivot_threshold,
        "pivot_reason": result.pivot_reason,
    }

    # pydantic_core.to_jsonable_python must not raise — this is the step that
    # fails when scores are numpy.float32 instead of native Python floats.
    try:
        serialized = pydantic_core.to_jsonable_python(response)
    except Exception as exc:  # noqa: BLE001
        raise AssertionError(
            f"pydantic_core.to_jsonable_python raised {type(exc).__name__}: {exc}\n"
            f"Score types: {[(type(score).__name__, type(score).__module__) for _, score in result.results]}"
        ) from exc

    # json.dumps catches any remaining non-serializable types that slipped through.
    try:
        json_str = json.dumps(serialized)
    except (TypeError, ValueError) as exc:
        raise AssertionError(
            f"json.dumps raised {type(exc).__name__}: {exc}\n"
            f"serialized={serialized!r}"
        ) from exc

    # Verify the round-tripped data has the expected structure.
    round_tripped = json.loads(json_str)
    assert "results" in round_tripped, "Serialized response missing 'results' key"
    assert isinstance(round_tripped["results"], list), "'results' must be a list"
    assert len(round_tripped["results"]) == len(result.results), (
        f"Round-tripped result count {len(round_tripped['results'])} "
        f"!= original {len(result.results)}"
    )

    for idx, item in enumerate(round_tripped["results"]):
        assert "content" in item, f"Result {idx} missing 'content'"
        assert "relevance_score" in item, f"Result {idx} missing 'relevance_score'"
        assert isinstance(item["relevance_score"], (int, float)), (
            f"Result {idx} relevance_score is {type(item['relevance_score']).__name__}, "
            f"expected int or float after JSON round-trip"
        )

    assert "pivot_suggested" in round_tripped, "Serialized response missing 'pivot_suggested'"


# ---------------------------------------------------------------------------
# 4. Campaign-scoped search with domain boosting
# ---------------------------------------------------------------------------


async def test_campaign_scoped_search_with_domain_boost(
    async_session: AsyncSession,
    embedding_service: MockEmbeddingService,
) -> None:
    """Campaign-scoped memories with domains should be retrievable with domain boosting.

    Creates campaign-scoped memories tagged with frontend domains, then
    searches with domain boost parameters to verify that campaign memories
    are found and the domain boost reorders results correctly.

    Campaign memories use owner_id as the campaign UUID and require
    campaign_ids to be passed for visibility.
    """
    campaign_id = "campaign-frontend-2026"

    # Campaign memory tagged with React + TypeScript.
    await create_memory(
        _make(
            "campaign react typescript component architecture patterns",
            owner_id=campaign_id,
            scope=MemoryScope.CAMPAIGN,
            weight=0.85,
            domains=["React", "TypeScript"],
        ),
        async_session, embedding_service, skip_curation=True,
    )
    # Campaign memory tagged with Vue + TypeScript.
    await create_memory(
        _make(
            "campaign vue typescript composition api best practices",
            owner_id=campaign_id,
            scope=MemoryScope.CAMPAIGN,
            weight=0.85,
            domains=["Vue", "TypeScript"],
        ),
        async_session, embedding_service, skip_curation=True,
    )
    # Campaign memory with no domain tags.
    await create_memory(
        _make(
            "campaign frontend performance optimization strategies",
            owner_id=campaign_id,
            scope=MemoryScope.CAMPAIGN,
            weight=0.85,
        ),
        async_session, embedding_service, skip_curation=True,
    )

    query = "frontend component patterns typescript"
    focus = "frontend web development"

    # Campaign memories require authorized_scopes with campaign_ids to be visible.
    auth_scopes = {"campaign": None}

    # Search WITHOUT domain boost.
    no_boost: FocusedSearchResult = await search_with_focus(
        query, async_session, embedding_service,
        focus_string=focus,
        session_focus_weight=0.4,
        authorized_scopes=auth_scopes,
        campaign_ids={campaign_id},
    )

    # Search WITH React domain boost.
    with_boost: FocusedSearchResult = await search_with_focus(
        query, async_session, embedding_service,
        focus_string=focus,
        session_focus_weight=0.4,
        authorized_scopes=auth_scopes,
        campaign_ids={campaign_id},
        domains=["React"],
        domain_boost_weight=0.3,
    )

    assert len(no_boost.results) > 0, "Campaign search returned no results without boost"
    assert len(with_boost.results) > 0, "Campaign search returned no results with boost"

    # Same memories should be returned regardless of boost.
    assert _content_set(no_boost.results) == _content_set(with_boost.results), (
        "Domain boost changed the result set instead of just reordering"
    )

    # The React-tagged campaign memory should be at the top when boosted.
    top_node = with_boost.results[0][0]
    top_text = top_node.content if hasattr(top_node, "content") else (top_node.stub or "")
    assert "react" in top_text.lower(), (
        f"Expected React-tagged campaign memory at rank 0 with domain boost, "
        f"got: {top_text!r}"
    )

    # Verify the React memory's rank improved (or stayed at top) with the boost.
    react_rank_boosted = _rank_of(with_boost.results, "react")
    react_rank_plain = _rank_of(no_boost.results, "react")
    assert react_rank_boosted is not None, "React memory missing from boosted results"
    assert react_rank_plain is not None, "React memory missing from plain results"
    assert react_rank_boosted <= react_rank_plain, (
        f"Domain boost did not improve React campaign memory rank: "
        f"boosted={react_rank_boosted}, plain={react_rank_plain}"
    )


async def test_campaign_memories_invisible_without_campaign_ids(
    async_session: AsyncSession,
    embedding_service: MockEmbeddingService,
) -> None:
    """Campaign-scoped memories are invisible when campaign_ids is not provided.

    This verifies the authorization gate: even when authorized_scopes includes
    'campaign', the search returns nothing if campaign_ids is empty.
    """
    campaign_id = "campaign-invisible-test"

    await create_memory(
        _make(
            "campaign secret architecture decision records",
            owner_id=campaign_id,
            scope=MemoryScope.CAMPAIGN,
            weight=0.9,
            domains=["React"],
        ),
        async_session, embedding_service, skip_curation=True,
    )

    # Search with campaign scope authorized but no campaign_ids.
    results = await search_memories(
        "architecture decision records",
        async_session, embedding_service,
        authorized_scopes={"campaign": None},
        # campaign_ids intentionally omitted
    )

    assert len(results) == 0, (
        f"Expected no results without campaign_ids, got {len(results)}: "
        f"{[n.content if hasattr(n, 'content') else n.stub for n, _ in results]}"
    )
