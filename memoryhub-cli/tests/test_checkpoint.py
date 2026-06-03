"""Tests for the checkpoint CLI command."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typer.testing import CliRunner

from memoryhub_cli.main import app

runner = CliRunner()


# ── Helpers ─────────────────────────────────────────────────────────────────


def _stub_client(checkpoint_return):
    """Build a mock MemoryHubClient whose checkpoint() returns the given value."""
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.checkpoint = AsyncMock(return_value=checkpoint_return)
    return client


def _patch_client(client_mock):
    """Context manager that patches _get_client and _get_project_id_default."""
    return (
        patch("memoryhub_cli.main._get_client", return_value=client_mock),
        patch("memoryhub_cli.main._get_project_id_default", return_value=None),
    )


READ_RESPONSE = {
    "workflow_name": "daily-digest",
    "state": {"last_run": "2026-06-02", "cursor": 42},
}

UPSERT_CREATED = {
    "workflow_name": "daily-digest",
    "state": {"last_run": "2026-06-03"},
    "created": True,
    "memory_id": "abc-123-def",
}

UPSERT_UPDATED = {
    "workflow_name": "daily-digest",
    "state": {"last_run": "2026-06-03"},
    "created": False,
    "memory_id": "abc-123-def",
}


# ── Tests ───────────────────────────────────────────────────────────────────


class TestCheckpointRead:
    """checkpoint <workflow> without --state reads existing checkpoint."""

    def test_read_checkpoint_table(self):
        client = _stub_client(READ_RESPONSE)
        p1, p2 = _patch_client(client)
        with p1, p2:
            result = runner.invoke(app, ["checkpoint", "daily-digest"])

        assert result.exit_code == 0
        assert "Checkpoint:" in result.output
        assert "daily-digest" in result.output
        assert "last_run" in result.output
        client.checkpoint.assert_awaited_once_with(
            "daily-digest", state=None, scope="user", project_id=None,
        )

    def test_read_empty_state(self):
        client = _stub_client({"workflow_name": "wf", "state": {}})
        p1, p2 = _patch_client(client)
        with p1, p2:
            result = runner.invoke(app, ["checkpoint", "wf"])

        assert result.exit_code == 0
        assert "(empty)" in result.output


class TestCheckpointUpsert:
    """checkpoint <workflow> --state '...' upserts."""

    def test_upsert_created(self):
        client = _stub_client(UPSERT_CREATED)
        p1, p2 = _patch_client(client)
        with p1, p2:
            result = runner.invoke(
                app,
                ["checkpoint", "daily-digest", "--state", '{"last_run":"2026-06-03"}'],
            )

        assert result.exit_code == 0
        assert "Created checkpoint:" in result.output
        assert "abc-123-def" in result.output
        client.checkpoint.assert_awaited_once_with(
            "daily-digest",
            state={"last_run": "2026-06-03"},
            scope="user",
            project_id=None,
        )

    def test_upsert_updated(self):
        client = _stub_client(UPSERT_UPDATED)
        p1, p2 = _patch_client(client)
        with p1, p2:
            result = runner.invoke(
                app,
                ["checkpoint", "daily-digest", "--state", '{"last_run":"2026-06-03"}'],
            )

        assert result.exit_code == 0
        assert "Updated checkpoint:" in result.output

    def test_scope_and_project_forwarded(self):
        client = _stub_client(UPSERT_CREATED)
        p1, p2 = _patch_client(client)
        with p1, p2:
            result = runner.invoke(
                app,
                [
                    "checkpoint", "wf",
                    "--state", '{"k": 1}',
                    "--scope", "project",
                    "--project-id", "my-proj",
                ],
            )

        assert result.exit_code == 0
        client.checkpoint.assert_awaited_once_with(
            "wf",
            state={"k": 1},
            scope="project",
            project_id="my-proj",
        )


class TestCheckpointInvalidJson:
    """--state with non-JSON text should fail."""

    def test_invalid_json_exits_with_error(self):
        # _get_client should not even be called for invalid JSON
        p1 = patch("memoryhub_cli.main._get_client", side_effect=AssertionError("should not be called"))
        p2 = patch("memoryhub_cli.main._get_project_id_default", return_value=None)
        with p1, p2:
            result = runner.invoke(
                app,
                ["checkpoint", "wf", "--state", "not-json"],
            )

        assert result.exit_code == 1
        assert "invalid_json" in result.output or "must be valid JSON" in result.output


class TestCheckpointJsonOutput:
    """--output json wraps result in the standard envelope."""

    def test_json_read(self):
        client = _stub_client(READ_RESPONSE)
        p1, p2 = _patch_client(client)
        with p1, p2:
            result = runner.invoke(
                app,
                ["checkpoint", "daily-digest", "--output", "json"],
            )

        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert parsed["status"] == "ok"
        assert parsed["data"]["workflow_name"] == "daily-digest"
        assert parsed["data"]["state"]["cursor"] == 42

    def test_json_upsert(self):
        client = _stub_client(UPSERT_CREATED)
        p1, p2 = _patch_client(client)
        with p1, p2:
            result = runner.invoke(
                app,
                [
                    "checkpoint", "daily-digest",
                    "--state", '{"last_run":"2026-06-03"}',
                    "--output", "json",
                ],
            )

        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert parsed["data"]["created"] is True
        assert parsed["data"]["memory_id"] == "abc-123-def"


class TestCheckpointQuietOutput:
    """--output quiet produces no output."""

    def test_quiet_read(self):
        client = _stub_client(READ_RESPONSE)
        p1, p2 = _patch_client(client)
        with p1, p2:
            result = runner.invoke(
                app,
                ["checkpoint", "daily-digest", "--output", "quiet"],
            )

        assert result.exit_code == 0
        assert result.output.strip() == ""
