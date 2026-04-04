"""Add curator_rules table for memory curation policies.

Revision ID: 004_add_curator_rules
Revises: 003_add_memory_relationships
Create Date: 2026-04-04
"""

import sqlalchemy as sa

from alembic import op

revision = "004_add_curator_rules"
down_revision = "003_add_memory_relationships"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "curator_rules",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v4()"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("trigger", sa.String(30), nullable=False),
        sa.Column("tier", sa.String(20), nullable=False),
        sa.Column("config", sa.JSON(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("action", sa.String(30), nullable=False),
        sa.Column("scope_filter", sa.String(20), nullable=True),
        sa.Column("layer", sa.String(20), nullable=False),
        sa.Column("owner_id", sa.String(255), nullable=True),
        sa.Column("override", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("layer", "owner_id", "name", name="uq_curator_rules_layer_owner_name"),
    )

    op.create_index(
        "ix_curator_rules_layer_owner",
        "curator_rules",
        ["layer", "owner_id"],
    )
    op.create_index(
        "ix_curator_rules_trigger",
        "curator_rules",
        ["trigger"],
    )
    op.create_index(
        "ix_curator_rules_enabled",
        "curator_rules",
        ["enabled"],
        postgresql_where=sa.text("enabled = true"),
    )


def downgrade() -> None:
    op.drop_index("ix_curator_rules_enabled", table_name="curator_rules")
    op.drop_index("ix_curator_rules_trigger", table_name="curator_rules")
    op.drop_index("ix_curator_rules_layer_owner", table_name="curator_rules")
    op.drop_table("curator_rules")
