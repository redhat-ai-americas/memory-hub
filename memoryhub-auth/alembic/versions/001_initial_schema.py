"""Initial schema — oauth_clients, refresh_tokens, auth_sessions.

Captures the full memoryhub-auth schema as of the PKCE broker feature.
This migration is idempotent: it uses IF NOT EXISTS for tables and columns
so it can run against both fresh and existing databases.

Revision ID: 001
Revises: None
Create Date: 2026-04-13
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # --- oauth_clients -----------------------------------------------------------
    # This table may already exist from the pre-Alembic era.
    if not _table_exists(conn, "oauth_clients"):
        op.create_table(
            "oauth_clients",
            sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v4()"), primary_key=True),
            sa.Column("client_id", sa.String(255), unique=True, nullable=False),
            sa.Column("client_secret_hash", sa.String(255), nullable=False),
            sa.Column("client_name", sa.String(255), nullable=False),
            sa.Column("identity_type", sa.String(10), server_default=sa.text("'user'"), nullable=False),
            sa.Column("tenant_id", sa.String(255), nullable=False),
            sa.Column("default_scopes", sa.JSON(), nullable=False),
            sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
            sa.Column("redirect_uris", sa.JSON(), nullable=True),
            sa.Column("public", sa.Boolean(), server_default=sa.text("false"), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
    else:
        # Table exists — add PKCE columns if missing.
        if not _column_exists(conn, "oauth_clients", "redirect_uris"):
            op.add_column("oauth_clients", sa.Column("redirect_uris", sa.JSON(), nullable=True))
        if not _column_exists(conn, "oauth_clients", "public"):
            op.add_column(
                "oauth_clients",
                sa.Column("public", sa.Boolean(), server_default=sa.text("false"), nullable=False),
            )

    # --- refresh_tokens ----------------------------------------------------------
    if not _table_exists(conn, "refresh_tokens"):
        op.create_table(
            "refresh_tokens",
            sa.Column("id", sa.UUID(), server_default=sa.text("uuid_generate_v4()"), primary_key=True),
            sa.Column("token_hash", sa.String(255), unique=True, nullable=False),
            sa.Column(
                "client_id",
                sa.String(255),
                sa.ForeignKey("oauth_clients.client_id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("subject", sa.String(255), nullable=False),
            sa.Column("scopes", sa.JSON(), nullable=False),
            sa.Column("tenant_id", sa.String(255), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("revoked", sa.Boolean(), server_default=sa.text("false"), nullable=False),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )

    # --- auth_sessions -----------------------------------------------------------
    if not _table_exists(conn, "auth_sessions"):
        op.create_table(
            "auth_sessions",
            sa.Column("session_id", sa.String(64), primary_key=True),
            sa.Column("client_id", sa.String(255), nullable=False),
            sa.Column("client_redirect_uri", sa.String(2048), nullable=False),
            sa.Column("client_state", sa.String(2048), nullable=False),
            sa.Column("code_challenge", sa.String(128), nullable=False),
            sa.Column("code_challenge_method", sa.String(8), server_default=sa.text("'S256'"), nullable=False),
            sa.Column("code_hash", sa.String(64), nullable=True),
            sa.Column("subject", sa.String(255), nullable=True),
            sa.Column("identity_type", sa.String(32), nullable=True),
            sa.Column("tenant_id", sa.String(255), nullable=True),
            sa.Column("scopes", sa.JSON(), nullable=True),
            sa.Column("status", sa.String(16), server_default=sa.text("'pending'"), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("ix_auth_sessions_code_hash", "auth_sessions", ["code_hash"])
        op.create_index("ix_auth_sessions_expires_at", "auth_sessions", ["expires_at"])


def downgrade() -> None:
    op.drop_table("auth_sessions")
    op.drop_column("oauth_clients", "public")
    op.drop_column("oauth_clients", "redirect_uris")
    op.drop_table("refresh_tokens")
    op.drop_table("oauth_clients")


def _table_exists(conn, table_name: str) -> bool:
    result = conn.execute(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
            "WHERE table_name = :name)"
        ),
        {"name": table_name},
    )
    return result.scalar()


def _column_exists(conn, table_name: str, column_name: str) -> bool:
    result = conn.execute(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
            "WHERE table_name = :table AND column_name = :col)"
        ),
        {"table": table_name, "col": column_name},
    )
    return result.scalar()
