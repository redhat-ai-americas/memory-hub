"""Add generating_model column to memory_nodes.

Tracks which LLM produced dreaming-extracted memories. Nullable because
user-stated memories have no generating model.

Part of #566 (OMP-informed improvements).

Revision ID: 029_add_generating_model
Revises: 028_add_upstream_trust_level
Create Date: 2026-09-10
"""

import sqlalchemy as sa

from alembic import op

revision = "029_add_generating_model"
down_revision = "028_add_upstream_trust_level"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "memory_nodes",
        sa.Column(
            "generating_model",
            sa.String(255),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("memory_nodes", "generating_model")
