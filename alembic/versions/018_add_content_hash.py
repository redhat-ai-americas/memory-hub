"""Add content_hash for entity deduplication.

Revision ID: 018_add_content_hash
Revises: 017_add_content_type
Create Date: 2026-05-19
"""

import sqlalchemy as sa

from alembic import op

revision = "018_add_content_hash"
down_revision = "017_add_content_type"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add content_hash column (nullable)
    op.add_column(
        "memory_nodes",
        sa.Column(
            "content_hash",
            sa.String(64),
            nullable=True,
        ),
    )

    # Add partial unique index for entity scope deduplication
    # Only enforce uniqueness on non-deleted entity nodes
    op.execute("""
        CREATE UNIQUE INDEX uq_memory_nodes_content_hash
        ON memory_nodes (content_hash)
        WHERE scope = 'entity' AND deleted_at IS NULL
    """)


def downgrade() -> None:
    # Drop the partial unique index first
    op.drop_index("uq_memory_nodes_content_hash", "memory_nodes")

    # Drop the content_hash column
    op.drop_column("memory_nodes", "content_hash")
