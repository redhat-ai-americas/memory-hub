"""Background task runner for entity extraction.

Manages async extraction tasks with bounded concurrency. Extraction
runs after memory writes commit, in a separate DB session, and never
blocks or fails the write response. All exceptions are caught and
logged.
"""

import asyncio
import logging
import uuid
from typing import Any

from memoryhub_core.config import AppSettings
from memoryhub_core.services.database import get_session
from memoryhub_core.services.extraction import extract_entities_from_memory

logger = logging.getLogger(__name__)

_semaphore: asyncio.Semaphore | None = None
_active_tasks: dict[uuid.UUID, asyncio.Task] = {}


def _get_semaphore() -> asyncio.Semaphore:
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(AppSettings().entity_extraction_concurrency)
    return _semaphore


async def _update_extraction_status(
    memory_id: uuid.UUID,
    status: str,
    entities: list[dict[str, Any]] | None = None,
) -> None:
    """Update the extraction_status field in a memory's metadata."""
    from sqlalchemy import select
    from memoryhub_core.models.memory import MemoryNode

    async for session in get_session():
        stmt = select(MemoryNode).where(MemoryNode.id == memory_id)
        result = await session.execute(stmt)
        node = result.scalar_one_or_none()
        if node is None:
            return

        meta = dict(node.metadata_ or {})
        meta["extraction_status"] = status
        if entities is not None:
            meta["extracted_entities"] = entities
        node.metadata_ = meta
        await session.commit()
        break


async def _run_extraction(
    memory_id: uuid.UUID,
    content: str,
    tenant_id: str,
    owner_id: str,
    embedding_service: Any,
) -> None:
    """Execute extraction in a fresh DB session with semaphore guard."""
    sem = _get_semaphore()
    async with sem:
        try:
            async for session in get_session():
                result = await extract_entities_from_memory(
                    memory_id=memory_id,
                    content=content,
                    session=session,
                    embedding_service=embedding_service,
                    tenant_id=tenant_id,
                    owner_id=owner_id,
                )
                break

            await _update_extraction_status(
                memory_id, "complete", result.get("entities", []),
            )

            if result["count"] > 0:
                logger.info(
                    "Extracted %d entities from memory %s",
                    result["count"], memory_id,
                )
        except Exception:
            logger.warning(
                "Entity extraction failed for memory %s; memory is saved but unextracted",
                memory_id,
                exc_info=True,
            )
            try:
                await _update_extraction_status(memory_id, "failed")
            except Exception:
                logger.warning(
                    "Failed to update extraction_status to 'failed' for memory %s",
                    memory_id,
                    exc_info=True,
                )


def _task_done(memory_id: uuid.UUID, task: asyncio.Task) -> None:
    """Cleanup callback when an extraction task completes."""
    _active_tasks.pop(memory_id, None)
    if task.cancelled():
        logger.debug("Extraction task cancelled for memory %s", memory_id)
    elif task.exception():
        logger.warning(
            "Extraction task raised for memory %s: %s",
            memory_id, task.exception(),
        )


async def trigger_extraction(
    memory_id: uuid.UUID,
    content: str,
    tenant_id: str,
    owner_id: str,
    embedding_service: Any,
) -> None:
    """Fire-and-forget entity extraction for a committed memory.

    Returns immediately. Never raises -- all exceptions are caught internally.
    No-op when entity_extraction_enabled is False.
    """
    try:
        if not AppSettings().entity_extraction_enabled:
            return

        if memory_id in _active_tasks:
            logger.debug("Extraction already in progress for %s", memory_id)
            return

        task = asyncio.create_task(
            _run_extraction(memory_id, content, tenant_id, owner_id, embedding_service),
            name=f"extract-{memory_id}",
        )
        _active_tasks[memory_id] = task
        task.add_done_callback(lambda t: _task_done(memory_id, t))
    except Exception:
        logger.warning(
            "Failed to schedule extraction for memory %s",
            memory_id,
            exc_info=True,
        )
