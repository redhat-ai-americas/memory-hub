"""Tests for CLI parity commands: promote, graduate, checkpoint, project describe."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

from typer.testing import CliRunner

from memoryhub.exceptions import NotFoundError
from memoryhub.models import Memory
from memoryhub_cli.main import app

runner = CliRunner()

# ── Fixtures ─────────────────────────────────────────────────────────────────

SAMPLE_MEMORY = Memory(
    id="aaaa-bbbb-cccc-dddd",
    content="Test content",
    scope="organizational",
    weight=0.7,
    version=1,
    content_type="knowledge",
    owner_id="test-user",
)

SAMPLE_BEHAVIORAL = Memory(
    id="eeee-ffff-gggg-hhhh",
    content="Experiential memory",
    scope="user",
    weight=0.6,
    version=1,
    content_type="behavioral",
    owner_id="test-user",
)

SAMPLE_CHECKPOINT_WRITE = {
    "workflow_name": "my-workflow",
    "state": {"step": 3, "progress": "halfway"},
    "created": True,
    "memory_id": "checkpoint-mem-id",
}

SAMPLE_CHECKPOINT_READ = {
    "workflow_name": "my-workflow",
    "state": {"step": 3, "progress": "halfway"},
    "created": False,
    "memory_id": "checkpoint-mem-id",
}

SAMPLE_CHECKPOINT_EMPTY = {
    "workflow_name": "my-workflow",
    "state": None,
    "created": False,
    "memory_id": None,
}

SAMPLE_PROJECT_DESC = {
    "project": {
        "name": "my-project",
        "description": "Test project",
        "invite_only": False,
        "memory_count": 42,
        "created_by": "alice",
        "created_at": "2026-01-01T12:00:00",
    },
    "members": [
        {"user_id": "alice", "role": "owner", "joined_at": "2026-01-01T12:00:00"},
        {"user_id": "bob", "role": "member", "joined_at": "2026-01-02T14:30:00"},
    ],
    "total_members": 2,
}


def _mock_client(**overrides):
    """Build a mock MemoryHubClient with async context manager support."""
    mock = AsyncMock()
    mock.__aenter__ = AsyncMock(return_value=mock)
    mock.__aexit__ = AsyncMock(return_value=False)
    for k, v in overrides.items():
        setattr(mock, k, v)
    return mock


# ── promote ──────────────────────────────────────────────────────────────────


class TestPromote:
    def test_happy_path(self):
        promoted = SAMPLE_MEMORY.model_copy(update={"scope": "organizational"})
        mock_client = _mock_client(promote=AsyncMock(return_value=promoted))

        with patch("memoryhub_cli.main._get_client", return_value=mock_client):
            result = runner.invoke(app, ["promote", "mem-id", "organizational"])

        assert result.exit_code == 0
        assert "Promoted" in result.output
        assert promoted.id in result.output

    def test_json_output(self):
        promoted = SAMPLE_MEMORY.model_copy(update={"scope": "organizational"})
        mock_client = _mock_client(promote=AsyncMock(return_value=promoted))

        with patch("memoryhub_cli.main._get_client", return_value=mock_client):
            result = runner.invoke(
                app, ["promote", "mem-id", "organizational", "--output", "json"]
            )

        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert parsed["status"] == "ok"
        assert parsed["data"]["id"] == promoted.id
        assert parsed["data"]["scope"] == "organizational"

    def test_with_target_scope_id(self):
        promoted = SAMPLE_MEMORY.model_copy(update={"scope": "project"})
        mock_promote = AsyncMock(return_value=promoted)
        mock_client = _mock_client(promote=mock_promote)

        with patch("memoryhub_cli.main._get_client", return_value=mock_client):
            result = runner.invoke(
                app,
                [
                    "promote",
                    "mem-id",
                    "project",
                    "--target-scope-id",
                    "proj-1",
                ],
            )

        assert result.exit_code == 0
        mock_promote.assert_called_once()
        call_kwargs = mock_promote.call_args[1]
        assert call_kwargs["target_scope_id"] == "proj-1"

    def test_not_found(self):
        mock_promote = AsyncMock(
            side_effect=NotFoundError("mem-id", "Memory not found")
        )
        mock_client = _mock_client(promote=mock_promote)

        with patch("memoryhub_cli.main._get_client", return_value=mock_client):
            result = runner.invoke(app, ["promote", "mem-id", "organizational"])

        assert result.exit_code == 1
        assert "not_found" in result.output or "not found" in result.output.lower()


# ── graduate ─────────────────────────────────────────────────────────────────


class TestGraduate:
    def test_happy_path(self):
        graduated = SAMPLE_BEHAVIORAL.model_copy(
            update={"content_type": "knowledge"}
        )
        mock_client = _mock_client(graduate=AsyncMock(return_value=graduated))

        with patch("memoryhub_cli.main._get_client", return_value=mock_client):
            result = runner.invoke(app, ["graduate", "mem-id"])

        assert result.exit_code == 0
        assert "Graduated" in result.output
        assert graduated.id in result.output

    def test_json_output(self):
        graduated = SAMPLE_BEHAVIORAL.model_copy(
            update={"content_type": "knowledge"}
        )
        mock_client = _mock_client(graduate=AsyncMock(return_value=graduated))

        with patch("memoryhub_cli.main._get_client", return_value=mock_client):
            result = runner.invoke(app, ["graduate", "mem-id", "--output", "json"])

        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert parsed["status"] == "ok"
        assert parsed["data"]["id"] == graduated.id
        assert parsed["data"]["content_type"] == "knowledge"

    def test_with_evidence(self):
        graduated = SAMPLE_BEHAVIORAL.model_copy(
            update={"content_type": "knowledge"}
        )
        mock_graduate = AsyncMock(return_value=graduated)
        mock_client = _mock_client(graduate=mock_graduate)

        with patch("memoryhub_cli.main._get_client", return_value=mock_client):
            result = runner.invoke(
                app,
                ["graduate", "mem-id", "--evidence", "Supporting proof"],
            )

        assert result.exit_code == 0
        assert "Evidence branch" in result.output
        mock_graduate.assert_called_once()
        call_kwargs = mock_graduate.call_args[1]
        assert call_kwargs["evidence"] == "Supporting proof"

    def test_not_found(self):
        mock_graduate = AsyncMock(
            side_effect=NotFoundError("mem-id", "Memory not found")
        )
        mock_client = _mock_client(graduate=mock_graduate)

        with patch("memoryhub_cli.main._get_client", return_value=mock_client):
            result = runner.invoke(app, ["graduate", "mem-id"])

        assert result.exit_code == 1
        assert "not_found" in result.output or "not found" in result.output.lower()


# ── checkpoint ───────────────────────────────────────────────────────────────


class TestCheckpoint:
    def test_write(self):
        mock_client = _mock_client(
            checkpoint=AsyncMock(return_value=SAMPLE_CHECKPOINT_WRITE)
        )

        with patch("memoryhub_cli.main._get_client", return_value=mock_client):
            result = runner.invoke(
                app,
                [
                    "checkpoint",
                    "my-workflow",
                    "--state",
                    '{"step": 3, "progress": "halfway"}',
                ],
            )

        assert result.exit_code == 0
        assert "Created checkpoint" in result.output
        assert "my-workflow" in result.output

    def test_read(self):
        mock_client = _mock_client(
            checkpoint=AsyncMock(return_value=SAMPLE_CHECKPOINT_READ)
        )

        with patch("memoryhub_cli.main._get_client", return_value=mock_client):
            result = runner.invoke(app, ["checkpoint", "my-workflow"])

        assert result.exit_code == 0
        assert "Checkpoint" in result.output
        assert "my-workflow" in result.output
        assert "step" in result.output

    def test_read_no_state(self):
        mock_client = _mock_client(
            checkpoint=AsyncMock(return_value=SAMPLE_CHECKPOINT_EMPTY)
        )

        with patch("memoryhub_cli.main._get_client", return_value=mock_client):
            result = runner.invoke(app, ["checkpoint", "my-workflow"])

        assert result.exit_code == 0
        assert "No checkpoint found" in result.output

    def test_json_output(self):
        mock_client = _mock_client(
            checkpoint=AsyncMock(return_value=SAMPLE_CHECKPOINT_WRITE)
        )

        with patch("memoryhub_cli.main._get_client", return_value=mock_client):
            result = runner.invoke(
                app,
                [
                    "checkpoint",
                    "my-workflow",
                    "--state",
                    '{"step": 3}',
                    "--output",
                    "json",
                ],
            )

        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert parsed["status"] == "ok"
        assert parsed["data"]["workflow_name"] == "my-workflow"

    def test_invalid_json(self):
        mock_client = _mock_client(
            checkpoint=AsyncMock(return_value=SAMPLE_CHECKPOINT_WRITE)
        )

        with patch("memoryhub_cli.main._get_client", return_value=mock_client):
            result = runner.invoke(
                app, ["checkpoint", "my-workflow", "--state", "not-json"]
            )

        assert result.exit_code == 1
        assert "invalid_json" in result.output


# ── project describe ─────────────────────────────────────────────────────────


class TestProjectDescribe:
    def test_happy_path(self):
        mock_client = _mock_client(
            describe_project=AsyncMock(return_value=SAMPLE_PROJECT_DESC)
        )

        with patch("memoryhub_cli.main._get_client", return_value=mock_client):
            result = runner.invoke(app, ["project", "describe", "my-project"])

        assert result.exit_code == 0
        assert "my-project" in result.output
        assert "alice" in result.output
        assert "bob" in result.output
        assert "owner" in result.output
        assert "member" in result.output

    def test_json_output(self):
        mock_client = _mock_client(
            describe_project=AsyncMock(return_value=SAMPLE_PROJECT_DESC)
        )

        with patch("memoryhub_cli.main._get_client", return_value=mock_client):
            result = runner.invoke(
                app, ["project", "describe", "my-project", "--output", "json"]
            )

        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert parsed["status"] == "ok"
        assert parsed["data"]["project"]["name"] == "my-project"
        assert len(parsed["data"]["members"]) == 2

    def test_not_found(self):
        mock_describe = AsyncMock(
            side_effect=NotFoundError("my-project", "Project not found")
        )
        mock_client = _mock_client(describe_project=mock_describe)

        with patch("memoryhub_cli.main._get_client", return_value=mock_client):
            result = runner.invoke(app, ["project", "describe", "ghost-project"])

        assert result.exit_code == 1
        assert "not_found" in result.output or "not found" in result.output.lower()
