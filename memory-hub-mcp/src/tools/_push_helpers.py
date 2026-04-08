"""Post-commit broadcast helpers for the #62 push pipeline.

The mutating tools (``write_memory``, ``update_memory``, ``delete_memory``)
call :func:`broadcast_after_write` after a successful DB commit. This
helper centralizes three concerns those tools all share:

1. **Fast path on no subscribers.** Reads ``memoryhub:active_sessions``
   first. If only the writing session is in the set (or the set is empty),
   the helper returns immediately without paying the embedding cost. This
   keeps single-session deployments cheap.
2. **Per-write embedding for the focus filter.** If there are subscribers
   other than the writer, the new memory's content is embedded once and
   passed to ``broadcast_to_sessions``. The cost is amortized across all
   subscribers — one embed call per write, not per subscriber.
3. **Non-fatal failure semantics.** Any exception is logged at DEBUG and
   swallowed. A broadcast failure must never roll back a successful DB
   commit, and never raise back into the tool's response path. Pull-based
   loading continues to work even when push is broken.

The helper is intentionally not part of ``memoryhub_core.services`` because
it depends on the MCP claims dict and the per-tool embedding service
fetcher — both of which live in the tool layer.
"""

from __future__ import annotations

import logging
from typing import Any

from memoryhub_core.services.embeddings import EmbeddingService
from memoryhub_core.services.push_broadcast import broadcast_to_sessions
from memoryhub_core.services.valkey_client import (
    ValkeyUnavailableError,
    get_valkey_client,
)

logger = logging.getLogger(__name__)


async def broadcast_after_write(
    memory_id: str,
    notification: dict[str, Any],
    claims: dict[str, Any],
    *,
    content_for_filter: str | None = None,
    embedding_service: EmbeddingService | None = None,
) -> None:
    """Broadcast a memory change to active sessions after a successful commit.

    Args:
        memory_id: The new (or deleted) memory's ID, used only for logging.
        notification: Pre-built notification dict from
            :func:`memoryhub_core.services.push_broadcast.build_uri_only_notification`
            or :func:`build_full_content_notification`.
        claims: The authenticated agent's JWT claims dict. The ``sub`` claim
            is used as the writer's session_id and excluded from the broadcast
            so an agent doesn't receive a notification for its own write.
        content_for_filter: Memory content to embed for the focus filter.
            Pass ``None`` to skip the filter entirely (used for deletes,
            where the broadcast goes to every active session unconditionally).
        embedding_service: Required when ``content_for_filter`` is set. May
            be ``None`` for deletes.

    Returns:
        ``None``. Failures are logged at DEBUG and swallowed.
    """
    try:
        valkey_client = get_valkey_client()
        try:
            active_sessions = await valkey_client.read_active_sessions()
        except ValkeyUnavailableError as exc:
            logger.debug(
                "Skipping broadcast for %s: cannot read active_sessions (%s)",
                memory_id, exc,
            )
            return

        writer_id = claims.get("sub")
        relevant = [sid for sid in active_sessions if sid != writer_id]
        if not relevant:
            # Fast path: no other subscribers, nothing to do. Crucially,
            # we skip the embedding service call here so single-session
            # deployments pay zero broadcast overhead per write.
            logger.debug(
                "No relevant subscribers for broadcast of %s; skipping",
                memory_id,
            )
            return

        memory_embedding: list[float] | None = None
        if content_for_filter is not None:
            if embedding_service is None:
                logger.debug(
                    "embedding_service required when content_for_filter is set; "
                    "delivering %s unfiltered",
                    memory_id,
                )
            else:
                try:
                    memory_embedding = await embedding_service.embed(
                        content_for_filter
                    )
                except Exception as exc:
                    logger.debug(
                        "Failed to embed content for broadcast filter on %s: %s; "
                        "delivering unfiltered",
                        memory_id, exc,
                    )

        result = await broadcast_to_sessions(
            notification=notification,
            memory_embedding=memory_embedding,
            valkey_client=valkey_client,
            exclude_session_id=writer_id,
        )
        logger.debug(
            "Broadcast of %s to %d sessions: delivered=%d filtered=%d errors=%d",
            memory_id,
            result["targeted"],
            result["delivered"],
            result["filtered"],
            result["errors"],
        )
    except Exception as exc:
        # Catch-all so a broadcast bug never propagates into the tool's
        # response path. The DB commit has already happened by the time we
        # reach here, so silently degrading is the right behavior.
        logger.debug("Post-commit broadcast failed for %s: %s", memory_id, exc)
