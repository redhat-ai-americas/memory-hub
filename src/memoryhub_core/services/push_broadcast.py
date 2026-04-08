"""Pattern E (#62): writer-side push broadcast helpers.

Composes with the pull-based loading patterns from
``docs/agent-memory-ergonomics``. When an agent writes a memory, this module's
``broadcast_to_sessions`` is called from the mutating MCP tool after DB commit.
It enumerates the ``memoryhub:active_sessions`` set, reads each session's
focus vector from the #61 hash, computes cosine similarity against the new
memory's embedding, and LPUSHes a serialized notification envelope onto each
targeted session's broadcast queue.

The reader side (BRPOP subscriber loop + session lifecycle) lives in
``push_subscriber.py``. The only coupling between the two modules is the
Valkey queue schema defined in ``valkey_client.py`` (``memoryhub:broadcast:*``).

Why memory-hub has its own broadcast pipeline instead of reusing FastMCP's:
FastMCP 3's built-in ``push_notification`` + ``notification_subscriber_loop``
hard-code a method whitelist (only ``notifications/tasks/status`` is accepted).
Memory-hub sends ``notifications/resources/updated`` and a custom
``notifications/memoryhub/memory_written``, neither of which would survive
that whitelist. The pattern here is cloned from FastMCP's reference
implementation at ``fastmcp/server/tasks/notifications.py`` but namespaced
separately and method-agnostic.
"""

from __future__ import annotations

import json
import logging
import math
from typing import Any

from memoryhub_core.services.valkey_client import (
    ValkeyClient,
    ValkeyUnavailableError,
    get_valkey_client,
)

logger = logging.getLogger(__name__)


# Default push filter weight: session-focus cosine similarity below this
# threshold skips the broadcast for that session. Lower values deliver more
# broadly; higher values are stricter filters. Mirrors the pull-side
# ``session_focus_weight`` knob (default 0.4 from #58) but is independently
# configurable because push filtering and pull biasing may want different
# strictness — see docs/agent-memory-ergonomics/design.md §Pattern E.
DEFAULT_PUSH_FILTER_WEIGHT = 0.6


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two float vectors in [-1.0, 1.0].

    Returns 0.0 if either vector is all-zero to avoid division by zero.
    Raises ValueError if the vectors have different lengths — callers are
    responsible for ensuring both embeddings came from the same model.
    """
    if len(a) != len(b):
        raise ValueError(f"vector length mismatch: {len(a)} vs {len(b)}")
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def memory_uri(memory_id: str) -> str:
    """Canonical MCP URI for a memory node."""
    return f"memoryhub://memory/{memory_id}"


def build_uri_only_notification(memory_id: str) -> dict[str, Any]:
    """Spec-compliant ``ResourceUpdatedNotification`` payload as a dict.

    Subscribers receive the URI and are expected to call ``read_memory``
    (or ``resources/read``) to fetch the actual content. Small wire
    footprint, spec-compliant, one round-trip per interested subscriber.

    Use this when ``push_payload: uri_only`` (the default) is configured.
    """
    return {
        "method": "notifications/resources/updated",
        "params": {"uri": memory_uri(memory_id)},
    }


def build_full_content_notification(memory: dict[str, Any]) -> dict[str, Any]:
    """Custom ``notifications/memoryhub/memory_written`` carrying the full record.

    Non-spec but valid under MCP's ``notifications/$vendor/$method`` pattern.
    Clients that don't know the custom method will ignore the notification
    (standard MCP behavior for unknown notifications). Larger wire footprint
    but zero follow-up round-trips.

    Use this when ``push_payload: full_content`` is configured. The ``memory``
    dict should already be serialized (e.g., ``node.model_dump(mode="json")``).
    """
    return {
        "method": "notifications/memoryhub/memory_written",
        "params": {
            "uri": memory_uri(memory["id"]),
            "memory": memory,
        },
    }


async def broadcast_to_sessions(
    notification: dict[str, Any],
    memory_embedding: list[float] | None,
    valkey_client: ValkeyClient | None = None,
    push_filter_weight: float = DEFAULT_PUSH_FILTER_WEIGHT,
    exclude_session_id: str | None = None,
) -> dict[str, int]:
    """Push ``notification`` to every active session whose focus passes the filter.

    Enumerates ``memoryhub:active_sessions``, optionally filters each session
    by cosine similarity between its stored focus vector and the memory
    embedding, and LPUSHes a JSON envelope onto surviving sessions' broadcast
    queues. Non-raising — backend errors are counted and returned rather
    than propagating. Never blocks on delivery confirmation (the subscriber
    loop on the reader side is responsible for actually forwarding messages
    to the client via ``session.send_notification``).

    Args:
        notification: Dict with ``method`` and ``params`` keys. Use
            :func:`build_uri_only_notification` or
            :func:`build_full_content_notification` to construct.
        memory_embedding: The new memory's embedding vector. If ``None``, the
            focus filter is skipped and the notification is delivered to all
            active sessions. Pass ``None`` for deletes that don't carry a
            stored embedding.
        valkey_client: Override for testing. Defaults to the module client.
        push_filter_weight: Minimum cosine similarity (0.0-1.0) between the
            memory embedding and a session's focus vector for the broadcast
            to reach that session. Sessions with no declared focus bypass
            the filter entirely (match the pull-side "focus is optional"
            convention).
        exclude_session_id: Optional session_id to skip. Typically set to
            the writing session so an agent doesn't receive a broadcast for
            its own write.

    Returns:
        A dict ``{"targeted", "delivered", "filtered", "errors"}`` with
        per-broadcast counts. Callers can log or expose these for monitoring
        but must not rely on them for correctness.
    """
    if valkey_client is None:
        valkey_client = get_valkey_client()

    try:
        active_sessions = await valkey_client.read_active_sessions()
    except ValkeyUnavailableError as exc:
        logger.warning("Cannot read active_sessions for broadcast: %s", exc)
        return {"targeted": 0, "delivered": 0, "filtered": 0, "errors": 1}

    envelope = {"notification": notification, "attempt": 0}
    serialized = json.dumps(envelope)

    targeted = 0
    delivered = 0
    filtered = 0
    errors = 0

    for session_id in active_sessions:
        if session_id == exclude_session_id:
            continue
        targeted += 1

        # Session-focus pre-filter. Skip the LPUSH when the session declared
        # a focus and that focus is cosine-distant from the memory embedding.
        # Sessions without a focus vector fall through unconditionally.
        if memory_embedding is not None:
            try:
                session_focus = await valkey_client.read_session_focus_vector(
                    session_id
                )
            except ValkeyUnavailableError as exc:
                logger.debug(
                    "Skipping focus filter for %s due to read error: %s",
                    session_id, exc,
                )
                session_focus = None

            if session_focus is not None:
                try:
                    similarity = cosine_similarity(memory_embedding, session_focus)
                except ValueError as exc:
                    logger.warning(
                        "Focus/memory vector length mismatch for %s; "
                        "delivering unfiltered: %s",
                        session_id, exc,
                    )
                else:
                    if similarity < push_filter_weight:
                        filtered += 1
                        continue

        try:
            await valkey_client.push_broadcast_message(session_id, serialized)
            delivered += 1
        except ValkeyUnavailableError as exc:
            logger.warning("Failed to push broadcast to %s: %s", session_id, exc)
            errors += 1

    return {
        "targeted": targeted,
        "delivered": delivered,
        "filtered": filtered,
        "errors": errors,
    }
