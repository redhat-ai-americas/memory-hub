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
    # When the client last obtained a token or had a key accepted, and how (#721).
    last_used_at: datetime | None = None
    last_used_via: str | None = None
    api_key_last_used_at: datetime | None = None


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


class CreateApiKeyRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    # Internal admin API only: the BFF passes its verified principal.
    created_by: str | None = Field(default=None, max_length=255)


class ApiKeyResponse(BaseModel):
    id: str
    client_id: str
    name: str
    key_prefix: str
    created_at: datetime
    created_by: str | None = None
    last_used_at: datetime | None = None
    revoked_at: datetime | None = None


class ApiKeyCreatedResponse(ApiKeyResponse):
    api_key: str  # plaintext, shown once


class VerifySecretRequest(BaseModel):
    client_secret: str = Field(min_length=1, max_length=512)
