"""Tests for CLI persona subcommands: compile, show, status, edit."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

from typer.testing import CliRunner

from memoryhub_cli.main import app

runner = CliRunner()

# ── Shared fixtures ───────────────────────────────────────────────────────────

SYNOPSIS = {
    "id": "syn-abc123def456",
    "version": 3,
    "content": "Prefers Python. Works on MemoryHub.",
    "updated_at": "2026-11-01T12:00:00",
}

COMPILE_RESULT = {
    "content": "Prefers Python. Works on MemoryHub.",
    "version": 3,
    "synopsis_id": "syn-abc123def456",
    "source_fact_count": 7,
    "pin_count": 1,
    "previous_synopsis_id": "syn-prev000000",
}

GET_RESULT = {
    "synopsis": SYNOPSIS,
    "is_stale": False,
    "compiled_fact_count": 7,
    "source_fact_count": 7,
}

GET_RESULT_STALE = {
    "synopsis": SYNOPSIS,
    "is_stale": True,
    "stale_reason": "3 new facts since last compile",
    "compiled_fact_count": 4,
    "source_fact_count": 7,
}

GET_RESULT_NO_SYNOPSIS = {
    "synopsis": None,
    "is_stale": True,
    "source_fact_count": 2,
    "compiled_fact_count": None,
}

PIN_RESULT = {
    "pin_id": "pin-deadbeef0000",
    "content": "I prefer Rust for systems code.",
}


def _mock_client(call_return=None, call_side_effect=None):
    mock = AsyncMock()
    mock.__aenter__ = AsyncMock(return_value=mock)
    mock.__aexit__ = AsyncMock(return_value=False)
    if call_side_effect is not None:
        mock._call = AsyncMock(side_effect=call_side_effect)
    else:
        mock._call = AsyncMock(return_value=call_return)
    return mock


# ── compile ───────────────────────────────────────────────────────────────────


class TestPersonaCompile:
    def test_happy_path(self):
        mock = _mock_client(COMPILE_RESULT)
        with patch("memoryhub_cli.persona._get_client", return_value=mock):
            result = runner.invoke(app, ["persona", "compile", "--user", "alice"])

        assert result.exit_code == 0
        mock._call.assert_called_once_with(
            "persona",
            {"action": "compile", "user_id": "alice", "project_id": None},
        )
        assert "v3" in result.output

    def test_json_output(self):
        mock = _mock_client(COMPILE_RESULT)
        with patch("memoryhub_cli.persona._get_client", return_value=mock):
            result = runner.invoke(
                app, ["persona", "compile", "--user", "alice", "--output", "json"]
            )

        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert parsed["status"] == "ok"
        assert parsed["data"]["version"] == 3
        assert parsed["data"]["source_fact_count"] == 7

    def test_server_error(self):
        mock = _mock_client(call_side_effect=RuntimeError("LLM unavailable"))
        with patch("memoryhub_cli.persona._get_client", return_value=mock):
            result = runner.invoke(app, ["persona", "compile", "--user", "alice"])

        assert result.exit_code != 0


# ── show ──────────────────────────────────────────────────────────────────────


class TestPersonaShow:
    def test_happy_path(self):
        mock = _mock_client(GET_RESULT)
        with patch("memoryhub_cli.persona._get_client", return_value=mock):
            result = runner.invoke(app, ["persona", "show", "--user", "alice"])

        assert result.exit_code == 0
        mock._call.assert_called_once_with(
            "persona",
            {"action": "get", "user_id": "alice", "project_id": None},
        )
        assert "v3" in result.output

    def test_stale_warning(self):
        mock = _mock_client(GET_RESULT_STALE)
        with patch("memoryhub_cli.persona._get_client", return_value=mock):
            result = runner.invoke(app, ["persona", "show", "--user", "alice"])

        assert result.exit_code == 0
        assert "stale" in result.output.lower()

    def test_no_synopsis(self):
        mock = _mock_client(GET_RESULT_NO_SYNOPSIS)
        with patch("memoryhub_cli.persona._get_client", return_value=mock):
            result = runner.invoke(app, ["persona", "show", "--user", "alice"])

        assert result.exit_code == 0
        assert "compile" in result.output.lower()

    def test_json_output(self):
        mock = _mock_client(GET_RESULT)
        with patch("memoryhub_cli.persona._get_client", return_value=mock):
            result = runner.invoke(
                app, ["persona", "show", "--user", "alice", "--output", "json"]
            )

        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert parsed["status"] == "ok"
        assert parsed["data"]["synopsis"]["version"] == 3

    def test_compact_output(self):
        mock = _mock_client(GET_RESULT)
        with patch("memoryhub_cli.persona._get_client", return_value=mock):
            result = runner.invoke(
                app, ["persona", "show", "--user", "alice", "--output", "compact"]
            )

        assert result.exit_code == 0
        assert "<memoryhub-persona" in result.output
        assert 'user="alice"' in result.output


# ── status ────────────────────────────────────────────────────────────────────


class TestPersonaStatus:
    def test_happy_path(self):
        mock = _mock_client(GET_RESULT)
        with patch("memoryhub_cli.persona._get_client", return_value=mock):
            result = runner.invoke(app, ["persona", "status", "--user", "alice"])

        assert result.exit_code == 0
        mock._call.assert_called_once_with(
            "persona",
            {"action": "get", "user_id": "alice", "project_id": None},
        )

    def test_calls_dispatcher_not_get_persona(self):
        """Regression: status must route through the persona dispatcher."""
        mock = _mock_client(GET_RESULT)
        with patch("memoryhub_cli.persona._get_client", return_value=mock):
            runner.invoke(app, ["persona", "status", "--user", "alice"])

        tool, payload = mock._call.call_args[0]
        assert tool == "persona"
        assert payload["action"] == "get"

    def test_stale_shows_compile_hint(self):
        mock = _mock_client(GET_RESULT_STALE)
        with patch("memoryhub_cli.persona._get_client", return_value=mock):
            result = runner.invoke(app, ["persona", "status", "--user", "alice"])

        assert result.exit_code == 0
        assert "compile" in result.output.lower()

    def test_no_synopsis(self):
        mock = _mock_client(GET_RESULT_NO_SYNOPSIS)
        with patch("memoryhub_cli.persona._get_client", return_value=mock):
            result = runner.invoke(app, ["persona", "status", "--user", "alice"])

        assert result.exit_code == 0
        assert "none" in result.output.lower() or "compile" in result.output.lower()

    def test_json_output(self):
        mock = _mock_client(GET_RESULT)
        with patch("memoryhub_cli.persona._get_client", return_value=mock):
            result = runner.invoke(
                app, ["persona", "status", "--user", "alice", "--output", "json"]
            )

        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert parsed["status"] == "ok"
        assert parsed["data"]["is_stale"] is False


# ── edit ──────────────────────────────────────────────────────────────────────


class TestPersonaEdit:
    def test_happy_path(self):
        mock = _mock_client(PIN_RESULT)
        with patch("memoryhub_cli.persona._get_client", return_value=mock):
            result = runner.invoke(
                app,
                ["persona", "edit", "--user", "alice", "--fact", "I prefer Rust for systems code."],
            )

        assert result.exit_code == 0
        mock._call.assert_called_once_with(
            "persona",
            {"action": "add_pin", "user_id": "alice", "content": "I prefer Rust for systems code."},
        )
        assert "Pin stored" in result.output

    def test_calls_dispatcher_not_edit_persona(self):
        """Regression: edit must route through the persona dispatcher."""
        mock = _mock_client(PIN_RESULT)
        with patch("memoryhub_cli.persona._get_client", return_value=mock):
            runner.invoke(
                app, ["persona", "edit", "--user", "alice", "--fact", "some fact"]
            )

        tool, payload = mock._call.call_args[0]
        assert tool == "persona"
        assert payload["action"] == "add_pin"

    def test_json_output(self):
        mock = _mock_client(PIN_RESULT)
        with patch("memoryhub_cli.persona._get_client", return_value=mock):
            result = runner.invoke(
                app,
                [
                    "persona", "edit",
                    "--user", "alice",
                    "--fact", "I prefer Rust for systems code.",
                    "--output", "json",
                ],
            )

        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert parsed["status"] == "ok"
        assert "pin_id" in parsed["data"]

    def test_server_error(self):
        mock = _mock_client(call_side_effect=RuntimeError("storage failure"))
        with patch("memoryhub_cli.persona._get_client", return_value=mock):
            result = runner.invoke(
                app, ["persona", "edit", "--user", "alice", "--fact", "some fact"]
            )

        assert result.exit_code != 0
