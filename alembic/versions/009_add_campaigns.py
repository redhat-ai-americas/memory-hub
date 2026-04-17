"""Add campaigns and campaign_memberships tables for cross-project knowledge sharing.

Revision ID: 009_add_campaigns
Revises: 008_add_tenant_id
Create Date: 2026-04-09
"""

import sqlalchemy as sa

from alembic import op

revision = "009_add_campaigns"
down_revision = "008_add_tenant_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "campaigns",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v4()"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(20), server_default=sa.text("'active'"), nullable=False),
        sa.Column("default_ttl", sa.Interval(), nullable=True),
        sa.Column("tenant_id", sa.String(255), server_default=sa.text("'default'"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "name", name="uq_campaigns_tenant_name"),
    )

    op.create_index("ix_campaigns_tenant", "campaigns", ["tenant_id"])

    op.create_table(
        "campaign_memberships",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v4()"), nullable=False),
        sa.Column("campaign_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.String(255), nullable=False),
        sa.Column("enrolled_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("enrolled_by", sa.String(255), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("campaign_id", "project_id", name="uq_campaign_memberships_enrollment"),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"], ondelete="CASCADE"),
    )

    op.create_index("ix_campaign_memberships_campaign", "campaign_memberships", ["campaign_id"])
    op.create_index("ix_campaign_memberships_project", "campaign_memberships", ["project_id"])


def downgrade() -> None:
    op.drop_index("ix_campaign_memberships_project", table_name="campaign_memberships")
    op.drop_index("ix_campaign_memberships_campaign", table_name="campaign_memberships")
    op.drop_table("campaign_memberships")

    op.drop_index("ix_campaigns_tenant", table_name="campaigns")
    op.drop_table("campaigns")
