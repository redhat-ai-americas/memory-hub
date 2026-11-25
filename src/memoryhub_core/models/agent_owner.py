"""Tenant-scoped proof that a human owns an OAuth client."""

from sqlalchemy import Column, Index, String

from memoryhub_core.models.base import Base


class AgentOwner(Base):
    __tablename__ = "memoryhub_ui_agent_owners"

    tenant_id = Column(String(255), primary_key=True)
    client_id = Column(String(255), primary_key=True)
    owner = Column(String(255), nullable=False)
    __table_args__ = (Index("ix_memoryhub_ui_agent_owners_owner", "tenant_id", "owner"),)
