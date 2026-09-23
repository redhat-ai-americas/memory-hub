"""SQLAlchemy ORM model for curation rules.

CuratorRule rows define how the curation engine evaluates memory writes and reads.
Rules are layered (system → organizational → user) and the engine applies them in
priority order, stopping at the first rule whose action is terminal (block, reject).

Each edit creates a new row (copy-on-write). is_current=True identifies the active
version; previous_version_id chains versions for audit history.
"""

import uuid

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column

from memoryhub_core.models.base import Base, TimestampMixin


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

    # Multi-tenant isolation — populated from JWT claims on the server side
    tenant_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        server_default=text("'default'"),
    )

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

    # Versioning — same pattern as memory_nodes
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default=text("1"))
    previous_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("curator_rules.id", ondelete="SET NULL"),
        nullable=True,
    )
    is_current: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("true"),
        index=True,
    )
    # Who made the edit that produced this version (null for system-seeded rules)
    edited_by: Mapped[str | None] = mapped_column(String(255), nullable=True)

    __table_args__ = (
        # Partial unique index: only one current rule per (layer, owner_id, name)
        Index(
            "uq_curator_rules_current_layer_owner_name",
            "layer", "owner_id", "name",
            unique=True,
            postgresql_where=text("is_current = true"),
        ),
        Index("ix_curator_rules_layer_owner", "layer", "owner_id"),
        Index("ix_curator_rules_trigger", "trigger"),
        Index(
            "ix_curator_rules_enabled",
            "enabled",
            postgresql_where=text("enabled = true"),
        ),
        Index("ix_curator_rules_tenant", "tenant_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<CuratorRule id={self.id!s:.8} layer={self.layer} "
            f"trigger={self.trigger} action={self.action} priority={self.priority} v{self.version}>"
        )
