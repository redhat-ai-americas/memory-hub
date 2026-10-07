"""Merge the audit_log and curator_rule_versioning heads.

PRs #533 (audit log persistence) and #592 (curation rule versioning) were
branched from 027 independently and merged in the same batch, leaving two
revisions numbered 028 with no shared ancestor. `alembic upgrade head` then
fails with "Multiple head revisions are present", which breaks the
integration suite (tests/integration/conftest.py runs the upgrade) and blocks
every subsequent schema change.

This revision has no schema effect. It exists only to rejoin the two
branches so there is a single head again. Later migrations should revise
029_merge_audit_and_curator.

Revision ID: 029_merge_audit_and_curator
Revises: 028_add_audit_log, 028_add_curator_rule_versioning
Create Date: 2026-10-07
"""

revision = "029_merge_audit_and_curator"
down_revision = ("028_add_audit_log", "028_add_curator_rule_versioning")
branch_labels = None
depends_on = None


def upgrade() -> None:
    """No-op: this revision only rejoins two migration branches."""


def downgrade() -> None:
    """No-op: resplitting into two heads requires no schema change."""
