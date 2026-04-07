"""Shared dependencies for MCP tools."""

import os

from memoryhub.services.database import get_session
from memoryhub.services.embeddings import (
    EmbeddingService,
    HttpEmbeddingService,
    MockEmbeddingService,
)
from memoryhub.services.rerank import (
    HttpRerankerService,
    NoopRerankerService,
    RerankerService,
)
from src.tools.auth import require_auth

_embedding_service: EmbeddingService | None = None
_reranker_service: RerankerService | None = None


def get_embedding_service() -> EmbeddingService:
    """Return the embedding service, using HTTP if MEMORYHUB_EMBEDDING_URL is set."""
    global _embedding_service
    if _embedding_service is None:
        url = os.environ.get("MEMORYHUB_EMBEDDING_URL")
        if url:
            _embedding_service = HttpEmbeddingService(url)
        else:
            _embedding_service = MockEmbeddingService()
    return _embedding_service


def get_reranker_service() -> RerankerService:
    """Return the cross-encoder reranker, or a Noop when MEMORYHUB_RERANKER_URL unset.

    The Noop instance has is_configured=False so search_memories_with_focus
    will skip the rerank stage and fall back to cosine ranks. The function
    is still safe to call when no reranker is deployed -- callers don't
    need to check for None.
    """
    global _reranker_service
    if _reranker_service is None:
        url = os.environ.get("MEMORYHUB_RERANKER_URL")
        if url:
            _reranker_service = HttpRerankerService(url)
        else:
            _reranker_service = NoopRerankerService()
    return _reranker_service


async def get_db_session():
    gen = get_session()
    session = await gen.__anext__()
    return session, gen


async def release_db_session(gen):
    try:
        await gen.__anext__()
    except StopAsyncIteration:
        pass


def get_authenticated_owner() -> str | None:
    """Return the authenticated user's user_id, or None if no session is registered.

    Deprecated: Use get_claims_from_context() from src.core.authz instead.
    """
    try:
        user = require_auth()
        return user["user_id"]
    except RuntimeError:
        return None


def get_caller_id() -> str | None:
    """Return the caller's identity from JWT or session, or None."""
    try:
        from src.core.authz import get_claims_from_context
        claims = get_claims_from_context()
        return claims["sub"]
    except Exception:
        return None
