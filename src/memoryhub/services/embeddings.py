"""Embedding service interface and implementations."""

import hashlib
import math
from abc import ABC, abstractmethod

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
