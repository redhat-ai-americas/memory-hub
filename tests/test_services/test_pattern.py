"""Tests for within-user pattern detection service.

Pattern detection requires pgvector (cosine_distance operator), so the
core query path is tested via integration tests against real PostgreSQL.
These unit tests verify the PatternSignal dataclass, the function
signature, and the graceful fallback when pgvector is unavailable.
"""

import dataclasses
import uuid

import pytest

from memoryhub_core.services.pattern import PatternSignal, detect_patterns


class TestPatternSignal:
    """PatternSignal dataclass structure and field requirements."""

    def test_fields(self):
        fields = {f.name for f in dataclasses.fields(PatternSignal)}
        assert fields == {
            "pattern",
            "matching_memories",
            "time_window_days",
            "representative_id",
            "summary_hint",
        }

    def test_construction(self):
        sig = PatternSignal(
            pattern="topic_cluster",
            matching_memories=5,
            time_window_days=7,
            representative_id="abc-123",
            summary_hint="5 recent memories match this topic cluster",
        )
        assert sig.pattern == "topic_cluster"
        assert sig.matching_memories == 5
        assert sig.time_window_days == 7
        assert sig.representative_id == "abc-123"
        assert sig.summary_hint == "5 recent memories match this topic cluster"

    def test_serialization_round_trip(self):
        """PatternSignal can be converted to dict for JSON serialization."""
        sig = PatternSignal(
            pattern="topic_cluster",
            matching_memories=3,
            time_window_days=30,
            representative_id=str(uuid.uuid4()),
            summary_hint="3 recent memories cluster around this topic",
        )
        d = dataclasses.asdict(sig)
        assert d["pattern"] == "topic_cluster"
        assert d["matching_memories"] == 3
        assert isinstance(d, dict)


class TestDetectPatternsFallback:
    """detect_patterns returns empty list when pgvector is unavailable."""

    @pytest.mark.asyncio
    async def test_returns_empty_on_sqlite(self, async_session):
        """SQLite sessions lack pgvector; detect_patterns should return []."""
        fake_embedding = [0.1] * 384
        result = await detect_patterns(
            fake_embedding,
            async_session,
            owner_id="test-user",
            tenant_id="default",
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_custom_thresholds_accepted(self, async_session):
        """All keyword arguments are accepted without error."""
        fake_embedding = [0.1] * 384
        result = await detect_patterns(
            fake_embedding,
            async_session,
            owner_id="test-user",
            tenant_id="default",
            similarity_threshold=0.90,
            min_cluster_size=5,
            time_window_days=7,
            max_candidates=100,
        )
        assert result == []
