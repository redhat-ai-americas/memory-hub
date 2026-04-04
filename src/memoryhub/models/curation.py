"""SQLAlchemy ORM model for curation rules.

CuratorRule rows define how the curation engine evaluates memory writes and reads.
Rules are layered (system → organizational → user) and the engine applies them in
priority order, stopping at the first rule whose action is terminal (block, reject).
"""

import uuid

from sqlalchemy import Boolean, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column

from memoryhub.models.base import Base, TimestampMixin


class CuratorRule(TimestampMixin, Base):
    """A single curation policy rule.

    Rules are evaluated in ascending priority order (lower number = higher priority).
    The layer hierarchy (system < organizational < user) determines who can define rules,
    and the override flag controls whether a lower layer can supersede a higher one.
    """

    __tablename__ = "curator_rules"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuid_generate_v4()"),
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # When this rule fires
    trigger: Mapped[str] = mapped_column(String(30), nullable=False)

    # Evaluation strategy: regex pattern match or embedding similarity check
    tier: Mapped[str] = mapped_column(String(20), nullable=False)

    # Rule-specific parameters (pattern, threshold, etc.) as free-form JSON
    config: Mapped[dict] = mapped_column(
        JSON,
        server_default=text("'{}'::jsonb"),
        nullable=False,
    )

    # What to do when the rule matches
    action: Mapped[str] = mapped_column(String(30), nullable=False)

    # Restrict to a specific MemoryScope value; null means all scopes
    scope_filter: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # Which layer owns this rule
    layer: Mapped[str] = mapped_column(String(20), nullable=False)

    # null for system and organizational rules; set to owner identifier for user rules
    owner_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # When true, this rule can override rules from a higher layer
    override: Mapped[bool] = mapped_column(
        Boolean,
        server_default=text("false"),
        nullable=False,
    )

    enabled: Mapped[bool] = mapped_column(
        Boolean,
        server_default=text("true"),
        nullable=False,
    )

    # Lower number = evaluated first
    priority: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        UniqueConstraint("layer", "owner_id", "name", name="uq_curator_rules_layer_owner_name"),
        Index("ix_curator_rules_layer_owner", "layer", "owner_id"),
        Index("ix_curator_rules_trigger", "trigger"),
        Index(
            "ix_curator_rules_enabled",
            "enabled",
            postgresql_where=text("enabled = true"),
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<CuratorRule id={self.id!s:.8} layer={self.layer} "
            f"trigger={self.trigger} action={self.action} priority={self.priority}>"
        )
