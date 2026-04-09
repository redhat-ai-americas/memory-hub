"""Add domains text array column to memory_nodes for crosscutting knowledge categorization.

Revision ID: 010_add_domains
Revises: 009_add_campaigns
Create Date: 2026-04-09
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "010_add_domains"
down_revision = "009_add_campaigns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "memory_nodes",
        sa.Column(
            "domains",
            postgresql.ARRAY(sa.Text()),
            nullable=True,
            server_default=sa.text("'{}'::text[]"),
        ),
    )

    # GIN index enables efficient array containment queries (@> operator),
    # e.g. finding all nodes tagged with a given domain.
    op.create_index(
        "ix_memory_nodes_domains",
        "memory_nodes",
        ["domains"],
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_index("ix_memory_nodes_domains", table_name="memory_nodes")
    op.drop_column("memory_nodes", "domains")
