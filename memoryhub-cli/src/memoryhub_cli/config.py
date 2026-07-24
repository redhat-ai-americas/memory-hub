"""Configuration management for MemoryHub CLI."""

from __future__ import annotations

import configparser
import io
import json
import os
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "memoryhub"
CONFIG_FILE = CONFIG_DIR / "config.json"
API_KEY_FILE = CONFIG_DIR / "api-key"
CREDENTIALS_FILE = CONFIG_DIR / "credentials"

_CREDENTIALS_HEADER = (
    "# MemoryHub credentials -- managed by memoryhub CLI and deploy scripts.\n"
)

_MIGRATION_COMMENT = (
    "# This key has been migrated to ~/.config/memoryhub/credentials\n"
    "# under the [default] section. You can delete this file once all\n"
    "# tools and agent configurations have been updated.\n"
)


def load_config() -> dict:
    """Load config from disk. Returns empty dict if not found."""
    if not CONFIG_FILE.exists():
        return {}
    return json.loads(CONFIG_FILE.read_text())


def save_config(config: dict) -> None:
    """Save config to disk."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(config, indent=2) + "\n")
    CONFIG_FILE.chmod(0o600)


def read_credentials_section(context: str | None = None) -> dict[str, str] | None:
    """Read a section from the INI-style credentials file."""
    if not CREDENTIALS_FILE.exists():
        return None

    cp = configparser.ConfigParser(interpolation=None)
    cp.read(CREDENTIALS_FILE)

    section = context or os.environ.get("MEMORYHUB_CONTEXT", "").strip() or "default"
    if not cp.has_section(section):
        return None

    result = {}
    for key in ("api_key", "url"):
        val = cp.get(section, key, fallback=None)
        if val:
            result[key] = val
    return result


def write_credentials_section(
    context: str, api_key: str, url: str | None = None,
) -> None:
    """Write or update a section in the credentials file."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    cp = configparser.ConfigParser(interpolation=None)
    if CREDENTIALS_FILE.exists():
        cp.read(CREDENTIALS_FILE)

    if not cp.has_section(context):
        cp.add_section(context)
    cp.set(context, "api_key", api_key)
    if url:
        cp.set(context, "url", url)
    elif cp.has_option(context, "url"):
        cp.remove_option(context, "url")

    buf = io.StringIO()
    cp.write(buf)
    CREDENTIALS_FILE.write_text(_CREDENTIALS_HEADER + buf.getvalue())
    CREDENTIALS_FILE.chmod(0o600)


def migrate_flat_to_credentials() -> bool:
    """Migrate flat api-key file to credentials file if needed."""
    if not API_KEY_FILE.exists() or CREDENTIALS_FILE.exists():
        return False

    raw = API_KEY_FILE.read_text()
    key = ""
    for line in raw.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            key = stripped
            break

    if not key:
        return False

    write_credentials_section("default", key)
    API_KEY_FILE.write_text(_MIGRATION_COMMENT + raw)
    return True


def get_api_key() -> str | None:
    """Resolve API key: env var > credentials file > flat file > config.json."""
    key = os.environ.get("MEMORYHUB_API_KEY", "").strip()
    if key:
        return key

    creds = read_credentials_section()
    if creds and creds.get("api_key"):
        return creds["api_key"]

    if API_KEY_FILE.exists():
        for line in API_KEY_FILE.read_text().splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                return stripped

    return load_config().get("api_key") or None


def get_server_url() -> str | None:
    """Resolve server URL: env var > credentials file > config.json."""
    url = os.environ.get("MEMORYHUB_URL", "").strip()
    if url:
        return url

    creds = read_credentials_section()
    if creds and creds.get("url"):
        return creds["url"]

    return load_config().get("url") or None


def get_credentials() -> tuple[str | None, str | None]:
    """Resolve (api_key, url) paired from the same source."""
    key = os.environ.get("MEMORYHUB_API_KEY", "").strip()
    if key:
        return key, get_server_url()

    creds = read_credentials_section()
    if creds and creds.get("api_key"):
        return creds["api_key"], creds.get("url")

    if API_KEY_FILE.exists():
        for line in API_KEY_FILE.read_text().splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                return stripped, get_server_url()

    config = load_config()
    cfg_key = config.get("api_key") or None
    if cfg_key:
        return cfg_key, config.get("url") or None

    return None, None


def get_connection_params() -> dict:
    """Get OAuth connection parameters, preferring env vars over config file.

    Required keys: url, auth_url, client_id, client_secret.
    """
    config = load_config()
    return {
        "url": os.environ.get("MEMORYHUB_URL", config.get("url", "")),
        "auth_url": os.environ.get("MEMORYHUB_AUTH_URL", config.get("auth_url", "")),
        "client_id": os.environ.get("MEMORYHUB_CLIENT_ID", config.get("client_id", "")),
        "client_secret": os.environ.get(
            "MEMORYHUB_CLIENT_SECRET", config.get("client_secret", "")
        ),
    }
