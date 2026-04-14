"""Valkey (Redis-compatible) client for session focus state and broadcasts.

Four key prefixes back #61 (session focus history as a usage signal) and
#62 (Pattern E real-time push broadcast):

- ``memoryhub:sessions:<session_id>`` — hash containing the active-session
  state: ``focus``, ``focus_vector`` (base64-encoded float32 array),
  ``user_id``, ``project``, ``created_at``, ``expires_at``. Carries a TTL
  matching the JWT lifetime so stale sessions clear automatically. Written
  by #61's ``set_session_focus``; read by #62's broadcast filter.
- ``memoryhub:session_focus_history:<project>:<yyyy-mm-dd>`` — list of
  append-only JSON entries capturing focus declarations per project per day.
  Each daily list auto-expires after ``history_retention_days``.
- ``memoryhub:active_sessions`` — set of session_ids with live subscribers.
  Populated when an agent calls ``register_session``; depopulated on session
  close. Enumerated by the #62 broadcast helper to decide who to push to.
- ``memoryhub:compilation:<tenant_id>:<owner_id>`` — hash containing a
  compilation epoch for cache-optimized memory assembly (#175). Stores
  ``epoch``, ``ordered_ids`` (pipe-delimited), ``compilation_hash``,
  ``compiled_at``. 7-day TTL refreshed on read.
- ``memoryhub:broadcast:<session_id>`` — per-session reliable queue.
  ``broadcast_to_sessions`` LPUSHes JSON-serialized notifications here; the
  memoryhub subscriber loop BRPOPs from it and forwards to the client via
  ``session.send_notification``. 5-minute TTL so disconnected sessions'
  queues clear automatically. Mirrors FastMCP's own ``fastmcp:notifications``
  pattern but is namespaced separately because FastMCP's built-in subscriber
  hard-codes a ``notifications/tasks/status`` method whitelist (see
  ``fastmcp/server/tasks/notifications.py::_send_mcp_notification``).

Uses ``redis.asyncio`` because Valkey is protocol-compatible with Redis and
the ``redis`` Python client works unchanged. This matches the team-wide
"Valkey, not Redis" infrastructure rule (see project memory) while keeping
the client library choice unconstrained.
"""

from __future__ import annotations

import base64
import json
import logging
import struct
from datetime import date, datetime, timedelta, timezone
from typing import Any

from redis import asyncio as redis_async
from redis.exceptions import RedisError

from memoryhub_core.config import ValkeySettings

logger = logging.getLogger(__name__)


class ValkeyUnavailableError(Exception):
    """Raised when the Valkey backend cannot be reached or a command fails."""


def encode_vector(vector: list[float]) -> str:
    """Encode a float vector as a base64 ASCII string.

    Uses IEEE-754 single precision (4 bytes per element) to halve the footprint
    vs JSON-encoded floats. 384-dim embeddings become ~2 KB of base64.
    """
    packed = struct.pack(f"{len(vector)}f", *vector)
    return base64.b64encode(packed).decode("ascii")


def decode_vector(encoded: str) -> list[float]:
    """Decode a base64-encoded float32 vector back to a Python list."""
    packed = base64.b64decode(encoded)
    count = len(packed) // 4
    return list(struct.unpack(f"{count}f", packed))


ACTIVE_SESSIONS_KEY = "memoryhub:active_sessions"


def _session_key(session_id: str) -> str:
    return f"memoryhub:sessions:{session_id}"


def _history_key(project: str, day: date) -> str:
    return f"memoryhub:session_focus_history:{project}:{day.isoformat()}"


def _broadcast_key(session_id: str) -> str:
    return f"memoryhub:broadcast:{session_id}"


def _compilation_key(tenant_id: str, owner_id: str) -> str:
    return f"memoryhub:compilation:{tenant_id}:{owner_id}"


class ValkeyClient:
    """Thin async wrapper over ``redis.asyncio`` for MemoryHub's session state.

    Tests inject a fakeredis client via the ``client`` constructor arg to
    avoid a running Valkey instance. In production, the client is created
    lazily from ``ValkeySettings.url``.
    """

    def __init__(
        self,
        settings: ValkeySettings | None = None,
        client: Any | None = None,
    ) -> None:
        self._settings = settings or ValkeySettings()
        self._client = client

    async def _get_client(self) -> Any:
        if self._client is None:
            self._client = redis_async.from_url(self._settings.url, decode_responses=True)
        return self._client

    async def ping(self) -> bool:
        """Return True if the backend responds to PING, else False.

        Non-raising: intended for health checks. Logs the error at DEBUG so
        repeated checks don't spam warnings when Valkey is expected-unavailable
        in some test environments.
        """
        try:
            client = await self._get_client()
            await client.ping()
            return True
        except RedisError as exc:
            logger.debug("Valkey ping failed: %s", exc)
            return False

    async def write_session_focus(
        self,
        session_id: str,
        focus: str,
        focus_vector: list[float],
        user_id: str,
        project: str,
        ttl_seconds: int | None = None,
        now: datetime | None = None,
    ) -> dict[str, str]:
        """Write the active-session hash AND append a history entry atomically.

        Returns a summary dict carrying ``session_id`` and ``expires_at`` so
        callers can surface them to the agent. The ``now`` parameter is for
        deterministic tests; production should let it default.

        Raises:
            ValkeyUnavailableError: if the backend is unreachable or the
                pipeline fails.
        """
        ttl = ttl_seconds if ttl_seconds is not None else self._settings.session_ttl_seconds
        created_at = now or datetime.now(timezone.utc)
        expires_at = created_at + timedelta(seconds=ttl)
        history_retention = self._settings.history_retention_days * 86400

        session_key = _session_key(session_id)
        history_key = _history_key(project, created_at.date())
        history_entry = json.dumps(
            {
                "focus": focus,
                "session_id": session_id,
                "user_id": user_id,
                "timestamp": created_at.isoformat(),
            }
        )

        try:
            client = await self._get_client()
            async with client.pipeline(transaction=True) as pipe:
                pipe.hset(
                    session_key,
                    mapping={
                        "focus": focus,
                        "focus_vector": encode_vector(focus_vector),
                        "user_id": user_id,
                        "project": project,
                        "created_at": created_at.isoformat(),
                        "expires_at": expires_at.isoformat(),
                    },
                )
                pipe.expire(session_key, ttl)
                pipe.lpush(history_key, history_entry)
                pipe.expire(history_key, history_retention)
                await pipe.execute()
        except RedisError as exc:
            raise ValkeyUnavailableError(f"Failed to write session focus: {exc}") from exc

        return {"session_id": session_id, "expires_at": expires_at.isoformat()}

    async def read_focus_history(
        self,
        project: str,
        start_date: date,
        end_date: date,
    ) -> list[dict[str, Any]]:
        """Read all history entries for a project within an inclusive date range.

        Returns a flat list in unspecified order. Callers aggregate as needed.
        Malformed JSON entries are skipped silently — the underlying write path
        always emits JSON, so this is a defence-in-depth clause.

        Raises:
            ValueError: if ``end_date < start_date``.
            ValkeyUnavailableError: if the backend is unreachable.
        """
        if end_date < start_date:
            raise ValueError(f"end_date ({end_date}) is before start_date ({start_date})")

        entries: list[dict[str, Any]] = []
        try:
            client = await self._get_client()
            current = start_date
            while current <= end_date:
                history_key = _history_key(project, current)
                raw_entries = await client.lrange(history_key, 0, -1)
                for raw in raw_entries:
                    try:
                        entries.append(json.loads(raw))
                    except json.JSONDecodeError:
                        logger.warning(
                            "Skipping malformed focus history entry in %s: %r",
                            history_key,
                            raw,
                        )
                current += timedelta(days=1)
        except RedisError as exc:
            raise ValkeyUnavailableError(f"Failed to read focus history: {exc}") from exc

        return entries

    # ---------------------------------------------------------------- #62 #
    # Active session registry and per-session broadcast queue for Pattern E #
    # ---------------------------------------------------------------------- #

    async def register_active_session(self, session_id: str) -> None:
        """Add ``session_id`` to the active-sessions set.

        Called from ``register_session`` when an agent connects. The set is
        enumerated by ``broadcast_to_sessions`` to decide who to push to.
        Idempotent — SADD on an existing member is a no-op.

        Raises:
            ValkeyUnavailableError: if the backend is unreachable.
        """
        try:
            client = await self._get_client()
            await client.sadd(ACTIVE_SESSIONS_KEY, session_id)
        except RedisError as exc:
            raise ValkeyUnavailableError(
                f"Failed to register active session {session_id}: {exc}"
            ) from exc

    async def deregister_active_session(self, session_id: str) -> None:
        """Remove ``session_id`` from the active-sessions set.

        Called from the session-close cleanup hook. Idempotent — SREM on a
        non-member is a no-op. Also deletes the session's broadcast queue
        so orphan messages don't linger past the session lifetime.

        Raises:
            ValkeyUnavailableError: if the backend is unreachable.
        """
        try:
            client = await self._get_client()
            async with client.pipeline(transaction=True) as pipe:
                pipe.srem(ACTIVE_SESSIONS_KEY, session_id)
                pipe.delete(_broadcast_key(session_id))
                await pipe.execute()
        except RedisError as exc:
            raise ValkeyUnavailableError(
                f"Failed to deregister active session {session_id}: {exc}"
            ) from exc

    async def read_active_sessions(self) -> list[str]:
        """Return the list of session_ids currently in the active-sessions set.

        Order is unspecified. Callers should treat the result as a set.

        Raises:
            ValkeyUnavailableError: if the backend is unreachable.
        """
        try:
            client = await self._get_client()
            members = await client.smembers(ACTIVE_SESSIONS_KEY)
        except RedisError as exc:
            raise ValkeyUnavailableError(
                f"Failed to read active sessions: {exc}"
            ) from exc
        return list(members)

    async def read_session_focus_vector(
        self, session_id: str
    ) -> list[float] | None:
        """Read the stored focus vector for a session, decoded from base64.

        Returns ``None`` if the session hash does not exist or has no
        ``focus_vector`` field (which is the case when an agent has
        connected but never called ``set_session_focus``). The broadcast
        filter treats a None vector as "no focus declared" and delivers
        the notification unconditionally — consistent with the pull-side
        convention that focus is optional.

        Raises:
            ValkeyUnavailableError: if the backend is unreachable or the
                stored vector is malformed (not base64 or wrong length).
        """
        try:
            client = await self._get_client()
            encoded = await client.hget(_session_key(session_id), "focus_vector")
        except RedisError as exc:
            raise ValkeyUnavailableError(
                f"Failed to read session focus vector for {session_id}: {exc}"
            ) from exc

        if encoded is None:
            return None

        try:
            return decode_vector(encoded)
        except (ValueError, struct.error) as exc:
            raise ValkeyUnavailableError(
                f"Malformed focus_vector for session {session_id}: {exc}"
            ) from exc

    async def push_broadcast_message(
        self,
        session_id: str,
        payload: str,
    ) -> None:
        """LPUSH a serialized notification onto ``session_id``'s broadcast queue.

        The queue key carries a TTL from ``broadcast_ttl_seconds`` so that
        disconnected sessions' queues clear automatically instead of growing
        unbounded. Callers pre-serialize to a string (typically JSON) so
        this layer stays agnostic about notification shape.

        Raises:
            ValkeyUnavailableError: if the backend is unreachable.
        """
        key = _broadcast_key(session_id)
        try:
            client = await self._get_client()
            async with client.pipeline(transaction=True) as pipe:
                pipe.lpush(key, payload)
                pipe.expire(key, self._settings.broadcast_ttl_seconds)
                await pipe.execute()
        except RedisError as exc:
            raise ValkeyUnavailableError(
                f"Failed to push broadcast message for {session_id}: {exc}"
            ) from exc

    async def pop_broadcast_message(
        self,
        session_id: str,
        timeout_seconds: int | None = None,
    ) -> str | None:
        """BRPOP one message from ``session_id``'s broadcast queue.

        Blocks up to ``timeout_seconds`` (default: ``broadcast_pop_timeout_seconds``
        from settings) waiting for a message. Returns ``None`` on timeout — the
        caller's subscriber loop uses the return to refresh its heartbeat and
        retry rather than treating it as an error.

        Raises:
            ValkeyUnavailableError: if the backend is unreachable.
        """
        timeout = (
            timeout_seconds
            if timeout_seconds is not None
            else self._settings.broadcast_pop_timeout_seconds
        )
        key = _broadcast_key(session_id)
        try:
            client = await self._get_client()
            result = await client.brpop([key], timeout=timeout)
        except RedisError as exc:
            raise ValkeyUnavailableError(
                f"Failed to pop broadcast message for {session_id}: {exc}"
            ) from exc

        if result is None:
            return None
        _key, message = result
        return message

    # ---- Compilation epoch state (#175) -------------------------------------

    async def write_compilation(
        self,
        tenant_id: str,
        owner_id: str,
        epoch_data: dict[str, str],
        ttl_seconds: int | None = None,
    ) -> None:
        """Persist a compilation epoch as a Valkey hash.

        ``epoch_data`` is the dict returned by ``CompilationEpoch.to_dict()``.
        The key carries a long TTL (default 7 days) refreshed on every read
        so active compilations stay warm indefinitely.

        Raises:
            ValkeyUnavailableError: if the backend is unreachable.
        """
        ttl = ttl_seconds if ttl_seconds is not None else self._settings.compilation_ttl_seconds
        key = _compilation_key(tenant_id, owner_id)
        try:
            client = await self._get_client()
            async with client.pipeline(transaction=True) as pipe:
                pipe.delete(key)
                pipe.hset(key, mapping=epoch_data)
                pipe.expire(key, ttl)
                await pipe.execute()
        except RedisError as exc:
            raise ValkeyUnavailableError(
                f"Failed to write compilation for {tenant_id}/{owner_id}: {exc}"
            ) from exc

    async def read_compilation(
        self,
        tenant_id: str,
        owner_id: str,
    ) -> dict[str, str] | None:
        """Read the current compilation epoch, refreshing TTL on hit.

        Returns the raw hash dict (callers reconstruct ``CompilationEpoch``
        via ``from_dict``), or ``None`` if no compilation exists.

        Raises:
            ValkeyUnavailableError: if the backend is unreachable.
        """
        key = _compilation_key(tenant_id, owner_id)
        try:
            client = await self._get_client()
            data = await client.hgetall(key)
            if not data:
                return None
            # Refresh TTL so active compilations stay warm.
            await client.expire(
                key, self._settings.compilation_ttl_seconds
            )
            return data
        except RedisError as exc:
            raise ValkeyUnavailableError(
                f"Failed to read compilation for {tenant_id}/{owner_id}: {exc}"
            ) from exc

    async def delete_compilation(
        self,
        tenant_id: str,
        owner_id: str,
    ) -> None:
        """Remove a compilation epoch (manual reset or post-compaction cleanup).

        Raises:
            ValkeyUnavailableError: if the backend is unreachable.
        """
        key = _compilation_key(tenant_id, owner_id)
        try:
            client = await self._get_client()
            await client.delete(key)
        except RedisError as exc:
            raise ValkeyUnavailableError(
                f"Failed to delete compilation for {tenant_id}/{owner_id}: {exc}"
            ) from exc

    async def close(self) -> None:
        """Close the underlying client, if any."""
        if self._client is not None:
            try:
                await self._client.aclose()
            except RedisError as exc:
                logger.debug("Valkey close failed: %s", exc)
            self._client = None


# Module-level default client. Tools call ``get_valkey_client`` so tests can
# inject a fake via ``set_valkey_client``.
_default_client: ValkeyClient | None = None


def get_valkey_client() -> ValkeyClient:
    """Return the process-wide default ValkeyClient, creating it on first use."""
    global _default_client
    if _default_client is None:
        _default_client = ValkeyClient()
    return _default_client


def set_valkey_client(client: ValkeyClient | None) -> None:
    """Override the default client; used by tests to inject fakeredis."""
    global _default_client
    _default_client = client
