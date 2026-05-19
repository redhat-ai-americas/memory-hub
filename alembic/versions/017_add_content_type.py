"""Add content_type column for behavioral memory.

Revision ID: 017_add_content_type
Revises: 016_escalate_pii_to_block
Create Date: 2026-05-19
"""

import sqlalchemy as sa

from alembic import op

revision = "017_add_content_type"
down_revision = "016_escalate_pii_to_block"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add content_type column with default 'experiential'
    op.add_column(
        "memory_nodes",
        sa.Column(
            "content_type",
            sa.String(20),
            nullable=False,
            server_default="experiential",
        ),
    )

    # Add CHECK constraint for valid content types
    op.create_check_constraint(
        "ck_memory_nodes_content_type",
        "memory_nodes",
        "content_type IN ('experiential', 'knowledge', 'behavioral')",
    )

    # Add index on content_type for filtering
    op.create_index(
        "ix_memory_nodes_content_type",
        "memory_nodes",
        ["content_type"],
    )

    # Add composite index on (content_type, scope) for common query patterns
    op.create_index(
        "ix_memory_nodes_content_type_scope",
        "memory_nodes",
        ["content_type", "scope"],
    )


def downgrade() -> None:
    # Drop indexes first
    op.drop_index("ix_memory_nodes_content_type_scope", "memory_nodes")
    op.drop_index("ix_memory_nodes_content_type", "memory_nodes")

    # Drop CHECK constraint
    op.drop_constraint("ck_memory_nodes_content_type", "memory_nodes")

    # Drop column
    op.drop_column("memory_nodes", "content_type")
