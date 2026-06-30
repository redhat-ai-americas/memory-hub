"""Shared dependencies for MCP tools."""

import contextlib
import os

from memoryhub_core.services.database import get_session
from memoryhub_core.services.embeddings import (
    EmbeddingService,
    HttpEmbeddingService,
    MockEmbeddingService,
)
from memoryhub_core.services.rerank import (
    HttpRerankerService,
    NoopRerankerService,
    RerankerService,
)
from memoryhub_core.storage.s3 import S3StorageAdapter
from src.tools.auth import require_auth

_embedding_service: EmbeddingService | None = None
_reranker_service: RerankerService | None = None
_s3_adapter: S3StorageAdapter | None = None
_s3_checked: bool = False


def get_embedding_service() -> EmbeddingService:
    """Return the embedding service, using HTTP if MEMORYHUB_EMBEDDING_URL is set."""
    global _embedding_service
    if _embedding_service is None:
        url = os.environ.get("MEMORYHUB_EMBEDDING_URL")
        _embedding_service = HttpEmbeddingService(url) if url else MockEmbeddingService()
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
        _reranker_service = HttpRerankerService(url) if url else NoopRerankerService()
    return _reranker_service


async def get_db_session():
    gen = get_session()
    session = await gen.__anext__()
    return session, gen


async def release_db_session(gen):
    with contextlib.suppress(StopAsyncIteration):
        await gen.__anext__()


def get_s3_adapter() -> S3StorageAdapter | None:
    """Return the S3 adapter, or None if MEMORYHUB_S3_ACCESS_KEY is not set.

    Follows the same singleton pattern as get_embedding_service. Returns
    None (rather than raising) when S3 is not configured so callers can
    degrade gracefully to inline storage.
    """
    global _s3_adapter, _s3_checked
    if not _s3_checked:
        from memoryhub_core.config import MinIOSettings
        settings = MinIOSettings()
        if settings.access_key:
            _s3_adapter = S3StorageAdapter(settings)
        _s3_checked = True
    return _s3_adapter


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


def resolve_driver_id(per_request: str | None, claims: dict) -> str:
    """Resolve driver_id: per-request > session default > actor_id.

    The three-tier fallback captures who is ultimately driving a write:
      1. Explicit per-request driver_id (highest priority)
      2. Session-level default set at register_session time
      3. The authenticated actor_id (autonomous agent acting for itself)
    """
    if per_request is not None:
        return per_request
    from src.tools.auth import get_default_driver_id
    session_default = get_default_driver_id()
    if session_default is not None:
        return session_default
    return claims["sub"]
