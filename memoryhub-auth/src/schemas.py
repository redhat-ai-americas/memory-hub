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
    # Internal admin API only: BFF derives this from its verified principal.
    # Auth persists the binding in the same transaction as the client.
    owner: str | None = Field(default=None, min_length=1, max_length=255)


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
    api_key: str  # plaintext, shown once


class SecretRotatedResponse(BaseModel):
    client_id: str
    client_secret: str  # plaintext, shown once
    api_key: str  # also regenerated, shown once


class ApiKeyRotatedResponse(BaseModel):
    client_id: str
    api_key: str


class ValidateApiKeyRequest(BaseModel):
    api_key: str


class ValidateApiKeyResponse(BaseModel):
    user_id: str
    name: str
    identity_type: str
    tenant_id: str
    scopes: list[str]


class EndSessionsRequest(BaseModel):
    """Explicit end of a person's sessions (compromise, offboarding, block)."""

    tenant_id: str
    # Also revoke the refresh tokens of agents the person owns.
    include_agents: bool = False
    # Block the person: a disabled profile is refused by the dashboard, the
    # broker, refresh and every personal agent until re-enabled.
    disable: bool = False
    reason: str = Field(min_length=3, max_length=500)


class EndSessionsResponse(BaseModel):
    username: str
    sessions_revoked: int
    agent_tokens_revoked: int
    disabled: bool
    profile_found: bool
