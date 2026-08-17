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
_DEFAULT_MAX_TOKENS = 8192


class EmbeddingService(ABC):
    """Interface for generating text embeddings."""

    @property
    @abstractmethod
    def max_tokens(self) -> int:
        """Max input tokens the embedding model accepts."""
        ...

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

    def __init__(self, max_tokens: int = _DEFAULT_MAX_TOKENS):
        self._max_tokens = max_tokens

    @property
    def max_tokens(self) -> int:
        return self._max_tokens

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

    Compatible with TEI-served models (granite-embedding-small-english-r2,
    all-MiniLM-L6-v2, etc.): POST {"inputs": "text"} -> [[float, ...]]

    Queries TEI's ``GET /info`` endpoint on first use to discover the
    model's actual ``max_input_length``.  Falls back to the env var
    ``MEMORYHUB_EMBEDDING_MAX_TOKENS`` or ``_DEFAULT_MAX_TOKENS`` if
    ``/info`` is unreachable.
    """

    def __init__(self, url: str | None = None):
        self.url = url or os.environ.get(
            "MEMORYHUB_EMBEDDING_URL",
            "http://localhost:8080/embed",
        )
        timeout = float(os.environ.get("MEMORYHUB_EMBEDDING_TIMEOUT", "120"))
        self._client = httpx.AsyncClient(timeout=timeout)
        self._max_tokens: int | None = None
        self._info_fetched = False

    @property
    def max_tokens(self) -> int:
        if self._max_tokens is not None:
            return self._max_tokens
        return self._fallback_max_tokens()

    async def _fetch_info(self) -> None:
        """Query TEI /info once to discover max_input_length."""
        if self._info_fetched:
            return
        self._info_fetched = True

        # /info lives at the TEI server root, not under /embed
        base_url = self.url.rsplit("/", 1)[0]
        info_url = f"{base_url}/info"
        try:
            resp = await self._client.get(info_url, timeout=10)
            resp.raise_for_status()
            info = resp.json()
            max_input = info.get("max_input_length")
            if max_input is not None:
                self._max_tokens = int(max_input)
                logger.info(
                    "Embedding model max_input_length: %d tokens (from TEI /info)",
                    self._max_tokens,
                )
            else:
                logger.warning(
                    "TEI /info response missing max_input_length; "
                    "falling back to %d tokens",
                    self._fallback_max_tokens(),
                )
        except httpx.ConnectError:
            logger.warning(
                "Could not connect to TEI /info at %s; "
                "using fallback max_tokens=%d",
                info_url,
                self._fallback_max_tokens(),
            )
        except httpx.TimeoutException:
            logger.warning(
                "TEI /info request timed out (%s); "
                "using fallback max_tokens=%d",
                info_url,
                self._fallback_max_tokens(),
            )
        except Exception:
            logger.warning(
                "Failed to query TEI /info at %s; "
                "using fallback max_tokens=%d",
                info_url,
                self._fallback_max_tokens(),
                exc_info=True,
            )

    @staticmethod
    def _fallback_max_tokens() -> int:
        env = os.environ.get("MEMORYHUB_EMBEDDING_MAX_TOKENS")
        if env is not None:
            return int(env)
        return _DEFAULT_MAX_TOKENS

    async def embed(self, text: str) -> list[float]:
        await self._fetch_info()
        try:
            response = await self._client.post(self.url, json={"inputs": text})
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (413, 422):
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
