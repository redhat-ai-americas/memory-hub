"""Tests for memoryhub_cli.config — API key detection, server URL resolution, and config init URL prompt."""

from __future__ import annotations

import json

import pytest

from memoryhub_cli.config import get_api_key, get_server_url, load_config, save_config


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Remove MemoryHub env vars so tests start from a clean slate."""
    for var in ("MEMORYHUB_API_KEY", "MEMORYHUB_URL", "MEMORYHUB_AUTH_URL",
                "MEMORYHUB_CLIENT_ID", "MEMORYHUB_CLIENT_SECRET"):
        monkeypatch.delenv(var, raising=False)


class TestGetApiKey:
    def test_env_var_wins(self, monkeypatch):
        monkeypatch.setenv("MEMORYHUB_API_KEY", "mh-dev-from-env")
        assert get_api_key() == "mh-dev-from-env"

    def test_key_file_second(self, monkeypatch, tmp_path):
        key_file = tmp_path / "api-key"
        key_file.write_text("mh-dev-from-file\n")
        monkeypatch.setattr("memoryhub_cli.config.API_KEY_FILE", key_file)
        assert get_api_key() == "mh-dev-from-file"

    def test_config_json_third(self, monkeypatch, tmp_path):
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({"api_key": "mh-dev-from-config"}))
        monkeypatch.setattr("memoryhub_cli.config.CONFIG_FILE", config_file)
        # Also ensure key file doesn't exist
        monkeypatch.setattr("memoryhub_cli.config.API_KEY_FILE", tmp_path / "nope")
        assert get_api_key() == "mh-dev-from-config"

    def test_env_var_overrides_file(self, monkeypatch, tmp_path):
        monkeypatch.setenv("MEMORYHUB_API_KEY", "mh-dev-env")
        key_file = tmp_path / "api-key"
        key_file.write_text("mh-dev-file")
        monkeypatch.setattr("memoryhub_cli.config.API_KEY_FILE", key_file)
        assert get_api_key() == "mh-dev-env"

    def test_returns_none_when_nothing_set(self, monkeypatch, tmp_path):
        monkeypatch.setattr("memoryhub_cli.config.API_KEY_FILE", tmp_path / "nope")
        monkeypatch.setattr("memoryhub_cli.config.CONFIG_FILE", tmp_path / "nope.json")
        assert get_api_key() is None

    def test_whitespace_stripped(self, monkeypatch):
        monkeypatch.setenv("MEMORYHUB_API_KEY", "  mh-dev-padded  ")
        assert get_api_key() == "mh-dev-padded"

    def test_empty_env_var_skipped(self, monkeypatch, tmp_path):
        monkeypatch.setenv("MEMORYHUB_API_KEY", "")
        monkeypatch.setattr("memoryhub_cli.config.API_KEY_FILE", tmp_path / "nope")
        monkeypatch.setattr("memoryhub_cli.config.CONFIG_FILE", tmp_path / "nope.json")
        assert get_api_key() is None


class TestGetServerUrl:
    def test_env_var_wins(self, monkeypatch):
        monkeypatch.setenv("MEMORYHUB_URL", "https://mem.example.com")
        assert get_server_url() == "https://mem.example.com"

    def test_config_fallback(self, monkeypatch, tmp_path):
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({"url": "https://from-config.example.com"}))
        monkeypatch.setattr("memoryhub_cli.config.CONFIG_FILE", config_file)
        assert get_server_url() == "https://from-config.example.com"

    def test_returns_none_when_nothing_set(self, monkeypatch, tmp_path):
        monkeypatch.setattr("memoryhub_cli.config.CONFIG_FILE", tmp_path / "nope.json")
        assert get_server_url() is None


class TestSaveConfigMerge:
    """Verify save_config writes to config.json and preserves existing keys."""

    def test_save_creates_file(self, monkeypatch, tmp_path):
        config_dir = tmp_path / "memoryhub"
        config_file = config_dir / "config.json"
        monkeypatch.setattr("memoryhub_cli.config.CONFIG_DIR", config_dir)
        monkeypatch.setattr("memoryhub_cli.config.CONFIG_FILE", config_file)
        save_config({"url": "https://example.com/mcp/"})
        data = json.loads(config_file.read_text())
        assert data["url"] == "https://example.com/mcp/"

    def test_save_preserves_existing_keys(self, monkeypatch, tmp_path):
        config_dir = tmp_path / "memoryhub"
        config_dir.mkdir()
        config_file = config_dir / "config.json"
        config_file.write_text(json.dumps({"client_id": "old", "url": "old-url"}))
        monkeypatch.setattr("memoryhub_cli.config.CONFIG_DIR", config_dir)
        monkeypatch.setattr("memoryhub_cli.config.CONFIG_FILE", config_file)
        existing = load_config()
        existing["url"] = "https://new.example.com/mcp/"
        save_config(existing)
        data = json.loads(config_file.read_text())
        assert data["url"] == "https://new.example.com/mcp/"
        assert data["client_id"] == "old"
