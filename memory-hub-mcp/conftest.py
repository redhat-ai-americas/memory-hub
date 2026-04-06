"""Pytest configuration for MCP server projects.

This file is placed at the project root to ensure the src directory
is added to Python's path before any test modules are imported.
"""

import sys
from pathlib import Path

import pytest

# Add the src directory to Python path
project_root = Path(__file__).parent
src_path = project_root / "src"

if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))


@pytest.fixture(autouse=True)
def _default_test_session():
    """Provide a fully-privileged session for all tests.

    This ensures existing tests continue passing after RBAC enforcement
    is wired into tools. Tests that specifically check authorization
    denial should override this by calling set_session() with a
    restricted user.
    """
    from src.tools.auth import set_session
    import src.tools.auth as auth_mod

    set_session({
        "user_id": "test-user",
        "name": "Test User",
        "api_key": "test-key",
        "scopes": ["user", "project", "role", "organizational", "enterprise"],
        "identity_type": "user",
    })
    yield
    auth_mod._current_session = None
