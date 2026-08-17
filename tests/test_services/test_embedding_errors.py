"""Tests for HttpEmbeddingService error translation and /info discovery (#119, #511).

Verifies that httpx-level failures are caught and re-raised as the appropriate
domain exception: EmbeddingContentTooLargeError (413/422), EmbeddingServiceError
(other HTTP errors), and EmbeddingServiceUnavailableError (connect/timeout).

Also verifies that max_tokens is discovered from TEI /info and that failures
fall back gracefully.
"""

import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from memoryhub_core.services.embeddings import (
    HttpEmbeddingService,
    MockEmbeddingService,
    _DEFAULT_MAX_TOKENS,
)
from memoryhub_core.services.exceptions import (
    EmbeddingContentTooLargeError,
    EmbeddingServiceError,
    EmbeddingServiceUnavailableError,
)

_URL = "http://test-embedder/embed"


def _http_response(status_code: int, body: bytes = b"") -> httpx.Response:
    """Build a minimal httpx.Response for a given status code."""
    return httpx.Response(
        status_code,
        request=httpx.Request("POST", _URL),
        content=body,
    )


@pytest.fixture
def service() -> HttpEmbeddingService:
    svc = HttpEmbeddingService(url=_URL)
    svc._info_fetched = True
    return svc


# -- Error translation --


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
async def test_422_raises_content_too_large(service: HttpEmbeddingService):
    """A 422 response (TEI with auto_truncate=false) must also raise
    EmbeddingContentTooLargeError."""
    response = _http_response(422)
    mock_post = AsyncMock(return_value=response)

    with patch.object(service._client, "post", mock_post):
        with pytest.raises(EmbeddingContentTooLargeError):
            await service.embed("x" * 1000)


@pytest.mark.asyncio
async def test_500_raises_embedding_service_error(service: HttpEmbeddingService):
    """A 5xx response must raise EmbeddingServiceError (not the subclass)
    and the error message must not expose the embedder URL."""
    response = _http_response(500)
    mock_post = AsyncMock(return_value=response)

    with patch.object(service._client, "post", mock_post), pytest.raises(EmbeddingServiceError) as exc_info:
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

    with patch.object(service._client, "post", mock_post), pytest.raises(EmbeddingServiceUnavailableError):
        await service.embed("some text")


@pytest.mark.asyncio
async def test_timeout_raises_unavailable(service: HttpEmbeddingService):
    """A timeout must raise EmbeddingServiceUnavailableError."""
    mock_post = AsyncMock(side_effect=httpx.TimeoutException("timed out"))

    with patch.object(service._client, "post", mock_post), pytest.raises(EmbeddingServiceUnavailableError):
        await service.embed("some text")


@pytest.mark.asyncio
async def test_embed_batch_propagates_413(service: HttpEmbeddingService):
    """embed_batch calls embed internally; a 413 from the first item propagates
    as EmbeddingContentTooLargeError rather than being swallowed."""
    response = _http_response(413)
    mock_post = AsyncMock(return_value=response)

    with patch.object(service._client, "post", mock_post), pytest.raises(EmbeddingContentTooLargeError):
        await service.embed_batch(["a", "b"])


# -- TEI /info discovery (#511) --


@pytest.mark.asyncio
async def test_info_sets_max_tokens_from_tei():
    """HttpEmbeddingService reads max_input_length from TEI /info on first embed."""
    svc = HttpEmbeddingService(url=_URL)

    info_body = json.dumps({"max_input_length": 256, "model_id": "all-MiniLM-L6-v2"}).encode()
    info_response = httpx.Response(200, request=httpx.Request("GET", "http://test-embedder/info"), content=info_body)
    embed_response = httpx.Response(200, request=httpx.Request("POST", _URL), content=b"[[0.1, 0.2]]")

    mock_get = AsyncMock(return_value=info_response)
    mock_post = AsyncMock(return_value=embed_response)

    with patch.object(svc._client, "get", mock_get), patch.object(svc._client, "post", mock_post):
        await svc.embed("hello")

    assert svc.max_tokens == 256
    mock_get.assert_called_once()


@pytest.mark.asyncio
async def test_info_fallback_on_connect_error():
    """When /info is unreachable, max_tokens falls back to the default."""
    svc = HttpEmbeddingService(url=_URL)

    embed_response = httpx.Response(200, request=httpx.Request("POST", _URL), content=b"[[0.1, 0.2]]")
    mock_get = AsyncMock(side_effect=httpx.ConnectError("refused"))
    mock_post = AsyncMock(return_value=embed_response)

    with patch.object(svc._client, "get", mock_get), patch.object(svc._client, "post", mock_post):
        await svc.embed("hello")

    assert svc.max_tokens == _DEFAULT_MAX_TOKENS
    assert svc._info_fetched is True


@pytest.mark.asyncio
async def test_info_fallback_on_timeout():
    """When /info times out, max_tokens falls back to the default."""
    svc = HttpEmbeddingService(url=_URL)

    embed_response = httpx.Response(200, request=httpx.Request("POST", _URL), content=b"[[0.1, 0.2]]")
    mock_get = AsyncMock(side_effect=httpx.TimeoutException("timed out"))
    mock_post = AsyncMock(return_value=embed_response)

    with patch.object(svc._client, "get", mock_get), patch.object(svc._client, "post", mock_post):
        await svc.embed("hello")

    assert svc.max_tokens == _DEFAULT_MAX_TOKENS


@pytest.mark.asyncio
async def test_info_fetched_only_once():
    """/info is queried at most once, even across multiple embed calls."""
    svc = HttpEmbeddingService(url=_URL)

    info_body = json.dumps({"max_input_length": 512}).encode()
    info_response = httpx.Response(200, request=httpx.Request("GET", "http://test-embedder/info"), content=info_body)
    embed_response = httpx.Response(200, request=httpx.Request("POST", _URL), content=b"[[0.1, 0.2]]")

    mock_get = AsyncMock(return_value=info_response)
    mock_post = AsyncMock(return_value=embed_response)

    with patch.object(svc._client, "get", mock_get), patch.object(svc._client, "post", mock_post):
        await svc.embed("first")
        await svc.embed("second")

    assert mock_get.call_count == 1
    assert svc.max_tokens == 512


@pytest.mark.asyncio
async def test_info_fallback_env_var(monkeypatch):
    """MEMORYHUB_EMBEDDING_MAX_TOKENS env var overrides the hardcoded default
    when /info is unreachable."""
    monkeypatch.setenv("MEMORYHUB_EMBEDDING_MAX_TOKENS", "256")
    svc = HttpEmbeddingService(url=_URL)

    embed_response = httpx.Response(200, request=httpx.Request("POST", _URL), content=b"[[0.1, 0.2]]")
    mock_get = AsyncMock(side_effect=httpx.ConnectError("refused"))
    mock_post = AsyncMock(return_value=embed_response)

    with patch.object(svc._client, "get", mock_get), patch.object(svc._client, "post", mock_post):
        await svc.embed("hello")

    assert svc.max_tokens == 256


# -- MockEmbeddingService max_tokens --


def test_mock_embedding_service_default_max_tokens():
    """MockEmbeddingService defaults to _DEFAULT_MAX_TOKENS."""
    svc = MockEmbeddingService()
    assert svc.max_tokens == _DEFAULT_MAX_TOKENS


def test_mock_embedding_service_custom_max_tokens():
    """MockEmbeddingService accepts a custom max_tokens."""
    svc = MockEmbeddingService(max_tokens=256)
    assert svc.max_tokens == 256
