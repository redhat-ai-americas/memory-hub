"""Add memory_relationships table for graph edges.

Revision ID: 003_add_memory_relationships
Revises: 002_add_expires_at
Create Date: 2026-04-04
"""

import sqlalchemy as sa

from alembic import op

revision = "003_add_memory_relationships"
down_revision = "002_add_expires_at"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "memory_relationships",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v4()"), nullable=False),
        sa.Column("source_id", sa.UUID(), nullable=False),
        sa.Column("target_id", sa.UUID(), nullable=False),
        sa.Column("relationship_type", sa.String(50), nullable=False),
        sa.Column("metadata_", sa.JSON(), server_default=sa.text("'{}'::jsonb"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["source_id"], ["memory_nodes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["target_id"], ["memory_nodes.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("source_id", "target_id", "relationship_type", name="uq_memory_relationships_edge"),
        sa.CheckConstraint("source_id != target_id", name="ck_memory_relationships_no_self_ref"),
    )

    op.create_index(
        "ix_memory_relationships_source_type",
        "memory_relationships",
        ["source_id", "relationship_type"],
    )
    op.create_index(
        "ix_memory_relationships_target_type",
        "memory_relationships",
        ["target_id", "relationship_type"],
    )
    op.create_index(
        "ix_memory_relationships_type",
        "memory_relationships",
        ["relationship_type"],
    )


def downgrade() -> None:
    op.drop_index("ix_memory_relationships_type", table_name="memory_relationships")
    op.drop_index("ix_memory_relationships_target_type", table_name="memory_relationships")
    op.drop_index("ix_memory_relationships_source_type", table_name="memory_relationships")
    op.drop_table("memory_relationships")
