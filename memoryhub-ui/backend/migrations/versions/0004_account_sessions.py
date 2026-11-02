"""Revoke local account sessions when permissions or account status change."""

from alembic import op

revision = "0004_account_sessions"
down_revision = "0003_break_glass"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE memoryhub_ui_accounts ADD COLUMN IF NOT EXISTS session_version INTEGER NOT NULL DEFAULT 0")


def downgrade() -> None:
    op.execute("ALTER TABLE memoryhub_ui_accounts DROP COLUMN IF EXISTS session_version")
