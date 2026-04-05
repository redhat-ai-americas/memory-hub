from datetime import datetime

from sqlalchemy import Boolean, DateTime, JSON, String, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
import sqlalchemy as sa


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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, server_default=sa.text("uuid_generate_v4()"))
    token_hash: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    client_id: Mapped[str] = mapped_column(String(255), ForeignKey("oauth_clients.client_id", ondelete="CASCADE"), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    scopes: Mapped[list] = mapped_column(JSON, nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(255), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=sa.text("false"))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
