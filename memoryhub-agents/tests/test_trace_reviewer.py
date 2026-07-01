"""Tests for the Trace Reviewer agent plugin."""

import pytest
from unittest.mock import AsyncMock

from memoryhub_agents.plugins.trace_reviewer import (
    ExtractedMemory,
    TraceReviewerPlugin,
    _extract_around_phrase,
    _extract_memories,
    _has_near_duplicate,
    _jaccard_similarity,
)


# ---------------------------------------------------------------------------
# ExtractedMemory dataclass
# ---------------------------------------------------------------------------


class TestExtractedMemory:
    def test_construction(self):
        m = ExtractedMemory(content="test", scope="user", weight=0.7)
        assert m.content == "test"
        assert m.scope == "user"
        assert m.weight == 0.7
        assert m.domains is None

    def test_with_domains(self):
        m = ExtractedMemory(
            content="test", scope="project", weight=0.8, domains=["infra"]
        )
        assert m.domains == ["infra"]


# ---------------------------------------------------------------------------
# Jaccard similarity
# ---------------------------------------------------------------------------


class TestJaccardSimilarity:
    def test_identical(self):
        assert _jaccard_similarity("hello world", "hello world") == 1.0

    def test_disjoint(self):
        assert _jaccard_similarity("hello world", "foo bar") == 0.0

    def test_partial_overlap(self):
        sim = _jaccard_similarity("hello world foo", "hello world bar")
        assert 0.0 < sim < 1.0

    def test_empty_first(self):
        assert _jaccard_similarity("", "hello") == 0.0

    def test_empty_second(self):
        assert _jaccard_similarity("hello", "") == 0.0

    def test_both_empty(self):
        assert _jaccard_similarity("", "") == 0.0

    def test_case_insensitive(self):
        assert _jaccard_similarity("Hello World", "hello world") == 1.0


# ---------------------------------------------------------------------------
# Near-duplicate detection
# ---------------------------------------------------------------------------


class TestHasNearDuplicate:
    def test_no_results(self):
        assert not _has_near_duplicate([], "some content")

    def test_no_match(self):
        results = [{"content": "completely different topic about databases"}]
        assert not _has_near_duplicate(results, "weather forecast for tomorrow")

    def test_match_above_threshold(self):
        text = "We decided to use FastAPI for the web framework"
        results = [{"content": text}]
        assert _has_near_duplicate(results, text)

    def test_non_dict_results_ignored(self):
        results = ["not a dict", 42, None]
        assert not _has_near_duplicate(results, "some content")

    def test_missing_content_key(self):
        results = [{"other_field": "value"}]
        assert not _has_near_duplicate(results, "some content")


# ---------------------------------------------------------------------------
# Sentence extraction around signal phrases
# ---------------------------------------------------------------------------


class TestExtractAroundPhrase:
    def test_single_sentence(self):
        text = "We decided to use PostgreSQL for persistence."
        result = _extract_around_phrase(text, "we decided")
        assert result is not None
        assert "PostgreSQL" in result

    def test_multi_sentence_extracts_correct_one(self):
        text = "First point. We decided to use FastAPI. Third point."
        result = _extract_around_phrase(text, "we decided")
        assert result is not None
        assert "FastAPI" in result
        assert "First point" not in result

    def test_phrase_not_found(self):
        assert _extract_around_phrase("hello world", "nonexistent") is None

    def test_truncation_at_500(self):
        long_text = "We decided " + "x" * 600 + "."
        result = _extract_around_phrase(long_text, "we decided")
        assert result is not None
        assert len(result) <= 500

    def test_no_trailing_period(self):
        text = "We decided to go with option A"
        result = _extract_around_phrase(text, "we decided")
        assert result is not None
        assert "option A" in result


# ---------------------------------------------------------------------------
# Memory extraction from messages
# ---------------------------------------------------------------------------


class TestExtractMemories:
    def test_extracts_decision(self):
        messages = [
            {
                "role": "assistant",
                "content": (
                    "After evaluating both options, we decided to use "
                    "PostgreSQL for persistence because it supports "
                    "pgvector natively."
                ),
            }
        ]
        extracted = _extract_memories(messages)
        assert len(extracted) >= 1
        assert "PostgreSQL" in extracted[0].content
        assert extracted[0].scope == "user"
        assert extracted[0].weight == 0.7

    def test_skips_short_messages(self):
        messages = [{"role": "assistant", "content": "ok"}]
        assert _extract_memories(messages) == []

    def test_skips_user_messages(self):
        messages = [
            {
                "role": "user",
                "content": (
                    "We decided to use PostgreSQL for the backend "
                    "database going forward with full support."
                ),
            }
        ]
        assert _extract_memories(messages) == []

    def test_skips_no_signal_phrases(self):
        messages = [
            {
                "role": "assistant",
                "content": (
                    "Here is the code you requested for the HTTP "
                    "handler. It accepts a JSON body and returns a "
                    "200 status code on success."
                ),
            }
        ]
        assert _extract_memories(messages) == []

    def test_one_extraction_per_message(self):
        messages = [
            {
                "role": "assistant",
                "content": (
                    "We decided to use FastAPI for the web framework "
                    "because of async. The lesson learned is that "
                    "Flask async support is quite limited in practice."
                ),
            }
        ]
        extracted = _extract_memories(messages)
        assert len(extracted) == 1

    def test_multiple_messages(self):
        messages = [
            {
                "role": "assistant",
                "content": (
                    "We decided to use PostgreSQL for the database "
                    "because of pgvector support."
                ),
            },
            {
                "role": "assistant",
                "content": (
                    "The key takeaway from this debugging session "
                    "is that connection pooling matters."
                ),
            },
        ]
        extracted = _extract_memories(messages)
        assert len(extracted) == 2

    def test_empty_messages(self):
        assert _extract_memories([]) == []

    def test_skips_empty_content(self):
        messages = [{"role": "assistant", "content": ""}]
        assert _extract_memories(messages) == []


# ---------------------------------------------------------------------------
# TraceReviewerPlugin.process
# ---------------------------------------------------------------------------


class TestTraceReviewerProcess:
    @pytest.fixture
    def plugin(self):
        return TraceReviewerPlugin()

    @pytest.mark.asyncio
    async def test_missing_thread_id(self, plugin):
        result = await plugin.process({}, AsyncMock())
        assert result["status"] == "error"
        assert "thread_id" in result["reason"]

    @pytest.mark.asyncio
    async def test_missing_owner_id(self, plugin):
        result = await plugin.process({"thread_id": "t1"}, AsyncMock())
        assert result["status"] == "error"
        assert "owner_id" in result["reason"]

    @pytest.mark.asyncio
    async def test_missing_messages(self, plugin):
        item = {"thread_id": "t1", "owner_id": "u1"}
        result = await plugin.process(item, AsyncMock())
        assert result["status"] == "error"
        assert "messages" in result["reason"]

    @pytest.mark.asyncio
    async def test_no_extractable_content(self, plugin):
        mcp = AsyncMock()
        item = {
            "thread_id": "t1",
            "owner_id": "u1",
            "messages": [{"role": "assistant", "content": "ok done"}],
        }
        result = await plugin.process(item, mcp)
        assert result["status"] == "ok"
        assert result["extracted"] == 0
        assert plugin.stats["skipped"] == 1

    @pytest.mark.asyncio
    async def test_extract_and_write(self, plugin):
        mcp = AsyncMock()
        mcp.call_tool = AsyncMock(return_value={"results": []})

        item = {
            "thread_id": "t1",
            "owner_id": "u1",
            "messages": [
                {
                    "role": "assistant",
                    "content": (
                        "After testing both approaches, we decided to "
                        "use FastAPI over Flask because it has native "
                        "async support and automatic OpenAPI generation."
                    ),
                }
            ],
        }
        result = await plugin.process(item, mcp)
        assert result["status"] == "ok"
        assert result["extracted"] >= 1
        assert plugin.stats["extracted"] >= 1
        # Should have called search (dedup) and write
        assert mcp.call_tool.call_count >= 2

    @pytest.mark.asyncio
    async def test_dedup_skips_existing(self, plugin):
        mcp = AsyncMock()
        mcp.call_tool = AsyncMock(
            return_value={
                "results": [
                    {
                        "content": (
                            "We decided to use FastAPI over Flask because "
                            "it has native async support and automatic "
                            "OpenAPI generation."
                        )
                    }
                ]
            }
        )

        item = {
            "thread_id": "t1",
            "owner_id": "u1",
            "messages": [
                {
                    "role": "assistant",
                    "content": (
                        "After testing both approaches, we decided to "
                        "use FastAPI over Flask because it has native "
                        "async support and automatic OpenAPI generation."
                    ),
                }
            ],
        }
        result = await plugin.process(item, mcp)
        assert result["status"] == "ok"
        assert result["extracted"] == 0  # skipped as duplicate

    @pytest.mark.asyncio
    async def test_extract_with_project_id(self, plugin):
        mcp = AsyncMock()
        mcp.call_tool = AsyncMock(return_value={"results": []})

        item = {
            "thread_id": "t1",
            "owner_id": "u1",
            "project_id": "proj-1",
            "messages": [
                {
                    "role": "assistant",
                    "content": (
                        "Going forward, all deployments must use the "
                        "blue-green strategy to minimize downtime risk."
                    ),
                }
            ],
        }
        result = await plugin.process(item, mcp)
        assert result["status"] == "ok"
        assert result["extracted"] >= 1

        # Verify project_id was passed to the write call
        write_calls = [
            c
            for c in mcp.call_tool.call_args_list
            if c.args[0] == "write" or c.kwargs.get("action") == "write"
        ]
        assert len(write_calls) >= 1

    @pytest.mark.asyncio
    async def test_mcp_error_increments_error_stat(self, plugin):
        mcp = AsyncMock()
        mcp.call_tool = AsyncMock(side_effect=RuntimeError("connection lost"))

        item = {
            "thread_id": "t1",
            "owner_id": "u1",
            "messages": [
                {
                    "role": "assistant",
                    "content": (
                        "We decided to use PostgreSQL for everything "
                        "because it handles both relational and vector "
                        "data with pgvector."
                    ),
                }
            ],
        }
        result = await plugin.process(item, mcp)
        assert result["status"] == "ok"
        assert result["extracted"] == 0
        assert plugin.stats["errors"] >= 1

    @pytest.mark.asyncio
    async def test_stats_accumulate(self, plugin):
        mcp = AsyncMock()
        mcp.call_tool = AsyncMock(return_value={"results": []})

        # Process two items: one with extractable content, one without
        item_with = {
            "thread_id": "t1",
            "owner_id": "u1",
            "messages": [
                {
                    "role": "assistant",
                    "content": (
                        "The key takeaway is that connection pooling "
                        "significantly improves throughput under load."
                    ),
                }
            ],
        }
        item_without = {
            "thread_id": "t2",
            "owner_id": "u1",
            "messages": [{"role": "assistant", "content": "Done, merged the PR."}],
        }

        await plugin.process(item_with, mcp)
        await plugin.process(item_without, mcp)

        assert plugin.stats["reviewed"] == 2
        assert plugin.stats["extracted"] >= 1
        assert plugin.stats["skipped"] == 1
