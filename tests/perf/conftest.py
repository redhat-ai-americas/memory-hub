"""Pytest configuration for the perf test directory.

The perf marker keeps these tests out of the default CI run; invoke them
explicitly with `pytest -m perf`. Each test that talks to the deployed
embedding/reranker services should be marked so accidental CI runs don't
hammer cluster resources.
"""

import pytest


def pytest_collection_modifyitems(config, items):
    """Auto-mark every test in tests/perf/ as 'perf' so the suite is opt-in."""
    for item in items:
        if "tests/perf/" in str(item.fspath):
            item.add_marker(pytest.mark.perf)
