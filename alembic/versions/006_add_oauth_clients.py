"""Add oauth_clients and refresh_tokens tables for OAuth 2.1 auth service.

Revision ID: 006_add_oauth_clients
Revises: 005_add_contradiction_reports
Create Date: 2026-04-05
"""

import sqlalchemy as sa
from alembic import op

revision = "006_add_oauth_clients"
down_revision = "005_add_contradiction_reports"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "oauth_clients",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v4()"), nullable=False),
        sa.Column("client_id", sa.String(255), nullable=False),
        sa.Column("client_secret_hash", sa.String(255), nullable=False),
        sa.Column("client_name", sa.String(255), nullable=False),
        sa.Column("identity_type", sa.String(10), server_default=sa.text("'user'"), nullable=False),
        sa.Column("tenant_id", sa.String(255), nullable=False),
        sa.Column("default_scopes", sa.JSON(), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("client_id"),
    )

    op.create_index("ix_oauth_clients_client_id", "oauth_clients", ["client_id"], unique=True)
    op.create_index("ix_oauth_clients_tenant_id", "oauth_clients", ["tenant_id"])
    op.create_index("ix_oauth_clients_active", "oauth_clients", ["active"])

    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v4()"), nullable=False),
        sa.Column("token_hash", sa.String(255), nullable=False),
        sa.Column("client_id", sa.String(255), nullable=False),
        sa.Column("subject", sa.String(255), nullable=False),
        sa.Column("scopes", sa.JSON(), nullable=False),
        sa.Column("tenant_id", sa.String(255), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
        sa.ForeignKeyConstraint(["client_id"], ["oauth_clients.client_id"], ondelete="CASCADE"),
    )

    op.create_index("ix_refresh_tokens_token_hash", "refresh_tokens", ["token_hash"], unique=True)
    op.create_index("ix_refresh_tokens_client_id", "refresh_tokens", ["client_id"])
    op.create_index("ix_refresh_tokens_revoked_expires_at", "refresh_tokens", ["revoked", "expires_at"])
    op.create_index("ix_refresh_tokens_subject", "refresh_tokens", ["subject"])


def downgrade() -> None:
    op.drop_index("ix_refresh_tokens_subject", table_name="refresh_tokens")
    op.drop_index("ix_refresh_tokens_revoked_expires_at", table_name="refresh_tokens")
    op.drop_index("ix_refresh_tokens_client_id", table_name="refresh_tokens")
    op.drop_index("ix_refresh_tokens_token_hash", table_name="refresh_tokens")
    op.drop_table("refresh_tokens")

    op.drop_index("ix_oauth_clients_active", table_name="oauth_clients")
    op.drop_index("ix_oauth_clients_tenant_id", table_name="oauth_clients")
    op.drop_index("ix_oauth_clients_client_id", table_name="oauth_clients")
    op.drop_table("oauth_clients")
