"""Pydantic v2 schemas for memory node API data.

These models handle validation, serialization, and documentation for the
REST API layer. They are intentionally separate from the SQLAlchemy ORM models.
"""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class MemoryScope(StrEnum):
    """Scope hierarchy from personal to enterprise-wide."""

    USER = "user"
    PROJECT = "project"
    ROLE = "role"
    ORGANIZATIONAL = "organizational"
    ENTERPRISE = "enterprise"


class StorageType(StrEnum):
    """Where the memory content is physically stored."""

    INLINE = "inline"
    S3 = "s3"


# -- Input schemas --


class MemoryNodeCreate(BaseModel):
    """Input schema for creating a new memory node."""

    content: str = Field(min_length=1, description="The memory content text")
    scope: MemoryScope
    weight: float = Field(default=0.7, ge=0.0, le=1.0, description="Injection priority (0.0-1.0)")
    owner_id: str = Field(min_length=1, description="Owning user, project, or org identifier")
    parent_id: uuid.UUID | None = Field(default=None, description="Parent node for branch creation")
    branch_type: str | None = Field(
        default=None,
        description="Branch type (rationale, provenance, description, etc.). Null for root memories.",
    )
    metadata: dict[str, Any] | None = Field(default=None, description="Extensible metadata")


class MemoryNodeUpdate(BaseModel):
    """Input schema for updating an existing memory node.

    All fields are optional; only provided fields are applied.
    """

    content: str | None = Field(default=None, min_length=1)
    weight: float | None = Field(default=None, ge=0.0, le=1.0)
    metadata: dict[str, Any] | None = None


# -- Output schemas --


class MemoryNodeRead(BaseModel):
    """Full output schema for reading a memory node.

    Note: has_children and has_rationale are not ORM attributes — they must be
    populated explicitly by the service layer via query results.
    """

    model_config = {"from_attributes": True, "populate_by_name": True}

    id: uuid.UUID
    parent_id: uuid.UUID | None
    content: str
    stub: str
    storage_type: StorageType
    content_ref: str | None
    weight: float
    scope: MemoryScope
    branch_type: str | None
    owner_id: str
    is_current: bool
    version: int
    previous_version_id: uuid.UUID | None
    metadata: dict[str, Any] | None = Field(default=None, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime
    has_children: bool = False  # populated by service layer, not from ORM
    has_rationale: bool = False  # populated by service layer, not from ORM


class MemoryNodeStub(BaseModel):
    """Lightweight output for stub injection into agent context."""

    model_config = {"from_attributes": True}

    id: uuid.UUID
    stub: str
    scope: MemoryScope
    weight: float
    branch_type: str | None = None
    has_children: bool = False
    has_rationale: bool = False


class MemoryVersionInfo(BaseModel):
    """Version chain entry for a memory node."""

    model_config = {"from_attributes": True}

    id: uuid.UUID
    version: int = Field(ge=1)
    is_current: bool
    created_at: datetime
    stub: str
