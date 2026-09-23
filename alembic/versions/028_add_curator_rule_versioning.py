"""Add versioning columns to curator_rules for audit trail.

Adds version, previous_version_id, is_current, and edited_by columns
following the same pattern as memory_nodes versioning.

Revision ID: 028_add_curator_rule_versioning
Revises: 027_add_logical_id
Create Date: 2026-09-23
"""

import sqlalchemy as sa
from alembic import op

revision = "028_add_curator_rule_versioning"
down_revision = "027_add_logical_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("curator_rules", sa.Column("version", sa.Integer(), server_default="1", nullable=False))
    op.add_column("curator_rules", sa.Column("previous_version_id", sa.UUID(), nullable=True))
    op.add_column("curator_rules", sa.Column("is_current", sa.Boolean(), server_default=sa.text("true"), nullable=False))
    op.add_column("curator_rules", sa.Column("edited_by", sa.String(255), nullable=True))

    op.create_foreign_key(
        "fk_curator_rules_previous_version",
        "curator_rules",
        "curator_rules",
        ["previous_version_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # Replace unique constraint with partial index on current versions only.
    # The original constraint prevented multiple versions of the same rule.
    op.drop_constraint("uq_curator_rules_layer_owner_name", "curator_rules", type_="unique")
    op.create_index(
        "uq_curator_rules_current_layer_owner_name",
        "curator_rules",
        ["layer", "owner_id", "name"],
        unique=True,
        postgresql_where=sa.text("is_current = true"),
    )

    op.create_index("ix_curator_rules_is_current", "curator_rules", ["is_current"])

    # Backfill existing rows
    op.execute("UPDATE curator_rules SET version = 1, is_current = true WHERE version IS NULL OR is_current IS NULL")


def downgrade() -> None:
    op.drop_index("ix_curator_rules_is_current", table_name="curator_rules")
    op.drop_index("uq_curator_rules_current_layer_owner_name", table_name="curator_rules")
    # Historical (non-current) versions would violate the pre-versioning unique constraint;
    # delete them before recreating it. Only the current version of each rule survives downgrade.
    op.execute("DELETE FROM curator_rules WHERE is_current = false")
    op.create_unique_constraint(
        "uq_curator_rules_layer_owner_name",
        "curator_rules",
        ["layer", "owner_id", "name"],
    )
    op.drop_constraint("fk_curator_rules_previous_version", "curator_rules", type_="foreignkey")
    op.drop_column("curator_rules", "edited_by")
    op.drop_column("curator_rules", "is_current")
    op.drop_column("curator_rules", "previous_version_id")
    op.drop_column("curator_rules", "version")
