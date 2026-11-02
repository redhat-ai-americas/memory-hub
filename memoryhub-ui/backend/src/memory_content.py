"""Resolve complete memory content before presenting it for editing or copying."""

import logging
from functools import lru_cache

from fastapi import HTTPException
from memoryhub_core.config import MinIOSettings
from memoryhub_core.models.memory import MemoryNode
from memoryhub_core.storage.s3 import S3StorageAdapter

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_memory_storage() -> S3StorageAdapter | None:
    settings = MinIOSettings()
    return S3StorageAdapter(settings) if settings.access_key else None


async def full_memory_content(node: MemoryNode, cache: dict[str, str] | None = None) -> str:
    if node.storage_type != "s3":
        return node.content
    storage = get_memory_storage()
    if storage is None or not node.content_ref:
        raise HTTPException(status_code=503, detail="Full memory content is unavailable: configure S3 storage access.")
    if cache is not None and node.content_ref in cache:
        return cache[node.content_ref]
    try:
        content = await storage.get_content(node.content_ref)
    except Exception:
        logger.warning("Could not load stored memory content", exc_info=True)
        raise HTTPException(
            status_code=503, detail="Full memory content could not be loaded. Try again later."
        ) from None
    if cache is not None:
        cache[node.content_ref] = content
    return content
