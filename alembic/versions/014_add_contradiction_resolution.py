"""Add resolution metadata to contradiction_reports (#103).

Adds resolution_action and resolved_by columns so contradiction
resolutions carry a disposition (accept_new, keep_old, etc.) and
the identity of the resolver.

Revision ID: 014_add_contradiction_resolution
Revises: 013_add_relationship_validity
Create Date: 2026-04-20
"""

import sqlalchemy as sa

from alembic import op

revision = "014_add_contradiction_resolution"
down_revision = "013_add_relationship_validity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "contradiction_reports",
        sa.Column("resolution_action", sa.String(50), nullable=True),
    )
    op.add_column(
        "contradiction_reports",
        sa.Column("resolved_by", sa.String(255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("contradiction_reports", "resolved_by")
    op.drop_column("contradiction_reports", "resolution_action")
