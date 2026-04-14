"""Shared fixtures for tool-level tests.

Tool tests mock the service layer; scope-isolation is exercised
in integration tests instead. We disable both isolation flags so
tool tests don't need to mock get_roles_for_user / get_projects_for_user
(which require a real async SQLAlchemy session).
"""

from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture(autouse=True)
def _disable_scope_isolation():
    """Disable project and role isolation for all tool tests."""
    with (
        patch("src.tools.search_memory.ROLE_ISOLATION_ENABLED", False),
        patch("src.tools.search_memory.PROJECT_ISOLATION_ENABLED", False),
    ):
        yield


@pytest.fixture()
def mock_valkey():
    """Return a mock ValkeyClient with no-op compilation methods.

    Used by tests that exercise the cache-optimized assembly path.
    Tests that don't care about compilation can ignore this fixture --
    the _PatchedSearchCall helper patches get_valkey_client internally.
    """
    valkey = AsyncMock()
    valkey.read_compilation = AsyncMock(return_value=None)
    valkey.write_compilation = AsyncMock()
    return valkey
