"""Async S3 storage adapter for oversized memory content.

Wraps the synchronous minio SDK via asyncio.to_thread.
"""

import asyncio
import io
import logging
import uuid
from functools import partial

from minio import Minio

from memoryhub_core.config import MinIOSettings

logger = logging.getLogger(__name__)


class S3StorageAdapter:
    """Async wrapper around the minio SDK for storing oversized memory content."""

    def __init__(self, settings: MinIOSettings | None = None) -> None:
        if settings is None:
            settings = MinIOSettings()
        self._settings = settings
        self._client = Minio(
            settings.endpoint,
            access_key=settings.access_key,
            secret_key=settings.secret_key,
            secure=settings.secure,
        )
        self._bucket = settings.bucket

    async def ensure_bucket(self) -> None:
        """Create the bucket if it doesn't exist. Call once at startup."""
        exists = await asyncio.to_thread(self._client.bucket_exists, self._bucket)
        if not exists:
            await asyncio.to_thread(self._client.make_bucket, self._bucket)
            logger.info("Created S3 bucket: %s", self._bucket)

    @staticmethod
    def _build_key(tenant_id: str, memory_id: uuid.UUID, version_id: uuid.UUID) -> str:
        return f"{tenant_id}/{memory_id}/{version_id}"

    async def put_content(
        self,
        tenant_id: str,
        memory_id: uuid.UUID,
        version_id: uuid.UUID,
        content: str,
    ) -> str:
        """Store content and return the content_ref key."""
        key = self._build_key(tenant_id, memory_id, version_id)
        data = content.encode("utf-8")
        stream = io.BytesIO(data)
        await asyncio.to_thread(
            partial(
                self._client.put_object,
                self._bucket,
                key,
                stream,
                length=len(data),
                content_type="text/plain; charset=utf-8",
            )
        )
        return key

    async def get_content(self, content_ref: str) -> str:
        """Retrieve full content from S3 by content_ref key."""
        response = await asyncio.to_thread(
            self._client.get_object, self._bucket, content_ref
        )
        try:
            return response.read().decode("utf-8")
        finally:
            response.close()
            response.release_conn()

    async def delete_content(self, content_ref: str) -> None:
        """Delete a single S3 object."""
        await asyncio.to_thread(
            self._client.remove_object, self._bucket, content_ref
        )

    async def delete_contents(self, content_refs: list[str]) -> None:
        """Batch-delete multiple S3 objects."""
        if not content_refs:
            return
        from minio.deleteobjects import DeleteObject

        objects = [DeleteObject(ref) for ref in content_refs]
        errors = await asyncio.to_thread(
            lambda: list(self._client.remove_objects(self._bucket, objects))
        )
        for err in errors:
            logger.warning("Failed to delete S3 object %s: %s", err.name, err.message)
