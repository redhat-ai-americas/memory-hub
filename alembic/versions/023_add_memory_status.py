"""Add status column to memory_nodes.

Supports the content moderation workflow (issue #45). Memories carry a
status field governing visibility: 'active' (default), 'quarantined'
(hidden from non-admin queries), or 'soft_deleted' (pending GC).
Existing rows default to 'active' so this migration is non-destructive.

Revision ID: 023_add_memory_status
Revises: 022_add_relevant_until
Create Date: 2026-06-30
"""

import sqlalchemy as sa

from alembic import op

revision = "023_add_memory_status"
down_revision = "022_add_relevant_until"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "memory_nodes",
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="active",
        ),
    )
    op.create_index(
        "ix_memory_nodes_status",
        "memory_nodes",
        ["status"],
    )


def downgrade() -> None:
    op.drop_index("ix_memory_nodes_status", "memory_nodes")
    op.drop_column("memory_nodes", "status")
