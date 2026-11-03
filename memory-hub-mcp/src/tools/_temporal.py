"""Parsing helpers for explicit semantic relevance dates."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, time

_DATE_ONLY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_relevant_until(value: str) -> datetime:
    """Parse ISO-8601 timestamps; date-only values remain valid through that day."""
    normalized = value.strip()
    if _DATE_ONLY.fullmatch(normalized):
        return datetime.combine(date.fromisoformat(normalized), time.max, tzinfo=UTC)

    parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)
