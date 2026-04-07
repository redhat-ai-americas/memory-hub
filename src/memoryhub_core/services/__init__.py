"""Business logic for memory operations."""

from memoryhub_core.services.database import close_db, get_session, init_db
from memoryhub_core.services.embeddings import EMBEDDING_DIM, EmbeddingService, MockEmbeddingService
from memoryhub_core.services.exceptions import (
    ContradictionNotFoundError,
    MemoryAccessDeniedError,
    MemoryNotCurrentError,
    MemoryNotFoundError,
)
from memoryhub_core.services.memory import (
    create_memory,
    get_memory_history,
    read_memory,
    report_contradiction,
    resolve_contradiction,
    search_memories,
    update_memory,
)

__all__ = [
    "EMBEDDING_DIM",
    "EmbeddingService",
    "MemoryAccessDeniedError",
    "MemoryNotCurrentError",
    "MemoryNotFoundError",
    "MockEmbeddingService",
    "close_db",
    "create_memory",
    "get_memory_history",
    "get_session",
    "init_db",
    "read_memory",
    "ContradictionNotFoundError",
    "report_contradiction",
    "resolve_contradiction",
    "search_memories",
    "update_memory",
]
