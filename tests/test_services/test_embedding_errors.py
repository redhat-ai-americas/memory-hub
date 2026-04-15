"""Tests for HttpEmbeddingService error translation (#119).

Verifies that httpx-level failures are caught and re-raised as the appropriate
domain exception: EmbeddingContentTooLargeError (413), EmbeddingServiceError
(other HTTP errors), and EmbeddingServiceUnavailableError (connect/timeout).
"""

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from memoryhub_core.services.embeddings import HttpEmbeddingService
from memoryhub_core.services.exceptions import (
    EmbeddingContentTooLargeError,
    EmbeddingServiceError,
    EmbeddingServiceUnavailableError,
)

_URL = "http://test-embedder/embed"


def _http_response(status_code: int) -> httpx.Response:
    """Build a minimal httpx.Response for a given status code."""
    return httpx.Response(
        status_code,
        request=httpx.Request("POST", _URL),
    )


@pytest.fixture
def service() -> HttpEmbeddingService:
    return HttpEmbeddingService(url=_URL)


@pytest.mark.asyncio
async def test_413_raises_content_too_large(service: HttpEmbeddingService):
    """A 413 response must raise EmbeddingContentTooLargeError with content_length
    set to the character count of the input text."""
    response = _http_response(413)
    mock_post = AsyncMock(return_value=response)

    with patch.object(service._client, "post", mock_post):
        text = "x" * 256
        with pytest.raises(EmbeddingContentTooLargeError) as exc_info:
            await service.embed(text)

    assert exc_info.value.content_length == len(text), (
        f"Expected content_length={len(text)}, got {exc_info.value.content_length}"
    )


@pytest.mark.asyncio
async def test_500_raises_embedding_service_error(service: HttpEmbeddingService):
    """A 5xx response must raise EmbeddingServiceError (not the subclass)
    and the error message must not expose the embedder URL."""
    response = _http_response(500)
    mock_post = AsyncMock(return_value=response)

    with patch.object(service._client, "post", mock_post):
        with pytest.raises(EmbeddingServiceError) as exc_info:
            await service.embed("some text")

    # Must be the base class, not the too-large subclass.
    assert type(exc_info.value) is EmbeddingServiceError, (
        f"Expected EmbeddingServiceError, got {type(exc_info.value).__name__}"
    )
    # URL must not leak into the message (avoids exposing internal topology).
    assert _URL not in str(exc_info.value), (
        f"Error message must not contain the embedder URL: {exc_info.value}"
    )


@pytest.mark.asyncio
async def test_connect_error_raises_unavailable(service: HttpEmbeddingService):
    """A connection failure must raise EmbeddingServiceUnavailableError."""
    mock_post = AsyncMock(side_effect=httpx.ConnectError("connection refused"))

    with patch.object(service._client, "post", mock_post):
        with pytest.raises(EmbeddingServiceUnavailableError):
            await service.embed("some text")


@pytest.mark.asyncio
async def test_timeout_raises_unavailable(service: HttpEmbeddingService):
    """A timeout must raise EmbeddingServiceUnavailableError."""
    mock_post = AsyncMock(side_effect=httpx.TimeoutException("timed out"))

    with patch.object(service._client, "post", mock_post):
        with pytest.raises(EmbeddingServiceUnavailableError):
            await service.embed("some text")


@pytest.mark.asyncio
async def test_embed_batch_propagates_413(service: HttpEmbeddingService):
    """embed_batch calls embed internally; a 413 from the first item propagates
    as EmbeddingContentTooLargeError rather than being swallowed."""
    response = _http_response(413)
    mock_post = AsyncMock(return_value=response)

    with patch.object(service._client, "post", mock_post):
        with pytest.raises(EmbeddingContentTooLargeError):
            await service.embed_batch(["a", "b"])
