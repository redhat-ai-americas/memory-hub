"""Super-user incident grants and the #667 admin scope model.

Revision ID: 0003_break_glass
Revises: 0002_verify_results
Create Date: 2026-10-29

* ``memoryhub_ui_break_glass``: time-limited grants that let a super-user open
  user-scope memories for one incident (#667 tier 3). Every grant carries an
  incident reference and a justification; reads under it are audited.
* Tenants still on the old default admin scope list (organizational and
  enterprise only) move to the #667 default: admins read and moderate every
  scope except user. A list an operator changed on purpose is left alone.
"""

from alembic import op

revision = "0003_break_glass"
down_revision = "0002_verify_results"
branch_labels = None
depends_on = None

TABLES = ["memoryhub_ui_break_glass"]


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS memoryhub_ui_break_glass (
            id UUID PRIMARY KEY,
            tenant_id VARCHAR(255) NOT NULL,
            username VARCHAR(255) NOT NULL,
            incident_ref VARCHAR(64) NOT NULL,
            justification TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            expires_at TIMESTAMPTZ NOT NULL,
            ended_at TIMESTAMPTZ
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_memoryhub_ui_break_glass_user "
        "ON memoryhub_ui_break_glass (tenant_id, username, expires_at DESC)"
    )
    op.execute(
        """
        UPDATE memoryhub_ui_settings
        SET settings = jsonb_set(
            settings::jsonb, '{privacy,admin_readable_scopes}',
            '["project", "campaign", "role", "organizational", "enterprise"]'::jsonb
        )
        WHERE settings::jsonb #> '{privacy,admin_readable_scopes}' = '["organizational", "enterprise"]'::jsonb
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS memoryhub_ui_break_glass")
