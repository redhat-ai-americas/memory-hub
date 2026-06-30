"""Tests for relevant_until and temporal_status MCP tool integration."""

from src.tools.memory import _SEARCH_OPTS, _WRITE_OPTS


class TestOptionForwarding:
    """Verify the unified dispatcher forwards relevant_until and temporal_status."""

    def test_write_opts_contains_relevant_until(self):
        assert "relevant_until" in _WRITE_OPTS

    def test_search_opts_contains_temporal_status(self):
        assert "temporal_status" in _SEARCH_OPTS

    def test_write_opts_is_frozen(self):
        assert isinstance(_WRITE_OPTS, frozenset)

    def test_search_opts_is_frozen(self):
        assert isinstance(_SEARCH_OPTS, frozenset)
