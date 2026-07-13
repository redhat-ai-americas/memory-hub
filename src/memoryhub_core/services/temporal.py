"""Lightweight temporal classifier for memory content.

Classifies memory content by temporal signal and returns a
``relevant_until`` timestamp (or None for evergreen/version-bound
content). Runs synchronously in the write path -- this is a
regex/heuristic classifier, NOT an LLM call.

Categories:
- Explicit deadline: "deploy by 2026-07-15" -> specific date
- Relative deadline: "within 2 weeks" -> computed date
- Implicit temporal: "currently using" -> now + 90 days
- Version-bound: "PostgreSQL 15" -> None
- Evergreen: "prefers dark mode" -> None
"""

from __future__ import annotations

import calendar
import re
from datetime import UTC, datetime, timedelta

# Implicit temporal markers -> now + 90 days
_IMPLICIT_TEMPORAL_PATTERNS = [
    re.compile(r"\bcurrently\b", re.IGNORECASE),
    re.compile(r"\bright now\b", re.IGNORECASE),
    re.compile(r"\bat the moment\b", re.IGNORECASE),
    re.compile(r"\bfor now\b", re.IGNORECASE),
    re.compile(r"\bat present\b", re.IGNORECASE),
    re.compile(r"\bfor the time being\b", re.IGNORECASE),
    re.compile(r"\btemporarily\b", re.IGNORECASE),
]

_IMPLICIT_TEMPORAL_DAYS = 90

# ISO date pattern: 2026-07-15
_ISO_DATE_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")

# Deadline phrases with ISO dates: "by 2026-07-15", "deadline 2026-07-15",
# "due 2026-07-15", "before 2026-07-15", "until 2026-07-15"
_DEADLINE_ISO_RE = re.compile(
    r"\b(?:by|deadline|due|before|until)\s+(\d{4})-(\d{2})-(\d{2})\b",
    re.IGNORECASE,
)

# Month names for natural-language date parsing
_MONTH_NAMES = {
    name.lower(): num
    for num, name in enumerate(calendar.month_name)
    if num > 0
}
_MONTH_ABBREVS = {
    name.lower(): num
    for num, name in enumerate(calendar.month_abbr)
    if num > 0
}
_ALL_MONTHS = {**_MONTH_NAMES, **_MONTH_ABBREVS}

# Deadline phrases with natural dates: "by July 15", "deadline July 15, 2026",
# "due March 1st"
_MONTH_PATTERN = "|".join(
    re.escape(m) for m in sorted(_ALL_MONTHS.keys(), key=len, reverse=True)
)
_DEADLINE_NATURAL_RE = re.compile(
    rf"\b(?:by|deadline|due|before|until)\s+"
    rf"({_MONTH_PATTERN})\s+(\d{{1,2}})(?:st|nd|rd|th)?"
    rf"(?:,?\s+(\d{{4}}))?",
    re.IGNORECASE,
)

# Relative deadline: "within N days/weeks/months", "in N days/weeks/months"
_RELATIVE_RE = re.compile(
    r"\b(?:within|in)\s+(\d+)\s+(days?|weeks?|months?)\b",
    re.IGNORECASE,
)

# "next week", "next month"
_NEXT_UNIT_RE = re.compile(
    r"\bnext\s+(week|month)\b",
    re.IGNORECASE,
)

# Version-bound patterns: these indicate version-specific content that is
# not time-bound. Return None when found (no semantic expiry).
_VERSION_RE = re.compile(
    r"\bv\d+(?:\.\d+)*\b|\bversion\s+\d+",
    re.IGNORECASE,
)


def classify_temporal(
    content: str,
    created_at: datetime | None = None,
) -> datetime | None:
    """Classify memory content and return a relevant_until timestamp.

    Returns None for evergreen or version-bound content (no semantic expiry).
    The classifier checks patterns in priority order:
    1. Deadline phrases with explicit dates
    2. Standalone ISO dates
    3. Relative deadlines ("within N weeks")
    4. "Next week/month"
    5. Implicit temporal markers ("currently", "for now")
    6. Version references -> None (version-bound, skip)
    7. No signal -> None (evergreen)
    """
    now = created_at or datetime.now(UTC)

    # 1. Deadline phrases with ISO dates (highest priority -- most explicit)
    m = _DEADLINE_ISO_RE.search(content)
    if m:
        return _parse_iso_match(m.group(1), m.group(2), m.group(3))

    # 2. Deadline phrases with natural dates
    m = _DEADLINE_NATURAL_RE.search(content)
    if m:
        parsed = _parse_natural_date(m.group(1), m.group(2), m.group(3), now)
        if parsed is not None:
            return parsed

    # 3. Standalone ISO dates (e.g., "Deploy 2026-07-15")
    m = _ISO_DATE_RE.search(content)
    if m:
        return _parse_iso_match(m.group(1), m.group(2), m.group(3))

    # 4. Relative deadlines
    m = _RELATIVE_RE.search(content)
    if m:
        count = int(m.group(1))
        unit = m.group(2).lower().rstrip("s")
        return _apply_relative(now, count, unit)

    # 5. "Next week/month"
    m = _NEXT_UNIT_RE.search(content)
    if m:
        unit = m.group(1).lower()
        if unit == "week":
            return now + timedelta(weeks=1)
        if unit == "month":
            return now + timedelta(days=30)

    # 6. Implicit temporal markers
    for pattern in _IMPLICIT_TEMPORAL_PATTERNS:
        if pattern.search(content):
            return now + timedelta(days=_IMPLICIT_TEMPORAL_DAYS)

    # 7. No temporal signal found -> evergreen
    return None


def compute_temporal_status(relevant_until: datetime | None) -> str | None:
    """Compute temporal status from a relevant_until timestamp.

    Returns:
        None: evergreen or version-bound (no semantic expiry)
        "expired": relevant_until is in the past
        "expiring_soon": relevant_until is within 7 days
        "current": relevant_until is more than 7 days away
    """
    if relevant_until is None:
        return None
    now = datetime.now(UTC)
    if relevant_until.tzinfo is None:
        relevant_until = relevant_until.replace(tzinfo=UTC)
    if relevant_until < now:
        return "expired"
    if relevant_until < now + timedelta(days=7):
        return "expiring_soon"
    return "current"


def _parse_iso_match(year_s: str, month_s: str, day_s: str) -> datetime | None:
    """Parse year/month/day strings into a UTC datetime, or None on error."""
    try:
        return datetime(
            int(year_s), int(month_s), int(day_s),
            23, 59, 59, tzinfo=UTC,
        )
    except (ValueError, OverflowError):
        return None


def _parse_natural_date(
    month_s: str,
    day_s: str,
    year_s: str | None,
    now: datetime,
) -> datetime | None:
    """Parse a natural-language month + day + optional year."""
    month_num = _ALL_MONTHS.get(month_s.lower())
    if month_num is None:
        return None
    try:
        day = int(day_s)
        year = int(year_s) if year_s else now.year
        return datetime(year, month_num, day, 23, 59, 59, tzinfo=UTC)
    except (ValueError, OverflowError):
        return None


def _apply_relative(now: datetime, count: int, unit: str) -> datetime:
    """Apply a relative offset (days/weeks/months) to now."""
    if unit == "day":
        return now + timedelta(days=count)
    if unit == "week":
        return now + timedelta(weeks=count)
    if unit == "month":
        return now + timedelta(days=count * 30)
    return now
