"""Add logical_id column to memory_nodes.

Stable identity that persists across all versions of the same memory.
V1 nodes set logical_id = id; updates inherit from the previous version.
Backfills existing data using a recursive CTE to walk version chains.

Part of #472 (graph edge versioning).

Revision ID: 027_add_logical_id
Revises: 026_add_source_column
Create Date: 2026-07-29
"""

import sqlalchemy as sa
from alembic import op

revision = "027_add_logical_id"
down_revision = "026_add_source_column"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "memory_nodes",
        sa.Column("logical_id", sa.UUID(), nullable=True),
    )

    # Backfill: current versions get logical_id = id
    op.execute("UPDATE memory_nodes SET logical_id = id WHERE is_current = true")

    # Backfill: walk version chains backward from current heads
    op.execute("""
        WITH RECURSIVE chain AS (
            SELECT id, previous_version_id, id AS logical_id
            FROM memory_nodes WHERE is_current = true
            UNION ALL
            SELECT mn.id, mn.previous_version_id, c.logical_id
            FROM memory_nodes mn
            JOIN chain c ON mn.id = c.previous_version_id
        )
        UPDATE memory_nodes SET logical_id = chain.logical_id
        FROM chain WHERE memory_nodes.id = chain.id
    """)

    # Catch orphaned nodes (all versions deleted, no current head)
    op.execute("UPDATE memory_nodes SET logical_id = id WHERE logical_id IS NULL")

    op.alter_column("memory_nodes", "logical_id", nullable=False)
    op.create_index("ix_memory_nodes_logical_id", "memory_nodes", ["logical_id"])


def downgrade() -> None:
    op.drop_index("ix_memory_nodes_logical_id", table_name="memory_nodes")
    op.drop_column("memory_nodes", "logical_id")
