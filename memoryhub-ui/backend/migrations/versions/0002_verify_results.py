"""Connection check results.

Revision ID: 0002_verify_results
Revises: 0001_ui_tables
Create Date: 2026-10-22

Results of the end-user connection check (R1-024): the checks the dashboard
runs itself and results produced on an agent host by a verifier command and
uploaded here. Secrets are stripped before a row is written.
"""

from alembic import op

revision = "0002_verify_results"
down_revision = "0001_ui_tables"
branch_labels = None
depends_on = None

TABLES = ["memoryhub_ui_verify_results"]


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS memoryhub_ui_verify_results (
            id UUID PRIMARY KEY,
            tenant_id VARCHAR(255) NOT NULL,
            owner VARCHAR(255) NOT NULL,
            source VARCHAR(16) NOT NULL,
            result JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_memoryhub_ui_verify_owner "
        "ON memoryhub_ui_verify_results (tenant_id, owner, created_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS memoryhub_ui_verify_results")
