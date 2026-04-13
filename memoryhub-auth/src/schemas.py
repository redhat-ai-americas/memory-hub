from datetime import datetime

from pydantic import BaseModel, Field


class CreateClientRequest(BaseModel):
    client_id: str = Field(min_length=1, max_length=255)
    client_name: str = Field(min_length=1, max_length=255)
    identity_type: str = Field(default="user", pattern="^(user|service)$")
    tenant_id: str = Field(min_length=1, max_length=255)
    default_scopes: list[str] = Field(default_factory=lambda: ["memory:read"])
    redirect_uris: list[str] | None = None
    public: bool = False


class UpdateClientRequest(BaseModel):
    client_name: str | None = None
    active: bool | None = None
    default_scopes: list[str] | None = None
    redirect_uris: list[str] | None = None
    public: bool | None = None


class ClientResponse(BaseModel):
    client_id: str
    client_name: str
    identity_type: str
    tenant_id: str
    default_scopes: list[str]
    redirect_uris: list[str] | None = None
    public: bool
    active: bool
    created_at: datetime
    updated_at: datetime


class ClientCreatedResponse(ClientResponse):
    client_secret: str  # plaintext, shown once


class SecretRotatedResponse(BaseModel):
    client_id: str
    client_secret: str  # plaintext, shown once
