"""Record when clients and API keys are used; add named API keys per client.

Revision ID: 003
Revises: 002
Create Date: 2026-11-22
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "003"
down_revision: str | None = "002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("oauth_clients", sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("oauth_clients", sa.Column("last_used_via", sa.String(32), nullable=True))
    op.add_column("oauth_clients", sa.Column("api_key_last_used_at", sa.DateTime(timezone=True), nullable=True))
    op.create_table(
        "api_keys",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=False), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("client_id", sa.String(255),
                  sa.ForeignKey("oauth_clients.client_id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("key_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("key_prefix", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_by", sa.String(255), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_api_keys_client_id", "api_keys", ["client_id"])


def downgrade() -> None:
    op.drop_index("ix_api_keys_client_id", table_name="api_keys")
    op.drop_table("api_keys")
    op.drop_column("oauth_clients", "api_key_last_used_at")
    op.drop_column("oauth_clients", "last_used_via")
    op.drop_column("oauth_clients", "last_used_at")
