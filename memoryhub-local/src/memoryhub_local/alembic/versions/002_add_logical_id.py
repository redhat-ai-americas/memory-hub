"""Add logical_id column to memory_nodes.

Stable identity that persists across all versions of the same memory.
V1 nodes set logical_id = id; updates inherit from the previous version.

Part of #472 (graph edge versioning).

Revision ID: 002_add_logical_id
Revises: e05b0e59db47
Create Date: 2026-07-29
"""

import sqlalchemy as sa
from alembic import op

import memoryhub_local.models.dialect  # noqa: F401

revision = "002_add_logical_id"
down_revision = "e05b0e59db47"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("memory_nodes") as batch_op:
        batch_op.add_column(
            sa.Column("logical_id", memoryhub_local.models.dialect.PortableUUID(length=36), nullable=True),
        )
        batch_op.create_index("ix_memory_nodes_logical_id", ["logical_id"])

    # Backfill: current versions get logical_id = id
    op.execute("UPDATE memory_nodes SET logical_id = id WHERE is_current = 1")

    # Backfill: walk version chains backward from current heads.
    # SQLite lacks UPDATE...FROM, so use a correlated subquery.
    op.execute("""
        WITH RECURSIVE chain AS (
            SELECT id, previous_version_id, id AS logical_id
            FROM memory_nodes WHERE is_current = 1
            UNION ALL
            SELECT mn.id, mn.previous_version_id, c.logical_id
            FROM memory_nodes mn
            JOIN chain c ON mn.id = c.previous_version_id
        )
        UPDATE memory_nodes SET logical_id = (
            SELECT chain.logical_id FROM chain WHERE chain.id = memory_nodes.id
        )
        WHERE memory_nodes.id IN (SELECT id FROM chain)
    """)

    # Catch orphaned nodes
    op.execute("UPDATE memory_nodes SET logical_id = id WHERE logical_id IS NULL")


def downgrade() -> None:
    with op.batch_alter_table("memory_nodes") as batch_op:
        batch_op.drop_index("ix_memory_nodes_logical_id")
        batch_op.drop_column("logical_id")
