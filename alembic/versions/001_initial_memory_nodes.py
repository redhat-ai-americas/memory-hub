"""Create memory_nodes table with extensions.

Revision ID: 001_initial
Revises:
Create Date: 2026-04-03
"""

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

from alembic import op

revision = "001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Enable required PostgreSQL extensions
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "memory_nodes",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v4()"), nullable=False),
        sa.Column("parent_id", sa.UUID(), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("stub", sa.Text(), nullable=False),
        sa.Column("storage_type", sa.String(10), nullable=False, server_default="inline"),
        sa.Column("content_ref", sa.String(1024), nullable=True),
        sa.Column("weight", sa.Float(), nullable=False, server_default="0.7"),
        sa.Column("scope", sa.String(20), nullable=False),
        sa.Column("branch_type", sa.String(50), nullable=True),
        sa.Column("owner_id", sa.String(255), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("previous_version_id", sa.UUID(), nullable=True),
        sa.Column("embedding", Vector(384), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["parent_id"], ["memory_nodes.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["previous_version_id"], ["memory_nodes.id"], ondelete="SET NULL"),
    )

    # Individual column indexes
    op.create_index("ix_memory_nodes_parent_id", "memory_nodes", ["parent_id"])
    op.create_index("ix_memory_nodes_owner_id", "memory_nodes", ["owner_id"])
    op.create_index("ix_memory_nodes_scope", "memory_nodes", ["scope"])
    op.create_index("ix_memory_nodes_is_current", "memory_nodes", ["is_current"])

    # Composite index for the most common query pattern
    op.create_index(
        "ix_memory_nodes_owner_scope_current",
        "memory_nodes",
        ["owner_id", "scope", "is_current"],
    )


def downgrade() -> None:
    op.drop_index("ix_memory_nodes_owner_scope_current", table_name="memory_nodes")
    op.drop_index("ix_memory_nodes_is_current", table_name="memory_nodes")
    op.drop_index("ix_memory_nodes_scope", table_name="memory_nodes")
    op.drop_index("ix_memory_nodes_owner_id", table_name="memory_nodes")
    op.drop_index("ix_memory_nodes_parent_id", table_name="memory_nodes")
    op.drop_table("memory_nodes")

    # Note: not dropping extensions in downgrade — they may be shared
