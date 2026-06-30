"""Add relevant_until column to memory_nodes.

Semantic expiry timestamp for memory content, distinct from expires_at
(storage lifecycle). NULL means no semantic expiry (evergreen or
version-bound). Populated by the temporal classifier at write time.

Revision ID: 022_add_relevant_until
Revises: 021_add_extraction_failures
Create Date: 2026-06-30
"""

import sqlalchemy as sa

from alembic import op

revision = "022_add_relevant_until"
down_revision = "021_add_extraction_failures"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "memory_nodes",
        sa.Column("relevant_until", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_memory_nodes_relevant_until",
        "memory_nodes",
        ["relevant_until"],
        postgresql_where=sa.text("relevant_until IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_memory_nodes_relevant_until", "memory_nodes")
    op.drop_column("memory_nodes", "relevant_until")
