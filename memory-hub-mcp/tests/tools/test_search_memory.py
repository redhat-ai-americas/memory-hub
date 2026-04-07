"""Tests for search_memory tool."""

import inspect
from unittest.mock import AsyncMock, patch

import pytest

import src.tools.auth as auth_mod
from src.tools.search_memory import search_memory


def test_search_memory_is_importable():
    """Verify the tool module imports and the decorated function exists."""
    assert search_memory is not None
    assert callable(search_memory)


def test_search_memory_has_required_parameters():
    """Verify query is required and optional params have defaults."""
    sig = inspect.signature(search_memory)
    params = sig.parameters

    assert "query" in params
    assert "scope" in params
    assert "owner_id" in params
    assert "max_results" in params
    assert "weight_threshold" in params
    assert "current_only" in params
    assert "ctx" in params

    # query has no default -- it is required
    assert params["query"].default is inspect.Parameter.empty
    # optional params have defaults
    assert params["scope"].default is None
    assert params["max_results"].default == 10
    assert params["weight_threshold"].default == 0.0
    assert params["current_only"].default is True


@pytest.mark.asyncio
async def test_search_memory_rejects_empty_query():
    """Calling with an empty query should raise ToolError."""
    from fastmcp.exceptions import ToolError

    ctx = AsyncMock()
    with pytest.raises(ToolError, match="Query cannot be empty"):
        await search_memory(query="   ", ctx=ctx)


@pytest.mark.asyncio
async def test_search_memory_rejects_invalid_scope():
    """Calling with an invalid scope should raise ToolError."""
    from fastmcp.exceptions import ToolError

    ctx = AsyncMock()
    with pytest.raises(ToolError, match="Invalid scope filter"):
        await search_memory(query="test query", scope="invalid_scope", ctx=ctx)


def _fake_search_result(stub: str, weight: float):
    """Build a (MemoryNodeStub, score) tuple for use as a fake search result."""
    import uuid as _uuid

    from memoryhub.models.schemas import MemoryNodeStub, MemoryScope

    return (
        MemoryNodeStub(
            id=_uuid.uuid4(),
            stub=stub,
            scope=MemoryScope.USER,
            weight=weight,
            branch_type=None,
            has_children=False,
            has_rationale=False,
        ),
        0.9,
    )


def _fake_full_result(
    content: str,
    weight: float = 0.9,
    score: float = 0.9,
    *,
    parent_id=None,
    branch_type: str | None = None,
    node_id=None,
    has_rationale: bool = False,
    has_children: bool = False,
):
    """Build a (MemoryNodeRead, score) tuple for use as a fake full search result.

    Used by the #56/#57 tests that need to assert against full content,
    branch handling, and mode/budget degradation behavior.
    """
    import uuid as _uuid
    from datetime import datetime, timezone

    from memoryhub.models.schemas import MemoryNodeRead, MemoryScope, StorageType

    return (
        MemoryNodeRead(
            id=node_id or _uuid.uuid4(),
            parent_id=parent_id,
            content=content,
            stub=content[:80],
            storage_type=StorageType.INLINE,
            content_ref=None,
            weight=weight,
            scope=MemoryScope.USER,
            branch_type=branch_type,
            owner_id="wjackson",
            is_current=True,
            version=1,
            previous_version_id=None,
            metadata=None,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            expires_at=None,
            has_children=has_children,
            has_rationale=has_rationale,
            branch_count=1 if has_children or has_rationale else 0,
        ),
        score,
    )


def _patched_search_call(page_results, total_matching, **call_kwargs):
    """Helper that wires up the patches needed to call search_memory with
    canned service-layer results. Returns the awaited tool result.

    Sets the session globals before the call and tears them down after,
    so test bodies stay focused on the assertions.
    """
    return _PatchedSearchCall(page_results, total_matching, call_kwargs)


class _PatchedSearchCall:
    def __init__(self, page_results, total_matching, call_kwargs):
        self.page_results = page_results
        self.total_matching = total_matching
        self.call_kwargs = call_kwargs

    async def run(self):
        mock_session = AsyncMock()
        mock_gen = AsyncMock()
        fake_embedding_service = AsyncMock()

        auth_mod._current_session = {
            "user_id": "wjackson",
            "scopes": ["user"],
            "identity_type": "user",
        }
        try:
            with (
                patch(
                    "src.tools.search_memory.get_db_session",
                    return_value=(mock_session, mock_gen),
                ),
                patch(
                    "src.tools.search_memory.release_db_session",
                    new_callable=AsyncMock,
                ),
                patch(
                    "src.tools.search_memory.get_embedding_service",
                    return_value=fake_embedding_service,
                ),
                patch(
                    "src.tools.search_memory.search_memories",
                    new_callable=AsyncMock,
                    return_value=self.page_results,
                ),
                patch(
                    "src.tools.search_memory.count_search_matches",
                    new_callable=AsyncMock,
                    return_value=self.total_matching,
                ),
            ):
                return await search_memory(query="memory", **self.call_kwargs)
        finally:
            auth_mod._current_session = None


@pytest.mark.asyncio
async def test_search_memory_has_more_when_paginated():
    """Regression for #53: total_matching > page size must surface as has_more.

    Issues a search with max_results=2 against 5 fake matches and asserts
    has_more=true and total_matching=5.
    """
    mock_session = AsyncMock()
    mock_gen = AsyncMock()
    fake_embedding_service = AsyncMock()
    page_results = [
        _fake_search_result("first match", 0.5),
        _fake_search_result("second match", 0.4),
    ]

    auth_mod._current_session = {
        "user_id": "wjackson",
        "scopes": ["user"],
        "identity_type": "user",
    }
    try:
        with (
            patch("src.tools.search_memory.get_db_session", return_value=(mock_session, mock_gen)),
            patch("src.tools.search_memory.release_db_session", new_callable=AsyncMock),
            patch("src.tools.search_memory.get_embedding_service", return_value=fake_embedding_service),
            patch(
                "src.tools.search_memory.search_memories",
                new_callable=AsyncMock,
                return_value=page_results,
            ),
            patch(
                "src.tools.search_memory.count_search_matches",
                new_callable=AsyncMock,
                return_value=5,
            ),
        ):
            result = await search_memory(query="memory", max_results=2)
    finally:
        auth_mod._current_session = None

    assert result["total_matching"] == 5
    assert result["has_more"] is True
    assert len(result["results"]) == 2
    assert "total_accessible" not in result


@pytest.mark.asyncio
async def test_search_memory_has_more_false_when_page_holds_all():
    """When the page contains every match, has_more must be false."""
    mock_session = AsyncMock()
    mock_gen = AsyncMock()
    fake_embedding_service = AsyncMock()
    page_results = [_fake_search_result("only match", 0.5)]

    auth_mod._current_session = {
        "user_id": "wjackson",
        "scopes": ["user"],
        "identity_type": "user",
    }
    try:
        with (
            patch("src.tools.search_memory.get_db_session", return_value=(mock_session, mock_gen)),
            patch("src.tools.search_memory.release_db_session", new_callable=AsyncMock),
            patch("src.tools.search_memory.get_embedding_service", return_value=fake_embedding_service),
            patch(
                "src.tools.search_memory.search_memories",
                new_callable=AsyncMock,
                return_value=page_results,
            ),
            patch(
                "src.tools.search_memory.count_search_matches",
                new_callable=AsyncMock,
                return_value=1,
            ),
        ):
            result = await search_memory(query="memory", max_results=10)
    finally:
        auth_mod._current_session = None

    assert result["total_matching"] == 1
    assert result["has_more"] is False
    assert len(result["results"]) == 1


@pytest.mark.asyncio
async def test_search_memory_empty_returns_zero_total():
    """Empty results must still emit total_matching and has_more=False."""
    mock_session = AsyncMock()
    mock_gen = AsyncMock()
    fake_embedding_service = AsyncMock()

    auth_mod._current_session = {
        "user_id": "wjackson",
        "scopes": ["user"],
        "identity_type": "user",
    }
    try:
        with (
            patch("src.tools.search_memory.get_db_session", return_value=(mock_session, mock_gen)),
            patch("src.tools.search_memory.release_db_session", new_callable=AsyncMock),
            patch("src.tools.search_memory.get_embedding_service", return_value=fake_embedding_service),
            patch(
                "src.tools.search_memory.search_memories",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "src.tools.search_memory.count_search_matches",
                new_callable=AsyncMock,
                return_value=0,
            ),
        ):
            result = await search_memory(query="nothing")
    finally:
        auth_mod._current_session = None

    assert result["results"] == []
    assert result["total_matching"] == 0
    assert result["has_more"] is False


# ---------------------------------------------------------------------------
# #56 — branch handling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_memory_omits_branch_when_parent_in_results():
    """Default behavior: a branch whose parent is also in the result set is
    dropped from the page. The agent uses has_rationale to drill in."""
    parent, parent_score = _fake_full_result(
        "Use Podman, not Docker", has_rationale=True
    )
    branch, branch_score = _fake_full_result(
        "Rationale: Podman is daemonless and rootless by default",
        parent_id=parent.id,
        branch_type="rationale",
    )
    result = await _patched_search_call(
        page_results=[(parent, parent_score), (branch, branch_score)],
        total_matching=2,
    ).run()

    assert len(result["results"]) == 1
    assert result["results"][0]["id"] == str(parent.id)
    # The dropped branch did not turn into total_matching being incorrect.
    assert result["total_matching"] == 2


@pytest.mark.asyncio
async def test_search_memory_keeps_orphan_branch_as_top_level():
    """A branch whose parent is NOT in the result set surfaces as a top-level
    entry regardless of include_branches. parent_id stays populated so the
    agent can read_memory the parent if it cares."""
    import uuid as _uuid

    orphan_parent_id = _uuid.uuid4()
    branch, branch_score = _fake_full_result(
        "Rationale: Podman is daemonless",
        parent_id=orphan_parent_id,
        branch_type="rationale",
    )
    result = await _patched_search_call(
        page_results=[(branch, branch_score)],
        total_matching=1,
    ).run()

    assert len(result["results"]) == 1
    assert result["results"][0]["id"] == str(branch.id)
    assert result["results"][0]["parent_id"] == str(orphan_parent_id)


@pytest.mark.asyncio
async def test_search_memory_include_branches_nests_under_parent():
    """include_branches=True nests branches under their parent in a 'branches'
    field rather than ranking them as top-level siblings."""
    parent, parent_score = _fake_full_result(
        "Use Podman, not Docker", has_rationale=True
    )
    branch1, branch1_score = _fake_full_result(
        "Rationale: daemonless",
        parent_id=parent.id,
        branch_type="rationale",
        score=0.85,
    )
    branch2, branch2_score = _fake_full_result(
        "Provenance: team standard since 2024",
        parent_id=parent.id,
        branch_type="provenance",
        score=0.6,
    )
    result = await _patched_search_call(
        page_results=[
            (parent, parent_score),
            (branch1, branch1_score),
            (branch2, branch2_score),
        ],
        total_matching=3,
        include_branches=True,
    ).run()

    assert len(result["results"]) == 1
    parent_entry = result["results"][0]
    assert parent_entry["id"] == str(parent.id)
    assert "branches" in parent_entry
    assert len(parent_entry["branches"]) == 2
    branch_types = {b["branch_type"] for b in parent_entry["branches"]}
    assert branch_types == {"rationale", "provenance"}


@pytest.mark.asyncio
async def test_search_memory_default_does_not_emit_branches_field():
    """When include_branches=False (default), entries do NOT carry a 'branches'
    key — keeping the response shape stable for callers that don't opt in."""
    parent, parent_score = _fake_full_result("plain memory")
    result = await _patched_search_call(
        page_results=[(parent, parent_score)],
        total_matching=1,
    ).run()

    assert "branches" not in result["results"][0]


# ---------------------------------------------------------------------------
# #57 — mode and token-budget
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_memory_mode_index_stubs_everything():
    """mode='index' converts every full result to a stub, including high-weight
    results that mode='full' would have returned in full."""
    full1, score1 = _fake_full_result("first full memory", weight=0.95)
    full2, score2 = _fake_full_result("second full memory", weight=0.95)
    result = await _patched_search_call(
        page_results=[(full1, score1), (full2, score2)],
        total_matching=2,
        mode="index",
    ).run()

    assert len(result["results"]) == 2
    for entry in result["results"]:
        assert entry["result_type"] == "stub"
        # stub form does not carry full content
        assert "content" not in entry


@pytest.mark.asyncio
async def test_search_memory_mode_full_only_overrides_weight_threshold():
    """mode='full_only' must NOT pass the caller's weight_threshold through to
    the service layer — everything stays full regardless."""
    captured: dict = {}

    full_high, score_high = _fake_full_result("important", weight=0.9)
    full_low, score_low = _fake_full_result("low priority", weight=0.2)

    async def fake_search(*, weight_threshold, **kwargs):
        captured["weight_threshold"] = weight_threshold
        return [(full_high, score_high), (full_low, score_low)]

    mock_session = AsyncMock()
    mock_gen = AsyncMock()
    fake_embedding_service = AsyncMock()

    auth_mod._current_session = {
        "user_id": "wjackson",
        "scopes": ["user"],
        "identity_type": "user",
    }
    try:
        with (
            patch(
                "src.tools.search_memory.get_db_session",
                return_value=(mock_session, mock_gen),
            ),
            patch(
                "src.tools.search_memory.release_db_session", new_callable=AsyncMock
            ),
            patch(
                "src.tools.search_memory.get_embedding_service",
                return_value=fake_embedding_service,
            ),
            patch(
                "src.tools.search_memory.search_memories",
                new_callable=AsyncMock,
                side_effect=fake_search,
            ),
            patch(
                "src.tools.search_memory.count_search_matches",
                new_callable=AsyncMock,
                return_value=2,
            ),
        ):
            result = await search_memory(
                query="memory",
                weight_threshold=0.8,
                mode="full_only",
            )
    finally:
        auth_mod._current_session = None

    assert captured["weight_threshold"] == 0.0
    assert all(entry["result_type"] == "full" for entry in result["results"])


@pytest.mark.asyncio
async def test_search_memory_mode_full_passes_weight_threshold_through():
    """mode='full' (default) honors the caller's weight_threshold."""
    captured: dict = {}

    async def fake_search(*, weight_threshold, **kwargs):
        captured["weight_threshold"] = weight_threshold
        return []

    mock_session = AsyncMock()
    mock_gen = AsyncMock()
    fake_embedding_service = AsyncMock()

    auth_mod._current_session = {
        "user_id": "wjackson",
        "scopes": ["user"],
        "identity_type": "user",
    }
    try:
        with (
            patch(
                "src.tools.search_memory.get_db_session",
                return_value=(mock_session, mock_gen),
            ),
            patch(
                "src.tools.search_memory.release_db_session", new_callable=AsyncMock
            ),
            patch(
                "src.tools.search_memory.get_embedding_service",
                return_value=fake_embedding_service,
            ),
            patch(
                "src.tools.search_memory.search_memories",
                new_callable=AsyncMock,
                side_effect=fake_search,
            ),
            patch(
                "src.tools.search_memory.count_search_matches",
                new_callable=AsyncMock,
                return_value=0,
            ),
        ):
            await search_memory(query="memory", weight_threshold=0.7, mode="full")
    finally:
        auth_mod._current_session = None

    assert captured["weight_threshold"] == 0.7


@pytest.mark.asyncio
async def test_search_memory_token_budget_degrades_remainder_to_stub():
    """When the running token cost exceeds max_response_tokens, the offending
    entry and all subsequent entries are degraded to stub form. Earlier entries
    that fit the budget stay as full content."""
    # Three big-content full results. We compute the actual estimated cost of
    # one entry via the production helper, then size the budget to fit exactly
    # one and overflow on the second. This stays robust to JSON-overhead drift.
    from src.tools.search_memory import _format_entry, _estimate_tokens

    big_content = "x" * 4000
    full1, score1 = _fake_full_result(big_content, weight=0.9, score=0.95)
    full2, score2 = _fake_full_result(big_content, weight=0.9, score=0.85)
    full3, score3 = _fake_full_result(big_content, weight=0.9, score=0.75)

    one_entry_cost = _format_entry(full1, score1, [])[1]
    # Budget that fits exactly one full entry but not a second.
    budget = one_entry_cost + (one_entry_cost // 2)
    assert budget < 2 * one_entry_cost  # sanity: second entry must overflow

    result = await _patched_search_call(
        page_results=[(full1, score1), (full2, score2), (full3, score3)],
        total_matching=3,
        max_response_tokens=budget,
    ).run()

    assert len(result["results"]) == 3
    # First entry fits and stays full
    assert result["results"][0]["result_type"] == "full"
    # Subsequent entries are degraded to stub
    assert result["results"][1]["result_type"] == "stub"
    assert result["results"][2]["result_type"] == "stub"
    # And content is gone from the degraded entries
    assert "content" not in result["results"][1]
    assert "content" not in result["results"][2]


@pytest.mark.asyncio
async def test_search_memory_token_budget_keeps_all_full_when_room():
    """With a generous budget, every full result stays full."""
    full1, score1 = _fake_full_result("short", weight=0.9)
    full2, score2 = _fake_full_result("also short", weight=0.9)

    result = await _patched_search_call(
        page_results=[(full1, score1), (full2, score2)],
        total_matching=2,
        max_response_tokens=4000,
    ).run()

    assert len(result["results"]) == 2
    assert all(entry["result_type"] == "full" for entry in result["results"])


@pytest.mark.asyncio
async def test_search_memory_new_parameters_have_defaults():
    """Verify the new mode/include_branches/max_response_tokens parameters
    have the expected defaults."""
    sig = inspect.signature(search_memory)
    params = sig.parameters

    assert "mode" in params
    assert params["mode"].default == "full"
    assert "include_branches" in params
    assert params["include_branches"].default is False
    assert "max_response_tokens" in params
    assert params["max_response_tokens"].default == 4000
