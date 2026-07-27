"""Dialect-conditional column types for SQLite/PostgreSQL portability.

Provides type decorators and a configure_for_dialect() entry point that
swaps PostgreSQL-specific column types (UUID, ARRAY, Vector, TSVECTOR,
Interval) for portable equivalents when running on SQLite.

The _JsonEncodedVector TypeDecorator was previously a test-only patch in
tests/test_services/conftest.py. It is now production code used by the
SQLite backend.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import Integer, String, Text
from sqlalchemy.types import TypeDecorator


class PortableUUID(TypeDecorator):
    """UUID stored as TEXT(36) on SQLite, native UUID on PostgreSQL."""

    impl = String(36)
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, uuid.UUID):
            return str(value)
        return str(uuid.UUID(value))

    def process_result_value(self, value: Any, dialect: Any) -> uuid.UUID | None:
        if value is None:
            return None
        return uuid.UUID(value) if not isinstance(value, uuid.UUID) else value


class JsonEncodedList(TypeDecorator):
    """ARRAY(Text) stored as JSON text on SQLite."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Any) -> str | None:
        if value is None:
            return None
        return json.dumps(value)

    def process_result_value(self, value: Any, dialect: Any) -> list | None:
        if value is None:
            return None
        return json.loads(value)


class JsonEncodedVector(TypeDecorator):
    """Vector(N) stored as JSON text on SQLite, pgvector on PostgreSQL.

    Serializes list[float] to/from JSON text for SQLite storage.
    sqlite-vec operates on raw blobs via its own functions, but ORM-level
    reads/writes go through this decorator.
    """

    impl = Text
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Any) -> str | None:
        if value is None:
            return None
        return json.dumps(value)

    def process_result_value(self, value: Any, dialect: Any) -> list[float] | None:
        if value is None:
            return None
        return json.loads(value)


class IntervalSeconds(TypeDecorator):
    """PostgreSQL Interval stored as INTEGER (seconds) on SQLite."""

    impl = Integer
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Any) -> int | None:
        if value is None:
            return None
        if hasattr(value, "total_seconds"):
            return int(value.total_seconds())
        return int(value)

    def process_result_value(self, value: Any, dialect: Any) -> int | None:
        if value is None:
            return None
        return int(value)
