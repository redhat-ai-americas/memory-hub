"""Add contradiction_reports table for persistent contradiction tracking.

Revision ID: 005_add_contradiction_reports
Revises: 004_add_curator_rules
Create Date: 2026-04-05
"""

import sqlalchemy as sa

from alembic import op

revision = "005_add_contradiction_reports"
down_revision = "004_add_curator_rules"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "contradiction_reports",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v4()"), nullable=False),
        sa.Column("memory_id", sa.UUID(), nullable=False),
        sa.Column("observed_behavior", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("reporter", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("resolved", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["memory_id"], ["memory_nodes.id"], ondelete="CASCADE"),
    )

    op.create_index(
        "ix_contradiction_reports_memory_resolved",
        "contradiction_reports",
        ["memory_id", "resolved"],
    )
    op.create_index(
        "ix_contradiction_reports_resolved_created",
        "contradiction_reports",
        ["resolved", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_contradiction_reports_resolved_created", table_name="contradiction_reports")
    op.drop_index("ix_contradiction_reports_memory_resolved", table_name="contradiction_reports")
    op.drop_table("contradiction_reports")
