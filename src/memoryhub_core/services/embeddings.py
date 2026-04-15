"""Embedding service interface and implementations."""

import hashlib
import logging
import math
import os
from abc import ABC, abstractmethod

import httpx

from memoryhub_core.services.exceptions import (
    EmbeddingContentTooLargeError,
    EmbeddingServiceError,
    EmbeddingServiceUnavailableError,
)

logger = logging.getLogger(__name__)

EMBEDDING_DIM = 384


class EmbeddingService(ABC):
    """Interface for generating text embeddings."""

    @abstractmethod
    async def embed(self, text: str) -> list[float]:
        """Generate a 384-dimensional embedding vector for the given text."""
        ...

    @abstractmethod
    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for multiple texts."""
        ...


class MockEmbeddingService(EmbeddingService):
    """Deterministic mock embeddings for testing and development.

    Generates consistent 384-dim vectors from content hashes.
    Similar content produces similar vectors (via shared word hashes).
    """

    async def embed(self, text: str) -> list[float]:
        return self._hash_embed(text)

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self._hash_embed(t) for t in texts]

    def _hash_embed(self, text: str) -> list[float]:
        """Generate a deterministic embedding from text.

        Uses word-level hashing so texts with overlapping words
        produce somewhat similar vectors (useful for search testing).
        """
        vector = [0.0] * EMBEDDING_DIM
        words = text.lower().split()
        if not words:
            return vector
        for word in words:
            h = hashlib.sha256(word.encode()).digest()
            for i in range(EMBEDDING_DIM):
                byte_idx = i % len(h)
                vector[i] += h[byte_idx] / 255.0 - 0.5
        # Normalize to unit vector
        magnitude = math.sqrt(sum(x * x for x in vector))
        if magnitude > 0:
            vector = [x / magnitude for x in vector]
        return vector


class HttpEmbeddingService(EmbeddingService):
    """Embedding service that calls a remote HTTP endpoint.

    Compatible with the all-MiniLM-L6-v2 model served via standard
    embedding API: POST {"inputs": "text"} → [[float, ...]]
    """

    def __init__(self, url: str | None = None):
        self.url = url or os.environ.get(
            "MEMORYHUB_EMBEDDING_URL",
            "http://localhost:8080/embed",
        )
        self._client = httpx.AsyncClient(timeout=30.0)

    async def embed(self, text: str) -> list[float]:
        try:
            response = await self._client.post(self.url, json={"inputs": text})
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 413:
                raise EmbeddingContentTooLargeError(
                    content_length=len(text),
                    detail="Reduce content length or split into smaller memories.",
                ) from exc
            logger.error(
                "Embedding HTTP %d error (content length=%d)",
                exc.response.status_code,
                len(text),
            )
            raise EmbeddingServiceError(
                f"Embedding request failed (HTTP {exc.response.status_code})"
            ) from exc
        except httpx.ConnectError as exc:
            raise EmbeddingServiceUnavailableError(
                "Could not connect to embedding service"
            ) from exc
        except httpx.TimeoutException as exc:
            raise EmbeddingServiceUnavailableError(
                "Embedding request timed out (30s limit)"
            ) from exc

        data = response.json()
        # API returns [[float, ...]] — unwrap the outer array
        return data[0] if isinstance(data[0], list) else data

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        # Call one at a time — the API takes a single string
        return [await self.embed(t) for t in texts]
