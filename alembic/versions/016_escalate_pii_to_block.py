"""Escalate pii_scan system rule from flag to block.

Revision ID: 016_escalate_pii_to_block
Revises: 015_add_entity_extraction
Create Date: 2026-05-19
"""

from alembic import op

revision = "016_escalate_pii_to_block"
down_revision = "015_add_entity_extraction"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "UPDATE curator_rules SET action = 'block' WHERE name = 'pii_scan' AND layer = 'system'"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE curator_rules SET action = 'flag' WHERE name = 'pii_scan' AND layer = 'system'"
    )
