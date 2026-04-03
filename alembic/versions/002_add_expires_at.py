"""Add expires_at column for version TTL.

Revision ID: 002_add_expires_at
Revises: 001_initial
Create Date: 2026-04-03
"""

import sqlalchemy as sa

from alembic import op

revision = "002_add_expires_at"
down_revision = "001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "memory_nodes",
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_memory_nodes_expires_at",
        "memory_nodes",
        ["expires_at"],
        postgresql_where=sa.text("expires_at IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_memory_nodes_expires_at", table_name="memory_nodes")
    op.drop_column("memory_nodes", "expires_at")
