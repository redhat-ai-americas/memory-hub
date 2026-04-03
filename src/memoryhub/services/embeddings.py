"""Embedding service interface and implementations."""

import hashlib
import math
import os
from abc import ABC, abstractmethod

import httpx

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
        response = await self._client.post(self.url, json={"inputs": text})
        response.raise_for_status()
        data = response.json()
        # API returns [[float, ...]] — unwrap the outer array
        return data[0] if isinstance(data[0], list) else data

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        # Call one at a time — the API takes a single string
        return [await self.embed(t) for t in texts]
