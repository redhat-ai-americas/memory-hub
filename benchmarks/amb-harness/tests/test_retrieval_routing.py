from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from memoryhub.models import Memory

from memory_bench.memory.memoryhub import MemoryHubProvider


PATCH_TARGET = "memory_bench.memory.memoryhub.MemoryHubClient"


def _make_memory(id: str, content: str = "content", source: str = "agent") -> Memory:
    return Memory(id=id, content=content, source=source, weight=0.7)


def _make_search_result(memories: list[Memory]) -> MagicMock:
    result = MagicMock()
    result.results = memories
    return result


def _make_retrieval_client() -> AsyncMock:
    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    return client


# ---- Split routing ----


@patch(PATCH_TARGET)
async def test_split_mode_makes_two_searches(MockClient, provider):
    provider._routing_mode = "split"
    client = _make_retrieval_client()
    MockClient.return_value = client
    client.search = AsyncMock(side_effect=[
        _make_search_result([_make_memory("t1")]),
        _make_search_result([_make_memory("f1", source="dreaming")]),
    ])

    await provider._run_retrieve("test query", 70, "user1", None)

    assert client.search.call_count == 2
    first_kw = client.search.call_args_list[0].kwargs
    second_kw = client.search.call_args_list[1].kwargs
    assert first_kw["exclude_source"] == "dreaming"
    assert "source" not in first_kw
    assert second_kw["source"] == "dreaming"


@patch(PATCH_TARGET)
async def test_split_mode_uses_configured_k(MockClient, provider):
    provider._routing_mode = "split"
    provider._transcript_k = 80
    provider._fact_k = 30
    client = _make_retrieval_client()
    MockClient.return_value = client
    client.search = AsyncMock(side_effect=[
        _make_search_result([]),
        _make_search_result([]),
    ])

    await provider._run_retrieve("test query", 70, "user1", None)

    first_kw = client.search.call_args_list[0].kwargs
    second_kw = client.search.call_args_list[1].kwargs
    assert first_kw["max_results"] == 80
    assert second_kw["max_results"] == 30


@patch(PATCH_TARGET)
async def test_split_mode_interleaves_results(MockClient, provider):
    provider._routing_mode = "split"
    client = _make_retrieval_client()
    MockClient.return_value = client
    t1 = _make_memory("t1", "transcript-1")
    t2 = _make_memory("t2", "transcript-2")
    f1 = _make_memory("f1", "fact-1", "dreaming")
    f2 = _make_memory("f2", "fact-2", "dreaming")
    client.search = AsyncMock(side_effect=[
        _make_search_result([t1, t2]),
        _make_search_result([f1, f2]),
    ])

    docs, _ = await provider._run_retrieve("test query", 70, "user1", None)

    assert [d.id for d in docs] == ["t1", "f1", "t2", "f2"]


# ---- Merge (static method) ----


def test_round_robin_interleave():
    ts = [_make_memory(f"t{i}") for i in range(1, 4)]
    fs = [_make_memory(f"f{i}", source="dreaming") for i in range(1, 3)]
    merged = MemoryHubProvider._merge_results(ts, fs)
    assert [m.id for m in merged] == ["t1", "f1", "t2", "f2", "t3"]


def test_round_robin_empty_facts():
    ts = [_make_memory("t1"), _make_memory("t2")]
    merged = MemoryHubProvider._merge_results(ts, [])
    assert [m.id for m in merged] == ["t1", "t2"]


def test_round_robin_empty_transcripts():
    fs = [_make_memory("f1", source="dreaming"), _make_memory("f2", source="dreaming")]
    merged = MemoryHubProvider._merge_results([], fs)
    assert [m.id for m in merged] == ["f1", "f2"]


def test_round_robin_both_empty():
    assert MemoryHubProvider._merge_results([], []) == []


# ---- Token budget (static method) ----
#
# Token counts verified with cl100k_base:
#   "tok " * 100  -> 101 tokens
#   "x " * 500    -> 501 tokens
#   "x " * 25     ->  26 tokens


def test_budget_limits_output():
    memories = [_make_memory(f"m{i}", "tok " * 100) for i in range(3)]
    result = MemoryHubProvider._apply_token_budget(memories, 150)
    assert len(result) == 1
    assert result[0].id == "m0"


def test_budget_skips_large_keeps_small():
    large = _make_memory("big", "x " * 500)
    small1 = _make_memory("s1", "x " * 25)
    small2 = _make_memory("s2", "x " * 25)
    result = MemoryHubProvider._apply_token_budget([large, small1, small2], 120)
    assert len(result) == 2
    assert [m.id for m in result] == ["s1", "s2"]


def test_budget_none_returns_all():
    memories = [_make_memory(f"m{i}") for i in range(5)]
    result = MemoryHubProvider._apply_token_budget(memories, None)
    assert result is memories


# ---- Backward compat ----


@patch(PATCH_TARGET)
async def test_pooled_mode_unchanged(MockClient, provider):
    provider._source_filter = "agent"
    provider._exclude_source = "dreaming"
    client = _make_retrieval_client()
    MockClient.return_value = client
    client.search = AsyncMock(return_value=_make_search_result([_make_memory("m1")]))

    await provider._run_retrieve("test query", 70, "user1", None)

    assert client.search.call_count == 1
    kw = client.search.call_args.kwargs
    assert kw["source"] == "agent"
    assert kw["exclude_source"] == "dreaming"
    assert kw["owner_id"] == "amb-user1"
    assert kw["project_id"] == "amb-benchmark"
    assert kw["max_results"] == 70


# ---- Integration ----


@patch(PATCH_TARGET)
async def test_split_with_budget(MockClient, provider):
    provider._routing_mode = "split"
    provider._max_context_tokens = 210
    client = _make_retrieval_client()
    MockClient.return_value = client
    # "tok " * 50 = 51 tokens per memory
    transcripts = [_make_memory(f"t{i}", "tok " * 50) for i in range(1, 4)]
    facts = [_make_memory(f"f{i}", "tok " * 50, "dreaming") for i in range(1, 4)]
    client.search = AsyncMock(side_effect=[
        _make_search_result(transcripts),
        _make_search_result(facts),
    ])

    docs, _ = await provider._run_retrieve("test query", 70, "user1", None)

    # Merge order: t1, f1, t2, f2, t3, f3 (each 51 tokens)
    # Budget 210: t1(51) + f1(102) + t2(153) + f2(204) fit; t3(255) skips; f3 skips
    assert len(docs) == 4
    assert [d.id for d in docs] == ["t1", "f1", "t2", "f2"]
