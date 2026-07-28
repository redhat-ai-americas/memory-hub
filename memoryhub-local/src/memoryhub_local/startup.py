"""Shared initialization for database, embeddings, and recall backend.

Used by both the MCP server (server.py) and the dream CLI command.
"""

from __future__ import annotations

import logging
import sys

from memoryhub_local.database import auto_migrate, create_local_engine, make_session_factory
from memoryhub_local.embeddings import (
    MockEmbeddingService,
    OnnxEmbeddingService,
    download_model,
    get_default_model_dir,
    is_model_downloaded,
)
from memoryhub_local.storage.sqlite import SQLiteBackend
from memoryhub_local.tools._state import ServerState, init_state

logger = logging.getLogger(__name__)


async def initialize_backend(*, quiet: bool = False) -> ServerState:
    """Initialize database, embeddings, and recall backend.

    Returns the initialized ServerState. Also calls init_state() to make
    it available via get_state() for tool wrappers.

    Parameters
    ----------
    quiet:
        If True, suppress stderr output (useful for CLI commands that
        control their own output).
    """
    engine = await create_local_engine()
    await auto_migrate(engine)
    session_factory = make_session_factory(engine)

    model_dir = get_default_model_dir()
    if not is_model_downloaded(model_dir):
        try:
            download_model(model_dir)
        except Exception:
            logger.warning(
                "Model download failed. Falling back to mock embeddings. "
                "Run 'memoryhub doctor' for diagnostics.",
                exc_info=True,
            )

    if is_model_downloaded(model_dir):
        embedding_service = OnnxEmbeddingService(model_dir)
        embed_label = "onnx"
    else:
        embedding_service = MockEmbeddingService()
        embed_label = "mock (run 'memoryhub doctor' to check model status)"
        if not quiet:
            print(
                "WARNING: Using mock embeddings. Search results will not be "
                "semantically meaningful. Run 'memoryhub doctor' for details.",
                file=sys.stderr,
            )

    recall_backend = SQLiteBackend()
    state = ServerState(
        session_factory=session_factory,
        embedding_service=embedding_service,
        recall_backend=recall_backend,
    )
    init_state(session_factory, embedding_service, recall_backend)

    if not quiet:
        from memoryhub_local.database import get_default_db_path
        db_path = get_default_db_path()
        logger.info("MemoryHub personal edition ready (db: %s, embeddings: %s)", db_path, embed_label)
        print(f"MemoryHub personal edition ready (db: {db_path}, embeddings: {embed_label})", file=sys.stderr)  # noqa: T201, E501

    return state
