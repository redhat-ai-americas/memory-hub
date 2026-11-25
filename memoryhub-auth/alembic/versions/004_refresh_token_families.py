"""Refresh-token families, absolute session age and the person's uid.

family_id groups every token rotated from one grant so that reuse of a
revoked member revokes the whole family (RFC 9700 section 4.14).
family_started_at bounds the session regardless of rotations. subject_uid
records the OpenShift User uid of a person, so a deleted and recreated
account with the same username is detected at refresh. Existing tokens
start their own family; existing person tokens have no uid and therefore
end at their next refresh (one new sign-in).

Revision ID: 004
Revises: 003
Create Date: 2026-11-25
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "004"
down_revision: str | None = "003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("refresh_tokens", sa.Column("family_id", sa.String(64), nullable=True))
    op.add_column("refresh_tokens", sa.Column("family_started_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("refresh_tokens", sa.Column("subject_uid", sa.String(255), nullable=True))
    op.execute("UPDATE refresh_tokens SET family_id = CAST(id AS VARCHAR), family_started_at = created_at")
    op.alter_column("refresh_tokens", "family_id", nullable=False)
    op.alter_column("refresh_tokens", "family_started_at", nullable=False)
    op.create_index("ix_refresh_tokens_family_id", "refresh_tokens", ["family_id"])
    op.create_index("ix_refresh_tokens_subject", "refresh_tokens", ["tenant_id", "subject"])
    op.add_column("auth_sessions", sa.Column("subject_uid", sa.String(255), nullable=True))


def downgrade() -> None:
    op.drop_column("auth_sessions", "subject_uid")
    op.drop_index("ix_refresh_tokens_subject", table_name="refresh_tokens")
    op.drop_index("ix_refresh_tokens_family_id", table_name="refresh_tokens")
    op.drop_column("refresh_tokens", "subject_uid")
    op.drop_column("refresh_tokens", "family_started_at")
    op.drop_column("refresh_tokens", "family_id")
