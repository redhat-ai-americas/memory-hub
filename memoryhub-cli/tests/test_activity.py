"""Tests for client-side MemoryHub activity summaries."""

from __future__ import annotations

import json

from memoryhub_cli.activity import format_hook_output, process_activity_hook

_BASE_NS = 1_700_000_000_000_000_000


def _payload(session_id: str, cwd: str, **values):
    return {"session_id": session_id, "cwd": cwd, **values}


def test_tracks_successful_tool_activity_and_stores_end_summary(tmp_path):
    database = tmp_path / "activity.sqlite3"
    cwd = str(tmp_path / "project")
    session = "session-one"

    process_activity_hook(
        "session-start",
        _payload(session, cwd, source="startup"),
        database_path=database,
        now_ns=_BASE_NS,
    )
    search_summary = process_activity_hook(
        "post-tool-use",
        _payload(
            session,
            cwd,
            tool_name="mcp__memoryhub__memory",
            tool_input={"action": "search", "query": "private query text"},
            tool_response={"results": []},
        ),
        database_path=database,
        now_ns=_BASE_NS + 1,
    )
    assert search_summary is not None
    assert "0 successful new saves" in search_summary
    assert "1 successful searches" in search_summary

    save_summary = process_activity_hook(
        "post-tool-use",
        _payload(
            session,
            cwd,
            tool_name="mcp__memoryhub__memory",
            tool_input={"action": "write", "content": "private memory text"},
            tool_response={"memory": {"id": "mem-1", "content": "private memory text"}},
        ),
        database_path=database,
        now_ns=_BASE_NS + 2,
    )
    assert save_summary is not None
    assert "1 successful new saves" in save_summary

    gated_summary = process_activity_hook(
        "post-tool-use",
        _payload(
            session,
            cwd,
            tool_name="mcp__memoryhub__memory",
            tool_input={"action": "write", "content": "duplicate"},
            tool_response={"memory": None, "curation": {"gated": True}},
        ),
        database_path=database,
        now_ns=_BASE_NS + 3,
    )
    assert gated_summary is None

    process_activity_hook(
        "session-end",
        _payload(session, cwd),
        database_path=database,
        now_ns=_BASE_NS + 4,
    )
    previous = process_activity_hook(
        "session-start",
        _payload("session-two", cwd, source="startup"),
        database_path=database,
        now_ns=_BASE_NS + 5,
    )
    assert previous is not None
    assert "Previous MemoryHub session" in previous
    assert "1 successful new saves" in previous
    assert "1 successful searches" in previous

    stored_data = database.read_bytes()
    assert b"private query text" not in stored_data
    assert b"private memory text" not in stored_data


def test_nudges_every_ten_turns_and_resets_after_a_successful_write(tmp_path):
    database = tmp_path / "activity.sqlite3"
    cwd = str(tmp_path / "project")
    session = "session-one"
    process_activity_hook(
        "session-start",
        _payload(session, cwd, source="startup"),
        database_path=database,
        now_ns=_BASE_NS,
    )

    for turn in range(1, 11):
        summary = process_activity_hook(
            "user-prompt-submit",
            _payload(session, cwd, prompt=f"private prompt {turn}"),
            database_path=database,
            now_ns=_BASE_NS + turn,
        )
    assert summary is not None
    assert "10 user turns" in summary

    process_activity_hook(
        "post-tool-use",
        _payload(
            session,
            cwd,
            tool_name="mcp__memoryhub__write_memory",
            tool_input={"content": "saved"},
            tool_response={"id": "mem-1"},
        ),
        database_path=database,
        now_ns=_BASE_NS + 11,
    )
    next_summary = process_activity_hook(
        "user-prompt-submit",
        _payload(session, cwd),
        database_path=database,
        now_ns=_BASE_NS + 12,
    )
    assert next_summary is not None
    assert "No successful memory write" not in next_summary
    stored_data = database.read_bytes()
    assert b"private prompt" not in stored_data


def test_formats_host_hook_context_as_json():
    output = json.loads(format_hook_output("UserPromptSubmit", "activity summary"))
    assert output == {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": "activity summary",
        }
    }
