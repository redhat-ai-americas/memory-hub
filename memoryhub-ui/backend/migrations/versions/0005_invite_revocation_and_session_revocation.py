"""Invite revocation/supersession and server-side session revocation (QA 2026-11-06).

- memoryhub_ui_invites: revoked_at, revoked_by, revoke_reason
- older duplicate open invites for one address are marked superseded, then a
  partial unique index keeps at most one open invite per tenant + address
- memoryhub_ui_revoked_sessions: hashes of logged-out session cookies
"""
from alembic import op

revision = "0005_invite_session_revocation"
down_revision = "0004_account_sessions"
branch_labels = None
depends_on = None

TABLES = ["memoryhub_ui_revoked_sessions"]


def upgrade() -> None:
    op.execute("ALTER TABLE memoryhub_ui_invites ADD COLUMN IF NOT EXISTS revoked_at TIMESTAMPTZ")
    op.execute("ALTER TABLE memoryhub_ui_invites ADD COLUMN IF NOT EXISTS revoked_by TEXT")
    op.execute("ALTER TABLE memoryhub_ui_invites ADD COLUMN IF NOT EXISTS revoke_reason TEXT")
    op.execute(
        """
        UPDATE memoryhub_ui_invites SET revoked_at = now(), revoked_by = 'migration-0005',
               revoke_reason = 'superseded'
        WHERE code IN (
            SELECT code FROM (
                SELECT code, row_number() OVER (PARTITION BY tenant_id, lower(email) ORDER BY created_at DESC) AS rn
                FROM memoryhub_ui_invites
                WHERE email IS NOT NULL AND used_at IS NULL AND revoked_at IS NULL
            ) ranked WHERE rn > 1
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_ui_invites_one_open_per_email ON memoryhub_ui_invites "
        "(tenant_id, lower(email)) WHERE email IS NOT NULL AND used_at IS NULL AND revoked_at IS NULL"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS memoryhub_ui_revoked_sessions (
            token_hash TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            username TEXT NOT NULL,
            revoked_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            expires_at TIMESTAMPTZ NOT NULL
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_ui_revoked_sessions_expires ON memoryhub_ui_revoked_sessions (expires_at)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS memoryhub_ui_revoked_sessions")
    op.execute("DROP INDEX IF EXISTS uq_ui_invites_one_open_per_email")
    for col in ("revoke_reason", "revoked_by", "revoked_at"):
        op.execute(f"ALTER TABLE memoryhub_ui_invites DROP COLUMN IF EXISTS {col}")
