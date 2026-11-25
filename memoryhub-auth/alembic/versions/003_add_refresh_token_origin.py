"""Record whether a refresh token belongs to a person or to a client.

Refresh of a person's token (origin "broker") re-checks that the person may
still use MemoryHub (docs/auth/human-role-resolution.md). Existing rows are
backfilled: client_credentials tokens always have subject == client_id, so
any other subject is a person who signed in through the broker.

Revision ID: 003
Revises: 002
Create Date: 2026-11-25
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "003"
down_revision: str | None = "002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "refresh_tokens",
        sa.Column("origin", sa.String(16), nullable=False, server_default=sa.text("'client'")),
    )
    op.execute("UPDATE refresh_tokens SET origin = 'broker' WHERE subject <> client_id")


def downgrade() -> None:
    op.drop_column("refresh_tokens", "origin")
