"""Valkey (Redis-compatible) client for session focus state and history.

Two key prefixes back #61 (session focus history as a usage signal) and
#62 (Pattern E broadcast pre-filtering, when it lands):

- ``memoryhub:sessions:<session_id>`` — hash containing the active-session
  state: ``focus``, ``focus_vector`` (base64-encoded float32 array),
  ``user_id``, ``project``, ``created_at``, ``expires_at``. Carries a TTL
  matching the JWT lifetime so stale sessions clear automatically.
- ``memoryhub:session_focus_history:<project>:<yyyy-mm-dd>`` — list of
  append-only JSON entries capturing focus declarations per project per day.
  Each daily list auto-expires after ``history_retention_days``.

Only a small set of operations are needed by the MCP tools in this layer:
writing the pair of records, reading the history log across a date range,
and a health check. Session focus *reads* (used by the #62 broadcast filter)
are deferred until #62 lands.

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


def _session_key(session_id: str) -> str:
    return f"memoryhub:sessions:{session_id}"


def _history_key(project: str, day: date) -> str:
    return f"memoryhub:session_focus_history:{project}:{day.isoformat()}"


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
