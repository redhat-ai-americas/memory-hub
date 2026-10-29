import pytest


@pytest.fixture
def labs_on(monkeypatch):
    """Turn MemoryHub Labs on for one test (MEMORYHUB_UI_LABS=true)."""
    from src.config import get_settings

    monkeypatch.setenv("MEMORYHUB_UI_LABS", "true")
    get_settings.cache_clear()
    yield
    monkeypatch.delenv("MEMORYHUB_UI_LABS", raising=False)
    get_settings.cache_clear()
