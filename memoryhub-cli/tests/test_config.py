"""Tests for memoryhub_cli.config -- API key, server URL, and config merge."""

from __future__ import annotations

import configparser
import json

import pytest

from memoryhub_cli.config import (
    get_api_key,
    get_credentials,
    get_server_url,
    load_config,
    migrate_flat_to_credentials,
    read_credentials_section,
    save_config,
    write_credentials_section,
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Remove MemoryHub env vars so tests start from a clean slate."""
    for var in ("MEMORYHUB_API_KEY", "MEMORYHUB_URL", "MEMORYHUB_AUTH_URL",
                "MEMORYHUB_CLIENT_ID", "MEMORYHUB_CLIENT_SECRET",
                "MEMORYHUB_CONTEXT"):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture()
def _no_files(monkeypatch, tmp_path):
    """Point all config paths to nonexistent files under tmp_path."""
    monkeypatch.setattr("memoryhub_cli.config.CONFIG_DIR", tmp_path)
    monkeypatch.setattr("memoryhub_cli.config.API_KEY_FILE", tmp_path / "api-key")
    monkeypatch.setattr("memoryhub_cli.config.CREDENTIALS_FILE", tmp_path / "credentials")
    monkeypatch.setattr("memoryhub_cli.config.CONFIG_FILE", tmp_path / "config.json")
    return tmp_path


class TestGetApiKey:
    def test_env_var_wins(self, monkeypatch):
        monkeypatch.setenv("MEMORYHUB_API_KEY", "mh-dev-from-env")
        assert get_api_key() == "mh-dev-from-env"

    def test_key_file_second(self, monkeypatch, tmp_path):
        key_file = tmp_path / "api-key"
        key_file.write_text("mh-dev-from-file\n")
        monkeypatch.setattr("memoryhub_cli.config.API_KEY_FILE", key_file)
        monkeypatch.setattr("memoryhub_cli.config.CREDENTIALS_FILE", tmp_path / "nope")
        assert get_api_key() == "mh-dev-from-file"

    def test_config_json_third(self, monkeypatch, tmp_path):
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({"api_key": "mh-dev-from-config"}))
        monkeypatch.setattr("memoryhub_cli.config.CONFIG_FILE", config_file)
        monkeypatch.setattr("memoryhub_cli.config.API_KEY_FILE", tmp_path / "nope")
        monkeypatch.setattr("memoryhub_cli.config.CREDENTIALS_FILE", tmp_path / "nope2")
        assert get_api_key() == "mh-dev-from-config"

    def test_env_var_overrides_file(self, monkeypatch, tmp_path):
        monkeypatch.setenv("MEMORYHUB_API_KEY", "mh-dev-env")
        key_file = tmp_path / "api-key"
        key_file.write_text("mh-dev-file")
        monkeypatch.setattr("memoryhub_cli.config.API_KEY_FILE", key_file)
        assert get_api_key() == "mh-dev-env"

    def test_returns_none_when_nothing_set(self, monkeypatch, tmp_path):
        monkeypatch.setattr("memoryhub_cli.config.API_KEY_FILE", tmp_path / "nope")
        monkeypatch.setattr("memoryhub_cli.config.CREDENTIALS_FILE", tmp_path / "nope2")
        monkeypatch.setattr("memoryhub_cli.config.CONFIG_FILE", tmp_path / "nope.json")
        assert get_api_key() is None

    def test_whitespace_stripped(self, monkeypatch):
        monkeypatch.setenv("MEMORYHUB_API_KEY", "  mh-dev-padded  ")
        assert get_api_key() == "mh-dev-padded"

    def test_empty_env_var_skipped(self, monkeypatch, tmp_path):
        monkeypatch.setenv("MEMORYHUB_API_KEY", "")
        monkeypatch.setattr("memoryhub_cli.config.API_KEY_FILE", tmp_path / "nope")
        monkeypatch.setattr("memoryhub_cli.config.CREDENTIALS_FILE", tmp_path / "nope2")
        monkeypatch.setattr("memoryhub_cli.config.CONFIG_FILE", tmp_path / "nope.json")
        assert get_api_key() is None

    def test_flat_file_skips_comment_lines(self, _no_files, tmp_path):
        key_file = tmp_path / "api-key"
        key_file.write_text(
            "# migrated to credentials\n"
            "# you can delete this file\n"
            "mh-dev-actual-key\n"
        )
        assert get_api_key() == "mh-dev-actual-key"


class TestGetServerUrl:
    def test_env_var_wins(self, monkeypatch):
        monkeypatch.setenv("MEMORYHUB_URL", "https://mem.example.com")
        assert get_server_url() == "https://mem.example.com"

    def test_config_fallback(self, monkeypatch, tmp_path):
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({"url": "https://from-config.example.com"}))
        monkeypatch.setattr("memoryhub_cli.config.CONFIG_FILE", config_file)
        monkeypatch.setattr("memoryhub_cli.config.CREDENTIALS_FILE", tmp_path / "nope")
        assert get_server_url() == "https://from-config.example.com"

    def test_returns_none_when_nothing_set(self, monkeypatch, tmp_path):
        monkeypatch.setattr("memoryhub_cli.config.CONFIG_FILE", tmp_path / "nope.json")
        monkeypatch.setattr("memoryhub_cli.config.CREDENTIALS_FILE", tmp_path / "nope")
        assert get_server_url() is None

    def test_credentials_file_url(self, _no_files, tmp_path):
        creds = tmp_path / "credentials"
        creds.write_text("[default]\nurl = https://from-creds.example.com\n")
        assert get_server_url() == "https://from-creds.example.com"

    def test_env_overrides_credentials_url(self, _no_files, tmp_path, monkeypatch):
        creds = tmp_path / "credentials"
        creds.write_text("[default]\nurl = https://from-creds.example.com\n")
        monkeypatch.setenv("MEMORYHUB_URL", "https://from-env.example.com")
        assert get_server_url() == "https://from-env.example.com"


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


class TestReadCredentialsSection:
    def test_reads_named_section(self, _no_files, tmp_path):
        creds = tmp_path / "credentials"
        creds.write_text(
            "[cluster-a]\napi_key = key-a\nurl = https://a.example.com\n\n"
            "[cluster-b]\napi_key = key-b\n"
        )
        result = read_credentials_section("cluster-a")
        assert result == {"api_key": "key-a", "url": "https://a.example.com"}

    def test_context_from_env(self, _no_files, tmp_path, monkeypatch):
        creds = tmp_path / "credentials"
        creds.write_text("[my-ctx]\napi_key = key-ctx\n")
        monkeypatch.setenv("MEMORYHUB_CONTEXT", "my-ctx")
        result = read_credentials_section()
        assert result["api_key"] == "key-ctx"

    def test_falls_back_to_default(self, _no_files, tmp_path):
        creds = tmp_path / "credentials"
        creds.write_text("[default]\napi_key = key-default\n")
        assert read_credentials_section()["api_key"] == "key-default"

    def test_missing_context_returns_none(self, _no_files, tmp_path, monkeypatch):
        """When MEMORYHUB_CONTEXT names a missing section, return None."""
        creds = tmp_path / "credentials"
        creds.write_text("[default]\napi_key = key-default\n")
        monkeypatch.setenv("MEMORYHUB_CONTEXT", "nonexistent")
        assert read_credentials_section() is None

    def test_explicit_context_returns_none_if_missing(self, _no_files, tmp_path):
        creds = tmp_path / "credentials"
        creds.write_text("[default]\napi_key = key-default\n")
        assert read_credentials_section("nonexistent") is None

    def test_missing_file_returns_none(self, _no_files):
        assert read_credentials_section() is None

    def test_missing_section_returns_none(self, _no_files, tmp_path):
        creds = tmp_path / "credentials"
        creds.write_text("[other]\napi_key = other-key\n")
        assert read_credentials_section("missing") is None

    def test_percent_in_key_not_interpolated(self, _no_files, tmp_path):
        creds = tmp_path / "credentials"
        creds.write_text("[default]\napi_key = mh-dev-100%done\n")
        assert read_credentials_section()["api_key"] == "mh-dev-100%done"


class TestWriteCredentialsSection:
    def test_creates_file(self, _no_files, tmp_path):
        write_credentials_section("test-ctx", "mh-dev-abc123", "https://test.example.com")
        creds = tmp_path / "credentials"
        assert creds.exists()
        content = creds.read_text()
        assert "# MemoryHub credentials" in content

        cp = configparser.ConfigParser(interpolation=None)
        cp.read(creds)
        assert cp.get("test-ctx", "api_key") == "mh-dev-abc123"
        assert cp.get("test-ctx", "url") == "https://test.example.com"

    def test_preserves_other_sections(self, _no_files, tmp_path):
        write_credentials_section("ctx-a", "key-a")
        write_credentials_section("ctx-b", "key-b", "https://b.example.com")

        cp = configparser.ConfigParser(interpolation=None)
        cp.read(tmp_path / "credentials")
        assert cp.get("ctx-a", "api_key") == "key-a"
        assert cp.get("ctx-b", "api_key") == "key-b"

    def test_overwrites_existing_section(self, _no_files, tmp_path):
        write_credentials_section("ctx", "old-key")
        write_credentials_section("ctx", "new-key", "https://new.example.com")

        cp = configparser.ConfigParser(interpolation=None)
        cp.read(tmp_path / "credentials")
        assert cp.get("ctx", "api_key") == "new-key"
        assert cp.get("ctx", "url") == "https://new.example.com"

    def test_file_permissions(self, _no_files, tmp_path):
        write_credentials_section("ctx", "key")
        mode = (tmp_path / "credentials").stat().st_mode & 0o777
        assert mode == 0o600

    def test_url_omitted_when_none(self, _no_files, tmp_path):
        write_credentials_section("ctx", "key")
        cp = configparser.ConfigParser(interpolation=None)
        cp.read(tmp_path / "credentials")
        assert cp.get("ctx", "api_key") == "key"
        assert not cp.has_option("ctx", "url")


class TestMigration:
    def test_creates_credentials_from_flat(self, _no_files, tmp_path):
        flat = tmp_path / "api-key"
        flat.write_text("mh-dev-migrated-key\n")
        assert migrate_flat_to_credentials() is True

        cp = configparser.ConfigParser(interpolation=None)
        cp.read(tmp_path / "credentials")
        assert cp.get("default", "api_key") == "mh-dev-migrated-key"

    def test_annotates_flat_file(self, _no_files, tmp_path):
        flat = tmp_path / "api-key"
        flat.write_text("mh-dev-original\n")
        migrate_flat_to_credentials()
        content = flat.read_text()
        assert content.startswith("# This key has been migrated")
        assert "mh-dev-original" in content

    def test_key_still_readable_after_migration(self, _no_files, tmp_path):
        flat = tmp_path / "api-key"
        flat.write_text("mh-dev-readable\n")
        migrate_flat_to_credentials()
        assert get_api_key() == "mh-dev-readable"

    def test_skips_if_credentials_exists(self, _no_files, tmp_path):
        flat = tmp_path / "api-key"
        flat.write_text("mh-dev-old\n")
        creds = tmp_path / "credentials"
        creds.write_text("[default]\napi_key = mh-dev-existing\n")
        assert migrate_flat_to_credentials() is False

    def test_skips_if_no_flat_file(self, _no_files):
        assert migrate_flat_to_credentials() is False

    def test_skips_empty_flat_file(self, _no_files, tmp_path):
        flat = tmp_path / "api-key"
        flat.write_text("\n")
        assert migrate_flat_to_credentials() is False


class TestCredentialsInResolutionChain:
    """Verify credentials file integrates correctly into get_api_key/get_server_url."""

    def test_credentials_beats_flat_file(self, _no_files, tmp_path):
        (tmp_path / "credentials").write_text("[default]\napi_key = from-creds\n")
        (tmp_path / "api-key").write_text("from-flat\n")
        assert get_api_key() == "from-creds"

    def test_credentials_beats_config_json(self, _no_files, tmp_path):
        (tmp_path / "credentials").write_text("[default]\napi_key = from-creds\n")
        (tmp_path / "config.json").write_text(json.dumps({"api_key": "from-json"}))
        assert get_api_key() == "from-creds"

    def test_env_var_beats_credentials(self, _no_files, tmp_path, monkeypatch):
        (tmp_path / "credentials").write_text("[default]\napi_key = from-creds\n")
        monkeypatch.setenv("MEMORYHUB_API_KEY", "from-env")
        assert get_api_key() == "from-env"

    def test_context_selects_section(self, _no_files, tmp_path, monkeypatch):
        (tmp_path / "credentials").write_text(
            "[ctx-a]\napi_key = key-a\n\n[ctx-b]\napi_key = key-b\n"
        )
        monkeypatch.setenv("MEMORYHUB_CONTEXT", "ctx-b")
        assert get_api_key() == "key-b"

    def test_flat_file_fallback_when_no_creds(self, _no_files, tmp_path):
        (tmp_path / "api-key").write_text("from-flat\n")
        assert get_api_key() == "from-flat"


class TestGetCredentialsPaired:
    def test_paired_from_credentials_file(self, _no_files, tmp_path):
        (tmp_path / "credentials").write_text(
            "[default]\napi_key = key-1\nurl = https://paired.example.com\n"
        )
        key, url = get_credentials()
        assert key == "key-1"
        assert url == "https://paired.example.com"

    def test_env_var_key_with_url_resolution(self, _no_files, tmp_path, monkeypatch):
        monkeypatch.setenv("MEMORYHUB_API_KEY", "env-key")
        monkeypatch.setenv("MEMORYHUB_URL", "https://env-url.example.com")
        key, url = get_credentials()
        assert key == "env-key"
        assert url == "https://env-url.example.com"

    def test_both_none_when_nothing_configured(self, _no_files):
        key, url = get_credentials()
        assert key is None
        assert url is None

    def test_flat_file_key_with_config_url(self, _no_files, tmp_path):
        (tmp_path / "api-key").write_text("flat-key\n")
        (tmp_path / "config.json").write_text(json.dumps({"url": "https://cfg.example.com"}))
        key, url = get_credentials()
        assert key == "flat-key"
        assert url == "https://cfg.example.com"
