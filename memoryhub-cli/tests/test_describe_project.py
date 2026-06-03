"""Tests for `memoryhub project describe` CLI command."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

from typer.testing import CliRunner

from memoryhub_cli.main import app

runner = CliRunner()

# ── Fixtures ─────────────────────────────────────────────────────────────────

SAMPLE_PROJECT = {
    "name": "memory-hub",
    "description": "Kubernetes-native agent memory",
    "members": [
        {"user_id": "wjackson", "role": "admin"},
        {"user_id": "agent-01", "role": "member"},
    ],
}

SAMPLE_PROJECT_NO_DESC = {
    "name": "empty-proj",
    "members": [],
}


def _patch_describe(return_value):
    """Patch MemoryHubClient to return *return_value* from describe_project."""
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.describe_project = AsyncMock(return_value=return_value)
    return patch("memoryhub_cli.main._get_client", return_value=mock_client)


# ── Table output ─────────────────────────────────────────────────────────────


class TestDescribeProjectTable:
    def test_shows_project_name(self):
        with _patch_describe(SAMPLE_PROJECT):
            result = runner.invoke(app, ["project", "describe", "memory-hub"])

        assert result.exit_code == 0
        assert "memory-hub" in result.output

    def test_shows_description(self):
        with _patch_describe(SAMPLE_PROJECT):
            result = runner.invoke(app, ["project", "describe", "memory-hub"])

        assert result.exit_code == 0
        assert "Kubernetes-native agent memory" in result.output

    def test_shows_members_table(self):
        with _patch_describe(SAMPLE_PROJECT):
            result = runner.invoke(app, ["project", "describe", "memory-hub"])

        assert result.exit_code == 0
        assert "wjackson" in result.output
        assert "admin" in result.output
        assert "agent-01" in result.output
        assert "member" in result.output

    def test_no_members(self):
        with _patch_describe(SAMPLE_PROJECT_NO_DESC):
            result = runner.invoke(app, ["project", "describe", "empty-proj"])

        assert result.exit_code == 0
        assert "No members" in result.output

    def test_no_description_omits_line(self):
        with _patch_describe(SAMPLE_PROJECT_NO_DESC):
            result = runner.invoke(app, ["project", "describe", "empty-proj"])

        assert result.exit_code == 0
        assert "empty-proj" in result.output
        # Should not print a blank description line
        assert "Kubernetes" not in result.output


# ── JSON output ──────────────────────────────────────────────────────────────


class TestDescribeProjectJSON:
    def test_json_output(self):
        with _patch_describe(SAMPLE_PROJECT):
            result = runner.invoke(
                app, ["project", "describe", "memory-hub", "--output", "json"]
            )

        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert parsed["data"]["name"] == "memory-hub"
        assert len(parsed["data"]["members"]) == 2


# ── Quiet output ─────────────────────────────────────────────────────────────


class TestDescribeProjectQuiet:
    def test_quiet_output_minimal(self):
        with _patch_describe(SAMPLE_PROJECT):
            result = runner.invoke(
                app, ["project", "describe", "memory-hub", "--output", "quiet"]
            )

        assert result.exit_code == 0
        # Quiet mode should not print the table or project name
        assert "Members" not in result.output


# ── Help text ────────────────────────────────────────────────────────────────


class TestDescribeProjectHelp:
    def test_describe_in_help(self):
        result = runner.invoke(app, ["project", "--help"])
        assert result.exit_code == 0
        assert "describe" in result.output
