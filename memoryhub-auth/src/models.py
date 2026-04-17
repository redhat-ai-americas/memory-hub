from datetime import datetime

import sqlalchemy as sa
from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class OAuthClient(Base):
    __tablename__ = "oauth_clients"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, server_default=sa.text("uuid_generate_v4()"))
    client_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    client_secret_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    client_name: Mapped[str] = mapped_column(String(255), nullable=False)
    identity_type: Mapped[str] = mapped_column(String(10), nullable=False, server_default=sa.text("'user'"))
    tenant_id: Mapped[str] = mapped_column(String(255), nullable=False)
    default_scopes: Mapped[list] = mapped_column(JSON, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=sa.text("true"))
    redirect_uris: Mapped[list | None] = mapped_column(JSON, nullable=True)
    public: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=sa.text("false"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, server_default=sa.text("uuid_generate_v4()"))
    token_hash: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    client_id: Mapped[str] = mapped_column(
        String(255), ForeignKey("oauth_clients.client_id", ondelete="CASCADE"), nullable=False
    )
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    scopes: Mapped[list] = mapped_column(JSON, nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(255), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=sa.text("false"))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    session_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    client_id: Mapped[str] = mapped_column(String(255), nullable=False)
    client_redirect_uri: Mapped[str] = mapped_column(String(2048), nullable=False)
    client_state: Mapped[str] = mapped_column(String(2048), nullable=False)
    code_challenge: Mapped[str] = mapped_column(String(128), nullable=False)
    code_challenge_method: Mapped[str] = mapped_column(String(8), nullable=False, server_default=sa.text("'S256'"))
    code_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    subject: Mapped[str | None] = mapped_column(String(255), nullable=True)
    identity_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    tenant_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    scopes: Mapped[list | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=sa.text("'pending'"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        sa.Index("ix_auth_sessions_code_hash", "code_hash"),
        sa.Index("ix_auth_sessions_expires_at", "expires_at"),
    )
