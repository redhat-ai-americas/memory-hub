"""Bind dashboard people to their OAuth clients for object authorization.

Revision ID: 033_ui_agent_owners
Revises: 032_persona_source_values
"""

import sqlalchemy as sa

from alembic import op

revision = "033_ui_agent_owners"
down_revision = "032_persona_source_values"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "memoryhub_ui_agent_owners",
        sa.Column("tenant_id", sa.String(255), nullable=False),
        sa.Column("client_id", sa.String(255), nullable=False),
        sa.Column("owner", sa.String(255), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "client_id"),
    )
    op.create_index("ix_memoryhub_ui_agent_owners_owner", "memoryhub_ui_agent_owners", ["tenant_id", "owner"])


def downgrade() -> None:
    op.drop_index("ix_memoryhub_ui_agent_owners_owner", table_name="memoryhub_ui_agent_owners")
    op.drop_table("memoryhub_ui_agent_owners")
