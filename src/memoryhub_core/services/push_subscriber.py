"""Pattern E (#62): reader-side subscriber loop + lifecycle management.

The writer side (``push_broadcast.py``) LPUSHes serialized notifications onto
``memoryhub:broadcast:<session_id>``. This module's per-session subscriber
task BRPOPs from that queue and forwards messages to the connected client
via ``session.send_notification``.

Lifecycle is tied to the FastMCP session:
- ``register_session`` calls :func:`ensure_memoryhub_subscriber_running` to
  spawn the task when an agent connects. Idempotent — safe to call multiple
  times for the same session_id.
- The FastMCP ``_exit_stack.push_async_callback`` hook in ``register_session``
  registers a cleanup that calls :func:`stop_memoryhub_subscriber` when the
  session disconnects, cancelling the task cleanly. Pending messages stay
  in the Valkey queue (with TTL) so a reconnecting agent with the same
  session_id can pick them up.

The loop itself is cloned from FastMCP 3.2.0's reference implementation at
``fastmcp/server/tasks/notifications.py:76-162`` — same retry semantics, same
heartbeat-via-BRPOP-timeout pattern — but method-agnostic. Memory-hub can't
use FastMCP's built-in loop because its ``_send_mcp_notification`` helper
hard-codes a ``notifications/tasks/status`` method whitelist.
"""

from __future__ import annotations

import asyncio
import json
import logging
import weakref
from contextlib import suppress
from typing import Any

import mcp.types as mt
from mcp.server.session import ServerSession

from memoryhub_core.services.valkey_client import (
    ValkeyClient,
    ValkeyUnavailableError,
    get_valkey_client,
)

logger = logging.getLogger(__name__)


# Maximum delivery attempts before discarding a notification. Matches
# FastMCP's ``MAX_DELIVERY_ATTEMPTS`` so the retry behavior is consistent
# across both notification pipelines running in the same process.
MAX_DELIVERY_ATTEMPTS = 3


# Registry of active subscriber tasks per session.
# Keyed by session_id -> (task, weakref to ServerSession). The weakref lets
# us detect GC'd sessions that never triggered a clean shutdown (e.g., the
# HTTP connection dropped without the _exit_stack cleanup firing).
_active_subscribers: dict[
    str, tuple[asyncio.Task[None], weakref.ref[ServerSession]]
] = {}


def _reconstruct_notification(notification_dict: dict[str, Any]) -> Any:
    """Turn a BRPOPed notification dict back into a Pydantic model.

    Two paths:
    - ``notifications/resources/updated`` wraps in a typed
      ``ResourceUpdatedNotification`` inside ``ServerNotification`` (the
      closed union MCP expects for spec-compliant notifications).
    - Custom ``notifications/memoryhub/*`` methods bypass the closed union
      by constructing a plain :class:`mcp.types.Notification`. ``send_notification``
      accepts anything that serializes to ``{method, params}`` because it
      calls ``.model_dump()`` before building the JSON-RPC envelope.
    """
    method = notification_dict.get("method", "")
    params = notification_dict.get("params", {})

    if method == "notifications/resources/updated":
        return mt.ServerNotification(
            mt.ResourceUpdatedNotification(
                method="notifications/resources/updated",
                params=mt.ResourceUpdatedNotificationParams(uri=params.get("uri", "")),
            )
        )

    # Custom notifications/$vendor/$method path. Unknown-method notifications
    # are valid per the MCP spec; clients that don't recognize the method
    # will ignore them. We still pass through a Pydantic model so that
    # ServerSession.send_notification's .model_dump() call works.
    return mt.Notification[Any, str](method=method, params=params)


async def memoryhub_subscriber_loop(
    session_id: str,
    session: ServerSession,
    valkey_client: ValkeyClient,
) -> None:
    """BRPOPs ``memoryhub:broadcast:<session_id>`` and forwards to the client.

    Runs as a long-lived asyncio.Task started by :func:`ensure_memoryhub_subscriber_running`.
    On each iteration:
    1. BRPOPs one message from the session's broadcast queue (blocks up to
       the Valkey client's ``broadcast_pop_timeout_seconds``).
    2. Reconstructs the notification from the envelope.
    3. Forwards to the client via ``session.send_notification``.
    4. On delivery failure, re-queues with ``attempt+1`` until
       :data:`MAX_DELIVERY_ATTEMPTS` is exhausted, then discards.

    Shuts down cleanly on :exc:`asyncio.CancelledError` (raised by
    :func:`stop_memoryhub_subscriber` when the session disconnects).
    Transient errors from Valkey or the transport trigger a short backoff
    and retry rather than terminating the loop — the subscriber must stay
    resilient across brief connectivity blips for the lifetime of the HTTP
    session.
    """
    logger.debug("Starting memoryhub subscriber for session %s", session_id)

    while True:
        try:
            message = await valkey_client.pop_broadcast_message(session_id)
            if message is None:
                continue  # BRPOP timeout — refresh heartbeat and retry.

            try:
                envelope = json.loads(message)
            except json.JSONDecodeError as exc:
                logger.warning(
                    "Dropping malformed broadcast message for %s: %s",
                    session_id, exc,
                )
                continue

            attempt = envelope.get("attempt", 0)
            notification_dict = envelope.get("notification", {})

            try:
                notification = _reconstruct_notification(notification_dict)
                await session.send_notification(notification)
                logger.debug(
                    "Delivered memoryhub notification to session %s (attempt %d)",
                    session_id, attempt + 1,
                )
            except Exception as send_error:
                if attempt < MAX_DELIVERY_ATTEMPTS - 1:
                    retry_envelope = {
                        "notification": notification_dict,
                        "attempt": attempt + 1,
                        "last_error": str(send_error),
                    }
                    try:
                        await valkey_client.push_broadcast_message(
                            session_id, json.dumps(retry_envelope)
                        )
                    except ValkeyUnavailableError as exc:
                        logger.warning(
                            "Failed to requeue broadcast for %s: %s",
                            session_id, exc,
                        )
                    logger.debug(
                        "Requeued broadcast for %s (attempt %d): %s",
                        session_id, attempt + 2, send_error,
                    )
                else:
                    logger.warning(
                        "Discarding broadcast for %s after %d attempts: %s",
                        session_id, MAX_DELIVERY_ATTEMPTS, send_error,
                    )
        except asyncio.CancelledError:
            logger.debug("memoryhub subscriber cancelled for session %s", session_id)
            raise
        except Exception as exc:
            logger.debug(
                "memoryhub subscriber error for session %s: %s", session_id, exc
            )
            await asyncio.sleep(1)


async def ensure_memoryhub_subscriber_running(
    session_id: str,
    session: ServerSession,
    valkey_client: ValkeyClient | None = None,
) -> None:
    """Start a subscriber task for this session if one isn't already running.

    Idempotent — safe to call multiple times for the same session_id. If a
    task already exists and is still alive and the session weakref is still
    valid, the call is a no-op. If the task has finished or the session has
    been garbage-collected, the stale entry is cleaned up and a fresh
    subscriber is spawned.

    This is called from the ``register_session`` MCP tool during both the
    JWT-authenticated and API-key-authenticated code paths, so a pure-listener
    agent (one that never submits a task of its own) still has a subscriber
    loop running to receive broadcasts.
    """
    if valkey_client is None:
        valkey_client = get_valkey_client()

    if session_id in _active_subscribers:
        task, session_ref = _active_subscribers[session_id]
        if not task.done() and session_ref() is not None:
            return  # Already running, nothing to do.
        # Stale entry — cancel any lingering task and fall through to restart.
        if not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        del _active_subscribers[session_id]

    task = asyncio.create_task(
        memoryhub_subscriber_loop(session_id, session, valkey_client),
        name=f"memoryhub-subscriber-{session_id[:8]}",
    )
    _active_subscribers[session_id] = (task, weakref.ref(session))
    logger.debug("Started memoryhub subscriber for session %s", session_id)


async def stop_memoryhub_subscriber(session_id: str) -> None:
    """Cancel the subscriber task for a session and remove it from the registry.

    Called from the FastMCP ``_exit_stack`` cleanup registered in
    ``register_session``. Pending messages remain in the Valkey queue (with
    TTL from ``broadcast_ttl_seconds``) so a reconnecting agent with the same
    session_id can pick them up.
    """
    if session_id not in _active_subscribers:
        return

    task, _ = _active_subscribers.pop(session_id)
    if not task.done():
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
    logger.debug("Stopped memoryhub subscriber for session %s", session_id)


def get_active_subscriber_count() -> int:
    """Return the number of live subscriber tasks (for tests and monitoring)."""
    return len(_active_subscribers)


def _reset_subscriber_registry_for_tests() -> None:
    """Clear the module-level subscriber registry between tests.

    The registry is module-global because it tracks per-process state that
    outlives any individual request. Tests that exercise it should call this
    in a fixture or teardown to avoid state leakage across cases.
    """
    _active_subscribers.clear()
