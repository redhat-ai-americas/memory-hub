"""Configuration management for MemoryHub CLI."""

import json
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "memoryhub"
CONFIG_FILE = CONFIG_DIR / "config.json"


def load_config() -> dict:
    """Load config from disk. Returns empty dict if not found."""
    if not CONFIG_FILE.exists():
        return {}
    return json.loads(CONFIG_FILE.read_text())


def save_config(config: dict) -> None:
    """Save config to disk."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(config, indent=2) + "\n")
    # Restrict permissions — contains secrets
    CONFIG_FILE.chmod(0o600)


def get_connection_params() -> dict:
    """Get connection parameters, preferring env vars over config file.

    Required keys: url, auth_url, client_id, client_secret.
    Env vars: MEMORYHUB_URL, MEMORYHUB_AUTH_URL, MEMORYHUB_CLIENT_ID, MEMORYHUB_CLIENT_SECRET.
    """
    import os

    config = load_config()
    return {
        "url": os.environ.get("MEMORYHUB_URL", config.get("url", "")),
        "auth_url": os.environ.get("MEMORYHUB_AUTH_URL", config.get("auth_url", "")),
        "client_id": os.environ.get("MEMORYHUB_CLIENT_ID", config.get("client_id", "")),
        "client_secret": os.environ.get(
            "MEMORYHUB_CLIENT_SECRET", config.get("client_secret", "")
        ),
    }
