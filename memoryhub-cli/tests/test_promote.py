"""Tests for the promote CLI command."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typer.testing import CliRunner

from memoryhub_cli.main import app

runner = CliRunner()


def _mock_memory(**overrides):
    """Build a mock Memory object with sensible defaults."""
    defaults = {
        "id": "abc-123-def-456",
        "scope": "organizational",
        "weight": 0.80,
        "content": "Promoted memory content",
        "version": 1,
    }
    defaults.update(overrides)
    mem = MagicMock()
    for k, v in defaults.items():
        setattr(mem, k, v)
    mem.model_dump.return_value = defaults
    return mem


@pytest.fixture(autouse=True)
def _stub_auth(monkeypatch):
    """Bypass auth so every invoke reaches the command logic."""
    monkeypatch.setattr("memoryhub_cli.main.get_api_key", lambda: "mh-dev-test")
    monkeypatch.setattr("memoryhub_cli.main.get_server_url", lambda: "https://mem.example.com")
    monkeypatch.setattr("memoryhub_cli.main._get_project_id_default", lambda: None)


class TestPromote:
    def test_table_output(self):
        mock_mem = _mock_memory()
        with patch("memoryhub_cli.main._get_client") as mock_gc:
            client = AsyncMock()
            client.promote.return_value = mock_mem
            client.__aenter__ = AsyncMock(return_value=client)
            client.__aexit__ = AsyncMock(return_value=False)
            mock_gc.return_value = client

            result = runner.invoke(app, ["promote", "abc-123", "organizational"])

        assert result.exit_code == 0
        assert "Promoted:" in result.output
        assert "abc-123-def-456" in result.output
        assert "organizational" in result.output
        assert "0.80" in result.output

    def test_json_output(self):
        mock_mem = _mock_memory()
        with patch("memoryhub_cli.main._get_client") as mock_gc:
            client = AsyncMock()
            client.promote.return_value = mock_mem
            client.__aenter__ = AsyncMock(return_value=client)
            client.__aexit__ = AsyncMock(return_value=False)
            mock_gc.return_value = client

            result = runner.invoke(app, ["promote", "abc-123", "organizational", "-o", "json"])

        assert result.exit_code == 0
        assert '"status": "ok"' in result.output
        assert "abc-123-def-456" in result.output

    def test_quiet_output(self):
        mock_mem = _mock_memory()
        with patch("memoryhub_cli.main._get_client") as mock_gc:
            client = AsyncMock()
            client.promote.return_value = mock_mem
            client.__aenter__ = AsyncMock(return_value=client)
            client.__aexit__ = AsyncMock(return_value=False)
            mock_gc.return_value = client

            result = runner.invoke(app, ["promote", "abc-123", "organizational", "-o", "quiet"])

        assert result.exit_code == 0
        assert result.output.strip() == ""

    def test_missing_required_args(self):
        result = runner.invoke(app, ["promote"])
        assert result.exit_code != 0

    def test_missing_target_scope(self):
        result = runner.invoke(app, ["promote", "abc-123"])
        assert result.exit_code != 0

    def test_passes_target_scope_id(self):
        mock_mem = _mock_memory()
        with patch("memoryhub_cli.main._get_client") as mock_gc:
            client = AsyncMock()
            client.promote.return_value = mock_mem
            client.__aenter__ = AsyncMock(return_value=client)
            client.__aexit__ = AsyncMock(return_value=False)
            mock_gc.return_value = client

            result = runner.invoke(app, [
                "promote", "abc-123", "project",
                "--target-scope-id", "my-project",
            ])

        assert result.exit_code == 0
        client.promote.assert_called_once_with(
            "abc-123", "project",
            target_scope_id="my-project",
            project_id=None,
        )

    def test_passes_project_id(self):
        mock_mem = _mock_memory()
        with patch("memoryhub_cli.main._get_client") as mock_gc:
            client = AsyncMock()
            client.promote.return_value = mock_mem
            client.__aenter__ = AsyncMock(return_value=client)
            client.__aexit__ = AsyncMock(return_value=False)
            mock_gc.return_value = client

            result = runner.invoke(app, [
                "promote", "abc-123", "organizational",
                "-p", "memory-hub",
            ])

        assert result.exit_code == 0
        client.promote.assert_called_once_with(
            "abc-123", "organizational",
            target_scope_id=None,
            project_id="memory-hub",
        )
