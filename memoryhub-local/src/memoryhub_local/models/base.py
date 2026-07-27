"""SQLAlchemy base class and shared mixins for memoryhub-local.

Identical to memoryhub_core.models.base -- a separate Base is needed so that
the local models register their tables independently of the core models.
"""

from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Base class for all memoryhub-local SQLAlchemy ORM models."""


class TimestampMixin:
    """Mixin that adds created_at and updated_at columns with timezone-aware UTC timestamps."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
