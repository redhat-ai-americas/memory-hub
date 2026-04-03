"""Shared test fixtures for MemoryHub."""

import pytest


@pytest.fixture
def sample_memory_data():
    """Minimal memory node data for testing."""
    return {
        "content": "prefers Podman over Docker",
        "scope": "user",
        "weight": 0.9,
        "owner_id": "user-123",
    }
