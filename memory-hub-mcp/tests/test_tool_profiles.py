"""Tests for tiered tool profiles (#201).

Verifies that MEMORYHUB_TOOL_PROFILE selects the correct tool set
and instructions. Tests import the profile configuration directly
rather than reloading the module (which would require env var
manipulation at import time).
"""

import pytest

from src.main import (
    _TOOLS_COMPACT,
    _TOOLS_FULL,
    _TOOLS_MINIMAL,
    _INSTRUCTIONS_COMPACT,
    _INSTRUCTIONS_FULL,
    _INSTRUCTIONS_MINIMAL,
    _PROFILE_MAP,
    _VALID_PROFILES,
)


class TestProfileDefinitions:
    def test_three_profiles_defined(self):
        assert _VALID_PROFILES == {"compact", "full", "minimal"}

    def test_compact_has_2_tools(self):
        assert len(_TOOLS_COMPACT) == 2

    def test_full_has_10_tools(self):
        assert len(_TOOLS_FULL) == 10

    def test_minimal_has_4_tools(self):
        assert len(_TOOLS_MINIMAL) == 4

    def test_all_profiles_include_register_session(self):
        from src.tools.register_session import register_session
        for profile_name, (tools, _) in _PROFILE_MAP.items():
            assert register_session in tools, (
                f"Profile '{profile_name}' missing register_session"
            )

    def test_compact_includes_memory_dispatcher(self):
        from src.tools.memory import memory
        assert memory in _TOOLS_COMPACT

    def test_compact_excludes_flat_tools(self):
        from src.tools.write_memory import write_memory
        from src.tools.search_memory import search_memory
        assert write_memory not in _TOOLS_COMPACT
        assert search_memory not in _TOOLS_COMPACT

    def test_full_excludes_memory_dispatcher(self):
        from src.tools.memory import memory
        assert memory not in _TOOLS_FULL

    def test_full_includes_all_flat_tools(self):
        from src.tools.write_memory import write_memory
        from src.tools.read_memory import read_memory
        from src.tools.update_memory import update_memory
        from src.tools.delete_memory import delete_memory
        from src.tools.search_memory import search_memory
        from src.tools.manage_session import manage_session
        from src.tools.manage_graph import manage_graph
        from src.tools.manage_curation import manage_curation
        from src.tools.manage_project import manage_project
        for fn in [write_memory, read_memory, update_memory, delete_memory,
                   search_memory, manage_session, manage_graph,
                   manage_curation, manage_project]:
            assert fn in _TOOLS_FULL, f"{fn.__name__} missing from full profile"

    def test_minimal_has_search_write_read(self):
        from src.tools.search_memory import search_memory
        from src.tools.write_memory import write_memory
        from src.tools.read_memory import read_memory
        assert search_memory in _TOOLS_MINIMAL
        assert write_memory in _TOOLS_MINIMAL
        assert read_memory in _TOOLS_MINIMAL

    def test_minimal_excludes_advanced_tools(self):
        from src.tools.manage_graph import manage_graph
        from src.tools.manage_curation import manage_curation
        from src.tools.update_memory import update_memory
        from src.tools.delete_memory import delete_memory
        assert manage_graph not in _TOOLS_MINIMAL
        assert manage_curation not in _TOOLS_MINIMAL
        assert update_memory not in _TOOLS_MINIMAL
        assert delete_memory not in _TOOLS_MINIMAL


class TestProfileInstructions:
    def test_compact_mentions_memory_action(self):
        assert "memory(action=...)" in _INSTRUCTIONS_COMPACT

    def test_compact_does_not_mention_individual_tools(self):
        assert "write_memory" not in _INSTRUCTIONS_COMPACT
        assert "search_memory" not in _INSTRUCTIONS_COMPACT

    def test_full_mentions_individual_tools(self):
        assert "write_memory" in _INSTRUCTIONS_FULL
        assert "search_memory" in _INSTRUCTIONS_FULL
        assert "manage_graph" in _INSTRUCTIONS_FULL

    def test_full_does_not_mention_memory_action(self):
        assert "memory(action=" not in _INSTRUCTIONS_FULL

    def test_minimal_mentions_only_three_tools(self):
        assert "search_memory" in _INSTRUCTIONS_MINIMAL
        assert "write_memory" in _INSTRUCTIONS_MINIMAL
        assert "read_memory" in _INSTRUCTIONS_MINIMAL
        assert "manage_graph" not in _INSTRUCTIONS_MINIMAL
        assert "update_memory" not in _INSTRUCTIONS_MINIMAL

    def test_all_instructions_mention_register_session(self):
        for name, (_, instructions) in _PROFILE_MAP.items():
            assert "register_session" in instructions, (
                f"Profile '{name}' instructions missing register_session"
            )


class TestProfileMap:
    def test_all_valid_profiles_in_map(self):
        for profile in _VALID_PROFILES:
            assert profile in _PROFILE_MAP

    def test_map_entries_are_tuple_of_list_and_str(self):
        for name, (tools, instructions) in _PROFILE_MAP.items():
            assert isinstance(tools, list), f"{name}: tools not a list"
            assert isinstance(instructions, str), f"{name}: instructions not a str"
