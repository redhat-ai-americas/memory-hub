"""Add upstream_trust_level column to memory_nodes.

Tracks the trust level of upstream content that produced this memory.
Dreaming-extracted memories inherit trust from their source conversation.
Existing rows default to 'trusted'.

Part of #559 (OMP-informed improvements).

Revision ID: 031_add_upstream_trust_level
Revises: 030_add_procedural_content_type
Create Date: 2026-09-10
"""

import sqlalchemy as sa
from alembic import op

revision = "031_add_upstream_trust_level"
down_revision = "030_add_procedural_content_type"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "memory_nodes",
        sa.Column(
            "upstream_trust_level",
            sa.String(20),
            nullable=False,
            server_default="trusted",
        ),
    )
    op.create_index(
        "ix_memory_nodes_upstream_trust_level",
        "memory_nodes",
        ["upstream_trust_level"],
    )


def downgrade() -> None:
    op.drop_index("ix_memory_nodes_upstream_trust_level", table_name="memory_nodes")
    op.drop_column("memory_nodes", "upstream_trust_level")
