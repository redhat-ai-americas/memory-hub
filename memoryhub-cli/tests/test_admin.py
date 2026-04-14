"""Tests for memoryhub_cli.admin — admin subcommands."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import httpx
from typer.testing import CliRunner

from memoryhub_cli.main import app

runner = CliRunner()

# ── Fixtures ─────────────────────────────────────────────────────────────────

SAMPLE_CLIENT = {
    "client_id": "test-agent",
    "client_name": "test-agent",
    "identity_type": "user",
    "tenant_id": "default",
    "default_scopes": ["user", "project"],
    "redirect_uris": None,
    "public": False,
    "active": True,
    "created_at": "2026-04-14T12:00:00",
    "updated_at": "2026-04-14T12:00:00",
}

SAMPLE_CREATED = {**SAMPLE_CLIENT, "client_secret": "super-secret-value"}

SAMPLE_ROTATED = {
    "client_id": "test-agent",
    "client_secret": "new-secret-value",
}


def _mock_response(data, status_code=200):
    """Build a mock httpx.Response."""
    resp = httpx.Response(
        status_code=status_code,
        json=data,
        request=httpx.Request("GET", "http://test"),
    )
    return resp


def _mock_error_response(status_code, detail="error"):
    """Build a mock httpx.Response that triggers raise_for_status."""
    resp = httpx.Response(
        status_code=status_code,
        json={"detail": detail},
        request=httpx.Request("GET", "http://test"),
    )
    return resp


def _env_with_admin_key(**extra):
    """Base env vars for tests that need an admin key and auth URL."""
    env = {
        "MEMORYHUB_ADMIN_KEY": "test-admin-key",
        "MEMORYHUB_AUTH_URL": "http://auth.test",
    }
    env.update(extra)
    return env


# ── create-agent ─────────────────────────────────────────────────────────────


class TestCreateAgent:
    def test_happy_path(self):
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=_mock_response(SAMPLE_CREATED, 201))

        with patch.dict("os.environ", _env_with_admin_key(), clear=False):
            with patch("memoryhub_cli.admin.httpx.AsyncClient", return_value=mock_client):
                result = runner.invoke(app, ["admin", "create-agent", "test-agent"])

        assert result.exit_code == 0
        assert "test-agent" in result.output
        assert "super-secret-value" in result.output
        assert "Save this secret" in result.output

    def test_json_output(self):
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=_mock_response(SAMPLE_CREATED, 201))

        with patch.dict("os.environ", _env_with_admin_key(), clear=False):
            with patch("memoryhub_cli.admin.httpx.AsyncClient", return_value=mock_client):
                result = runner.invoke(
                    app, ["admin", "create-agent", "test-agent", "--json"]
                )

        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert parsed["client_id"] == "test-agent"
        assert parsed["client_secret"] == "super-secret-value"

    def test_write_config(self, tmp_path):
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=_mock_response(SAMPLE_CREATED, 201))

        with patch.dict("os.environ", _env_with_admin_key(), clear=False):
            with patch("memoryhub_cli.admin.httpx.AsyncClient", return_value=mock_client):
                with patch("memoryhub_cli.admin.CONFIG_DIR", tmp_path):
                    result = runner.invoke(
                        app,
                        ["admin", "create-agent", "test-agent", "--write-config"],
                    )

        assert result.exit_code == 0
        api_key_file = tmp_path / "api-key"
        assert api_key_file.exists()
        assert api_key_file.read_text() == "super-secret-value"

    def test_conflict_409(self):
        error_resp = _mock_error_response(
            409, "Client with client_id 'test-agent' already exists"
        )
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(
            side_effect=httpx.HTTPStatusError(
                "conflict", request=error_resp.request, response=error_resp
            )
        )

        with patch.dict("os.environ", _env_with_admin_key(), clear=False):
            with patch("memoryhub_cli.admin.httpx.AsyncClient", return_value=mock_client):
                result = runner.invoke(app, ["admin", "create-agent", "test-agent"])

        assert result.exit_code == 1
        assert "Conflict" in result.output


# ── list-agents ──────────────────────────────────────────────────────────────


class TestListAgents:
    def test_happy_path(self):
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(
            return_value=_mock_response([SAMPLE_CLIENT])
        )

        with patch.dict("os.environ", _env_with_admin_key(), clear=False):
            with patch("memoryhub_cli.admin.httpx.AsyncClient", return_value=mock_client):
                result = runner.invoke(app, ["admin", "list-agents"])

        assert result.exit_code == 0
        assert "test-agent" in result.output
        assert "Yes" in result.output  # active

    def test_json_output(self):
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(
            return_value=_mock_response([SAMPLE_CLIENT])
        )

        with patch.dict("os.environ", _env_with_admin_key(), clear=False):
            with patch("memoryhub_cli.admin.httpx.AsyncClient", return_value=mock_client):
                result = runner.invoke(app, ["admin", "list-agents", "--json"])

        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert len(parsed) == 1
        assert parsed[0]["client_id"] == "test-agent"

    def test_empty_list(self):
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=_mock_response([]))

        with patch.dict("os.environ", _env_with_admin_key(), clear=False):
            with patch("memoryhub_cli.admin.httpx.AsyncClient", return_value=mock_client):
                result = runner.invoke(app, ["admin", "list-agents"])

        assert result.exit_code == 0
        assert "No agents registered" in result.output


# ── rotate-secret ────────────────────────────────────────────────────────────


class TestRotateSecret:
    def test_happy_path(self):
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(
            return_value=_mock_response(SAMPLE_ROTATED)
        )

        with patch.dict("os.environ", _env_with_admin_key(), clear=False):
            with patch("memoryhub_cli.admin.httpx.AsyncClient", return_value=mock_client):
                result = runner.invoke(
                    app, ["admin", "rotate-secret", "test-agent"]
                )

        assert result.exit_code == 0
        assert "new-secret-value" in result.output
        assert "rotated" in result.output.lower()

    def test_json_output(self):
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(
            return_value=_mock_response(SAMPLE_ROTATED)
        )

        with patch.dict("os.environ", _env_with_admin_key(), clear=False):
            with patch("memoryhub_cli.admin.httpx.AsyncClient", return_value=mock_client):
                result = runner.invoke(
                    app, ["admin", "rotate-secret", "test-agent", "--json"]
                )

        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert parsed["client_secret"] == "new-secret-value"

    def test_not_found(self):
        error_resp = _mock_error_response(404, "Client 'ghost' not found")
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(
            side_effect=httpx.HTTPStatusError(
                "not found", request=error_resp.request, response=error_resp
            )
        )

        with patch.dict("os.environ", _env_with_admin_key(), clear=False):
            with patch("memoryhub_cli.admin.httpx.AsyncClient", return_value=mock_client):
                result = runner.invoke(app, ["admin", "rotate-secret", "ghost"])

        assert result.exit_code == 1
        assert "Not found" in result.output


# ── disable-agent ────────────────────────────────────────────────────────────


class TestDisableAgent:
    def test_happy_path(self):
        disabled = {**SAMPLE_CLIENT, "active": False}
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.patch = AsyncMock(return_value=_mock_response(disabled))

        with patch.dict("os.environ", _env_with_admin_key(), clear=False):
            with patch("memoryhub_cli.admin.httpx.AsyncClient", return_value=mock_client):
                result = runner.invoke(
                    app, ["admin", "disable-agent", "test-agent"]
                )

        assert result.exit_code == 0
        assert "disabled" in result.output.lower()


# ── Missing admin key ────────────────────────────────────────────────────────


class TestMissingAdminKey:
    def test_no_admin_key_errors(self):
        """When no admin key is available, commands should fail with a clear message."""
        env = {"MEMORYHUB_AUTH_URL": "http://auth.test"}
        with patch.dict("os.environ", env, clear=False):
            # Ensure config file returns no admin_key either
            with patch("memoryhub_cli.admin.load_config", return_value={}):
                result = runner.invoke(app, ["admin", "list-agents"])

        assert result.exit_code == 1
        assert "admin key" in result.output.lower()


# ── HTTP error handling ──────────────────────────────────────────────────────


class TestHttpErrors:
    def test_401_auth_failed(self):
        error_resp = _mock_error_response(401, "Invalid or missing admin key")
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(
            side_effect=httpx.HTTPStatusError(
                "unauthorized", request=error_resp.request, response=error_resp
            )
        )

        with patch.dict("os.environ", _env_with_admin_key(), clear=False):
            with patch("memoryhub_cli.admin.httpx.AsyncClient", return_value=mock_client):
                result = runner.invoke(app, ["admin", "list-agents"])

        assert result.exit_code == 1
        assert "Authentication failed" in result.output

    def test_generic_http_error(self):
        error_resp = _mock_error_response(500, "Internal server error")
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(
            side_effect=httpx.HTTPStatusError(
                "server error", request=error_resp.request, response=error_resp
            )
        )

        with patch.dict("os.environ", _env_with_admin_key(), clear=False):
            with patch("memoryhub_cli.admin.httpx.AsyncClient", return_value=mock_client):
                result = runner.invoke(app, ["admin", "list-agents"])

        assert result.exit_code == 1
        assert "HTTP 500" in result.output
