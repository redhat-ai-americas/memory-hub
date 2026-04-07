"""MemoryHub SDK response models."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Memory(BaseModel):
    """A memory node returned by search, read, or write operations."""

    model_config = ConfigDict(extra="allow")

    id: str
    content: str
    stub: str | None = None
    weight: float = 0.7
    scope: str
    branch_type: str | None = None
    owner_id: str
    is_current: bool = True
    version: int = 1
    parent_id: str | None = None
    previous_version_id: str | None = None
    storage_type: str = "inline"
    content_ref: str | None = None
    metadata: dict[str, Any] | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    expires_at: datetime | None = None
    has_children: bool = False
    has_rationale: bool = False
    branch_count: int = 0
    current_version_id: str | None = None
    relationships: list[dict[str, Any]] | None = None
    relevance_score: float | None = None
    result_type: str | None = None  # "full" or "stub"


class CurationInfo(BaseModel):
    """Curation feedback returned when writing a memory."""

    model_config = ConfigDict(extra="allow")

    blocked: bool = False
    similar_count: int = 0
    nearest_id: str | None = None
    nearest_score: float | None = None
    flags: list[str] = Field(default_factory=list)


class WriteResult(BaseModel):
    """Result of a write_memory operation."""

    model_config = ConfigDict(extra="allow")

    memory: Memory
    curation: CurationInfo


class DeleteResult(BaseModel):
    """Result of a delete_memory operation."""

    model_config = ConfigDict(extra="allow")

    deleted_id: str
    versions_deleted: int = 0
    branches_deleted: int = 0
    total_deleted: int = 0


class SearchResult(BaseModel):
    """Result of a search_memory operation."""

    model_config = ConfigDict(extra="allow")

    results: list[Memory]
    total_matching: int = 0
    has_more: bool = False


class VersionEntry(BaseModel):
    """A single version in a memory's history."""

    model_config = ConfigDict(extra="allow")

    id: str
    version: int
    content: str
    stub: str | None = None
    is_current: bool = False
    created_at: datetime | None = None


class HistoryResult(BaseModel):
    """Result of a get_memory_history operation."""

    model_config = ConfigDict(extra="allow")

    memory_id: str
    versions: list[VersionEntry]
    total_versions: int = 0
    has_more: bool = False
    offset: int = 0


class ContradictionResult(BaseModel):
    """Result of a report_contradiction operation."""

    model_config = ConfigDict(extra="allow")

    memory_id: str
    contradiction_count: int = 0
    threshold: int = 5
    revision_triggered: bool = False
    message: str = ""


class SimilarMemory(BaseModel):
    """A memory returned by get_similar_memories with similarity score."""

    model_config = ConfigDict(extra="allow")

    memory: Memory
    score: float


class RelationshipInfo(BaseModel):
    """A relationship between two memory nodes."""

    model_config = ConfigDict(extra="allow")

    id: str | None = None
    source_id: str
    target_id: str
    relationship_type: str
    metadata: dict[str, Any] | None = None
    created_at: datetime | None = None


class RelationshipsResult(BaseModel):
    """Result of a get_relationships operation."""

    model_config = ConfigDict(extra="allow")

    relationships: list[RelationshipInfo]
    count: int = 0
    provenance_chain: list[dict[str, Any]] | None = None


class CurationRule(BaseModel):
    """A curation rule configuration."""

    model_config = ConfigDict(extra="allow")

    name: str
    tier: str = "embedding"
    action: str = "flag"
    config: dict[str, Any] | None = None
    scope_filter: str | None = None
    enabled: bool = True
    priority: int = 10


class CurationRuleResult(BaseModel):
    """Result of a set_curation_rule operation."""

    model_config = ConfigDict(extra="allow")

    created: bool = False
    updated: bool = False
    rule: CurationRule | dict[str, Any]


class SessionInfo(BaseModel):
    """Result of register_session (used internally)."""

    model_config = ConfigDict(extra="allow")

    user_id: str
    name: str
    scopes: list[str]
    message: str = ""
