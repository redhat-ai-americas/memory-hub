"""Structured audit logging for MemoryHub MCP operations.

Every tool invocation that touches authorization or data mutation emits
a JSON event via the ``memoryhub.audit`` logger. This stub writes to the
standard Python logging pipeline; a future phase will persist events to
a durable store (PostgreSQL audit table or external SIEM).

Events are fire-and-forget: audit failures never block the tool operation.
"""

import json
import logging
from datetime import UTC, datetime

logger = logging.getLogger("memoryhub.audit")


def record_event(
    event_type: str | None,
    actor_id: str,
    driver_id: str,
    scope: str,
    owner_id: str,
    memory_id: str | None,
    decision: str,
    metadata: dict | None = None,
) -> None:
    """Emit a structured audit event as JSON to the memoryhub.audit logger.

    Args:
        event_type: Dot-separated event kind (e.g. "memory.write",
            "session.registered").
        actor_id: Authenticated principal performing the operation.
        driver_id: Upstream human or system on whose behalf the action
            was taken. Equals actor_id for autonomous agents.
        scope: Memory scope (user, project, campaign, ...) or "session".
        owner_id: Owner of the target memory or resource.
        memory_id: UUID of the target memory, or None for non-memory ops.
        decision: "allowed" or "denied".
        metadata: Optional dict with additional context (query terms,
            result counts, etc.).
    """
    event = {
        "timestamp": datetime.now(UTC).isoformat(),
        "event_type": event_type,
        "actor_id": actor_id,
        "driver_id": driver_id,
        "scope": scope,
        "owner_id": owner_id,
        "memory_id": str(memory_id) if memory_id else None,
        "decision": decision,
    }
    if metadata:
        event["metadata"] = metadata
    logger.info(json.dumps(event, sort_keys=True))
