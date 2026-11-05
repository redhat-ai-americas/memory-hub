"""Tests for _get_client() dual auth mode."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from memoryhub_cli.main import _get_client


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for var in ("MEMORYHUB_API_KEY", "MEMORYHUB_URL", "MEMORYHUB_AUTH_URL",
                "MEMORYHUB_CLIENT_ID", "MEMORYHUB_CLIENT_SECRET"):
        monkeypatch.delenv(var, raising=False)


class TestGetClient:
    def test_api_key_mode(self, monkeypatch):
        monkeypatch.setattr("memoryhub_cli.main.get_api_key", lambda: "mh-dev-test")
        monkeypatch.setattr("memoryhub_cli.main.get_server_url", lambda: "https://mem.example.com")

        with patch("memoryhub.MemoryHubClient", autospec=True) as mock_cls:
            mock_cls.return_value = MagicMock()
            _get_client()
            mock_cls.assert_called_once_with(url="https://mem.example.com", api_key="mh-dev-test")

    def test_api_key_without_url_errors(self, monkeypatch):
        monkeypatch.setattr("memoryhub_cli.main.get_api_key", lambda: "mh-dev-test")
        monkeypatch.setattr("memoryhub_cli.main.get_server_url", lambda: None)

        with pytest.raises((SystemExit, RuntimeError)):
            _get_client()

    def test_oauth_fallback(self, monkeypatch):
        monkeypatch.setattr("memoryhub_cli.main.get_api_key", lambda: None)
        monkeypatch.setattr("memoryhub_cli.main.get_connection_params", lambda: {
            "url": "https://mem.example.com",
            "auth_url": "https://auth.example.com",
            "client_id": "cid",
            "client_secret": "csec",
        })

        with patch("memoryhub.MemoryHubClient", autospec=True) as mock_cls:
            mock_cls.return_value = MagicMock()
            _get_client()
            mock_cls.assert_called_once_with(
                url="https://mem.example.com",
                auth_url="https://auth.example.com",
                client_id="cid",
                client_secret="csec",
            )

    def test_named_context_selects_api_key_and_url(self, monkeypatch):
        monkeypatch.setattr(
            "memoryhub_cli.main.read_credentials_section",
            lambda context: {
                "api_key": "staging-key",
                "url": "https://staging.example.com/mcp/",
            } if context == "staging" else None,
        )
        monkeypatch.setattr(
            "memoryhub_cli.main.get_api_key",
            lambda context=None: "staging-key" if context == "staging" else None,
        )
        monkeypatch.setattr(
            "memoryhub_cli.main.get_server_url",
            lambda context=None: "https://staging.example.com/mcp/"
            if context == "staging" else None,
        )

        with patch("memoryhub.MemoryHubClient", autospec=True) as mock_cls:
            mock_cls.return_value = MagicMock()
            _get_client(context="staging")
            mock_cls.assert_called_once_with(
                url="https://staging.example.com/mcp/",
                api_key="staging-key",
            )

    def test_named_context_supplies_url_for_oauth_fallback(self, monkeypatch):
        monkeypatch.setattr(
            "memoryhub_cli.main.read_credentials_section",
            lambda context: {"url": "https://staging.example.com/mcp/"}
            if context == "staging" else None,
        )
        monkeypatch.setattr("memoryhub_cli.main.get_api_key", lambda context=None: None)
        monkeypatch.setattr(
            "memoryhub_cli.main.get_connection_params",
            lambda: {
                "url": "https://default.example.com/mcp/",
                "auth_url": "https://auth.example.com",
                "client_id": "cid",
                "client_secret": "csec",
            },
        )

        with patch("memoryhub.MemoryHubClient", autospec=True) as mock_cls:
            mock_cls.return_value = MagicMock()
            _get_client(context="staging")
            mock_cls.assert_called_once_with(
                url="https://staging.example.com/mcp/",
                auth_url="https://auth.example.com",
                client_id="cid",
                client_secret="csec",
            )

    def test_no_auth_at_all_errors(self, monkeypatch):
        monkeypatch.setattr("memoryhub_cli.main.get_api_key", lambda: None)
        monkeypatch.setattr("memoryhub_cli.main.get_connection_params", lambda: {
            "url": "", "auth_url": "", "client_id": "", "client_secret": "",
        })

        with pytest.raises((SystemExit, RuntimeError)):
            _get_client()
