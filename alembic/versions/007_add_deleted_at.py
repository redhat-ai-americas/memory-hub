"""Add deleted_at column to memory_nodes for soft-delete support.

Revision ID: 007_add_deleted_at
Revises: 006_add_oauth_clients
Create Date: 2026-04-06
"""

import sqlalchemy as sa
from alembic import op

revision = "007_add_deleted_at"
down_revision = "006_add_oauth_clients"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "memory_nodes",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_memory_nodes_deleted_at", "memory_nodes", ["deleted_at"])


def downgrade() -> None:
    op.drop_index("ix_memory_nodes_deleted_at", table_name="memory_nodes")
    op.drop_column("memory_nodes", "deleted_at")
