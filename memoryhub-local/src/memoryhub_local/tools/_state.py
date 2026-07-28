"""Shared server state for tool wrappers.

Holds references to the database session factory, embedding service,
and recall backend. Initialized once at server startup.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import sessionmaker

    from memoryhub_local.embeddings.base import EmbeddingService
    from memoryhub_local.storage.recall import RecallBackend

_state: ServerState | None = None


@dataclass
class ServerState:
    session_factory: sessionmaker
    embedding_service: EmbeddingService
    recall_backend: RecallBackend


def init_state(
    session_factory: sessionmaker,
    embedding_service: EmbeddingService,
    recall_backend: RecallBackend,
) -> None:
    """Initialize global server state. Called once at startup."""
    global _state
    _state = ServerState(
        session_factory=session_factory,
        embedding_service=embedding_service,
        recall_backend=recall_backend,
    )


def get_state() -> ServerState:
    """Get the current server state. Raises if not initialized."""
    if _state is None:
        raise RuntimeError("Server state not initialized. Call init_state() first.")
    return _state
