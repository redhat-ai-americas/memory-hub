"""Add temporal validity to memory_relationships (#170 Phase 1).

Adds valid_from and valid_until columns for relationship lifecycle tracking.
Replaces the absolute unique constraint with a partial unique index that
only enforces uniqueness on active (valid_until IS NULL) edges, allowing
the invalidate-and-recreate pattern.

Revision ID: 013_add_relationship_validity
Revises: 012_add_projects_table
Create Date: 2026-04-17
"""

import sqlalchemy as sa

from alembic import op

revision = "013_add_relationship_validity"
down_revision = "012_add_projects_table"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add valid_from, backfilled from created_at.
    op.add_column(
        "memory_relationships",
        sa.Column(
            "valid_from",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    # Backfill existing rows: valid_from = created_at.
    op.execute(
        "UPDATE memory_relationships SET valid_from = created_at"
    )

    # Add valid_until (nullable — NULL means currently active).
    op.add_column(
        "memory_relationships",
        sa.Column(
            "valid_until",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    # Drop the absolute unique constraint and replace with a partial
    # unique index on active edges only. This allows invalidated edges
    # (valid_until IS NOT NULL) to coexist with new active edges for the
    # same (source, target, type) triple.
    op.drop_constraint(
        "uq_memory_relationships_edge", "memory_relationships", type_="unique",
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_memory_relationships_active_edge "
        "ON memory_relationships (source_id, target_id, relationship_type) "
        "WHERE valid_until IS NULL"
    )

    # Index for "find all invalidated edges" queries.
    op.execute(
        "CREATE INDEX ix_memory_relationships_valid_until "
        "ON memory_relationships (valid_until) "
        "WHERE valid_until IS NOT NULL"
    )

    # Composite index for temporal traversal queries.
    op.create_index(
        "ix_memory_relationships_source_type_validity",
        "memory_relationships",
        ["source_id", "relationship_type", "valid_until"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_memory_relationships_source_type_validity",
        table_name="memory_relationships",
    )
    op.execute(
        "DROP INDEX IF EXISTS ix_memory_relationships_valid_until"
    )
    op.execute(
        "DROP INDEX IF EXISTS uq_memory_relationships_active_edge"
    )

    # Re-create the absolute unique constraint (only safe if no
    # invalidated duplicates exist).
    op.create_unique_constraint(
        "uq_memory_relationships_edge",
        "memory_relationships",
        ["source_id", "target_id", "relationship_type"],
    )

    op.drop_column("memory_relationships", "valid_until")
    op.drop_column("memory_relationships", "valid_from")
