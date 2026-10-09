"""Merge the audit log and curator rule versioning migration heads.

The audit log and curator rule versioning migrations were both created from
revision 027, which left two independent 028 heads.  This empty revision
rejoins those branches so ``alembic upgrade head`` has a single target.

Revision ID: 029_merge_audit_and_curator
Revises: 028_add_audit_log, 028_add_curator_rule_versioning
Create Date: 2026-10-09
"""

revision = "029_merge_audit_and_curator"
down_revision = ("028_add_audit_log", "028_add_curator_rule_versioning")
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Rejoin the two migration branches without changing the schema."""


def downgrade() -> None:
    """Split the migration graph without changing the schema."""
