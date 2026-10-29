"""Trajectory recording for Claude Code hooks (#554)."""

from __future__ import annotations

import json
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

from memoryhub_cli.main import app
from memoryhub_cli.trajectory import (
    latest_thread_for,
    locked_state,
    messages_from_hook_payload,
    outcome_message,
    redact_secrets,
)

runner = CliRunner()


@pytest.fixture(autouse=True)
def _state_home(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.delenv("MEMORYHUB_RECORD_TRAJECTORY", raising=False)


def _client():
    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.create_thread = AsyncMock(return_value=SimpleNamespace(id="thread-1"))
    client.append_message = AsyncMock(return_value=SimpleNamespace(id="msg-1"))
    return client


POST_TOOL = {
    "session_id": "sess-1",
    "cwd": "/work/api",
    "hook_event_name": "PostToolUse",
    "tool_name": "Bash",
    "tool_input": {"command": "podman build -t api ."},
    "tool_response": {"stdout": "Successfully tagged api", "stderr": ""},
    "tool_use_id": "toolu_1",
}


def test_payloads_map_to_thread_messages():
    user = messages_from_hook_payload(
        {"hook_event_name": "UserPromptSubmit", "prompt": "deploy api"}
    )
    assert [(m.role, m.content) for m in user] == [("user", "deploy api")]

    call, result = messages_from_hook_payload(POST_TOOL)
    assert call.role == "tool_call" and result.role == "tool_result"
    assert call.tool_call_id == result.tool_call_id == "toolu_1"
    assert json.loads(call.content) == {
        "tool": "Bash",
        "input": {"command": "podman build -t api ."},
    }
    assert "Successfully tagged" in result.content

    failed = messages_from_hook_payload(
        {**POST_TOOL, "hook_event_name": "PostToolUseFailure", "error": "exit 1"}
    )
    assert failed[1].content == "ERROR: exit 1" and failed[1].metadata == {"is_error": True}

    stop = messages_from_hook_payload(
        {"hook_event_name": "Stop", "last_assistant_message": "Deployed."}
    )
    assert [(m.role, m.content) for m in stop] == [("assistant", "Deployed.")]

    assert messages_from_hook_payload({**POST_TOOL, "tool_name": "mcp__memoryhub__memory"}) == []
    assert messages_from_hook_payload({"hook_event_name": "SessionStart"}) == []


def test_redaction_and_clipping():
    key = "AKIA" + "ABCDEFGHIJKLMNOP"
    token = "ghp" + "_" + "x" * 36
    assert redact_secrets(f"{key} {token}") == "[REDACTED] [REDACTED]"
    assert redact_secrets("API_KEY=abcdef123456") == "API_KEY=[REDACTED]"
    assert (
        redact_secrets("Authorization: Bearer abcdefghijklmnopqrstu")
        == "Authorization: Bearer [REDACTED]"
    )
    msgs = messages_from_hook_payload(
        {**POST_TOOL, "tool_response": f"key {key} " + "y" * 5000}, max_chars=500
    )
    assert (
        key not in msgs[1].content
        and "chars omitted" in msgs[1].content
        and len(msgs[1].content) < 560
    )


def test_outcome_message():
    msg = outcome_message("success", "tests green")
    assert msg.metadata == {"outcome": "success"} and msg.role == "system"
    with pytest.raises(ValueError):
        outcome_message("great")


def test_state_lock_serializes_thread_creation():
    created: list[str] = []

    def worker():
        with locked_state("sess-x") as state:
            if state.thread_id is None:
                created.append("new")
                state.thread_id = "t-1"
                state.project_dir = "/work"

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert created == ["new"]
    assert latest_thread_for("/work") == "t-1" and latest_thread_for("/elsewhere") is None


def test_record_command_creates_thread_once_and_appends():
    client = _client()
    with (
        patch("memoryhub_cli.main._get_client", return_value=client),
        patch("memoryhub_cli.main._get_project_id_default", return_value=None),
    ):
        first = runner.invoke(
            app, ["thread", "record", "--project-id", "api"], input=json.dumps(POST_TOOL)
        )
        second = runner.invoke(
            app,
            ["thread", "record", "--project-id", "api"],
            input=json.dumps(
                {
                    "session_id": "sess-1",
                    "hook_event_name": "Stop",
                    "last_assistant_message": "Done.",
                }
            ),
        )
    assert first.exit_code == 0 and second.exit_code == 0
    assert client.create_thread.await_count == 1
    args, kwargs = client.create_thread.await_args
    assert args == ("project",) and kwargs["scope_id"] == "api"
    roles = [c.args[1] for c in client.append_message.await_args_list]
    assert roles == ["tool_call", "tool_result", "assistant"]
    assert client.append_message.await_args_list[0].kwargs["tool_call_id"] == "toolu_1"


def test_record_command_never_fails_the_host(monkeypatch):
    client = _client()
    client.create_thread = AsyncMock(side_effect=RuntimeError("server down"))
    with patch("memoryhub_cli.main._get_client", return_value=client):
        assert runner.invoke(app, ["thread", "record"], input=json.dumps(POST_TOOL)).exit_code == 0
        assert runner.invoke(app, ["thread", "record"], input="not json").exit_code == 0
    monkeypatch.setenv("MEMORYHUB_RECORD_TRAJECTORY", "0")
    with patch("memoryhub_cli.main._get_client") as factory:
        assert runner.invoke(app, ["thread", "record"], input=json.dumps(POST_TOOL)).exit_code == 0
        factory.assert_not_called()


def test_outcome_command_uses_latest_session_or_explicit_thread(tmp_path, monkeypatch):
    with locked_state("sess-2") as state:
        state.thread_id = "thread-9"
        state.project_dir = str(tmp_path)
    monkeypatch.chdir(tmp_path)
    client = _client()
    with patch("memoryhub_cli.main._get_client", return_value=client):
        result = runner.invoke(app, ["thread", "outcome", "failure", "-o", "json"])
    assert result.exit_code == 0, result.output
    call = client.append_message.await_args
    assert call.args[0] == "thread-9" and call.kwargs["metadata"] == {"outcome": "failure"}
    with patch("memoryhub_cli.main._get_client", return_value=_client()):
        bad = runner.invoke(app, ["thread", "outcome", "meh", "--thread", "t"])
    assert bad.exit_code != 0


def test_config_init_installs_async_record_hooks_only_when_asked(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    assert (
        runner.invoke(
            app, ["config", "init", "--dir", str(plain), "--non-interactive", "-o", "quiet"]
        ).exit_code
        == 0
    )
    assert not (plain / ".claude" / "hooks" / "record-trajectory.sh").exists()

    proj = tmp_path / "proj"
    proj.mkdir()
    args = [
        "config",
        "init",
        "--dir",
        str(proj),
        "--non-interactive",
        "-o",
        "quiet",
        "--record-trajectories",
    ]
    assert runner.invoke(app, args).exit_code == 0
    script = proj / ".claude" / "hooks" / "record-trajectory.sh"
    assert script.exists() and "thread record" in script.read_text()
    settings = json.loads((proj / ".claude" / "settings.json").read_text())
    for event in ("UserPromptSubmit", "PostToolUse", "PostToolUseFailure", "Stop"):
        hooks = [
            h
            for e in settings["hooks"][event]
            for h in e["hooks"]
            if "record-trajectory" in h["command"]
        ]
        assert len(hooks) == 1 and hooks[0]["async"] is True
    # idempotent
    assert runner.invoke(app, [*args, "--force"]).exit_code == 0
    settings = json.loads((proj / ".claude" / "settings.json").read_text())
    assert (
        sum(
            "record-trajectory" in h["command"]
            for e in settings["hooks"]["PostToolUse"]
            for h in e["hooks"]
        )
        == 1
    )
