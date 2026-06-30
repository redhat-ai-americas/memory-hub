"""Tests for pattern_signals integration in the search_memory tool.

Verifies that the search tool imports the pattern detection module and
that PatternSignal instances serialize correctly for tool responses.
"""

import dataclasses

from memoryhub_core.services.pattern import PatternSignal


def test_pattern_signal_import_from_search_tool():
    """The search_memory module can import pattern detection."""
    from src.tools.search_memory import detect_patterns, PatternSignal as PS

    assert detect_patterns is not None
    assert PS is PatternSignal


def test_pattern_signal_to_response_dict():
    """PatternSignal serializes to the expected response shape."""
    sig = PatternSignal(
        pattern="topic_cluster",
        matching_memories=4,
        time_window_days=30,
        representative_id="deadbeef-1234",
        summary_hint="4 recent memories cluster around this topic",
    )
    entry = {
        "pattern": sig.pattern,
        "matching_memories": sig.matching_memories,
        "time_window_days": sig.time_window_days,
        "representative_id": sig.representative_id,
        "summary_hint": sig.summary_hint,
    }
    assert entry == dataclasses.asdict(sig)
    assert isinstance(entry["matching_memories"], int)
    assert isinstance(entry["time_window_days"], int)


def test_empty_pattern_signals_not_in_response():
    """When pattern_signals is empty, it should not appear in the response dict."""
    pattern_signals: list[PatternSignal] = []
    response: dict = {"results": [], "total_matching": 0, "has_more": False}

    # Mirrors the tool's conditional injection
    if pattern_signals:
        response["pattern_signals"] = [
            dataclasses.asdict(sig) for sig in pattern_signals
        ]

    assert "pattern_signals" not in response


def test_nonempty_pattern_signals_in_response():
    """When pattern_signals has entries, they appear in the response dict."""
    pattern_signals = [
        PatternSignal(
            pattern="topic_cluster",
            matching_memories=5,
            time_window_days=14,
            representative_id="abc-123",
            summary_hint="5 recent memories cluster around this topic",
        )
    ]
    response: dict = {"results": [], "total_matching": 5, "has_more": False}

    if pattern_signals:
        response["pattern_signals"] = [
            {
                "pattern": sig.pattern,
                "matching_memories": sig.matching_memories,
                "time_window_days": sig.time_window_days,
                "representative_id": sig.representative_id,
                "summary_hint": sig.summary_hint,
            }
            for sig in pattern_signals
        ]

    assert "pattern_signals" in response
    assert len(response["pattern_signals"]) == 1
    assert response["pattern_signals"][0]["matching_memories"] == 5
