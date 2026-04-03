"""Shared dependencies for MCP tools."""

import os

from memoryhub.services.database import get_session
from memoryhub.services.embeddings import (
    EmbeddingService,
    HttpEmbeddingService,
    MockEmbeddingService,
)
from src.tools.auth import require_auth

_embedding_service: EmbeddingService | None = None


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

    Tools that want to fall back silently use this. Tools that must enforce auth
    should call src.tools.auth.require_auth() directly.
    """
    try:
        user = require_auth()
        return user["user_id"]
    except RuntimeError:
        return None
