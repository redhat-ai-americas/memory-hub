"""Local identity utilities for personal edition."""

import os

TENANT_ID = "local"


def get_owner_id() -> str:
    """Return the local user identity."""
    try:
        return os.getlogin()
    except OSError:
        return os.environ.get("USER", "local")
