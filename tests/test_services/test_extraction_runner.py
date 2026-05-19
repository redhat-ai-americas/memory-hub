"""Tests for the entity extraction background task runner."""

import asyncio
import uuid
from unittest.mock import AsyncMock, patch

import pytest

from memoryhub_core.services import extraction_runner


@pytest.fixture(autouse=True)
def reset_runner_state():
    """Reset module-level state between tests."""
    extraction_runner._semaphore = None
    extraction_runner._active_tasks.clear()
    yield
    extraction_runner._semaphore = None
    extraction_runner._active_tasks.clear()


@pytest.mark.asyncio
async def test_trigger_extraction_noop_when_disabled():
    """When entity_extraction_enabled is False, trigger does nothing."""
    with patch("memoryhub_core.services.extraction_runner.AppSettings") as mock_settings:
        mock_settings.return_value.entity_extraction_enabled = False

        await extraction_runner.trigger_extraction(
            memory_id=uuid.uuid4(),
            content="Alice met Bob",
            tenant_id="t1",
            owner_id="u1",
            embedding_service=None,
        )

    assert len(extraction_runner._active_tasks) == 0


@pytest.mark.asyncio
async def test_trigger_extraction_creates_task_when_enabled():
    """When enabled, trigger creates a background task."""
    mock_extract = AsyncMock(return_value={"count": 0, "entities": []})

    with (
        patch("memoryhub_core.services.extraction_runner.AppSettings") as mock_settings,
        patch("memoryhub_core.services.extraction_runner.extract_entities_from_memory", mock_extract),
        patch("memoryhub_core.services.extraction_runner.get_session") as mock_get_session,
        patch("memoryhub_core.services.extraction_runner._update_extraction_status", new_callable=AsyncMock),
    ):
        mock_settings.return_value.entity_extraction_enabled = True
        mock_settings.return_value.entity_extraction_concurrency = 5

        mock_session = AsyncMock()
        mock_get_session.return_value = mock_session
        mock_session.__aiter__ = AsyncMock(return_value=iter([AsyncMock()]))

        memory_id = uuid.uuid4()
        await extraction_runner.trigger_extraction(
            memory_id=memory_id,
            content="Alice met Bob",
            tenant_id="t1",
            owner_id="u1",
            embedding_service=None,
        )

        # Task was created
        assert memory_id in extraction_runner._active_tasks

        # Wait for the task to complete
        await extraction_runner._active_tasks[memory_id]

        # Task is cleaned up
        assert memory_id not in extraction_runner._active_tasks


@pytest.mark.asyncio
async def test_trigger_extraction_never_raises():
    """Even if something goes wrong internally, trigger never raises."""
    with (
        patch("memoryhub_core.services.extraction_runner.AppSettings") as mock_settings,
    ):
        mock_settings.return_value.entity_extraction_enabled = True
        mock_settings.return_value.entity_extraction_concurrency = 5
        # Force an error by making create_task fail
        with patch("asyncio.create_task", side_effect=RuntimeError("boom")):
            await extraction_runner.trigger_extraction(
                memory_id=uuid.uuid4(),
                content="test",
                tenant_id="t1",
                owner_id="u1",
                embedding_service=None,
            )
    # No exception raised


@pytest.mark.asyncio
async def test_trigger_extraction_skips_duplicate():
    """If extraction is already in progress for a memory, skip."""
    memory_id = uuid.uuid4()
    # Simulate an active task
    extraction_runner._active_tasks[memory_id] = asyncio.Future()

    with patch("memoryhub_core.services.extraction_runner.AppSettings") as mock_settings:
        mock_settings.return_value.entity_extraction_enabled = True

        await extraction_runner.trigger_extraction(
            memory_id=memory_id,
            content="test",
            tenant_id="t1",
            owner_id="u1",
            embedding_service=None,
        )

    # Still just the original task, no new one created
    assert len(extraction_runner._active_tasks) == 1

    # Clean up the future
    extraction_runner._active_tasks[memory_id].cancel()


@pytest.mark.asyncio
async def test_semaphore_bounds_concurrency():
    """Semaphore limits concurrent extractions."""
    with patch("memoryhub_core.services.extraction_runner.AppSettings") as mock_settings:
        mock_settings.return_value.entity_extraction_concurrency = 2
        extraction_runner._semaphore = None

        sem = extraction_runner._get_semaphore()
        assert sem._value == 2
