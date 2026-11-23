"""Last-use bookkeeping for clients and API keys (#721).

Writes at most once a minute per client or key, so a busy agent does not turn
every token request into an UPDATE. Timestamps only: no IPs, no request data.
"""

from datetime import UTC, datetime, timedelta

THROTTLE = timedelta(seconds=60)


def _stale(value: datetime | None, now: datetime) -> bool:
    if value is None:
        return True
    if value.tzinfo is None:  # SQLite in tests returns naive datetimes
        value = value.replace(tzinfo=UTC)
    return now - value >= THROTTLE


def mark_client_used(client, via: str) -> bool:
    """Record that ``client`` obtained a token through ``via``; True when a write is due."""
    now = datetime.now(UTC)
    if not _stale(client.last_used_at, now) and client.last_used_via == via:
        return False
    client.last_used_at = now
    client.last_used_via = via
    return True


def mark_key_used(row, attr: str = "last_used_at") -> bool:
    """Record that an API key was accepted; True when a write is due."""
    now = datetime.now(UTC)
    if not _stale(getattr(row, attr), now):
        return False
    setattr(row, attr, now)
    return True
