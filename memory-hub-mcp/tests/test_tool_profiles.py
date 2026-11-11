"""Tests for tiered tool profiles (#201).

Verifies that MEMORYHUB_TOOL_PROFILE selects the correct tool set
and instructions. Tests import the profile configuration directly
rather than reloading the module (which would require env var
manipulation at import time).
"""


from src.main import (
    _INSTRUCTIONS_COMPACT,
    _INSTRUCTIONS_FULL,
    _INSTRUCTIONS_MINIMAL,
    _PROFILE_MAP,
    _TOOLS_COMPACT,
    _TOOLS_FULL,
    _TOOLS_MINIMAL,
    _VALID_PROFILES,
)


class TestProfileDefinitions:
    def test_three_profiles_defined(self):
        assert {"compact", "full", "minimal"} == _VALID_PROFILES

    def test_compact_has_5_tools(self):
        assert len(_TOOLS_COMPACT) == 5

    def test_full_has_14_tools(self):
        assert len(_TOOLS_FULL) == 14

    def test_minimal_has_5_tools(self):
        assert len(_TOOLS_MINIMAL) == 5

    def test_all_profiles_include_register_session(self):
        from src.tools.register_session import register_session
        for profile_name, (tools, _) in _PROFILE_MAP.items():
            assert register_session in tools, (
                f"Profile '{profile_name}' missing register_session"
            )

    def test_compact_registers_exact_tool_set(self):
        assert {tool.__name__ for tool in _TOOLS_COMPACT} == {
            "register_session",
            "memory",
            "admin_memory",
            "thread",
            "persona",
        }

    def test_full_registers_exact_tool_set(self):
        assert {tool.__name__ for tool in _TOOLS_FULL} == {
            "register_session",
            "write_memory",
            "read_memory",
            "update_memory",
            "delete_memory",
            "search_memory",
            "list_memory",
            "manage_session",
            "manage_graph",
            "manage_curation",
            "manage_project",
            "admin_memory",
            "thread",
            "persona",
        }

    def test_minimal_registers_exact_tool_set(self):
        assert {tool.__name__ for tool in _TOOLS_MINIMAL} == {
            "register_session",
            "search_memory",
            "write_memory",
            "read_memory",
            "thread",
        }

    def test_compact_includes_memory_and_thread_dispatchers(self):
        from src.tools.memory import memory
        from src.tools.persona import persona
        from src.tools.thread import thread
        assert memory in _TOOLS_COMPACT
        assert thread in _TOOLS_COMPACT
        assert persona in _TOOLS_COMPACT

    def test_compact_excludes_flat_tools(self):
        from src.tools.compile_persona import compile_persona
        from src.tools.edit_persona import edit_persona
        from src.tools.get_persona import get_persona
        from src.tools.search_memory import search_memory
        from src.tools.write_memory import write_memory
        from src.tools.persona import persona
        assert persona in _TOOLS_COMPACT
        assert get_persona not in _TOOLS_COMPACT
        assert compile_persona not in _TOOLS_COMPACT
        assert edit_persona not in _TOOLS_COMPACT
        assert write_memory not in _TOOLS_COMPACT
        assert search_memory not in _TOOLS_COMPACT

    def test_full_excludes_memory_dispatcher(self):
        from src.tools.memory import memory
        assert memory not in _TOOLS_FULL

    def test_full_includes_all_flat_tools(self):
        from src.tools.delete_memory import delete_memory
        from src.tools.list_memory import list_memory
        from src.tools.manage_curation import manage_curation
        from src.tools.manage_graph import manage_graph
        from src.tools.manage_project import manage_project
        from src.tools.manage_session import manage_session
        from src.tools.read_memory import read_memory
        from src.tools.search_memory import search_memory
        from src.tools.thread import thread
        from src.tools.update_memory import update_memory
        from src.tools.write_memory import write_memory
        for fn in [write_memory, read_memory, update_memory, delete_memory,
                   search_memory, list_memory, manage_session, manage_graph,
                   manage_curation, manage_project, thread]:
            assert fn in _TOOLS_FULL, f"{fn.__name__} missing from full profile"

    def test_full_includes_persona_dispatcher_not_flat_persona_tools(self):
        from src.tools.compile_persona import compile_persona
        from src.tools.edit_persona import edit_persona
        from src.tools.get_persona import get_persona
        from src.tools.persona import persona

        assert persona in _TOOLS_FULL
        assert get_persona not in _TOOLS_FULL
        assert compile_persona not in _TOOLS_FULL
        assert edit_persona not in _TOOLS_FULL

    def test_minimal_has_search_write_read_thread(self):
        from src.tools.read_memory import read_memory
        from src.tools.search_memory import search_memory
        from src.tools.thread import thread
        from src.tools.write_memory import write_memory
        assert search_memory in _TOOLS_MINIMAL
        assert write_memory in _TOOLS_MINIMAL
        assert read_memory in _TOOLS_MINIMAL
        assert thread in _TOOLS_MINIMAL

    def test_minimal_excludes_advanced_tools(self):
        from src.tools.delete_memory import delete_memory
        from src.tools.manage_curation import manage_curation
        from src.tools.manage_graph import manage_graph
        from src.tools.update_memory import update_memory
        from src.tools.persona import persona
        assert manage_graph not in _TOOLS_MINIMAL
        assert manage_curation not in _TOOLS_MINIMAL
        assert update_memory not in _TOOLS_MINIMAL
        assert delete_memory not in _TOOLS_MINIMAL
        assert persona not in _TOOLS_MINIMAL


class TestProfileInstructions:
    def test_compact_mentions_memory_action(self):
        assert "memory(action=...)" in _INSTRUCTIONS_COMPACT

    def test_compact_does_not_mention_individual_tools(self):
        assert "write_memory" not in _INSTRUCTIONS_COMPACT
        assert "search_memory" not in _INSTRUCTIONS_COMPACT
        assert "get_persona()" not in _INSTRUCTIONS_COMPACT
        assert "compile_persona()" not in _INSTRUCTIONS_COMPACT
        assert "persona(action='get')" in _INSTRUCTIONS_COMPACT
        assert "persona(action='compile')" in _INSTRUCTIONS_COMPACT

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
